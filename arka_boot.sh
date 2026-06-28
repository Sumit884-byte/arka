#!/usr/bin/env bash
# Start all Arka background services (used by systemd and arka start).
set -euo pipefail

FISH_DIR="${FISH_DIR:-$HOME/.config/fish}"
ENV_FILE="${ENV_FILE:-$FISH_DIR/.env}"
CACHE_DIR="$HOME/.cache/fish-agent"
mkdir -p "$CACHE_DIR"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        line="${line%%#*}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        val="${BASH_REMATCH[2]}"
        val="${val#"${val%%[![:space:]]*}"}"
        val="${val%"${val##*[![:space:]]}"}"
        val="${val%$'\r'}"
        val="${val#\"}"; val="${val%\"}"
        export "$key"="$val"
    done < "$ENV_FILE"
    set +a
fi

remote_auto="${ARKA_REMOTE_AUTO:-1}"
wake_auto="${AGENT_WAKE_AUTO:-1}"
quiet="${ARKA_START_QUIET:-0}"

arka_log() {
    [[ "$quiet" = "1" || "$quiet" = "true" ]] && return 0
    echo "$@"
}

pid_alive() {
    local pidfile=$1
    [[ -f "$pidfile" ]] || return 1
    local pid
    pid=$(cat "$pidfile" 2>/dev/null) || return 1
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_remote() {
    if [[ "$remote_auto" != "1" && "$remote_auto" != "true" ]]; then
        return 0
    fi
    if pid_alive "$CACHE_DIR/arka_remote.pid"; then
        arka_log "[arka] remote already running"
        return 0
    fi
    arka_log "[arka] starting remote server ..."
    nohup python3 "$FISH_DIR/arka_remote_server.py" serve >>"$CACHE_DIR/arka_remote.log" 2>&1 &
    disown 2>/dev/null || true
}

WAKE_PY="$FISH_DIR/venv-arka/bin/python3"
[[ -x "$WAKE_PY" ]] || WAKE_PY=python3

start_listen() {
    if [[ "$wake_auto" != "1" && "$wake_auto" != "true" ]]; then
        return 0
    fi
    if pid_alive "$CACHE_DIR/arka_listen.pid"; then
        arka_log "[arka] wake listener already running"
        return 0
    fi
    arka_log "[arka] starting wake listener ..."
    "$WAKE_PY" "$FISH_DIR/arka_wake.py" --check >/dev/null
    nohup "$WAKE_PY" "$FISH_DIR/arka_wake.py" >>"$CACHE_DIR/arka_listen.log" 2>&1 &
    disown 2>/dev/null || true
}

start_usage() {
    local usage_auto="${ARKA_USAGE_TRACK:-1}"
    if [[ "$usage_auto" != "1" && "$usage_auto" != "true" ]]; then
        return 0
    fi
    if pid_alive "$CACHE_DIR/arka_usage.pid"; then
        arka_log "[arka] usage tracker already running"
        return 0
    fi
    arka_log "[arka] starting app + website usage tracker ..."
    python3 "$FISH_DIR/arka_usage.py" start 2>/dev/null || true
}

stop_usage() {
    python3 "$FISH_DIR/arka_usage.py" stop 2>/dev/null || true
}

stop_remote() {
    python3 "$FISH_DIR/arka_remote_server.py" stop 2>/dev/null || true
}

stop_listen() {
    local pidfile="$CACHE_DIR/arka_listen.pid"
    if pid_alive "$pidfile"; then
        kill "$(cat "$pidfile")" 2>/dev/null || true
        rm -f "$pidfile"
    fi
}

case "${1:-start}" in
    start)
        start_remote
        start_listen
        start_usage
        if [[ "$quiet" != "1" && "$quiet" != "true" ]]; then
            sleep 2
        fi
        ;;
    stop)
        stop_listen
        stop_remote
        stop_usage
        python3 "$FISH_DIR/indic_tts.py" stop 2>/dev/null || true
        ;;
    restart)
        "$0" stop
        sleep 1
        "$0" start
        ;;
    *)
        echo "Usage: arka_boot.sh {start|stop|restart}"
        exit 1
        ;;
esac
