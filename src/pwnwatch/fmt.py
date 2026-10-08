"""Human-friendly formatting shared by the TUI and the CLI."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .countries import name_of
from .ctf import Event


def age(dt: datetime | None, now: datetime | None = None) -> str:
    if not dt:
        return "—"
    now = now or datetime.now(timezone.utc)
    s = int((now - dt).total_seconds())
    if s < 60:
        return "now"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    if s < 7 * 86400:
        return f"{s // 86400}d"
    return dt.astimezone().strftime("%b %d")


def day_label(dt: datetime | None) -> str:
    if not dt:
        return "Undated"
    d = dt.astimezone().date()
    today = datetime.now().astimezone().date()
    delta = (today - d).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return d.strftime("%A, %d %B")


def get_tz(name: str | None) -> tzinfo | None:
    """'' → None (system time); 'UTC+03:00' / 'UTC-5' → fixed offset; else IANA name."""
    name = (name or "").strip()
    if not name:
        return None
    m = re.fullmatch(r"(?:UTC|GMT)?\s*([+-−])\s*(\d{1,2})(?::?(\d{2}))?", name, re.I)
    if m:
        sign = -1 if m.group(1) in "-−" else 1
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))
        return timezone(sign * delta)
    if name.upper() in ("UTC", "GMT", "Z"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def when(e: Event, now: datetime | None = None, tz: tzinfo | None = None) -> str:
    """'Sat 10 Oct 10:00 · 48h', 'Nov 19–20', 'Aug 05–08 2027', 'TBA'."""
    if e.tba:
        return "TBA"
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    s = e.start_dt.astimezone(tz)
    f = (e.finish_dt or e.start_dt).astimezone(tz)
    year = f" {s.year}" if s.year != now.year else ""
    if e.source == "ctftime":
        hours = max(1, round((f - s).total_seconds() / 3600))
        dur = f"{hours}h" if hours < 72 else f"{round(hours / 24)}d"
        return f"{s:%a %d %b %H:%M}{year} · {dur}"
    if s.date() == f.date():
        return f"{s:%a %d %b}{year}"
    if s.month == f.month:
        return f"{s:%b %d}–{f:%d}{year}"
    return f"{s:%b %d} – {f:%b %d}{year}"


def countdown(e: Event, now: datetime | None = None, tz: tzinfo | None = None) -> str:
    if e.tba:
        return "dates not announced"
    now = now or datetime.now(timezone.utc)
    s, f = e.start_dt, e.finish_dt or e.start_dt
    if s <= now <= f:
        h = int((f - now).total_seconds() // 3600)
        return f"LIVE · ends in {h}h" if h < 48 else f"LIVE · ends in {h // 24}d"
    secs = int((s - now).total_seconds())
    if secs < 3600:
        return f"starts in {max(1, secs // 60)}m"
    if secs < 48 * 3600:
        return f"starts in {secs // 3600}h"
    days = (s.astimezone(tz).date() - now.astimezone(tz).date()).days
    if days < 60:
        return f"in {days} days"
    return f"in {days // 30} months"


def country_cell(e: Event) -> str:
    if e.country:
        return e.country
    return "INTL" if e.mode == "online" else "?"


def country_long(e: Event) -> str:
    if not e.country:
        return "International (organiser country unknown)" if e.mode == "online" else "Unknown"
    scope = "International · organised from " if e.mode == "online" else ""
    return f"{scope}{name_of(e.country)} ({e.country})"


def weight_cell(e: Event) -> str:
    if e.weight is None:
        return "—"
    return f"{e.weight:.2f}".rstrip("0").rstrip(".") if e.weight else "0"
