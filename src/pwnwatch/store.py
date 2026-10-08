"""Tiny on-disk helpers: HTTP GET, JSON cache and 'seen' state."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, STATE_DIR, USER_AGENT


def http_get(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/json, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(path)


def cache_path(name: str) -> Path:
    return CACHE_DIR / name


def state_path(name: str) -> Path:
    return STATE_DIR / name


class SeenSet:
    """Remembers which links have been seen, so new stories can be marked."""

    def __init__(self, name: str = "seen.json", limit: int = 5000):
        self.path = state_path(name)
        self.limit = limit
        self.items: list[str] = read_json(self.path, [])
        self._set = set(self.items)

    def __contains__(self, key: str) -> bool:
        return key in self._set

    def add_many(self, keys) -> None:
        for k in keys:
            if k not in self._set:
                self._set.add(k)
                self.items.append(k)
        if len(self.items) > self.limit:
            self.items = self.items[-self.limit :]
            self._set = set(self.items)
        write_json(self.path, self.items)
