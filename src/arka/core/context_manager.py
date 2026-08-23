"""Unified context management for MCP clients and web chat."""

from __future__ import annotations

from typing import Any


def layers_status(*, channel: str = "", chat_id: str = "") -> dict[str, Any]:
    """Status of every memory layer Arka can inject into a reply."""
    info: dict[str, Any] = {"layers": {}}
    try:
        from arka.core.web_session_memory import is_isolated_chat_id, status as session_status

        info["layers"]["session_memory"] = session_status(channel or "open-webui", chat_id or "default")
        info["layers"]["session_memory"]["isolated"] = is_isolated_chat_id(chat_id or "")
    except ImportError:
        info["layers"]["session_memory"] = {"enabled": False}
    try:
        from arka.core.web_topic_memory import load_state, state_path

        ch = channel or "open-webui"
        cid = chat_id or "default"
        state = load_state(ch, cid)
        info["layers"]["topic_memory"] = {
            "topic": state.get("topic") or "",
            "covered_subtopics": state.get("covered_subtopics") or [],
            "path": str(state_path(ch, cid)),
        }
    except ImportError:
        info["layers"]["topic_memory"] = {"topic": ""}
    try:
        from arka.core.unified_memory import status as unified_status

        info["layers"]["unified_memory"] = unified_status(channel=channel, chat_id=chat_id)
    except ImportError:
        info["layers"]["unified_memory"] = {}
    try:
        from arka.core.chat_context_gate import _mode

        info["context_gate"] = _mode()
    except ImportError:
        info["context_gate"] = "heuristic"
    info["web_chat_fast"] = _web_chat_fast()
    return info


def _web_chat_fast() -> bool:
    import os

    return os.environ.get("WEB_CHAT_FAST", "1").strip().lower() not in {"0", "false", "no", "off"}


def inspect_turn(
    user_text: str,
    *,
    channel: str = "open-webui",
    chat_id: str = "default",
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """What Arka would attach before answering this turn (web parity)."""
    from arka.core.web_memory_inspect import inspect_turn as _inspect

    return _inspect(user_text, channel=channel, chat_id=chat_id, messages=messages)


def select_context(
    query: str,
    *,
    channel: str = "open-webui",
    chat_id: str = "default",
    limit_chars: int = 3000,
) -> dict[str, Any]:
    """N-gram / multigram shortcut — pick the best session slice for a query."""
    from arka.core.context_ngrams import context_hint_for_query, match_subtopic
    from arka.core.web_session_memory import is_isolated_chat_id, session_context
    from arka.core.web_topic_memory import load_state
    from arka.integrations.message_sessions import list_turns

    q = (query or "").strip()
    ch = channel or "open-webui"
    cid = chat_id or "default"
    topic = load_state(ch, cid)
    subs = [str(x) for x in (topic.get("covered_subtopics") or []) if str(x).strip()]
    rows: list[tuple[str, str]] = []
    for turn in list_turns(ch, cid):
        role = str(turn.get("role") or "user")
        text = str(turn.get("text") or "")
        if text:
            rows.append((role, text))
    hint = context_hint_for_query(q, rows, subtopics=subs)
    matched_sub = match_subtopic(q, subs) if subs else None
    ctx = session_context(ch, cid, limit_chars=limit_chars, query=q) if is_isolated_chat_id(cid) else ""
    return {
        "channel": ch,
        "chat_id": cid,
        "query": q,
        "context": ctx,
        "hint": hint,
        "matched_subtopic": matched_sub,
        "topic": topic.get("topic") or "",
        "covered_subtopics": subs,
        "isolated_chat": is_isolated_chat_id(cid),
    }


def gate_check(
    user_text: str,
    *,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Whether prior chat should be attached for this message."""
    from arka.core.chat_context_gate import (
        build_web_agent_text,
        needs_past_chat,
        needs_past_chat_heuristic,
        rows_from_openai_messages,
    )

    rows = rows_from_openai_messages(messages or [])
    if not rows and user_text:
        rows = [("user", user_text)]
    t = (user_text or "").strip()
    needs = needs_past_chat(t, rows) if rows else False
    agent_preview = build_web_agent_text(rows) if rows else t
    prebuilt = agent_preview != t and t in agent_preview
    return {
        "user_text": t,
        "needs_past_chat": needs,
        "heuristic": needs_past_chat_heuristic(t) if t else False,
        "prebuilt_transcript": prebuilt,
        "agent_text_preview": agent_preview[:1200],
    }


def format_inspect(report: dict[str, Any]) -> str:
    from arka.core.web_memory_inspect import format_report

    return format_report(report)
