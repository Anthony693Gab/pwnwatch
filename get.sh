#!/usr/bin/env bash
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/Anthony693Gab/pwnwatch/main/get.sh | bash
# Clones (or updates) pwnwatch into ~/.local/share/pwnwatch-src and runs install.sh.
set -euo pipefail

REPO="${PWNWATCH_REPO:-https://github.com/Anthony693Gab/pwnwatch.git}"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/pwnwatch-src"

command -v git >/dev/null || { echo "git is required (sudo pacman -S git)" >&2; exit 1; }
if ! command -v uv >/dev/null && ! command -v pipx >/dev/null; then
  if command -v pacman >/dev/null; then
    echo "==> installing uv"
    sudo pacman -S --needed --noconfirm uv
  else
    echo "Install uv or pipx first (https://docs.astral.sh/uv/)" >&2
    exit 1
  fi
fi

if [[ -d $DEST/.git ]]; then
  echo "==> updating $DEST"
  git -C "$DEST" pull --ff-only
else
  echo "==> cloning into $DEST"
  git clone --depth 1 "$REPO" "$DEST"
fi

exec "$DEST/install.sh" "$@"
