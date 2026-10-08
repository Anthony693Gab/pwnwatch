"""Security news: fetch RSS/Atom feeds, normalise, tag and cache them."""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

from .config import Config, active_feeds
from .store import cache_path, http_get, read_json, write_json

NEWS_CACHE = "news.json"

# (tag, regex) — applied to title + summary. Order = display order.
TAG_RULES: list[tuple[str, str]] = [
    ("0DAY", r"zero[- ]day|0[- ]day|actively exploited|in the wild"),
    ("RANSOM", r"ransomware|extortion|lockbit|blackcat|akira|killsec|qilin"),
    ("BREACH", r"breach|leak(?:ed|s)?\b|stolen data|data theft|exposed (?:data|records)"),
    ("ARREST", r"arrest|charged|sentenced|indict|extradit|europol|interpol|dismantl|takedown|seiz"),
    ("APT", r"\bapt ?\d+|state[- ]sponsored|nation[- ]state|espionage"),
    ("MALWARE", r"malware|trojan|botnet|stealer|backdoor|\brat\b|loader"),
    ("CVE", r"cve-\d{4}-\d{4,}"),
    ("PHISH", r"phishing|smishing|vishing"),
    ("AI", r"\bai\b|llm|chatgpt|deepfake"),
    ("OPPORTUNITY", r"capture[- ]the[- ]flag|\bctfs?\b|hackathon|scholarship|internship|olympiad|olimpiad"
                    r"|bootcamp|call for (?:papers|speakers|proposals)|registrations? (?:is |are )?(?:now )?open"
                    r"|bug bounty program|cyber ?(?:security )?(?:challenge|competition|contest)"),
]
_COMPILED = [(t, re.compile(p, re.I)) for t, p in TAG_RULES]


@dataclass
class Article:
    title: str
    link: str
    source: str
    published: str | None = None  # ISO 8601, UTC
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    watch: bool = False  # matches one of the user's watch words
    image: str = ""  # thumbnail URL from the feed (may be empty → og:image lookup)
    kind: str = "news"  # news | opportunity
    publisher: str = ""  # original site, for aggregated feeds (Google News)

    @property
    def id(self) -> str:
        return hashlib.sha1(self.link.encode()).hexdigest()[:12]

    @property
    def domain(self) -> str:
        host = urlparse(self.link).hostname or ""
        return host.removeprefix("www.")

    @property
    def dt(self) -> datetime | None:
        return datetime.fromisoformat(self.published) if self.published else None


# ---------------------------------------------------------------- parsing

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: str | None, limit: int = 600) -> str:
    if not s:
        return ""
    s = html.unescape(_TAG_RE.sub(" ", s))
    s = _WS_RE.sub(" ", s).strip()
    return s[: limit - 1] + "…" if len(s) > limit else s


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el: ET.Element, *names: str) -> str | None:
    c = _child(el, *names)
    return (c.text or "").strip() if c is not None and c.text else None


def parse_feed(source: str, data: bytes) -> list[Article]:
    """Parse RSS 2.0, RSS 1.0 (RDF) or Atom into Articles."""
    root = ET.fromstring(data)
    items = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    out: list[Article] = []
    for it in items:
        title = clean_text(_text(it, "title"), 300)
        link = None
        for c in it:
            if _local(c.tag) == "link":
                href = c.get("href")
                if href and c.get("rel", "alternate") == "alternate":
                    link = href
                    break
                if c.text and c.text.strip():
                    link = c.text.strip()
                    break
        if not link:
            link = _text(it, "guid", "id")
        if not title or not link:
            continue
        date = parse_date(_text(it, "pubdate", "published", "updated", "date"))
        raw_html = _text(it, "description", "summary", "content", "encoded") or ""
        summary = clean_text(raw_html)
        image = _find_image(it, raw_html + " " + (_text(it, "encoded") or ""))
        publisher = ""
        src_el = _child(it, "source")
        if src_el is not None and src_el.get("url"):  # Google News / aggregator items
            publisher = (src_el.text or "").strip()
            if publisher and title.endswith(" - " + publisher):
                title = title[: -len(publisher) - 3].rstrip()
            if publisher and summary.endswith(publisher):
                summary = summary[: -len(publisher)].rstrip(" -–·")
        out.append(
            Article(
                title=title,
                link=link,
                source=source,
                published=date.isoformat() if date else None,
                summary=summary,
                image=urljoin(link, image) if image else "",
                publisher=publisher,
            )
        )
    return out


_IMG_RE = re.compile(r"""<img[^>]+?src=["']([^"']+)["'][^>]*>""", re.I)


def _find_image(item: ET.Element, raw_html: str) -> str:
    """media:content / media:thumbnail / enclosure, else the first <img> in the HTML."""
    for c in item.iter():
        name = _local(c.tag)
        url = c.get("url")
        if not url:
            continue
        ctype = (c.get("type") or "").lower()
        if name in ("content", "thumbnail") and (
            c.get("medium", "image") == "image" or ctype.startswith("image")
        ):
            return url
        if name == "enclosure" and ctype.startswith("image"):
            return url
    for m in _IMG_RE.finditer(raw_html):
        tag, src = m.group(0), m.group(1)
        if re.search(r"width=[\"']?1[\"' >]|feedburner|pixel|gravatar|/emoji/", tag + src, re.I):
            continue
        return src
    return ""


def tag_article(a: Article, watch_words: list[str]) -> Article:
    blob = f"{a.title} {a.summary}"
    a.tags = [t for t, rx in _COMPILED if rx.search(blob)]
    a.watch = any(re.search(rf"\b{re.escape(w)}", blob, re.I) for w in watch_words if w)
    return a


# ---------------------------------------------------------------- fetching


def fetch_feed(name: str, url: str) -> list[Article]:
    return parse_feed(name, http_get(url))


GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"


def opportunity_feeds(cfg: Config) -> dict[str, str]:
    """Search feeds for competitions/CTFs/scholarships that news sites rarely cover.
    A query starting with 'ro:' searches Romanian-language news."""
    from urllib.parse import quote_plus

    out = {}
    for q in cfg.opportunity_queries:
        q = q.strip()
        if not q:
            continue
        lang, gl = "en", "US"
        if ":" in q[:4] and q.split(":", 1)[0].isalpha() and len(q.split(":", 1)[0]) == 2:
            lang, q = q.split(":", 1)
            lang, gl = lang.lower(), lang.upper()
            q = q.strip()
        hl = "en-US" if lang == "en" else lang
        out[f"Opportunities: {q}"] = GOOGLE_NEWS.format(
            q=quote_plus(q + " when:30d"), hl=hl, gl=gl, lang=lang)
    return out


def fetch_all(cfg: Config) -> tuple[list[Article], dict[str, str]]:
    """Fetch every feed in parallel. Returns (articles, {source: error})."""
    errors: dict[str, str] = {}
    articles: list[Article] = []

    def job(item):
        name, url = item
        try:
            return name, fetch_feed(name, url), None
        except Exception as exc:  # network, XML, HTTP errors — never fatal
            return name, [], f"{type(exc).__name__}: {exc}"

    feeds = list(active_feeds(cfg).items())
    opp = opportunity_feeds(cfg)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, arts, err in pool.map(job, feeds + list(opp.items())):
            if err:
                errors[name] = err
            if name in opp:
                for a in arts:
                    a.kind = "opportunity"
                    a.source = "Opportunities"
            articles.extend(arts)

    return finalize(articles, cfg), errors


def finalize(articles: list[Article], cfg: Config) -> list[Article]:
    """Dedupe, drop old stories, tag and sort newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.news_days)
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    out = []
    for a in articles:
        key_t = re.sub(r"\W+", "", a.title.lower())[:80]
        if a.link in seen_links or key_t in seen_titles:
            continue
        if a.dt and a.dt < cutoff:
            continue
        seen_links.add(a.link)
        seen_titles.add(key_t)
        out.append(tag_article(a, cfg.watch_words))
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    out.sort(key=lambda a: a.dt or epoch, reverse=True)
    return out


def save_cache(articles: list[Article]) -> None:
    write_json(
        cache_path(NEWS_CACHE),
        {"fetched": datetime.now(timezone.utc).isoformat(), "articles": [asdict(a) for a in articles]},
    )


def load_cache() -> tuple[list[Article], datetime | None]:
    raw = read_json(cache_path(NEWS_CACHE), {})
    arts = []
    for d in raw.get("articles", []):
        try:
            arts.append(Article(**d))
        except TypeError:
            continue
    fetched = raw.get("fetched")
    return arts, datetime.fromisoformat(fetched) if fetched else None
