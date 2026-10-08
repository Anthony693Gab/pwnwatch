#!/usr/bin/env bash
# Install pwnwatch for the current user.
#   ./install.sh               install the app + launcher entry + daily digest
#   ./install.sh --no-timer    skip the 09:00 daily notification
#   ./install.sh --uninstall   remove everything (keeps your settings and cache)
set -euo pipefail
cd "$(dirname "$0")"

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
TIMER=1
for arg in "$@"; do
  case "$arg" in
    --no-timer) TIMER=0 ;;
    --no-omarchy) ;;  # kept for compatibility; there is no bar integration any more
    --uninstall) UNINSTALL=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ -n "${UNINSTALL:-}" ]]; then
  if command -v pwnwatch >/dev/null; then
    pwnwatch cleanup || true
    pwnwatch stop >/dev/null 2>&1 || true
  fi
  rm -f "$ICONS/pwnwatch.svg"
  systemctl --user disable --now pwnwatch-digest.timer 2>/dev/null || true
  rm -f "$UNITS/pwnwatch-digest.service" "$UNITS/pwnwatch-digest.timer" "$APPS/pwnwatch.desktop"
  systemctl --user daemon-reload 2>/dev/null || true
  if command -v uv >/dev/null; then uv tool uninstall pwnwatch || true
  elif command -v pipx >/dev/null; then pipx uninstall pwnwatch || true; fi
  echo "pwnwatch removed (settings and cache in ~/.config, ~/.cache, ~/.local/state/pwnwatch kept)."
  exit 0
fi

echo "==> installing the pwnwatch command"
if command -v uv >/dev/null; then
  uv tool install --force .
elif command -v pipx >/dev/null; then
  pipx install --force .
else
  echo "Neither uv nor pipx found. Install one first:  sudo pacman -S uv" >&2
  echo "(pwnwatch has no Python dependencies; any Chromium-based browser shows the window.)" >&2
  exit 1
fi

BIN="$(command -v pwnwatch || echo "$HOME/.local/bin/pwnwatch")"
"$BIN" stop >/dev/null 2>&1 || true   # a backend from an older version would serve the old UI

echo "==> removing the bar icon/panel from older versions (if any)"
"$BIN" cleanup || true

echo "==> adding the app launcher and icon"
mkdir -p "$APPS" "$ICONS"
cp contrib/icons/pwnwatch.svg "$ICONS/pwnwatch.svg"
sed -e "s|@BIN@|$BIN|g" -e "s|@ICON@|$ICONS/pwnwatch.svg|g" contrib/pwnwatch.desktop > "$APPS/pwnwatch.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q "${ICONS%/scalable/apps}" 2>/dev/null || true

if [[ $TIMER == 1 ]]; then
  echo "==> enabling the daily digest (09:00)"
  mkdir -p "$UNITS"
  sed "s|@BIN@|$BIN|g" contrib/systemd/pwnwatch-digest.service > "$UNITS/pwnwatch-digest.service"
  cp contrib/systemd/pwnwatch-digest.timer "$UNITS/"
  systemctl --user daemon-reload
  systemctl --user enable --now pwnwatch-digest.timer
fi

echo
echo "Done. Open pwnwatch from the app launcher (Super + Space) or run 'pwnwatch'."
echo "Config: ~/.config/pwnwatch/config.toml (created on first run)."
