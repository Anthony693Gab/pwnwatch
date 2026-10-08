"""Local web backend: a tiny stdlib HTTP server bound to 127.0.0.1.

The UI is plain HTML/CSS/JS shown in a Chromium app window (the same way
Omarchy runs its web apps). Nothing listens on the network: requests whose
Host header is not 127.0.0.1/localhost are rejected (DNS-rebinding guard),
state-changing calls must be JSON POSTs (no CORS → no cross-site writes),
and the image proxy only fetches images that belong to known stories/events
and refuses private/loopback addresses.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import webbrowser
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections import deque
from urllib.parse import parse_qs, urlparse

from . import __version__, ctf, news, theme
from .config import (CACHE_DIR, DEFAULT_FEEDS, Config, load_config, read_settings,
                     write_settings)
from .countries import NAMES, name_of
from .fmt import country_cell, country_long, countdown, get_tz, when
from .snapshot import EventContext, tz_label
from .store import SeenSet, read_json, state_path, write_json

WEB = Path(__file__).parent / "web"
IMG_DIR = CACHE_DIR / "img"
DEFAULT_PORT = 47431
REFRESH_EVERY = 30 * 60
IDLE_EXIT = 180  # seconds without a page heartbeat before the server quits
MAX_IMAGE = 6 * 1024 * 1024
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"


# ====================================================================== state


class Hub:
    """Everything the UI shows, plus the background refresh loop."""

    def __init__(self, cfg: Config | None = None, offline: bool = False):
        self.cfg = cfg or load_config()
        self.offline = offline
        self.lock = threading.RLock()
        self.seen = SeenSet()
        self.saved: dict[str, dict] = read_json(state_path("saved.json"), {})
        # CTFs you saved / registered for / played, with a snapshot of the event so they
        # outlive CTFtime's window: {event_id: {status, event, notes, place, teams, ...}}
        self.mine: dict[str, dict] = read_json(state_path("mine.json"), {})
        self._opp_links: dict[str, str] = {}
        self.articles, fetched = news.load_cache()
        self.events, _ = ctf.load_cached_merged(self.cfg)
        self.team = read_json(CACHE_DIR / ctf.TEAM_INFO_CACHE, {})
        self.updated = fetched
        self.errors: dict[str, str] = {}
        self.busy = False
        self._refresh_lock = threading.Lock()
        self._bus = threading.Condition()
        self._events: deque = deque(maxlen=64)
        self._seq = 0

    # ---------------------------------------------------------- live events (SSE)
    def publish(self, name: str, data=None) -> None:
        with self._bus:
            self._seq += 1
            self._events.append((self._seq, name, data))
            self._bus.notify_all()

    def bus_seq(self) -> int:
        with self._bus:
            return self._seq

    def next_event(self, after: int, timeout: float):
        with self._bus:
            if self._seq <= after:
                self._bus.wait(timeout)
            for ev in self._events:
                if ev[0] > after:
                    return ev
        return None

    # ---------------------------------------------------------- refresh
    def refresh(self) -> None:
        if self.offline or not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self.busy = True
            errors: dict[str, str] = {}
            arts, feed_errs = news.fetch_all(self.cfg)
            errors.update(feed_errs)
            evs, ctf_err = ctf.fetch_all(self.cfg)
            if ctf_err:
                errors["CTFtime"] = ctf_err
            team, team_err = ctf.fetch_team(self.cfg.team_id, self.cfg.home_country)
            if team_err:
                errors["CTFtime team"] = team_err
            with self.lock:
                if arts:
                    news.save_cache(arts)
                    self.articles = arts
                    self.updated = datetime.now(timezone.utc)
                self.events = evs
                self.team = team
                self.errors = errors
        finally:
            self.busy = False
            self._refresh_lock.release()
            self.publish("state")

    def refresh_async(self) -> None:
        threading.Thread(target=self.refresh, daemon=True).start()
        threading.Timer(0.3, self.publish, args=("state",)).start()  # show the spinner

    def reload_config(self) -> None:
        with self.lock:
            self.cfg = load_config()
            self.events, _ = ctf.load_cached_merged(self.cfg)
            # re-tag cached stories with the new watch words
            self.articles = news.finalize(self.articles, self.cfg)

    # ---------------------------------------------------------- lookups
    def article(self, aid: str) -> dict | None:
        with self.lock:
            for a in self.articles:
                if a.id == aid:
                    return asdict(a) | {"id": a.id}
        return self.saved.get(aid)

    def all_events(self) -> list[ctf.Event]:
        """Current events plus your own ones that dropped out of the fetch window."""
        with self.lock:
            out = list(self.events)
            have = {e.id for e in out}
            for eid, rec in self.mine.items():
                if eid in have or not rec.get("event"):
                    continue
                try:
                    out.append(ctf.Event(**rec["event"]))
                except TypeError:
                    continue
        return out

    def event(self, eid: str) -> ctf.Event | None:
        return next((e for e in self.all_events() if e.id == eid), None)

    def known_urls(self) -> set[str]:
        with self.lock:
            urls = {a.link for a in self.articles} | {s["link"] for s in self.saved.values()}
            for e in self.all_events():
                urls.update(u for u in (e.url, e.ctftime_url) if u)
            team = self.team or {}
            if (team.get("team") or {}).get("url"):
                urls.add(team["team"]["url"])
            urls.update(r["url"] for r in team.get("results", []) if r.get("url"))
            urls.update(f"https://ctftime.org/team/{r.get('id')}" for r in team.get("top", []) if r.get("id"))
        return urls

    # ---------------------------------------------------------- serialise
    def state(self) -> dict:
        with self.lock:
            cfg = self.cfg
            now = datetime.now(timezone.utc)
            items = []
            for a in self.articles:
                items.append(self._article_json(asdict(a) | {"id": a.id}, a.domain))
            live_ids = {i["id"] for i in items}
            for sid, s in self.saved.items():
                if sid not in live_ids:
                    items.append(self._article_json(s, urlparse(s["link"]).hostname or "")
                                 | {"archived": True})

            ctx = EventContext(cfg)
            tz, lo, hi = ctx.tz, ctx.lo, ctx.hi
            results = {int(r["event_id"]): r for r in (self.team or {}).get("results", [])
                       if r.get("event_id")}
            evs = [ctx.event_json(e) | self._mine_json(e, results) for e in self.all_events()]
            items += self._opportunities(ctx, evs)

            return {
                "version": __version__,
                "news": items,
                "events": evs,
                "week": [lo.strftime("%a %d %b"), (hi - timedelta(days=1)).strftime("%a %d %b")],
                "team": self.team or {},
                "settings": {
                    "team_id": cfg.team_id,
                    "home_country": cfg.home_country,
                    "home_country_name": name_of(cfg.home_country),
                    "watch_words": cfg.watch_words,
                    "big_weight": cfg.big_weight,
                    "news_days": cfg.news_days,
                    "timezone": cfg.timezone,
                    "tz_label": tz_label(tz),
                    "rank_country": read_settings().get("rank_country") or "",
                    "countries": sorted(([c, n] for c, n in NAMES.items()), key=lambda x: x[1]),
                    "opportunity_queries": cfg.opportunity_queries,
                    "feeds": [
                        {"name": n, "url": u, "enabled": n not in cfg.disabled_feeds,
                         "builtin": n in DEFAULT_FEEDS}
                        for n, u in cfg.feeds.items()
                    ],
                },
                "updated": self.updated.isoformat() if self.updated else None,
                "busy": self.busy,
                "errors": self.errors,
                "history": history_stats(evs),
                "artwork_bytes": _dir_size(IMG_DIR),
                "theme": theme.load_palette().get("name", ""),
            }

    def _article_json(self, a: dict, domain: str) -> dict:
        return {
            "id": a["id"], "title": a["title"], "link": a["link"], "source": a["source"],
            "domain": (a.get("publisher") or domain.removeprefix("www.")),
            "published": a.get("published"),
            "summary": a.get("summary", ""), "tags": a.get("tags", []),
            "watch": a.get("watch", False), "unread": a["link"] not in self.seen,
            "saved": a["id"] in self.saved,
            "kind": a.get("kind", "news"),
            "opportunity": a.get("kind") == "opportunity" or "OPPORTUNITY" in a.get("tags", []),
        }

    def _mine_json(self, e: ctf.Event, results: dict) -> dict:
        rec = self.mine.get(e.id) or {}
        res = results.get(int(e.ctftime_id)) if e.ctftime_id else None
        place = rec.get("place") or (res or {}).get("place")
        teams = rec.get("teams") or (res or {}).get("teams")
        return {
            "mine": rec.get("status", ""),  # "" | saved | registered
            "notes": rec.get("notes", ""),
            "place": place,
            "teams": teams,
            "points": (res or {}).get("points"),
            "result_source": "manual" if rec.get("place") else ("ctftime" if res else ""),
        }

    def _opportunities(self, ctx: EventContext, evs: list[dict]) -> list[dict]:
        """CTFs that just appeared on CTFtime + hand-picked events coming up, as news items."""
        out = []
        now = ctx.now
        seen_at = ctf.first_seen()
        noticed = read_json(state_path("curated-noticed.json"), {})
        noticed_changed = False
        for e in evs:
            if e["past"] or not e.get("start"):
                continue
            fresh = seen_at.get(e["id"])
            if e["source"] == "ctftime":
                if not fresh or fresh.startswith("1970"):
                    continue
                published = fresh
                if now - datetime.fromisoformat(published) > timedelta(days=7):
                    continue
                title = f"New on CTFtime: {e['name']}"
            elif e["source"] in ("curated", "config") and e.get("start"):
                start = datetime.fromisoformat(e["start"])
                if not (now <= start <= now + timedelta(days=45)):
                    continue
                if e["id"] not in noticed:  # first time it came within 45 days
                    noticed[e["id"]] = now.isoformat()
                    noticed_changed = True
                published = noticed[e["id"]]
                title = f"Coming up: {e['name']}"
            else:
                continue
            link = e["url"] or e["ctftime_url"]
            if not link:
                continue
            bits = [e["when"], e["mode"].replace("onsite", "on-site"), e.get("duration") or "",
                    e["country_long"]]
            summary = " · ".join(b for b in bits if b)
            detail = (e.get("note") or e.get("description") or "").replace("\r", " ").replace("\n", " ")
            oid = "op-" + e["id"]
            self._opp_links[oid] = link
            out.append({
                "id": oid, "title": title, "link": link,
                "source": "Opportunities", "domain": "ctftime.org" if e["source"] == "ctftime" else "upcoming event",
                "published": published, "summary": (summary + ". " + detail[:280]).strip(" ."),
                "tags": ["CTF"], "watch": e["home"], "unread": link not in self.seen,
                "saved": False, "kind": "opportunity", "opportunity": True,
                "thumb": f"/img/c/{e['id']}" if e.get("logo") else "", "event_id": e["id"],
            })
        if noticed_changed:
            write_json(state_path("curated-noticed.json"), noticed)
        return out

    # ---------------------------------------------------------- mutations
    def mark_read(self, ids: list[str] | None) -> None:
        with self.lock:
            links = [a.link for a in self.articles if ids is None or a.id in ids]
            links += [l for i, l in self._opp_links.items() if ids is None or i in ids]
        self.seen.add_many(links)
        self.publish("state")

    def set_saved(self, aid: str, saved: bool) -> None:
        with self.lock:
            if saved:
                a = self.article(aid)
                if a:
                    self.saved[aid] = a
            else:
                self.saved.pop(aid, None)
            write_json(state_path("saved.json"), self.saved)
        self.publish("state")

    def set_mine(self, eid: str, status: str | None = None, notes: str | None = None,
                 place=None, teams=None) -> bool:
        ev = self.event(eid)
        with self.lock:
            rec = dict(self.mine.get(eid) or {})
            if status == "none":
                self.mine.pop(eid, None)
            else:
                if ev is None and not rec:
                    return False
                if ev is not None:
                    rec["event"] = asdict(ev)
                if status in ("saved", "registered"):
                    rec["status"] = status
                rec.setdefault("status", "saved")
                if notes is not None:
                    rec["notes"] = str(notes)[:2000]
                if place is not None:
                    rec["place"] = _pos_int(place)
                if teams is not None:
                    rec["teams"] = _pos_int(teams)
                rec.setdefault("added", datetime.now(timezone.utc).isoformat())
                rec["updated"] = datetime.now(timezone.utc).isoformat()
                self.mine[eid] = rec
            write_json(state_path("mine.json"), self.mine)
        self.publish("state")
        return True


def _pos_int(v):
    try:
        n = int(str(v).strip().lstrip("#"))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def history_stats(evs: list[dict]) -> dict:
    """Your CTF history: registered events that have ended."""
    played = [e for e in evs if e["mine"] == "registered" and e["past"]]
    onsite = [e for e in played if e["mode"] != "online"]
    places = [e["place"] for e in played if e.get("place")]
    countries = sorted({e["country"] for e in onsite if e.get("country")})
    cities = []
    for e in onsite:
        loc = (e.get("location") or "").split(",")[0].strip()
        if loc and loc not in cities:
            cities.append(loc)
    hours = sum(e.get("hours") or 0 for e in played)
    return {
        "played": len(played),
        "onsite": len(onsite),
        "best": min(places) if places else None,
        "countries": countries,
        "cities": cities[:12],
        "hours": round(hours),
        "upcoming": sum(1 for e in evs if e["mine"] == "registered" and not e["past"]),
    }


def _dir_size(d: Path) -> int:
    try:
        return sum(f.stat().st_size for f in d.iterdir() if f.is_file())
    except OSError:
        return 0


# ====================================================================== images


class Images:
    """Download-once thumbnail cache. Story → feed image or the page's og:image."""

    OG_RE = [
        re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["'][^>]*content=["']([^"']+)""", re.I),
        re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]*(?:property|name)=["'](?:og:image|twitter:image)["']""", re.I),
    ]

    def __init__(self, hub: Hub):
        self.hub = hub
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        self.index_path = CACHE_DIR / "img-index.json"
        self.index: dict[str, dict] = read_json(self.index_path, {})
        self.lock = threading.Lock()
        self.gate = threading.Semaphore(6)

    def _save_index(self) -> None:
        with self.lock:
            write_json(self.index_path, self.index)

    def get(self, kind: str, ident: str) -> Path | None:
        key = f"{kind}:{ident}"
        hit = self.index.get(key)
        if hit:
            if hit.get("file"):
                p = IMG_DIR / hit["file"]
                if p.exists():
                    return p
            elif time.time() - hit.get("t", 0) < 86400:  # remembered miss, retry daily
                return None
        if self.hub.offline:
            return None
        with self.gate:
            path = self._resolve(kind, ident)
        with self.lock:
            self.index[key] = {"file": path.name if path else "", "t": time.time()}
        self._save_index()
        return path

    def _resolve(self, kind: str, ident: str) -> Path | None:
        candidates: list[str] = []
        if kind == "n":
            a = self.hub.article(ident)
            if not a:
                return None
            if a.get("image"):
                candidates.append(a["image"])
            # Aggregator links are redirects whose og:image is the aggregator's logo.
            if (urlparse(a["link"]).hostname or "") not in ("news.google.com",):
                candidates.append(("og", a["link"]))
        elif kind == "c":
            e = self.hub.event(ident)
            if e and e.logo:
                candidates.append(e.logo)
        elif kind == "t":
            t = (self.hub.team or {}).get("team") or {}
            if str(t.get("id")) == ident and t.get("logo"):
                candidates.append(t["logo"])
        for c in candidates:
            url = self._og_image(c[1]) if isinstance(c, tuple) else c
            if url:
                p = self._download(url)
                if p:
                    return p
        return None

    def _og_image(self, page: str) -> str | None:
        try:
            html = safe_fetch(page, limit=600_000, accept="text/html")[0].decode("utf-8", "ignore")
        except Exception:
            return None
        for rx in self.OG_RE:
            m = rx.search(html)
            if m:
                from html import unescape
                from urllib.parse import urljoin
                return urljoin(page, unescape(m.group(1)).strip())
        return None

    def _download(self, url: str) -> Path | None:
        try:
            data, ctype = safe_fetch(url, limit=MAX_IMAGE, accept="image/*")
        except Exception:
            return None
        ctype = (ctype or "").split(";")[0].strip().lower()
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
               "image/gif": ".gif", "image/avif": ".avif"}.get(ctype)
        if not ext or len(data) < 200:  # no SVG (scriptable), no tracking pixels
            return None
        p = IMG_DIR / (hashlib.sha1(url.encode()).hexdigest()[:20] + ext)
        p.write_bytes(data)
        return p


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def safe_fetch(url: str, limit: int, accept: str = "*/*") -> tuple[bytes, str]:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("bad url")
    if not _is_public(u.hostname):
        raise ValueError("refusing non-public address")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=12) as r:
        final = urlparse(r.geturl())
        if final.hostname != u.hostname and not _is_public(final.hostname or ""):
            raise ValueError("redirect to non-public address")
        data = r.read(limit + 1)
        if len(data) > limit and accept.startswith("image"):
            raise ValueError("too large")
        return data[:limit], r.headers.get("Content-Type", "")


# ====================================================================== calendar


def ics_for(e: ctf.Event) -> str:
    def fmt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    desc = " · ".join(x for x in (e.mode.upper(), e.format, e.note or e.description[:300]) if x)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//pwnwatch//EN", "BEGIN:VEVENT",
        f"UID:{e.id}@pwnwatch", f"DTSTAMP:{fmt(datetime.now(timezone.utc))}",
        f"DTSTART:{fmt(e.start_dt)}", f"DTEND:{fmt(e.finish_dt or e.start_dt)}",
        f"SUMMARY:{esc(e.name)}", f"DESCRIPTION:{esc(desc)}",
        f"LOCATION:{esc(e.location or e.mode)}", f"URL:{e.url or e.ctftime_url}",
        "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", f"DESCRIPTION:{esc(e.name)} tomorrow",
        "END:VALARM", "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


# ====================================================================== HTTP


def open_external(url: str) -> None:
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        webbrowser.open(url)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, hub: Hub, keep_alive: bool = False):
        super().__init__(("127.0.0.1", port), Handler)
        self.hub = hub
        self.images = Images(hub)
        self.keep_alive = keep_alive
        self.last_beat = time.time()
        self.started = time.time()
        self.clients = 0

    def handle_error(self, request, client_address) -> None:
        pass  # a closed app window mid-request is normal; keep the log quiet


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # quiet
        pass

    # ---------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, default=str).encode(), "application/json",
                   {"Cache-Control": "no-store"})

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            self.close_connection = True
            raise ValueError("too large")
        raw = self.rfile.read(n) if n else b""  # always drain, keeps keep-alive in sync
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise PermissionError("json only")
        return json.loads(raw or b"{}")

    # ---------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        hub = self.server.hub
        path = urlparse(self.path).path
        self.server.last_beat = time.time()

        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path.removeprefix("/static/"))
        if path == "/theme.css":
            css, fp = theme.theme_css()
            return self._send(200, css.encode(), "text/css", {"Cache-Control": "no-store", "ETag": fp})
        if path == "/api/theme":
            return self._json({"fp": theme.theme_css()[1]})
        if path == "/api/ping":
            return self._json({"app": "pwnwatch", "version": __version__,
                               "clients": self.server.clients})
        if path == "/api/events":
            return self._events()
        if path == "/api/top":
            cc = (parse_qs(urlparse(self.path).query).get("cc") or [""])[0].upper()
            if not re.fullmatch(r"[A-Z]{2}", cc):
                return self._json({"error": "bad country"}, 400)
            if hub.offline:
                rows = read_json(CACHE_DIR / f"top-{cc}.json", {}).get("rows") or (
                    (hub.team or {}).get("top") if (hub.team or {}).get("country") == cc else [])
                err = None
            else:
                rows, err = ctf.fetch_top_country(cc)
            return self._json({"country": cc, "name": name_of(cc), "rows": rows, "error": err})
        if path == "/api/state":
            return self._json(hub.state())
        if path.startswith("/img/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2] in ("n", "c", "t") and re.fullmatch(r"[\w-]{1,40}", parts[3]):
                p = self.server.images.get(parts[2], parts[3])
                if p:
                    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    return self._send(200, p.read_bytes(), ctype,
                                      {"Cache-Control": "max-age=604800",
                                       "Content-Security-Policy": "sandbox"})
            return self._send(404, b"", "text/plain")
        m = re.fullmatch(r"/api/ics/([\w-]{1,40})", path)
        if m:
            e = hub.event(m.group(1))
            if e and not e.tba:
                name = re.sub(r"[^\w.-]+", "-", e.name).strip("-")[:60] or "event"
                return self._send(200, ics_for(e).encode(), "text/calendar",
                                  {"Content-Disposition": f'attachment; filename="{name}.ics"'})
            return self._send(404, b"", "text/plain")
        return self._send(404, b"not found", "text/plain")

    do_HEAD = do_GET

    def _events(self) -> None:
        """Server-sent events: 'state' (data changed), 'close', 'view'. Also the heartbeat."""
        hub, srv = self.server.hub, self.server
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        srv.clients += 1
        seq = hub.bus_seq()
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
            while True:
                ev = hub.next_event(seq, timeout=15)
                if ev:
                    seq, name, data = ev
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                srv.last_beat = time.time()
        except OSError:
            pass
        finally:
            srv.clients -= 1
            srv.last_beat = time.time()

    def _static(self, name: str) -> None:
        p = (WEB / name).resolve()
        if WEB.resolve() not in p.parents or not p.is_file():
            return self._send(404, b"", "text/plain")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        csp = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self._send(200, p.read_bytes(), ctype,
                   {"Cache-Control": "no-cache", "Content-Security-Policy": csp})

    # ---------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        try:
            body = self._body()
        except (PermissionError, ValueError):
            return self._json({"error": "bad request"}, 400)
        hub = self.server.hub
        path = urlparse(self.path).path

        if path == "/api/refresh":
            hub.refresh_async()
            return self._json({"ok": True})
        if path == "/api/read":
            ids = body.get("ids")
            hub.mark_read(None if body.get("all") else [str(i) for i in ids or []])
            return self._json({"ok": True})
        if path == "/api/save":
            hub.set_saved(str(body.get("id")), bool(body.get("saved")))
            return self._json({"ok": True})
        if path == "/api/open":
            url = str(body.get("url", ""))
            if url.startswith(("http://", "https://")) and (
                    url in hub.known_urls() or url.startswith("https://ctftime.org/")):
                open_external(url)
                return self._json({"ok": True})
            return self._json({"error": "unknown url"}, 400)
        if path == "/api/mine":
            ok = hub.set_mine(str(body.get("id", "")), status=body.get("status"),
                              notes=body.get("notes"), place=body.get("place"), teams=body.get("teams"))
            return self._json({"ok": ok}, 200 if ok else 404)
        if path == "/api/close":
            hub.publish("close")
            return self._json({"ok": True, "clients": self.server.clients})
        if path == "/api/view":
            view = str(body.get("view", ""))
            if view in ("news", "ctf", "team"):
                hub.publish("view", view)
            return self._json({"ok": True, "clients": self.server.clients})
        if path == "/api/settings":
            clean = _clean_settings(body)
            write_settings(clean)
            hub.reload_config()
            hub.refresh_async()
            return self._json({"ok": True, "settings": read_settings()})
        return self._json({"error": "not found"}, 404)


def _clean_settings(body: dict) -> dict:
    out: dict = {}
    if "team_id" in body:
        raw = str(body.get("team_id") or "").strip()
        m = re.search(r"(\d+)\s*/?\s*$", raw)  # accept "12345" or a full ctftime team URL
        out["team_id"] = int(m.group(1)) if m else None
    if body.get("home_country"):
        cc = str(body["home_country"]).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", cc):
            out["home_country"] = cc
    if isinstance(body.get("watch_words"), list):
        out["watch_words"] = [str(w).strip()[:40] for w in body["watch_words"] if str(w).strip()][:30]
    if body.get("big_weight") not in (None, ""):
        try:
            out["big_weight"] = max(0.0, min(100.0, float(body["big_weight"])))
        except (TypeError, ValueError):
            pass
    if "timezone" in body:
        tz = str(body.get("timezone") or "").strip()
        out["timezone"] = tz if (tz == "" or get_tz(tz) is not None) else ""
    if "rank_country" in body:
        cc = str(body.get("rank_country") or "").strip().upper()
        out["rank_country"] = cc if re.fullmatch(r"[A-Z]{2}", cc) else ""
    if isinstance(body.get("opportunity_queries"), list):
        out["opportunity_queries"] = [str(q).strip()[:200] for q in body["opportunity_queries"] if str(q).strip()][:12]
    if isinstance(body.get("disabled_feeds"), list):
        out["disabled_feeds"] = [str(f) for f in body["disabled_feeds"]][:100]
    if isinstance(body.get("extra_feeds"), dict):
        feeds = {}
        for k, v in body["extra_feeds"].items():
            v = str(v).strip()
            if v.startswith(("http://", "https://")) and str(k).strip():
                feeds[str(k).strip()[:40]] = v
        out["extra_feeds"] = feeds
    return out


# ====================================================================== lifecycle

RUNTIME = state_path("server.json")


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def server_info(port: int, timeout: float = 0.6) -> dict | None:
    try:
        with _LOCAL.open(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            data = json.loads(r.read())
            return data if data.get("app") == "pwnwatch" else None
    except Exception:
        return None


def ping(port: int, timeout: float = 0.6) -> bool:
    return server_info(port, timeout) is not None


def post_local(port: int, path: str, body: dict) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with _LOCAL.open(req, timeout=3) as r:
        return json.loads(r.read())


def running_port() -> int | None:
    info = read_json(RUNTIME, {})
    for port in (info.get("port"), DEFAULT_PORT):
        if port and ping(int(port)):
            return int(port)
    return None


def serve(port: int = DEFAULT_PORT, offline: bool = False, keep_alive: bool = False,
          on_ready=None) -> None:
    hub = Hub(offline=offline)
    try:
        httpd = Server(port, hub, keep_alive)
    except OSError:
        httpd = Server(0, hub, keep_alive)  # port taken by something else
    port = httpd.server_address[1]
    write_json(RUNTIME, {"port": port, "pid": __import__("os").getpid()})

    def background():
        last = 0.0
        while True:
            if time.time() - last > REFRESH_EVERY:
                last = time.time()
                hub.refresh()
            idle = time.time() - httpd.last_beat
            if not httpd.keep_alive and httpd.clients == 0 and idle > IDLE_EXIT:
                httpd.shutdown()
                return
            time.sleep(5)

    threading.Thread(target=background, daemon=True).start()
    if on_ready:
        on_ready(port)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()


def launch_window(url: str) -> None:
    """Open the UI as an app window, the Omarchy way when available.

    Deliberately not omarchy-launch-or-focus-webapp: that focuses *any* window
    whose title contains "pwnwatch" (e.g. a terminal sitting in the pwnwatch
    folder) instead of opening ours. Whether our window is already open is
    known from the backend's live connections, so the caller decides that.
    """
    log = log_file()
    if shutil.which("omarchy-launch-webapp"):
        cmd = ["omarchy-launch-webapp", url]
    else:
        browser = next((b for b in ("chromium", "google-chrome-stable", "google-chrome",
                                    "brave", "brave-browser", "microsoft-edge-stable")
                        if shutil.which(b)), None)
        if not browser:
            webbrowser.open(url)
            return
        cmd = [browser, f"--app={url}", "--class=pwnwatch"]
    with open(log, "a") as fh:
        fh.write(f"{datetime.now():%F %T} launch: {' '.join(cmd)}\n")
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=fh, start_new_session=True)


def focus_window() -> bool:
    """Bring an already-open pwnwatch window to the front (Hyprland)."""
    if not shutil.which("hyprctl"):
        return False
    try:
        out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=5).stdout
        addr = next((c["address"] for c in json.loads(out or "[]")
                     if str(c.get("class", "")).startswith("chrome-127.0.0.1")), None)
        if not addr:
            return False
        for cmd in (["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{addr}" }})'],
                    ["hyprctl", "dispatch", "focuswindow", f"address:{addr}"]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower():
                return True
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return False


def log_file() -> Path:
    p = state_path("pwnwatch.log")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if p.stat().st_size > 512_000:
            p.write_text("")
    except OSError:
        pass
    return p
