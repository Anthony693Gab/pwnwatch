"""Paths, defaults and the user config file (~/.config/pwnwatch/config.toml)."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP = "pwnwatch"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) pwnwatch/0.1"


def _xdg(var: str, fallback: str) -> Path:
    base = os.environ.get(var) or str(Path.home() / fallback)
    return Path(base) / APP


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config")
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache")
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state")
CONFIG_FILE = CONFIG_DIR / "config.toml"

# Well-known, English-language security news feeds. Override or extend in config.toml.
DEFAULT_FEEDS: dict[str, str] = {
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "The Record": "https://therecord.media/feed",
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "SecurityWeek": "https://www.securityweek.com/feed/",
    "Dark Reading": "https://www.darkreading.com/rss.xml",
    "Help Net Security": "https://www.helpnetsecurity.com/feed/",
    "DataBreaches.net": "https://databreaches.net/feed/",
    "CISA Advisories": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
}

# News searches for competitions and programs that security news sites rarely cover.
# "ro:" searches Romanian-language news (any 2-letter language code works).
DEFAULT_OPPORTUNITY_QUERIES = [
    '"capture the flag" competition',
    "CTF cybersecurity competition registration",
    "cybersecurity hackathon OR scholarship OR olympiad students",
    'ro:concurs securitate cibernetică OR "capture the flag"',
]

DEFAULT_CONFIG_TEXT = """\
# pwnwatch configuration
# Everything here is optional; delete a key to fall back to the default.

# ISO-3166 code of your country. Events and news from here get highlighted.
home_country = "RO"

# Your CTFtime team ID (the number in https://ctftime.org/team/<ID>).
# CTFtime has no API keys; the public team ID is all pwnwatch needs to show
# your team's rating, recent results and the national leaderboard.
# ctftime_team_id = 12345

# Timezone for CTF start/end times. Empty = your system time.
# Accepts an IANA name ("Europe/Bucharest") or a fixed offset ("UTC+03:00").
# timezone = "UTC"

# How many days of news to keep in the News tab.
news_days = 7

# How far ahead to pull CTFs from CTFtime (days).
ctf_days_ahead = 120

# CTFtime weight from which a CTF counts as a "big" event.
big_weight = 50.0

# Extra words that tag a story as relevant to you (case-insensitive).
watch_words = ["Romania", "Romanian", "Bucharest", "Bitdefender", "DNSC"]

# Add or replace news feeds. Feeds listed here are merged with the defaults;
# set a default feed to "" to disable it.
[feeds]
# "My Blog" = "https://example.com/feed.xml"
# "Dark Reading" = ""

# Your own events (conferences, local CTFs, meetups). They show in the CTF tab.
# [[events]]
# name     = "My university CTF"
# start    = "2026-12-05"          # leave out start/end for "dates TBA"
# end      = "2026-12-06"
# mode     = "onsite"              # online | onsite | hybrid
# country  = "RO"
# location = "Cluj-Napoca"
# url      = "https://example.com/register"
# kind     = "ctf"                 # ctf | conference
# note     = "Free registration until Nov 30"
"""


@dataclass
class Config:
    feeds: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FEEDS))
    home_country: str = "RO"
    news_days: int = 7
    ctf_days_ahead: int = 120
    big_weight: float = 50.0
    watch_words: list[str] = field(
        default_factory=lambda: ["Romania", "Romanian", "Bucharest", "Bitdefender", "DNSC"]
    )
    events: list[dict] = field(default_factory=list)
    team_id: int | None = None
    disabled_feeds: list[str] = field(default_factory=list)
    timezone: str = ""  # "" = system time; IANA name ("Europe/Bucharest") or "UTC+03:00"
    opportunity_queries: list[str] = field(default_factory=lambda: list(DEFAULT_OPPORTUNITY_QUERIES))


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, CACHE_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> Config:
    ensure_dirs()
    path = path or CONFIG_FILE
    if not path.exists():
        try:
            path.write_text(DEFAULT_CONFIG_TEXT)
        except OSError:
            pass
        return apply_settings(Config())

    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        cfg = Config()
        cfg.events = [{"name": f"config.toml error: {exc}", "kind": "note"}]
        return apply_settings(cfg)

    cfg = Config()
    feeds = dict(DEFAULT_FEEDS)
    for name, url in (raw.get("feeds") or {}).items():
        if url:
            feeds[name] = url
        else:
            feeds.pop(name, None)
    cfg.feeds = feeds
    cfg.home_country = str(raw.get("home_country", cfg.home_country)).upper()
    cfg.news_days = int(raw.get("news_days", cfg.news_days))
    cfg.ctf_days_ahead = int(raw.get("ctf_days_ahead", cfg.ctf_days_ahead))
    cfg.big_weight = float(raw.get("big_weight", cfg.big_weight))
    cfg.watch_words = list(raw.get("watch_words", cfg.watch_words))
    cfg.events = list(raw.get("events", []))
    cfg.timezone = str(raw.get("timezone", "") or "")
    if isinstance(raw.get("opportunity_queries"), list):
        cfg.opportunity_queries = [str(q) for q in raw["opportunity_queries"]]
    tid = raw.get("ctftime_team_id")
    cfg.team_id = int(tid) if tid else None
    return apply_settings(cfg)


# ---------------------------------------------------------------- UI settings
# The settings panel writes JSON here; it is applied on top of config.toml.

SETTINGS_FILE = STATE_DIR / "settings.json"
SETTINGS_KEYS = ("team_id", "home_country", "watch_words", "big_weight",
                 "disabled_feeds", "extra_feeds", "news_days", "timezone", "rank_country",
                 "opportunity_queries")


def read_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def write_settings(data: dict) -> dict:
    cur = read_settings()
    for k in SETTINGS_KEYS:
        if k in data:
            cur[k] = data[k]
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(cur, indent=1))
    return cur


def apply_settings(cfg: Config) -> Config:
    st = read_settings()
    if st.get("team_id") not in (None, ""):
        try:
            cfg.team_id = int(st["team_id"]) or None
        except (TypeError, ValueError):
            pass
    elif "team_id" in st:
        cfg.team_id = None
    if st.get("home_country"):
        cfg.home_country = str(st["home_country"]).upper()[:2]
    if isinstance(st.get("watch_words"), list):
        cfg.watch_words = [str(w) for w in st["watch_words"] if str(w).strip()]
    if st.get("big_weight") not in (None, ""):
        cfg.big_weight = float(st["big_weight"])
    if st.get("news_days"):
        cfg.news_days = int(st["news_days"])
    for name, url in (st.get("extra_feeds") or {}).items():
        if url:
            cfg.feeds[str(name)] = str(url)
    cfg.disabled_feeds = [str(f) for f in st.get("disabled_feeds") or []]
    if "timezone" in st:
        cfg.timezone = str(st.get("timezone") or "")
    if isinstance(st.get("opportunity_queries"), list):
        cfg.opportunity_queries = [str(q) for q in st["opportunity_queries"] if str(q).strip()]
    return cfg


def active_feeds(cfg: Config) -> dict[str, str]:
    return {k: v for k, v in cfg.feeds.items() if k not in cfg.disabled_feeds}
