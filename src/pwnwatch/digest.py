"""Daily digest: a desktop notification (mako on Omarchy) or plain text."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from . import ctf, news
from .config import Config
from .fmt import country_cell, countdown, get_tz, when
from .store import SeenSet


def build(cfg: Config, articles: list[news.Article], events: list[ctf.Event]) -> tuple[str, str, list[str]]:
    """Return (title, body, new_links) for the digest."""
    seen = SeenSet("digest-seen.json")
    fresh = [a for a in articles if a.link not in seen]
    # Watch-word stories first, then the most "interesting" tags, then newest.
    prio = {"0DAY": 0, "ARREST": 1, "RANSOM": 2, "BREACH": 3, "APT": 4}
    fresh.sort(key=lambda a: (not a.watch, min((prio.get(t, 9) for t in a.tags), default=9)))

    tz = get_tz(cfg.timezone)
    lo, hi = ctf.week_bounds(tz=tz)
    now = datetime.now(timezone.utc)
    week = [e for e in events if ctf.overlaps(e, lo, hi) and (e.finish_dt or e.start_dt) >= now]
    tomorrow = [e for e in events if e.start_dt and now <= e.start_dt <= now + timedelta(hours=36)]
    home_soon = [
        e for e in events
        if e.is_home(cfg.home_country) and e.start_dt and now <= e.start_dt <= now + timedelta(days=45)
    ]

    lines: list[str] = []
    for a in fresh[:6]:
        star = "★ " if a.watch else "• "
        lines.append(f"{star}{a.title}  ({a.source})")
    if len(fresh) > 6:
        lines.append(f"  …and {len(fresh) - 6} more")
    if tomorrow:
        lines.append("")
        lines.append("Starting soon:")
        lines += [f"⚑ {e.name} · {e.mode} · {countdown(e, tz=tz)}" for e in tomorrow[:4]]
    if week:
        lines.append("")
        lines.append(f"CTFs this week: {len(week)}")
        top = sorted(week, key=lambda e: -(e.weight or 0))[:4]
        lines += [f"  {e.name} · {when(e, tz=tz)} · {country_cell(e)}" for e in top]
    if home_soon:
        lines.append("")
        lines.append(f"In {cfg.home_country} soon:")
        lines += [f"★ {e.name} · {when(e, tz=tz)} · {countdown(e, tz=tz)}" for e in home_soon[:3]]

    title = f"pwnwatch · {len(fresh)} new stories · {len(week)} CTFs this week"
    return title, "\n".join(lines) or "Nothing new today.", [a.link for a in fresh]


def run(cfg: Config, print_only: bool = False) -> int:
    articles, errs = news.fetch_all(cfg)
    if articles:
        news.save_cache(articles)
    else:
        articles, _ = news.load_cache()
    events, _ = ctf.fetch_all(cfg)

    title, body, links = build(cfg, articles, events)
    if print_only or not shutil.which("notify-send"):
        print(title)
        print(body)
    else:
        subprocess.call(
            ["notify-send", "--app-name=pwnwatch", "--icon=security-high", "--expire-time=20000", title, body]
        )
    SeenSet("digest-seen.json").add_many(links)
    if errs:
        print("feed errors: " + "; ".join(f"{k}: {v}" for k, v in errs.items()))
    return 0
