"""Read the active Omarchy theme so the app always matches the desktop.

Omarchy keeps the current theme at ~/.local/state/omarchy/current/theme (older
releases: ~/.config/omarchy/current/theme). Each theme has a colors.toml with
semantic keys (accent, background, foreground, red, …). Themes that predate
colors.toml are read from their alacritty.toml instead.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tomllib
from pathlib import Path

HOME = Path.home()
THEME_DIRS = [
    HOME / ".local/state/omarchy/current/theme",
    HOME / ".config/omarchy/current/theme",
]

# Tokyo Night — Omarchy's default — used when no theme can be found.
FALLBACK = {
    "mode": "dark", "accent": "#7aa2f7", "selection": "#292e42", "muted": "#414868",
    "background": "#1a1b26", "dark_background": "#13141c", "lighter_background": "#24283b",
    "foreground": "#a9b1d6", "dark_foreground": "#565f89", "bright_foreground": "#c0caf5",
    "red": "#f7768e", "yellow": "#e0af68", "orange": "#eb927b", "green": "#9ece6a",
    "cyan": "#449dab", "blue": "#7aa2f7", "magenta": "#ad8ee6",
}

LEGACY = {"bg": "background", "fg": "foreground", "dark_bg": "dark_background",
          "lighter_bg": "lighter_background", "dark_fg": "dark_foreground",
          "bright_fg": "bright_foreground"}
ANSI = {"color0": "background", "color1": "red", "color2": "green", "color3": "yellow",
        "color4": "blue", "color5": "magenta", "color6": "cyan", "color7": "foreground",
        "color8": "dark_foreground"}
NORMAL = {"black": "color0", "red": "color1", "green": "color2", "yellow": "color3",
          "blue": "color4", "magenta": "color5", "cyan": "color6", "white": "color7"}


def _hex(v) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip().strip("'\"")
    if v.startswith("0x"):
        v = "#" + v[2:]
    if len(v) == 7 and v.startswith("#"):
        try:
            int(v[1:], 16)
            return v.lower()
        except ValueError:
            return None
    return None


def mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = (int(a[i : i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(
        round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t)
    )


def _luminance(h: str) -> int:
    return sum(int(h[i : i + 2], 16) for i in (1, 3, 5))


def _from_colors_toml(path: Path) -> dict:
    raw = tomllib.loads(path.read_text())
    out: dict = {}
    for k, v in raw.items():
        key = LEGACY.get(k, k)
        if key == "mode" or key == "theme_type":
            out["mode"] = str(v)
            continue
        h = _hex(v)
        if h:
            out.setdefault(key, h)
    for k, target in ANSI.items():
        if k in out:
            out.setdefault(target, out[k])
    return out


def _from_alacritty(path: Path) -> dict:
    raw = tomllib.loads(path.read_text()).get("colors", {})
    out: dict = {}
    prim = raw.get("primary", {})
    if _hex(prim.get("background")):
        out["background"] = _hex(prim["background"])
    if _hex(prim.get("foreground")):
        out["foreground"] = _hex(prim["foreground"])
    for name, c in NORMAL.items():
        h = _hex(raw.get("normal", {}).get(name))
        if h and ANSI[c] not in out:
            out[ANSI[c]] = h
    h = _hex(raw.get("bright", {}).get("black"))
    if h:
        out["dark_foreground"] = h
    sel = raw.get("selection", {})
    if _hex(sel.get("background")):
        out["selection"] = _hex(sel["background"])
    return out


def find_theme_file() -> Path | None:
    for d in THEME_DIRS:
        for name in ("colors.toml", "alacritty.toml"):
            p = d / name
            if p.is_file():
                return p
    return None


def theme_name() -> str:
    for p in (HOME / ".local/state/omarchy/current/theme.name",
              HOME / ".config/omarchy/current/theme.name"):
        try:
            return p.read_text().strip()
        except OSError:
            continue
    for d in THEME_DIRS:
        if d.is_symlink():
            return d.resolve().name
    return ""


def load_palette() -> dict:
    pal: dict = {}
    path = find_theme_file()
    if path:
        try:
            pal = _from_colors_toml(path) if path.name == "colors.toml" else _from_alacritty(path)
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            pal = {}
    bg = pal.get("background") or FALLBACK["background"]
    fg = pal.get("foreground") or FALLBACK["foreground"]
    if "mode" not in pal:
        pal["mode"] = "light" if _luminance(bg) > 382 else "dark"
    if not pal.get("background") and not pal.get("foreground"):
        pal = {**FALLBACK, **pal}
    pal.setdefault("background", bg)
    pal.setdefault("foreground", fg)
    pal.setdefault("accent", pal.get("blue") or FALLBACK["accent"])
    pal.setdefault("lighter_background", mix(bg, fg, 0.07))
    pal.setdefault("dark_foreground", mix(fg, bg, 0.45))
    pal.setdefault("bright_foreground", mix(fg, "#ffffff" if pal["mode"] == "dark" else "#000000", 0.25))
    pal.setdefault("muted", mix(bg, fg, 0.2))
    pal.setdefault("selection", mix(bg, pal["accent"], 0.18))
    for k in ("red", "green", "yellow", "blue", "magenta", "cyan", "orange"):
        pal.setdefault(k, FALLBACK[k])
    pal["name"] = theme_name()
    pal["source"] = str(path) if path else ""
    return pal


def monospace_font() -> str:
    """Same lookup as `omarchy-font-current`."""
    if shutil.which("fc-match"):
        try:
            out = subprocess.run(
                ["fc-match", "monospace", "-f", "%{family}\n"],
                capture_output=True, text=True, timeout=3,
            ).stdout
            fam = out.splitlines()[0].split(",")[0].strip() if out else ""
            if fam:
                return fam
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return "JetBrainsMono Nerd Font"


def theme_css() -> tuple[str, str]:
    """Return (css, fingerprint). The fingerprint changes when the theme changes."""
    p = load_palette()
    font = monospace_font()
    lines = [":root {"]
    for k in ("background", "lighter_background", "foreground", "bright_foreground",
              "dark_foreground", "muted", "selection", "accent", "red", "green", "yellow",
              "blue", "magenta", "cyan", "orange"):
        lines.append(f"  --{k.replace('_', '-')}: {p[k]};")
    lines.append(f"  --mode: {p['mode']};")
    lines.append(f"  --font: '{font}', 'JetBrainsMono Nerd Font', 'JetBrains Mono', ui-monospace, monospace;")
    lines.append(f"  color-scheme: {'light' if p['mode'] == 'light' else 'dark'};")
    lines.append("}")
    css = "\n".join(lines) + "\n"
    return css, hashlib.sha1(css.encode()).hexdigest()[:10]
