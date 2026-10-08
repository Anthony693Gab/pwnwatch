"""CTFs and events: CTFtime API + curated list + user events."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone

from .config import Config
from .countries import code_from_location
from .events import CURATED
from .store import cache_path, http_get, read_json, state_path, write_json

CTFTIME_EVENTS = "https://ctftime.org/api/v1/events/?limit={limit}&start={start}&finish={finish}"
CTFTIME_TEAM = "https://ctftime.org/api/v1/teams/{id}/"
CTF_CACHE = "ctf.json"
TEAM_CACHE = "teams.json"


@dataclass
class Event:
    name: str
    start: str | None = None  # ISO 8601 (UTC) or None = TBA
    finish: str | None = None
    url: str = ""
    ctftime_url: str = ""
    mode: str = "online"  # online | onsite | hybrid
    weight: float | None = None
    country: str = ""  # ISO-3166 alpha-2
    location: str = ""
    format: str = ""
    organizers: str = ""
    restrictions: str = ""
    participants: int | None = None
    kind: str = "ctf"  # ctf | conference
    source: str = "ctftime"  # ctftime | curated | config
    note: str = ""
    description: str = ""
    logo: str = ""
    ctftime_id: int | None = None

    @property
    def id(self) -> str:
        # CTFtime ids survive date changes; curated/config events hash name+start.
        if self.ctftime_id:
            return f"ct{self.ctftime_id}"
        return hashlib.sha1(self.key.encode()).hexdigest()[:12]

    @property
    def hours(self) -> float | None:
        if not self.start_dt or not self.finish_dt:
            return None
        return max(0.0, (self.finish_dt - self.start_dt).total_seconds() / 3600)

    @property
    def start_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.start) if self.start else None

    @property
    def finish_dt(self) -> datetime | None:
        if self.finish:
            return datetime.fromisoformat(self.finish)
        return self.start_dt

    @property
    def tba(self) -> bool:
        return self.start is None

    @property
    def key(self) -> str:
        return f"{self.name}|{self.start}"

    def is_big(self, threshold: float) -> bool:
        return self.source != "ctftime" or (self.weight or 0) >= threshold

    def is_home(self, home: str) -> bool:
        return bool(home) and self.country.upper() == home.upper()


# ---------------------------------------------------------------- week helpers


def week_bounds(now: datetime | None = None, tz=None) -> tuple[datetime, datetime]:
    """Monday 00:00 → next Monday 00:00 in `tz` (default: system time)."""
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    monday = (now - timedelta(days=now.weekday())).date()
    start = datetime.combine(monday, time.min, tzinfo=now.tzinfo)
    return start, start + timedelta(days=7)


def overlaps(e: Event, lo: datetime, hi: datetime) -> bool:
    s, f = e.start_dt, e.finish_dt
    return bool(s and f and s < hi and f >= lo)


# ---------------------------------------------------------------- CTFtime


def _team_countries(ids: set[int]) -> dict[str, str]:
    """Look up organiser team countries, cached forever on disk."""
    cache: dict[str, str] = read_json(cache_path(TEAM_CACHE), {})
    missing = [i for i in ids if str(i) not in cache]

    def job(tid: int):
        try:
            data = json.loads(http_get(CTFTIME_TEAM.format(id=tid), timeout=10))
            return tid, (data.get("country") or "").upper()
        except Exception:
            return tid, None

    if missing:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for tid, country in pool.map(job, missing[:80]):
                if country is not None:
                    cache[str(tid)] = country
        write_json(cache_path(TEAM_CACHE), cache)
    return cache


def parse_ctftime(items: list[dict], team_country: dict[str, str] | None = None) -> list[Event]:
    team_country = team_country or {}
    out = []
    for d in items:
        orgs = d.get("organizers") or []
        onsite = bool(d.get("onsite"))
        location = (d.get("location") or "").strip()
        country = code_from_location(location) if onsite else ""
        if not country:
            for o in orgs:
                c = team_country.get(str(o.get("id")), "")
                if c:
                    country = c
                    break
        out.append(
            Event(
                name=(d.get("title") or "?").strip(),
                start=_iso(d.get("start")),
                finish=_iso(d.get("finish")),
                url=(d.get("url") or "").strip(),
                ctftime_url=d.get("ctftime_url") or "",
                mode="onsite" if onsite else "online",
                weight=float(d["weight"]) if d.get("weight") not in (None, "") else None,
                country=country,
                location=location,
                format=d.get("format") or "",
                organizers=", ".join(o.get("name", "") for o in orgs),
                restrictions=d.get("restrictions") or "",
                participants=d.get("participants"),
                description=(d.get("description") or "").strip()[:900],
                logo=(d.get("logo") or "").strip(),
                ctftime_id=d.get("id"),
            )
        )
    return out


PAST_DAYS = 60


def fetch_ctftime(cfg: Config) -> list[Event]:
    """Upcoming events (incl. long ones already running) plus the last PAST_DAYS days."""
    now = datetime.now(timezone.utc)

    def window(lo: datetime, hi: datetime, limit: int) -> list[dict]:
        url = CTFTIME_EVENTS.format(limit=limit, start=int(lo.timestamp()), finish=int(hi.timestamp()))
        return json.loads(http_get(url))

    items = window(now - timedelta(days=10), now + timedelta(days=cfg.ctf_days_ahead), 300)
    try:
        items += window(now - timedelta(days=PAST_DAYS), now - timedelta(days=10), 200)
    except Exception:
        pass  # the past is nice to have; never lose upcoming events over it
    seen, uniq = set(), []
    for d in items:
        key = d.get("id") or (d.get("title"), d.get("start"))
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    ids = {o["id"] for d in uniq for o in (d.get("organizers") or []) if "id" in o}
    return parse_ctftime(uniq, _team_countries(ids))


# ---------------------------------------------------------------- curated / config


def _iso(v) -> str | None:
    if not v:
        return None
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, date):
        dt = datetime.combine(v, time(9, 0))
    else:
        s = str(v).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s if "T" in s or " " in s else s + "T09:00:00")
    if dt.tzinfo is None:
        dt = dt.astimezone()  # treat naive as local time
    return dt.astimezone(timezone.utc).isoformat()


def _from_dict(d: dict, source: str) -> Event:
    start = _iso(d.get("start"))
    end = d.get("end") or d.get("finish")
    finish = _iso(end)
    if finish and end and len(str(end)) == 10:  # whole day: end of that day
        finish = (datetime.fromisoformat(finish) + timedelta(hours=10)).isoformat()
    return Event(
        name=str(d.get("name", "?")),
        start=start,
        finish=finish or start,
        url=str(d.get("url", "")),
        mode=str(d.get("mode", "onsite")).lower(),
        country=str(d.get("country", "")).upper(),
        location=str(d.get("location", "")),
        format=str(d.get("format", "")),
        kind=str(d.get("kind", "ctf")),
        source=source,
        note=str(d.get("note", "")),
        weight=float(d["weight"]) if d.get("weight") else None,
    )


def curated_events(cfg: Config) -> list[Event]:
    evs = [_from_dict(d, "curated") for d in CURATED]
    for d in cfg.events:
        try:
            evs.append(_from_dict(d, "config"))
        except (ValueError, TypeError):
            continue
    return evs


# ---------------------------------------------------------------- merge + cache


def merge(ctftime: list[Event], extra: list[Event]) -> list[Event]:
    now = datetime.now(timezone.utc)
    names = {e.name.lower() for e in ctftime}
    out = [e for e in ctftime]
    out += [e for e in extra if e.name.lower() not in names]
    out = [e for e in out if e.tba or (e.finish_dt and e.finish_dt >= now - timedelta(days=PAST_DAYS))]
    far = datetime(9999, 1, 1, tzinfo=timezone.utc)
    out.sort(key=lambda e: e.start_dt or far)
    return out


def fetch_all(cfg: Config) -> tuple[list[Event], str | None]:
    err = None
    try:
        ctfs = fetch_ctftime(cfg)
        note_first_seen(ctfs)
        write_json(
            cache_path(CTF_CACHE),
            {"fetched": datetime.now(timezone.utc).isoformat(), "events": [asdict(e) for e in ctfs]},
        )
    except Exception as exc:
        err = f"CTFtime: {type(exc).__name__}: {exc}"
        ctfs, _ = load_cache()
    return merge(ctfs, curated_events(cfg)), err


FIRST_SEEN = "ctf-first-seen.json"


def note_first_seen(events: list[Event]) -> dict[str, str]:
    """Remember when each CTFtime event first showed up, to surface 'new on CTFtime'.
    On the very first run everything is marked as old so the news isn't flooded."""
    path = state_path(FIRST_SEEN)
    known: dict[str, str] = read_json(path, {})
    stamp = datetime.now(timezone.utc).isoformat() if known else "1970-01-01T00:00:00+00:00"
    changed = False
    for e in events:
        if e.ctftime_id and e.id not in known:
            known[e.id] = stamp
            changed = True
    if changed or not path.exists():
        write_json(path, known)
    return known


def first_seen() -> dict[str, str]:
    return read_json(state_path(FIRST_SEEN), {})


def load_cache() -> tuple[list[Event], datetime | None]:
    raw = read_json(cache_path(CTF_CACHE), {})
    evs = []
    for d in raw.get("events", []):
        try:
            evs.append(Event(**d))
        except TypeError:
            continue
    f = raw.get("fetched")
    return evs, datetime.fromisoformat(f) if f else None


def load_cached_merged(cfg: Config) -> tuple[list[Event], datetime | None]:
    ctfs, fetched = load_cache()
    return merge(ctfs, curated_events(cfg)), fetched


# ---------------------------------------------------------------- your team
# CTFtime has no API keys or personal tokens: the API is public and read-only.
# Personalisation works through your public team ID (ctftime.org/team/<ID>).

CTFTIME_TOP_COUNTRY = "https://ctftime.org/api/v1/top-by-country/{cc}/"
CTFTIME_RESULTS = "https://ctftime.org/api/v1/results/{year}/"
TEAM_INFO_CACHE = "team.json"


def parse_team(data: dict, year: int) -> dict:
    rating = (data.get("rating") or {}).get(str(year)) or {}
    return {
        "id": data.get("id"),
        "name": data.get("name") or data.get("primary_alias") or "?",
        "country": (data.get("country") or "").upper(),
        "logo": data.get("logo") or "",
        "academic": bool(data.get("academic")),
        "aliases": data.get("aliases") or [],
        "year": year,
        "place": rating.get("rating_place"),
        "points": rating.get("rating_points"),
        "country_place": rating.get("country_place"),
        "url": f"https://ctftime.org/team/{data.get('id')}",
    }


def parse_results(results: dict, team_id: int, limit: int = 8) -> list[dict]:
    """Pick this team's placings out of /api/v1/results/{year}/."""
    out = []
    for event_id, ev in (results or {}).items():
        for sc in ev.get("scores") or []:
            if int(sc.get("team_id", -1)) == int(team_id):
                out.append({
                    "event_id": int(event_id),
                    "title": ev.get("title", "?"),
                    "place": sc.get("place"),
                    "points": sc.get("points"),
                    "teams": len(ev.get("scores") or []),
                    "time": ev.get("time"),
                    "url": f"https://ctftime.org/event/{event_id}",
                })
                break
    out.sort(key=lambda r: r.get("time") or 0, reverse=True)
    return out[:limit]


def parse_top_country(data, cc: str, limit: int = 10) -> list[dict]:
    rows = data if isinstance(data, list) else (data or {}).get(cc.upper(), [])
    out = []
    for r in rows[:limit]:
        out.append({
            "id": r.get("team_id") or r.get("id"),
            "name": r.get("team_name") or r.get("name") or "?",
            "points": r.get("points"),
            "place": r.get("place"),
            "country_place": r.get("country_place"),
        })
    return out


def fetch_team(team_id: int | None, country: str) -> tuple[dict, str | None]:
    """Team card + recent results + national top 10. Never raises."""
    year = datetime.now().year
    info: dict = {"team": None, "results": [], "top": [], "country": country.upper()}
    errors = []
    if team_id:
        try:
            info["team"] = parse_team(json.loads(http_get(CTFTIME_TEAM.format(id=team_id))), year)
        except Exception as exc:
            errors.append(f"team {team_id}: {exc}")
        try:
            res = json.loads(http_get(CTFTIME_RESULTS.format(year=year), timeout=25))
            info["results"] = parse_results(res, team_id)
        except Exception as exc:
            errors.append(f"results: {exc}")
    if country:
        try:
            info["top"] = parse_top_country(
                json.loads(http_get(CTFTIME_TOP_COUNTRY.format(cc=country.lower()))), country
            )
        except Exception as exc:
            errors.append(f"top {country}: {exc}")
    if info["team"] or info["top"]:
        write_json(cache_path(TEAM_INFO_CACHE), info)
    else:
        info = read_json(cache_path(TEAM_INFO_CACHE), info)
    return info, ("; ".join(errors) or None)


def fetch_top_country(cc: str, max_age: int = 6 * 3600) -> tuple[list[dict], str | None]:
    """National leaderboard for any country, cached per country."""
    import time as _time

    cc = cc.upper()
    path = cache_path(f"top-{cc}.json")
    cached = read_json(path, {})
    if cached.get("rows") is not None and _time.time() - cached.get("t", 0) < max_age:
        return cached["rows"], None
    try:
        data = json.loads(http_get(CTFTIME_TOP_COUNTRY.format(cc=cc.lower())))
        rows = parse_top_country(data, cc, limit=50)
        write_json(path, {"t": _time.time(), "rows": rows})
        return rows, None
    except Exception as exc:
        return cached.get("rows") or [], f"{type(exc).__name__}: {exc}"
