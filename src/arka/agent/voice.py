#!/usr/bin/env python3
"""Voice-first helpers for arka listen: acknowledgments, formatting, session prep."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

from arka.agent.core import CACHE, load_json, save_json

VOICE_SESSION_FILE = CACHE / "voice_session.json"
MAX_VOICE_TURNS = int(os.environ.get("VOICE_SESSION_TURNS", "8"))
SPEAK_MAX = int(os.environ.get("AGENT_SPEAK_MAX", "900"))

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ROUTING_LINE_RE = re.compile(
    r"(?i)^("
    r"💡.*|→.*|▶.*|🔎.*|"
    r"offline routing|running skill|interpreted:|"
    r"usage:|example:|warning:"
    r")"
)
TTS_NOISE_RE = re.compile(r"(?i)(sarvam_speak|edge_speak|indic_tts|could not speak aloud|tts-setup)")
ERROR_HINT_RE = re.compile(r"(?i)(fetch failed|could not get|connection failed|check api key|module not found)")
BLOCK_HEADER_RE = re.compile(r"^━━━\s*.+\s*━━━$")
LIST_PREFIX_RE = re.compile(r"^\d+\.\s+")
MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")

HELP_PHRASES = {
    "help",
    "what can you do",
    "what do you do",
    "list skills",
    "show skills",
    "what are your skills",
    "what can i ask",
    "how do i use you",
    "voice help",
    "commands",
}

CLEAR_PHRASES = {
    "end conversation",
    "end session",
    "new conversation",
    "clear session",
    "stop talking",
}

STATUS_PHRASES = {"session status", "conversation status"}


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def is_voice_help(text: str) -> bool:
    low = re.sub(r"\s+", " ", text.lower().strip())
    low = re.sub(r"^(hey|hi|ok)\s+\w+\s+", "", low)
    if low in HELP_PHRASES:
        return True
    return bool(
        re.match(r"^(help|skills|commands)\s*$", low)
        or re.search(
            r"\b("
            r"tell\s+(?:me\s+)?(?:about\s+)?(?:all\s+)?(?:your\s+)?skills?|"
            r"tell\s+your\s+skills?|"
            r"(?:all|list|show)\s+(?:me\s+)?(?:all\s+)?(?:your\s+)?skills?|"
            r"what\s+(?:are\s+)?(?:all\s+)?your\s+skills?"
            r")\b",
            low,
        )
    )


def voice_help() -> str:
    name = (os.environ.get("AGENT_NAME") or "Arka").strip() or "Arka"
    return (
        f"I'm {name}. You can ask without looking at the screen. "
        "Try: what's the weather, play a song on Spotify, set a timer for five minutes, "
        "search the web, ask about your documents, open an app, check the news, "
        "translate text, live sports scores, or ask me anything. "
        "Third-party plugins work too — say their trigger phrase or run arka skills list. "
        "Say end conversation to start fresh."
    )


def _is_follow_up(text: str) -> bool:
    low = text.lower().strip()
    return bool(
        re.match(
            r"^(and |also |what about |how about |tell me more|follow up|continue|"
            r"explain that|why|who|when|where|can you|save that|remember that|"
            r"repeat that|say that again|more detail|in detail)",
            low,
        )
    )


def voice_session_load() -> dict:
    data = load_json(VOICE_SESSION_FILE, {})
    return data if isinstance(data, dict) else {}


def voice_session_save(data: dict) -> None:
    save_json(VOICE_SESSION_FILE, data)


def voice_ack(text: str) -> str:
    """Short spoken acknowledgment while a skill runs."""
    try:
        from arka.agent.skills import match_command, voice_ack_for

        if match_command(text):
            ack = voice_ack_for(text)
            if ack:
                return ack
    except ImportError:
        pass

    low = text.lower()
    if is_voice_help(text):
        return ""
    if re.search(r"\bweather\b|\bforecast\b|\btemperature\b|\brain\b", low):
        return "Checking the weather."
    if re.search(r"\b(play|spotify|music|song|youtube|video|movie)\b", low):
        return "Playing that for you."
    if re.search(r"\b(stop|pause)\b.*\b(music|song|spotify|playback)\b", low):
        return "Stopping playback."
    if re.search(r"\btimer\b|\bpomodoro\b|\balarm\b", low):
        m = re.search(r"(\d+)\s*(m|min|minute|minutes|h|hour|hours|s|sec|seconds)\b", low)
        if m:
            return f"Starting a {m.group(1)} {m.group(2)} timer."
        return "Starting your timer."
    if re.search(r"\b(open|launch|start)\b.*\b(app|application|program)\b", low):
        return "Opening that app."
    if re.search(r"\b(search|find|look up|google)\b", low):
        return "Searching for that."
    if re.search(r"\b(install|download|setup)\b", low):
        return "Working on the install."
    if re.search(r"\b(translate|translation)\b", low):
        return "Translating that."
    if re.search(r"\b(pdf|document|doc|file|summarize|ingest)\b", low):
        return "Looking in your documents."
    if re.search(r"\b(news|headline|brief|daily)\b", low):
        return "Fetching the latest news."
    if re.search(r"\b(stock|market|crypto|price)\b", low):
        return "Checking market data."
    if re.search(r"\b(ipl|cricket|nfl|nba|soccer|football|sports?|match|score|scores|game)\b", low):
        return "Checking live sports scores."
    if re.search(r"\b(password|passcode)\b", low):
        return "Working on your password request."
    if re.search(r"\b(remember|memory|recall)\b", low):
        return "Updating memory."
    if re.search(r"\b(whatsapp|message|text)\b", low):
        return "Sending your message."
    if re.search(r"\?$", low) or re.search(r"\b(what|who|where|when|why|how|tell me|explain)\b", low):
        return "Let me find that out."
    return "One moment."


def voice_progress(skill: str) -> str:
    """Human-readable progress line for a routed skill name."""
    key = (skill or "").strip().lower()
    table = {
        "weather": "Checking the weather.",
        "hyperlocal_weather": "Checking the weather near you.",
        "web_answer": "Searching for an answer.",
        "deep_web_answer": "Doing a deeper web search.",
        "agent_ask": "Thinking about that.",
        "play_spotify": "Starting Spotify.",
        "play_youtube": "Opening YouTube.",
        "play_song": "Playing music.",
        "play_movie": "Starting the video.",
        "stop_music": "Stopping playback.",
        "timer": "Starting your timer.",
        "pomodoro": "Starting a pomodoro timer.",
        "open_app": "Opening the app.",
        "open_file": "Opening the file.",
        "pdf_ask": "Reading your document.",
        "doc_ask": "Reading your document.",
        "pdf_ingest": "Adding that document.",
        "translate": "Translating.",
        "daily_brief": "Preparing your daily brief.",
        "send_whatsapp": "Sending on WhatsApp.",
        "search_web": "Searching the web.",
        "install_app": "Installing the app.",
        "install_apt": "Installing with apt.",
        "generate_password": "Generating a password.",
        "crypto_price": "Checking crypto prices.",
        "sports_score": "Checking live sports scores.",
        "live_scores": "Checking live sports scores.",
        "predictions": "Analyzing that.",
        "system_monitor": "Checking system stats.",
        "system_info": "Getting system information.",
        "list_folders": "Listing folders.",
        "show_folder": "Listing folder contents.",
        "search_files": "Searching files.",
        "find_files_by_size": "Finding files by size.",
        "calc": "Calculating.",
        "nearby_places": "Finding nearby places.",
    }
    return table.get(key, voice_ack(key.replace("_", " ")))


def voice_prepare(user_text: str) -> dict:
    """Split routing text from LLM-only session context."""
    low = user_text.lower().strip()
    if low in CLEAR_PHRASES:
        return {"action": "clear"}
    if low in STATUS_PHRASES:
        return {"action": "status"}
    if is_voice_help(user_text):
        return {"action": "help", "ack": ""}

    data = voice_session_load()
    turns: list[dict] = data.get("turns") or []
    active = data.get("active", False) or bool(turns)
    if not active and not _is_follow_up(user_text):
        data = {"active": True, "started": time.time(), "turns": []}
        voice_session_save(data)
        turns = data["turns"]

    llm_context = ""
    if turns or _is_follow_up(user_text):
        history = ""
        for turn in turns[-MAX_VOICE_TURNS:]:
            history += f"User: {turn.get('user', '')}\nAssistant: {turn.get('assistant', '')}\n"
        if history:
            llm_context = (
                f"[Voice session — use prior context for continuity]\n{history}\n"
                f"User now: {user_text}\n"
                "Answer the latest message in plain spoken language."
            )

    return {
        "action": "run",
        "route_text": user_text,
        "llm_context": llm_context,
        "ack": voice_ack(user_text),
    }


def _tts_cleanup(text: str) -> str:
    text = text.replace("°C", " degrees Celsius")
    text = text.replace("°F", " degrees Fahrenheit")
    text = text.replace("km/h", " kilometers per hour")
    text = text.replace("mph", " miles per hour")
    text = text.replace("&", " and ")
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_block(raw: str, marker: str) -> str:
    if marker not in raw:
        return raw
    return raw.split(marker, 1)[1].split("━━━", 1)[0].strip()


def voice_format(raw: str) -> str:
    """Turn any agent/skill output into plain speakable text."""
    text = strip_ansi(raw)
    if not text.strip():
        return ""

    for marker in (
        "━━━ Answer ━━━",
        "━━━ PDF answer ━━━",
        "━━━ Speaking ━━━",
    ):
        if marker in text:
            text = _extract_block(text, marker)
            break
    else:
        m = re.search(r"━━━ 📄 [^━]+ ━━━\s*(.*)", text, flags=re.S)
        if m:
            text = m.group(1)

    lines: list[str] = []
    for line in text.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("Tip:"):
            continue
        if t == "Brief:":
            continue
        if TTS_NOISE_RE.search(t):
            continue
        if BLOCK_HEADER_RE.match(t):
            continue
        if t.startswith("Usage:") or t.startswith("Example:"):
            continue
        t = re.sub(r"^\[(FROM SEARCH|FROM MEMORY)\]\s*", "", t, flags=re.I)
        t = re.sub(r"^🔎\s*", "", t)
        t = MARKDOWN_BOLD_RE.sub(r"\1", t)
        t = LIST_PREFIX_RE.sub("", t)
        t = re.sub(r"^\s*[-•*]\s+", "", t)
        t = re.sub(r":\s*-\s+", ", ", t)
        t = re.sub(r"\s*:\s*$", "", t)
        t = re.sub(r"^[▶🌐⏱⏰✗✓📄💡→]+\s*", "", t)
        t = t.strip()
        if t:
            lines.append(t)

    spoken = " ".join(lines)
    spoken = re.sub(r"\s*\d+\.\s+", ", ", spoken)
    spoken = re.sub(r"\s*:\s*-\s+", ", ", spoken)
    spoken = re.sub(r"\s+-\s+", ", ", spoken)
    spoken = re.sub(r"\.{2,}", ".", spoken)
    spoken = _tts_cleanup(spoken)

    if not spoken:
        # Action-only outputs (e.g. "Opened Firefox", "Playing …")
        for line in strip_ansi(raw).splitlines():
            t = line.strip()
            if not t or ROUTING_LINE_RE.match(t) or TTS_NOISE_RE.search(t):
                continue
            if re.search(r"(?i)(opened|playing|started|stopped|done|sent|installed|copied|saved|timer|time.s up)", t):
                spoken = _tts_cleanup(MARKDOWN_BOLD_RE.sub(r"\1", t))
                break

    if not spoken and ERROR_HINT_RE.search(raw):
        low = raw.lower()
        if "weather" in low:
            spoken = "Sorry, I couldn't fetch the weather right now. Please try again."
        elif re.search(r"\b(search|web|answer)\b", low):
            spoken = "Sorry, I couldn't find an answer right now. Please try again."
        elif re.search(r"\b(install|download)\b", low):
            spoken = "Sorry, the install didn't work. Check the screen for details or try again."
        else:
            spoken = "Sorry, that didn't work. Please try again."

    if len(spoken) > SPEAK_MAX:
        cut = spoken[:SPEAK_MAX]
        boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        if boundary > SPEAK_MAX // 2:
            spoken = cut[: boundary + 1].strip()
        else:
            spoken = cut.rstrip() + "…"
    return spoken


def voice_session_record(user_text: str, assistant_text: str) -> None:
    if user_text.strip():
        try:
            from arka.agent.core import memory_auto_detect

            memory_auto_detect(user_text, quiet=True)
        except ImportError:
            pass
    data = voice_session_load()
    if not data.get("active"):
        data = {"active": True, "started": time.time(), "turns": []}
    turns: list[dict] = data.setdefault("turns", [])
    clean = voice_format(assistant_text) or strip_ansi(assistant_text)
    clean = " ".join(clean.split())[:2000]
    turns.append(
        {
            "user": user_text.strip(),
            "assistant": clean,
            "ts": time.time(),
        }
    )
    data["turns"] = turns[-MAX_VOICE_TURNS:]
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    voice_session_save(data)


def voice_session_clear() -> str:
    if VOICE_SESSION_FILE.is_file():
        VOICE_SESSION_FILE.unlink(missing_ok=True)
    return "Conversation cleared."


def voice_session_status() -> str:
    data = voice_session_load()
    turns = data.get("turns") or []
    if not turns:
        return "No active conversation yet."
    last = turns[-1]
    preview = (last.get("assistant") or "")[:120]
    return f"Conversation active with {len(turns)} turns. Last reply: {preview}"


def voice_session_enrich(user_text: str) -> str:
    """Backward-compatible enrich hook; returns route text only."""
    prep = voice_prepare(user_text)
    action = prep.get("action")
    if action == "clear":
        return "__VOICE_SESSION_CLEAR__"
    if action == "status":
        return "__VOICE_SESSION_STATUS__"
    if action == "help":
        return "__VOICE_HELP__"
    return str(prep.get("route_text") or user_text)


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Arka voice helpers")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("help-text")
    p_fmt = sub.add_parser("format")
    p_fmt.add_argument("text")
    p_ack = sub.add_parser("ack")
    p_ack.add_argument("text")
    p_prog = sub.add_parser("progress")
    p_prog.add_argument("--skill", required=True)
    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("text")

    args = p.parse_args()
    if args.cmd == "help-text":
        print(voice_help())
    elif args.cmd == "format":
        print(voice_format(args.text))
    elif args.cmd == "ack":
        print(voice_ack(args.text))
    elif args.cmd == "progress":
        print(voice_progress(args.skill))
    elif args.cmd == "prepare":
        print(json.dumps(voice_prepare(args.text), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
