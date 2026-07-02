"""Track bot vs user WhatsApp messages (outgoing echo suppression)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

try:
    from arka.paths import cache_dir
except ImportError:
    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

STATE_PATH = cache_dir() / "whatsapp_message_state.json"
_DEFAULT_SELF_TITLES = ("you", "(you)", "message yourself")


def _load() -> dict:
    if not STATE_PATH.is_file():
        return {"outgoing": [], "chat_snapshots": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"outgoing": [], "chat_snapshots": {}}
    data.setdefault("outgoing", [])
    data.setdefault("chat_snapshots", {})
    return data


def _save(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    outgoing = data.get("outgoing", [])
    if len(outgoing) > 200:
        data["outgoing"] = outgoing[-200:]
    STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _text_key(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode()).hexdigest()[:20]


def bot_prefix() -> str:
    return os.environ.get("ARKA_WHATSAPP_BOT_PREFIX", "🤖 ").strip()


def format_bot_reply(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    prefix = bot_prefix()
    if prefix and not text.startswith(prefix):
        return f"{prefix}{text}"
    return text


def strip_bot_prefix(text: str) -> str:
    text = (text or "").strip()
    prefix = bot_prefix()
    if prefix and text.startswith(prefix):
        return text[len(prefix) :].strip()
    return text


def register_outgoing(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    data = _load()
    row = {"key": _text_key(text), "text": text[:500], "ts": time.time()}
    outgoing = data.setdefault("outgoing", [])
    if not any(r.get("key") == row["key"] for r in outgoing):
        outgoing.append(row)
    _save(data)


def is_outgoing_echo(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return True
    prefix = bot_prefix()
    if prefix and text.startswith(prefix):
        return True
    key = _text_key(text)
    data = _load()
    now = time.time()
    ttl = float(os.environ.get("ARKA_WHATSAPP_ECHO_TTL", "86400"))
    for row in data.get("outgoing", []):
        if row.get("key") == key:
            return True
        if now - float(row.get("ts", 0)) > ttl:
            continue
        prev = (row.get("text") or "").strip()
        if prev and (text == prev or text in prev or prev in text):
            return True
    return False


def is_user_message(text: str) -> bool:
    return not is_outgoing_echo(text)


def self_chat_enabled(num_allowed: int = 1) -> bool:
    raw = os.environ.get("ARKA_WHATSAPP_SELF", "auto").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return num_allowed == 1


def extra_chat_titles() -> list[str]:
    titles: list[str] = []
    raw = os.environ.get("ARKA_WHATSAPP_CHAT", "").strip()
    if raw:
        titles.extend(t.strip() for t in raw.split(",") if t.strip())
    if self_chat_enabled():
        titles.extend(_DEFAULT_SELF_TITLES)
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            out.append(t)
    return out


def chat_title_allowed(title: str, allowed_phones: list[str]) -> bool:
    title = (title or "").strip()
    if not title:
        return False
    low = title.lower()
    for alias in extra_chat_titles():
        if low == alias.lower():
            return True
    if any(phone_matches_title(title, p) for p in allowed_phones):
        return True
    digits = re.sub(r"\D", "", title)
    if digits:
        return any(phone_matches_title(digits, p) for p in allowed_phones)
    return False


def phone_matches_title(a: str, b: str) -> bool:
    from whatsapp_automation import phone_matches

    return phone_matches(a, b)


def sender_for_chat(title: str, allowed_phones: list[str]) -> str:
    from whatsapp_automation import normalize_phone

    low = (title or "").strip().lower()
    if self_chat_enabled() and low in {t.lower() for t in _DEFAULT_SELF_TITLES}:
        return allowed_phones[0] if allowed_phones else title
    digits = re.sub(r"\D", "", normalize_phone(title))
    if digits:
        return normalize_phone(title)
    return allowed_phones[0] if allowed_phones else title


def get_chat_snapshot(chat: str) -> list[str]:
    data = _load()
    snap = data.get("chat_snapshots", {}).get(chat, [])
    return list(snap) if isinstance(snap, list) else []


def set_chat_snapshot(chat: str, texts: list[str]) -> None:
    data = _load()
    snaps = data.setdefault("chat_snapshots", {})
    snaps[chat] = texts[-80:]
    _save(data)


def find_new_user_messages(
    chat: str, current: list[str], *, skip_echo: bool = True
) -> list[str]:
    prev = get_chat_snapshot(chat)
    if not prev:
        set_chat_snapshot(chat, current)
        return []

    prev_set = set(prev)
    new_msgs = [t for t in current if t and t not in prev_set]
    set_chat_snapshot(chat, current)

    if not new_msgs:
        return []

    out: list[str] = []
    for text in new_msgs:
        if skip_echo and is_outgoing_echo(text):
            continue
        out.append(text)
    return out
