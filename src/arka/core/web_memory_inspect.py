"""Inspect what memory Arka attaches before answering a web chat turn."""

from __future__ import annotations

from typing import Any


def inspect_turn(
    user_text: str,
    *,
    channel: str = "open-webui",
    chat_id: str = "default",
    messages: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the memory layers that would influence the next reply."""
    from arka.core.chat_context_gate import build_web_agent_text, rows_from_openai_messages
    from arka.core.unified_memory import recall_preferences
    from arka.core.web_topic_memory import load_state, prepare_turn
    from arka.integrations.openai_chat import chat_id_from_payload

    rows = rows_from_openai_messages(messages or [])
    if not rows and user_text:
        rows = [("user", user_text)]

    resolved_chat_id = chat_id
    if headers:
        resolved_chat_id = chat_id_from_payload({}, headers=headers) or chat_id

    topic_state = load_state(channel, resolved_chat_id)
    from arka.core.web_session_memory import (
        augment_prompt_with_session_memory,
        session_context,
        status as session_status,
    )

    session_ctx = session_context(channel, resolved_chat_id, query=user_text)
    session_meta = session_status(channel, resolved_chat_id)
    addon, pending_state = prepare_turn(
        channel,
        resolved_chat_id,
        user_text,
        session_ctx=session_ctx,
    )
    agent_text = build_web_agent_text(rows) if rows else user_text
    agent_text = augment_prompt_with_session_memory(
        agent_text,
        channel=channel,
        chat_id=resolved_chat_id,
        user_text=user_text,
    )
    lt_ctx = recall_preferences(user_text, limit_chars=1200)

    inject_session = "Session memory (this chat only):" in (agent_text or "")

    issues: list[str] = []
    if resolved_chat_id in {"default", ""}:
        issues.append("chat_id is 'default' — session memory disabled; chats share one bucket")
    if topic_state.get("topic") and topic_state.get("covered_subtopics"):
        covered = topic_state.get("covered_subtopics") or []
        if not _covered_matches_user(user_text, covered):
            issues.append(
                "topic memory has covered subtopics from another subject "
                f"({covered[:3]})"
            )
    if session_ctx and not inject_session:
        if "Mario" in session_ctx or "Unity" in session_ctx or "scoring_system" in session_ctx:
            if "Mario" not in user_text and "Unity" not in user_text:
                issues.append("session file contains unrelated game-dev turns (not injected)")

    return {
        "channel": channel,
        "chat_id": resolved_chat_id,
        "topic_memory_before": topic_state,
        "topic_addon": addon,
        "topic_state_after_prepare": pending_state,
        "session_memory": session_meta,
        "session_context": session_ctx,
        "inject_session_into_prompt": inject_session,
        "long_term_preferences": lt_ctx,
        "agent_text": agent_text,
        "issues": issues,
    }


def _covered_matches_user(user_text: str, covered: list[str]) -> bool:
    try:
        from arka.core.web_topic_memory import covered_related_to_user
    except ImportError:
        return True
    return covered_related_to_user(user_text, covered)


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"channel={report.get('channel')} chat_id={report.get('chat_id')}",
        "",
        "=== topic memory (before) ===",
        _short(report.get("topic_memory_before")),
        "",
        "=== topic addon (system) ===",
        (report.get("topic_addon") or "(none)").strip() or "(none)",
        "",
        "=== n-gram context hint ===",
        _ngram_hint(report),
        "",
        "=== session memory (this chat) ===",
        _short(report.get("session_memory")),
        f"inject_into_prompt={report.get('inject_session_into_prompt')}",
        (report.get("session_context") or "(none)").strip()[:1200] or "(none)",
        "",
        "=== long-term preferences ===",
        (report.get("long_term_preferences") or "(none)").strip()[:600] or "(none)",
        "",
        "=== agent text ===",
        (report.get("agent_text") or "").strip()[:800],
    ]
    issues = report.get("issues") or []
    if issues:
        lines.extend(["", "=== issues ===", *[f"- {x}" for x in issues]])
    return "\n".join(lines)


def _ngram_hint(report: dict[str, Any]) -> str:
    try:
        from arka.core.context_ngrams import context_hint_for_query

        user = ""
        agent = str(report.get("agent_text") or "")
        for line in agent.splitlines():
            if line.startswith("User:"):
                user = line.split(":", 1)[1].strip()
        if not user:
            return "(none)"
        subs = (report.get("topic_memory_before") or {}).get("covered_subtopics") or []
        return context_hint_for_query(user, [], subtopics=subs) or "(none)"
    except ImportError:
        return "(unavailable)"


def _short(obj: object) -> str:
    import json

    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except TypeError:
        return str(obj)
