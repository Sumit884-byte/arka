#!/usr/bin/env bash
# Start Arka desktop backends without Tauri (browser UI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/desktop"

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ -f "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
if [[ -f "$HOME/.config/arka/.env" ]]; then set -a; source "$HOME/.config/arka/.env"; set +a; fi

cleanup() {
  [[ -n "${REMOTE_PID:-}" ]] && kill "$REMOTE_PID" 2>/dev/null || true
  [[ -n "${BRIDGE_PID:-}" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting arka serve..."
python3 -m arka.integrations.remote_server serve &
REMOTE_PID=$!
sleep 2

echo "Starting bridge on :8766..."
python3 bridge.py &
BRIDGE_PID=$!
sleep 1

if [[ ! -d ui/dist ]]; then
  echo "Building UI..."
  npm install --prefix ui --silent 2>/dev/null || npm install --prefix ui
  npm run build --prefix ui
fi

echo "Open http://127.0.0.1:8766"
wait
