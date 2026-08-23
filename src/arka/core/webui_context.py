"""Open WebUI context — chat id resolution, n-gram hints, turn preparation."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any

WEBUI_CHANNEL = "open-webui"


def _fallback_chat_id_enabled() -> bool:
    return os.environ.get("WEBUI_CHAT_ID_FALLBACK", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _first_user_message(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        if isinstance(content, list):
            parts = [
                str(block.get("text") or block.get("input_text") or "").strip()
                for block in content
                if isinstance(block, dict)
            ]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                return joined
    return ""


def _hash_chat_id(seed: str, *, account: str = "") -> str:
    blob = f"{account}|{seed}".encode("utf-8")
    return f"owui-{hashlib.sha256(blob).hexdigest()[:20]}"


def resolve_chat_id(
    data: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    messages: object | None = None,
) -> tuple[str, str]:
    """Return (chat_id, source) — source explains how the id was chosen."""
    payload = data or {}
    try:
        from arka.integrations.openai_chat import chat_id_from_headers

        cid = chat_id_from_headers(headers)
        if cid:
            return cid, "header"
    except ImportError:
        pass

    meta = payload.get("metadata")
    if isinstance(meta, dict):
        for key in ("chat_id", "conversation_id", "session_id", "id"):
            cid = str(meta.get(key) or "").strip()
            if cid:
                return cid[:64], "payload"

    cid = str(payload.get("chat_id") or payload.get("session_id") or "").strip()
    if cid:
        return cid[:64], "payload"

    msgs = messages if messages is not None else payload.get("messages")
    first = _first_user_message(msgs)
    account = str(payload.get("user") or "").strip()
    if _fallback_chat_id_enabled() and first:
        return _hash_chat_id(first[:240], account=account), "thread_hash"

    return "default", "default"


def rows_from_messages(messages: object) -> list[tuple[str, str]]:
    try:
        from arka.core.chat_context_gate import rows_from_openai_messages

        return rows_from_openai_messages(messages)
    except ImportError:
        rows: list[tuple[str, str]] = []
        if not isinstance(messages, list):
            return rows
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = msg.get("content")
            text = content if isinstance(content, str) else str(content or "")
            text = text.strip()
            if text:
                rows.append((role, text))
        return rows


def build_agent_text(messages: object) -> str:
    rows = rows_from_messages(messages)
    last_user = ""
    for role, content in rows:
        if role == "user":
            last_user = content
    if not last_user:
        return ""
    try:
        from arka.core.chat_context_gate import build_web_agent_text, is_webui_meta_prompt

        if is_webui_meta_prompt(last_user):
            return last_user
        return build_web_agent_text(rows)
    except ImportError:
        return last_user


def context_hint(user_text: str, messages: object, *, channel: str, chat_id: str) -> str:
    rows = rows_from_messages(messages)
    subs: list[str] = []
    try:
        from arka.core.web_topic_memory import load_state, parse_subtopics

        subs = [str(x) for x in (load_state(channel, chat_id).get("covered_subtopics") or []) if str(x).strip()]
        if not subs:
            for role, content in reversed(rows):
                if role == "assistant":
                    subs = parse_subtopics(content)
                    break
    except ImportError:
        subs = []
    try:
        from arka.core.context_ngrams import context_hint_for_query

        return context_hint_for_query(user_text, rows, subtopics=subs)
    except ImportError:
        return ""


def augment_with_hint(agent_text: str, hint: str) -> str:
    h = (hint or "").strip()
    if not h or h in agent_text:
        return agent_text
    if re.search(r"(?m)^Context match \(", agent_text or ""):
        return agent_text
    return f"Context match ({h}):\n{agent_text}"


@dataclass
class WebUiTurn:
    channel: str
    chat_id: str
    chat_id_source: str
    last_user: str
    agent_text: str
    context_hint: str = ""
    isolated: bool = False
    needs_past_chat: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


def prepare_turn(
    data: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    channel: str = WEBUI_CHANNEL,
) -> WebUiTurn:
    """Prepare one Open WebUI chat completion turn with context metadata."""
    messages = data.get("messages") or []
    chat_id, chat_id_source = resolve_chat_id(data, headers=headers, messages=messages)
    rows = rows_from_messages(messages)
    last_user = ""
    for role, content in reversed(rows):
        if role == "user":
            last_user = content
            break

    agent_text = build_agent_text(messages)
    hint = context_hint(last_user, messages, channel=channel, chat_id=chat_id) if last_user else ""
    if hint and agent_text and not re.search(r"(?m)^(User|Assistant):\s", agent_text):
        agent_text = augment_with_hint(agent_text, hint)

    needs_past = False
    try:
        from arka.core.chat_context_gate import needs_past_chat

        needs_past = bool(last_user) and needs_past_chat(last_user, rows)
    except ImportError:
        pass

    isolated = False
    try:
        from arka.core.web_session_memory import is_isolated_chat_id

        isolated = is_isolated_chat_id(chat_id)
    except ImportError:
        isolated = chat_id not in {"", "default", "unknown"}

    return WebUiTurn(
        channel=channel,
        chat_id=chat_id,
        chat_id_source=chat_id_source,
        last_user=last_user,
        agent_text=agent_text,
        context_hint=hint,
        isolated=isolated,
        needs_past_chat=needs_past,
        meta={
            "turn_count": len(rows),
            "has_transcript": bool(re.search(r"(?m)^(User|Assistant):\s", agent_text or "")),
        },
    )


def inspect_payload(
    data: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    channel: str = WEBUI_CHANNEL,
    as_text: bool = False,
) -> str | dict[str, Any]:
    """MCP/bridge parity — inspect what context would attach for this WebUI request."""
    turn = prepare_turn(data, headers=headers, channel=channel)
    openai_messages = []
    for role, content in rows_from_messages(data.get("messages") or []):
        openai_messages.append({"role": role, "content": content})

    try:
        from arka.core.context_manager import format_inspect as _fmt
        from arka.core.context_manager import inspect_turn

        report = inspect_turn(
            turn.last_user,
            channel=channel,
            chat_id=turn.chat_id,
            messages=openai_messages,
        )
        report["webui"] = {
            "chat_id_source": turn.chat_id_source,
            "context_hint": turn.context_hint,
            "isolated": turn.isolated,
            "needs_past_chat": turn.needs_past_chat,
            "meta": turn.meta,
        }
        if as_text:
            return _fmt(report)
        return report
    except ImportError:
        payload = {
            "channel": channel,
            "chat_id": turn.chat_id,
            "chat_id_source": turn.chat_id_source,
            "agent_text": turn.agent_text[:1200],
            "context_hint": turn.context_hint,
        }
        return payload
