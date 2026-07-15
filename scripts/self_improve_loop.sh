#!/usr/bin/env bash
# Arka 1-minute self-improve loop (plan-only; no --apply).
# Uses arka.agent.iterate — interval runner, separate from `arka goal`.
#
# Prefer the launchd routine when you want a persistent scheduler:
#   python -m arka.integrations.routines add "every 1m" "self improve" --name self-improve-1m --install
# Stop that with: routines disable self-improve-1m  (or routines remove self-improve-1m)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/venv-arka/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

CACHE="${CACHE_DIR:-$HOME/.cache/fish-agent}"
PID_FILE="$CACHE/self_improve_loop.pid"
LOG_FILE="$CACHE/self_improve_loop.log"
INTERVAL="${INTERVAL:-60}"

cmd="${1:-start}"
case "$cmd" in
  start)
    mkdir -p "$CACHE"
    if [[ -f "$PID_FILE" ]]; then
      old_pid="$(cat "$PID_FILE")"
      if kill -0 "$old_pid" 2>/dev/null; then
        echo "Already running (PID $old_pid)"
        echo "Log: $LOG_FILE"
        exit 0
      fi
    fi
    cd "$ROOT"
    nohup env PYTHONUNBUFFERED=1 PYTHONPATH="${ROOT}/src" "$PYTHON" -c \
      "from arka.agent.iterate import main; raise SystemExit(main(['loop', '${INTERVAL}', 'self', 'improve']))" \
      >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    echo "Started Arka self-improve loop every ${INTERVAL}s (PID $(cat "$PID_FILE"))"
    echo "Task: self improve (plan-only)"
    echo "Log: $LOG_FILE"
    echo "Stop: $0 stop"
    ;;
  stop)
    if [[ ! -f "$PID_FILE" ]]; then
      echo "No PID file ($PID_FILE). Loop not running?"
      exit 1
    fi
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "Stopped loop (PID $pid)"
    else
      echo "Process $pid not running"
    fi
    rm -f "$PID_FILE"
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Running (PID $(cat "$PID_FILE"))"
      echo "Log: $LOG_FILE"
      tail -n 5 "$LOG_FILE" 2>/dev/null || true
    else
      echo "Not running"
      [[ -f "$PID_FILE" ]] && rm -f "$PID_FILE"
    fi
    ;;
  log)
    tail -n "${2:-30}" "$LOG_FILE" 2>/dev/null || echo "No log yet: $LOG_FILE"
    ;;
  *)
    echo "Usage: $0 {start|stop|status|log [lines]}"
    exit 1
    ;;
esac
