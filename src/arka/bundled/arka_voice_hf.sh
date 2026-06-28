#!/usr/bin/env bash
# Hugging Face speech-to-speech voice agent wired to Arka skills.
set -euo pipefail

FISH_DIR="${FISH_DIR:-$HOME/.config/fish}"
ENV_FILE="${ENV_FILE:-$FISH_DIR/.env}"
CACHE_DIR="$HOME/.cache/fish-agent"
S2S_DIR="$FISH_DIR/speech-to-speech"
VENV="$FISH_DIR/venv-voice-hf"
PY="$VENV/bin/python3"
BRIDGE_PID="$CACHE_DIR/arka_hf_bridge.pid"
VOICE_PID="$CACHE_DIR/arka_voice_hf.pid"
BRIDGE_LOG="$CACHE_DIR/arka_hf_bridge.log"
VOICE_LOG="$CACHE_DIR/arka_voice_hf.log"
BRIDGE_PORT="${ARKA_HF_BRIDGE_PORT:-8787}"
BRIDGE_URL="http://127.0.0.1:${BRIDGE_PORT}/v1"

mkdir -p "$CACHE_DIR"

_read_env() {
    local key=$1
    local default=${2:-}
    if [[ -f "$ENV_FILE" ]]; then
        local val
        val=$(grep -m1 "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed 's/#.*//' | tr -d '\r"' | xargs)
        if [[ -n "$val" ]]; then
            echo "$val"
            return
        fi
    fi
    echo "$default"
}

ARKA_SPEAK_LANG="$(_read_env ARKA_SPEAK_LANG en-IN)"
export ARKA_SPEAK_LANG

pid_alive() {
    local pidfile=$1
    [[ -f "$pidfile" ]] || return 1
    local pid
    pid=$(cat "$pidfile" 2>/dev/null) || return 1
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

ensure_venv() {
    if [[ ! -x "$PY" ]]; then
        echo "[arka-voice] Creating venv (Python 3.12) …"
        python3.12 -m venv "$VENV"
    fi
    if ! "$PY" -c "import speech_to_speech" 2>/dev/null; then
        echo "[arka-voice] Installing speech-to-speech (CPU: faster-whisper + pocket TTS) …"
        echo "[arka-voice] This may take several minutes on first run."
        "$PY" -m pip install -q -U pip wheel
        "$PY" -m pip install -q -e "${S2S_DIR}[faster-whisper,pocket]"
    fi
}

start_bridge() {
    if pid_alive "$BRIDGE_PID"; then
        echo "[arka-voice] Arka bridge already running (pid $(cat "$BRIDGE_PID"))"
        return 0
    fi
    echo "[arka-voice] Starting Arka LLM bridge on port $BRIDGE_PORT …"
    nohup "$PY" "$FISH_DIR/arka_hf_bridge.py" --port "$BRIDGE_PORT" >>"$BRIDGE_LOG" 2>&1 &
    echo $! >"$BRIDGE_PID"
    sleep 0.5
    if ! curl -sf "http://127.0.0.1:${BRIDGE_PORT}/health" >/dev/null; then
        echo "[arka-voice] Bridge failed. Check: $BRIDGE_LOG"
        tail -10 "$BRIDGE_LOG" 2>/dev/null || true
        return 1
    fi
    echo "[arka-voice] Bridge OK → routes voice queries to Arka agent"
}

stop_bridge() {
    if pid_alive "$BRIDGE_PID"; then
        kill "$(cat "$BRIDGE_PID")" 2>/dev/null || true
    fi
    rm -f "$BRIDGE_PID"
}

start_voice() {
    if pid_alive "$VOICE_PID"; then
        echo "[arka-voice] HF voice agent already running (pid $(cat "$VOICE_PID"))"
        return 0
    fi
    ensure_venv
    start_bridge

    local lang="${ARKA_SPEAK_LANG:-en-IN}"
    local lang_code="en"
    if [[ "$lang" == hi-* ]]; then lang_code="hi"; fi
    if [[ "$lang" == *"-IN" ]]; then lang_code="en"; fi

    local stt_model="${ARKA_HF_STT_MODEL:-distil-whisper/distil-small.en}"

    echo "[arka-voice] Starting HF speech-to-speech (mic → Arka → speaker) …"
    echo "[arka-voice] Speak naturally; VAD detects when you stop. Ctrl+C in log: tail -f $VOICE_LOG"

    nohup env \
        OPENAI_API_KEY="${ARKA_HF_BRIDGE_KEY:-local-bridge}" \
        "$PY" -m speech_to_speech.s2s_pipeline \
        --mode local \
        --device cpu \
        --stt faster-whisper \
        --faster_whisper_stt_model_name "$stt_model" \
        --faster_whisper_stt_device cpu \
        --faster_whisper_stt_compute_type int8 \
        --faster_whisper_stt_gen_language "$lang_code" \
        --llm_backend responses-api \
        --responses_api_base_url "$BRIDGE_URL" \
        --responses_api_api_key "${ARKA_HF_BRIDGE_KEY:-local-bridge}" \
        --responses_api_stream \
        --model_name arka \
        --tts pocket \
        --pocket_tts_voice "${ARKA_HF_TTS_VOICE:-jean}" \
        --pocket_tts_device cpu \
        --language "$lang_code" \
        --enable_live_transcription \
        --thresh 0.5 \
        --min_speech_ms 384 \
        --min_silence_ms 500 \
        >>"$VOICE_LOG" 2>&1 &
    echo $! >"$VOICE_PID"
    sleep 2
    if pid_alive "$VOICE_PID"; then
        echo "[arka-voice] Running (pid $(cat "$VOICE_PID"))"
        echo "[arka-voice] Logs: tail -f $VOICE_LOG"
        return 0
    fi
    echo "[arka-voice] Failed to start. Check: $VOICE_LOG"
    tail -20 "$VOICE_LOG" 2>/dev/null || true
    return 1
}

stop_voice() {
    if pid_alive "$VOICE_PID"; then
        kill "$(cat "$VOICE_PID")" 2>/dev/null || true
    fi
    rm -f "$VOICE_PID"
    stop_bridge
    echo "[arka-voice] Stopped"
}

status_voice() {
    if pid_alive "$VOICE_PID"; then
        echo "HF voice agent: running (pid $(cat "$VOICE_PID"))"
    else
        echo "HF voice agent: stopped"
    fi
    if pid_alive "$BRIDGE_PID"; then
        echo "Arka bridge:    running (pid $(cat "$BRIDGE_PID"), port $BRIDGE_PORT)"
    else
        echo "Arka bridge:    stopped"
    fi
    if [[ -d "$S2S_DIR" ]]; then
        echo "Repo:           $S2S_DIR"
    fi
}

case "${1:-status}" in
    start) start_voice ;;
    stop) stop_voice ;;
    restart) stop_voice; sleep 1; start_voice ;;
    bridge) start_bridge ;;
    status) status_voice ;;
    install) ensure_venv; echo "[arka-voice] Install complete" ;;
    *)
        echo "Usage: arka_voice_hf.sh {start|stop|restart|status|install|bridge}"
        exit 1
        ;;
esac
