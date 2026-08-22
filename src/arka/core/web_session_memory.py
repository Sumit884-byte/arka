"""Per-chat session memory for Open WebUI and other web frontends."""

from __future__ import annotations

import re

_WEB_CHANNELS = frozenset({"open-webui", "openai-api", "web", "webui"})


def is_isolated_chat_id(chat_id: str) -> bool:
    """True when chat_id identifies one conversation (not the shared default bucket)."""
    cid = (chat_id or "").strip()
    return bool(cid) and cid not in {"default", "unknown"}


def session_context(
    channel: str,
    chat_id: str,
    *,
    limit_chars: int = 3000,
    query: str = "",
) -> str:
    """Recent turns for this chat only — empty when chat_id is shared/default."""
    if not is_isolated_chat_id(chat_id):
        return ""
    try:
        from arka.integrations.message_sessions import context_for

        return context_for(channel, chat_id, limit_chars=limit_chars, query=query)
    except ImportError:
        return ""


def _agent_text_has_transcript(text: str) -> bool:
    return bool(re.search(r"(?m)^(User|Assistant):\s", text or ""))


def should_attach_session_memory(
    user_text: str,
    agent_text: str,
    *,
    channel: str,
    chat_id: str,
) -> bool:
    """Attach stored session turns when this chat is isolated and the turn needs context."""
    if channel not in _WEB_CHANNELS or not is_isolated_chat_id(chat_id):
        return False
    if _agent_text_has_transcript(agent_text):
        return False
    if not session_context(channel, chat_id):
        return False
    try:
        from arka.core.chat_context_gate import needs_past_chat_heuristic
        from arka.core.web_topic_memory import is_continue_request

        if is_continue_request(user_text) or needs_past_chat_heuristic(user_text):
            return True
    except ImportError:
        pass
    return False


def augment_prompt_with_session_memory(
    agent_text: str,
    *,
    channel: str,
    chat_id: str,
    user_text: str = "",
) -> str:
    """Prefix prompt with session memory when this chat has an isolated id."""
    if not should_attach_session_memory(
        user_text or agent_text,
        agent_text,
        channel=channel,
        chat_id=chat_id,
    ):
        return agent_text
    ctx = session_context(channel, chat_id, query=user_text or agent_text)
    if not ctx:
        return agent_text
    return (
        f"Session memory (this chat only):\n{ctx}\n\n"
        f"Latest message:\n{agent_text}"
    )


def status(channel: str, chat_id: str) -> dict[str, object]:
    """Inspect session memory for one web chat."""
    ctx = session_context(channel, chat_id)
    return {
        "enabled": is_isolated_chat_id(chat_id),
        "channel": channel,
        "chat_id": chat_id,
        "turns_chars": len(ctx),
        "has_context": bool(ctx),
        "isolated": is_isolated_chat_id(chat_id),
    }
