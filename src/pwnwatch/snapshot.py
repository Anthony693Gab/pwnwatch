"""One JSON shape for news + CTFs, shared by the web backend and the Omarchy panel.

`pwnwatch json` prints `snapshot()`: it reads only the local caches (never the
network) so the bar panel stays instant, and kicks off a background refresh
when the caches are stale.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from . import ctf, news
from .config import Config, read_settings
from .countries import name_of
from .fmt import country_cell, country_long, countdown, get_tz, when
from .store import SeenSet, read_json, state_path

SECTION_TITLES = {
    "past": "Ended",
    "week": "This week",
    "soon": "Next 4 weeks",
    "radar": "Further out",
    "later": "Later",
    "tba": "Dates not announced",
}


def tz_label(tz) -> str:
    off = datetime.now(timezone.utc).astimezone(tz).utcoffset() or timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "−"
    return f"UTC{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def event_range(e: ctf.Event, tz) -> str:
    if e.tba:
        return "dates not announced yet"
    s = e.start_dt.astimezone(tz)
    f = (e.finish_dt or e.start_dt).astimezone(tz)
    if e.source != "ctftime" and s.date() != f.date():
        return f"{s:%a %d %b} → {f:%a %d %b %Y}"
    return f"{s:%a %d %b, %H:%M} → {f:%a %d %b, %H:%M}"


def duration_label(e: ctf.Event) -> str:
    """'48h', '8h', '7d' for CTFtime; '1 day' / '4 days' for conferences."""
    if e.tba or e.hours is None:
        return ""
    if e.source != "ctftime":
        s, f = e.start_dt.astimezone(), (e.finish_dt or e.start_dt).astimezone()
        days = (f.date() - s.date()).days + 1
        return "1 day" if days == 1 else f"{days} days"
    h = e.hours
    if h < 1:
        return f"{round(h * 60)}m"
    if h <= 72:
        return f"{round(h)}h"
    return f"{round(h / 24)}d"


def _progress(e: ctf.Event, now: datetime) -> float | None:
    s, f = e.start_dt, e.finish_dt
    if not s or not f or not (s <= now <= f) or f == s:
        return None
    return round((now - s).total_seconds() / (f - s).total_seconds(), 3)


class EventContext:
    """Week boundaries etc. computed once per snapshot."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tz = get_tz(cfg.timezone)
        self.now = datetime.now(timezone.utc)
        self.lo, self.hi = ctf.week_bounds(tz=self.tz)
        self.soon_hi = self.hi + timedelta(days=28)

    def section(self, e: ctf.Event) -> str:
        if e.finish_dt and e.finish_dt < self.now:
            return "past"
        if ctf.overlaps(e, self.lo, self.hi):
            return "week"
        if e.tba:
            return "tba"
        if e.start_dt < self.soon_hi:
            return "soon"
        if e.is_big(self.cfg.big_weight):
            return "radar"
        return "later"

    def event_json(self, e: ctf.Event) -> dict:
        cfg, tz, now = self.cfg, self.tz, self.now
        s, f = e.start_dt, e.finish_dt
        return asdict(e) | {
            "id": e.id,
            "section": self.section(e),
            "when": when(e, tz=tz),
            "countdown": countdown(e, tz=tz),
            "country_cell": country_cell(e),
            "country_long": country_long(e),
            "country_name": name_of(e.country),
            "home": e.is_home(cfg.home_country),
            "big": e.is_big(cfg.big_weight),
            "live": bool(s and f and s <= now <= f),
            "day": s.astimezone(tz).strftime("%d") if s else "",
            "month": s.astimezone(tz).strftime("%b") if s else "TBA",
            "weekday": s.astimezone(tz).strftime("%a") if s else "",
            "year": s.astimezone(tz).year if s else None,
            "range": event_range(e, tz),
            "duration": duration_label(e),
            "hours": round(e.hours, 1) if e.hours is not None else None,
            "start_time": s.astimezone(tz).strftime("%H:%M") if s and e.source == "ctftime" else "",
            "ends": (f or s).astimezone(tz).strftime("%a %d %b, %H:%M") if s else "",
            "progress": _progress(e, now),
            "past": bool(f and f < now),
        }

    def week_label(self) -> list[str]:
        return [self.lo.strftime("%a %d %b"), (self.hi - timedelta(days=1)).strftime("%a %d %b")]


def article_json(a: dict, seen: SeenSet, saved: dict) -> dict:
    host = (urlparse(a["link"]).hostname or "").removeprefix("www.")
    return {
        "id": a["id"], "title": a["title"], "link": a["link"], "source": a["source"],
        "domain": host, "published": a.get("published"), "summary": a.get("summary", ""),
        "tags": a.get("tags", []), "watch": a.get("watch", False),
        "unread": a["link"] not in seen, "saved": a["id"] in saved,
    }


def snapshot(cfg: Config, max_news: int = 80) -> dict:
    """Everything the Omarchy panel needs, from caches only."""
    arts, fetched = news.load_cache()
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.news_days)
    arts = news.finalize([a for a in arts if not a.dt or a.dt >= cutoff], cfg)
    seen = SeenSet()
    saved = read_json(state_path("saved.json"), {})
    items = [article_json(asdict(a) | {"id": a.id}, seen, saved) for a in arts[:max_news]]

    events, _ = ctf.load_cached_merged(cfg)
    ctx = EventContext(cfg)
    evs = [ctx.event_json(e) for e in events]

    team = read_json(ctf.cache_path(ctf.TEAM_INFO_CACHE), {})
    rank_cc = (read_settings().get("rank_country") or (team.get("team") or {}).get("country")
               or cfg.home_country or "RO").upper()
    top = read_json(ctf.cache_path(f"top-{rank_cc}.json"), {}).get("rows")
    if top is None and team.get("country", "").upper() == rank_cc:
        top = team.get("top")

    return {
        "updated": fetched.isoformat() if fetched else None,
        "unread": sum(1 for i in items if i["unread"]),
        "week": ctx.week_label(),
        "weekCount": sum(1 for e in evs if e["section"] == "week"),
        "liveCount": sum(1 for e in evs if e["live"]),
        "tzLabel": tz_label(ctx.tz),
        "homeCountry": cfg.home_country,
        "bigWeight": cfg.big_weight,
        "news": items,
        "events": evs,
        "sections": SECTION_TITLES,
        "team": team.get("team"),
        "results": team.get("results") or [],
        "teamId": cfg.team_id,
        "rankCountry": rank_cc,
        "rankCountryName": name_of(rank_cc),
        "top": top or [],
    }
