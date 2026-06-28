#!/usr/bin/env bash
# After git clone on a new machine: pull latest, sync package bundle, reinstall.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "→ git pull"
git pull --ff-only

echo "→ sync bundled"
python3 "$ROOT/scripts/sync_bundled.py"

if [[ "${1:-}" == "--install" || "${1:-}" == "-i" ]]; then
  echo "→ pip install -e '.[chat]'"
  python3 -m pip install -e "$ROOT[chat]"
fi

if command -v arka >/dev/null 2>&1; then
  arka setup
else
  echo "→ copy env template"
  mkdir -p "${ARKA_CONFIG_DIR:-$HOME/.config/arka}"
  cp -n "$ROOT/.env.example" "${ARKA_CONFIG_DIR:-$HOME/.config/arka}/.env" 2>/dev/null || true
fi

echo "✓ Done. Edit ~/.config/arka/.env (or ~/.config/fish/.env) then: arka doctor"
