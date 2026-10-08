"""Background refresh helpers, and cleanup of the bar integrations older versions installed.

pwnwatch is a plain app now. Versions 0.3/0.4 added things to the Omarchy bar:
  * 0.3: a "command" module with id "pwnwatch" in ~/.config/omarchy/shell.json
         and a Hyprland rule (~/.config/hypr/pwnwatch.lua, required from hyprland.lua)
  * 0.4: a shell plugin in ~/.config/omarchy/plugins/pwnwatch.panel
`cleanup()` removes all of them and leaves the rest of your config untouched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ctf, news
from .config import Config
from .store import state_path

HOME = Path.home()
SHELL_JSON = HOME / ".config/omarchy/shell.json"
CREATED_MARK = SHELL_JSON.with_suffix(".json.pwnwatch-created")
HYPR_DIR = HOME / ".config/hypr"
PLUGIN_DIR = HOME / ".config/omarchy/plugins/pwnwatch.panel"
LEGACY_IDS = ("pwnwatch", "pwnwatch.panel")
MARK = "-- pwnwatch (added by `pwnwatch omarchy`)"


# ================================================================== background refresh


def maybe_refresh_in_background(fetched: datetime | None, max_age: int = 45 * 60) -> None:
    """Start `pwnwatch refresh` detached when the cache is stale (at most every 5 min)."""
    age = (datetime.now(timezone.utc) - fetched).total_seconds() if fetched else 1e9
    lock = state_path("refresh.lock")
    if age < max_age:
        return
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < 300:
            return
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
    except OSError:
        return
    subprocess.Popen([sys.executable, "-m", "pwnwatch", "refresh"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def refresh_caches(cfg: Config) -> None:
    from .server import post_local, running_port

    port = running_port()
    if port:  # let the live backend do it so the open window updates too
        post_local(port, "/api/refresh", {})
        return
    try:
        arts, _ = news.fetch_all(cfg)
        if arts:
            news.save_cache(arts)
        ctf.fetch_all(cfg)
        ctf.fetch_team(cfg.team_id, cfg.home_country)
    finally:
        try:
            state_path("refresh.lock").unlink()
        except OSError:
            pass


# ================================================================== cleanup of old bar integrations


def _ipc(*args: str) -> bool:
    if not shutil.which("omarchy-shell"):
        return False
    try:
        r = subprocess.run(["omarchy-shell", "shell", *args], capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def strip_bar_entries(cfg: dict) -> tuple[dict, bool]:
    """Remove pwnwatch entries from a shell.json dict. Returns (cfg, changed)."""
    changed = False
    layout = ((cfg or {}).get("bar") or {}).get("layout") or {}
    for sec, entries in list(layout.items()):
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not (isinstance(e, dict) and e.get("id") in LEGACY_IDS)]
        if len(kept) != len(entries):
            layout[sec] = kept
            changed = True
    plugins = (cfg or {}).get("plugins")
    if isinstance(plugins, list):
        kept = [p for p in plugins if not (isinstance(p, dict) and p.get("id") in LEGACY_IDS)]
        if len(kept) != len(plugins):
            cfg["plugins"] = kept
            changed = True
    return cfg, changed


def remove_hypr_rule(hypr_dir: Path | None = None) -> bool:
    d = hypr_dir or HYPR_DIR
    removed = False
    main = d / "hyprland.lua"
    if main.is_file():
        text = main.read_text()
        if MARK in text or "hypr.pwnwatch" in text:
            out = [ln for ln in text.splitlines() if ln.strip() != MARK and "hypr.pwnwatch" not in ln]
            main.write_text("\n".join(out).rstrip("\n") + "\n")
            removed = True
    rule = d / "pwnwatch.lua"
    if rule.exists():
        rule.unlink()
        removed = True
    return removed


def cleanup(shell_json: Path | None = None, plugin_dir: Path | None = None,
            hypr_dir: Path | None = None) -> list[str]:
    shell_json = shell_json or SHELL_JSON
    plugin_dir = plugin_dir or PLUGIN_DIR
    msgs: list[str] = []

    if plugin_dir.exists():
        _ipc("setPluginEnabled", "pwnwatch.panel", "false")
        shutil.rmtree(plugin_dir, ignore_errors=True)
        msgs.append(f"removed the bar plugin ({plugin_dir})")

    if shell_json.is_file():
        try:
            cfg = json.loads(shell_json.read_text())
            cfg, changed = strip_bar_entries(cfg)
            marker = shell_json.with_suffix(".json.pwnwatch-created")
            if changed:
                tmp = shell_json.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
                tmp.replace(shell_json)
                msgs.append("removed the pwnwatch icon from the bar layout")
            for extra in (marker, shell_json.with_suffix(".json.pwnwatch-backup")):
                extra.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            msgs.append(f"could not edit {shell_json}: {exc}")

    if remove_hypr_rule(hypr_dir):
        if shutil.which("hyprctl"):
            subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=10)
        msgs.append("removed the old Hyprland window rule")

    if msgs:
        _ipc("reloadConfig") or _ipc("rescanPlugins")
    return msgs
