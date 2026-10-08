"""Offline tests: parsing, tagging, countries, week maths, digest."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Keep tests away from the real ~/.config / ~/.cache.
_tmp = tempfile.mkdtemp()
for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
    os.environ[var] = _tmp

from pwnwatch import ctf, digest, news  # noqa: E402
from pwnwatch.config import Config  # noqa: E402
from pwnwatch.countries import code_from_location  # noqa: E402
from pwnwatch.fmt import country_cell, when  # noqa: E402

NOW = datetime.now(timezone.utc)


def rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


RSS = f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>Feed</title>
<item><title>Romanian teen behind KillSec ransomware gang arrested</title>
 <link>https://example.com/a</link><pubDate>{rfc822(NOW - timedelta(hours=2))}</pubDate>
 <description><![CDATA[<p>Police in <b>Bucharest</b> detained a 16-year-old&#8230;</p>]]></description></item>
<item><title>Chrome zero-day CVE-2026-1234 exploited in the wild</title>
 <link>https://example.com/b</link><pubDate>{rfc822(NOW - timedelta(days=1))}</pubDate></item>
<item><title>Old story</title><link>https://example.com/old</link>
 <pubDate>{rfc822(NOW - timedelta(days=30))}</pubDate></item>
</channel></rss>""".encode()

ATOM = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>APT29 phishing campaign targets diplomats</title>
 <link rel="alternate" href="https://example.org/x"/>
 <updated>{(NOW - timedelta(hours=5)).isoformat().replace('+00:00', 'Z')}</updated>
 <summary>Nation-state espionage.</summary></entry>
</feed>""".encode()


def test_parse_rss_and_atom():
    rss = news.parse_feed("RSS", RSS)
    atom = news.parse_feed("Atom", ATOM)
    assert [a.link for a in rss] == ["https://example.com/a", "https://example.com/b", "https://example.com/old"]
    assert "Bucharest" in rss[0].summary and "<" not in rss[0].summary
    assert atom[0].link == "https://example.org/x" and atom[0].dt is not None


def test_finalize_tags_dedupes_and_drops_old():
    cfg = Config()
    arts = news.parse_feed("RSS", RSS) + news.parse_feed("RSS2", RSS) + news.parse_feed("Atom", ATOM)
    out = news.finalize(arts, cfg)
    assert len(out) == 3  # 2 unique recent RSS + 1 atom; duplicates and old story gone
    killsec = next(a for a in out if "KillSec" in a.title)
    assert {"RANSOM", "ARREST"} <= set(killsec.tags) and killsec.watch
    chrome = next(a for a in out if "Chrome" in a.title)
    assert {"0DAY", "CVE"} <= set(chrome.tags) and not chrome.watch
    assert out[0].dt >= out[1].dt >= out[2].dt


@pytest.mark.parametrize(
    "loc,code",
    [("Bucharest, Romania", "RO"), ("Las Vegas, NV, USA", "US"), ("Online", ""),
     ("Cluj-Napoca", "RO"), ("Seoul, South Korea", "KR"), ("Taipei", "TW"), ("", "")],
)
def test_country_from_location(loc, code):
    assert code_from_location(loc) == code


def ctftime_item(title, start, hours, onsite=False, location="", weight=25.0, org_id=1):
    return {
        "title": title, "url": f"https://{title.lower().replace(' ', '')}.ctf",
        "ctftime_url": "https://ctftime.org/event/1/", "start": start.isoformat(),
        "finish": (start + timedelta(hours=hours)).isoformat(), "onsite": onsite,
        "location": location, "weight": weight, "format": "Jeopardy",
        "organizers": [{"id": org_id, "name": "team"}], "restrictions": "Open", "participants": 300,
    }


def sample_events(cfg: Config):
    lo, hi = ctf.week_bounds()
    mid = lo + (hi - lo) / 2
    items = [
        ctftime_item("Live Now CTF", NOW - timedelta(hours=3), 24, org_id=7),
        ctftime_item("Weekend CTF", max(mid, NOW + timedelta(hours=2)), 36, weight=55.2),
        ctftime_item("Bucharest Onsite Finals", NOW + timedelta(days=20), 10, onsite=True,
                     location="Bucharest, Romania", weight=0),
        ctftime_item("Far Big CTF", NOW + timedelta(days=90), 48, weight=80),
        ctftime_item("Already Over", NOW - timedelta(days=3), 5),
    ]
    evs = ctf.parse_ctftime(items, {"7": "RO", "1": "PL"})
    return ctf.merge(evs, ctf.curated_events(cfg))


def test_ctf_parsing_and_merge():
    cfg = Config()
    evs = sample_events(cfg)
    names = [e.name for e in evs]
    over = next(e for e in evs if e.name == "Already Over")  # kept for the Past tab
    assert over.finish_dt < NOW
    live = next(e for e in evs if e.name == "Live Now CTF")
    assert live.country == "RO" and live.mode == "online" and live.is_home("RO")
    onsite = next(e for e in evs if e.name == "Bucharest Onsite Finals")
    assert onsite.country == "RO" and onsite.mode == "onsite"
    assert any(e.name == "DEF CON 35" and e.start_dt.year == 2027 for e in evs)
    assert any(e.tba and "Olimpiada" in e.name for e in evs)
    assert any(not e.tba and "Bitdefender" in e.name for e in evs)
    lo, hi = ctf.week_bounds()
    assert ctf.overlaps(live, lo, hi)
    assert country_cell(next(e for e in evs if e.name == "Weekend CTF")) == "PL"


def test_when_formats():
    cfg = Config()
    dc = next(e for e in ctf.curated_events(cfg) if e.name == "DEF CON 35")
    assert when(dc) == "Aug 05–08 2027"
    tba = next(e for e in ctf.curated_events(cfg) if e.tba)
    assert when(tba) == "TBA"


def test_config_events_and_feed_override(tmp_path):
    from pwnwatch.config import load_config

    p = tmp_path / "c.toml"
    p.write_text(
        'home_country = "ro"\n[feeds]\n"Dark Reading" = ""\n"Mine" = "https://x/feed"\n'
        '[[events]]\nname = "Uni CTF"\nstart = 2027-01-10\nend = 2027-01-11\nmode = "onsite"\ncountry = "RO"\n'
    )
    cfg = load_config(p)
    assert cfg.home_country == "RO" and "Dark Reading" not in cfg.feeds and "Mine" in cfg.feeds
    uni = next(e for e in ctf.curated_events(cfg) if e.name == "Uni CTF")
    assert uni.source == "config" and uni.start_dt.year == 2027


def test_digest_build():
    cfg = Config()
    arts = news.finalize(news.parse_feed("RSS", RSS) + news.parse_feed("Atom", ATOM), cfg)
    title, body, links = digest.build(cfg, arts, sample_events(cfg))
    assert "3 new stories" in title
    assert body.splitlines()[0].startswith("★ Romanian teen")  # watch word first
    assert "CTFs this week" in body and len(links) == 3
