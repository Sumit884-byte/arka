"""OpenAI-compatible /v1/chat/completions helpers for local Arka agent access."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterator

OPENAI_CHANNEL = "openai-api"


def _normalize_model(model: str) -> str:
    name = (model or "arka").strip()
    if name.endswith(":latest"):
        name = name[:-7]
    return name or "arka"


def last_user_message(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(block.get("text") or block.get("input_text") or "").strip()
                for block in content
                if isinstance(block, dict)
            ]
            return "\n".join(p for p in parts if p).strip()
    return ""


def chat_id_from_headers(headers: dict[str, str] | None) -> str:
    """Open WebUI forwards the conversation id in ``X-OpenWebUI-Chat-Id``."""
    if not headers:
        return ""
    for key in (
        "X-OpenWebUI-Chat-Id",
        "x-openwebui-chat-id",
        "X-Chat-Id",
        "x-chat-id",
        "X-Open-WebUI-Chat-Id",
    ):
        cid = str(headers.get(key) or headers.get(key.lower()) or "").strip()
        if cid:
            return cid[:64]
    return ""


def chat_id_from_payload(data: dict[str, Any], *, headers: dict[str, str] | None = None) -> str:
    """Per-conversation id — prefer chat_id over OpenAI ``user`` (account id)."""
    cid = chat_id_from_headers(headers)
    if cid:
        return cid
    meta = data.get("metadata")
    if isinstance(meta, dict):
        for key in ("chat_id", "conversation_id", "session_id", "id"):
            cid = str(meta.get(key) or "").strip()
            if cid:
                return cid[:64]
    cid = str(data.get("chat_id") or "").strip()
    if cid:
        return cid[:64]
    sid = str(data.get("session_id") or "").strip()
    if sid:
        return sid[:64]
    uid = str(data.get("user") or "").strip()
    if uid:
        return uid[:64]
    return "default"


def agent_text_from_chat_payload(data: dict[str, Any]) -> tuple[str, str, str]:
    """Return (agent_text, model, chat_id) from an OpenAI chat payload."""
    messages = data.get("messages") or []
    model = _normalize_model(str(data.get("model") or "arka"))
    chat_id = chat_id_from_payload(data)

    from arka.core.chat_context_gate import build_web_agent_text, rows_from_openai_messages

    text = build_web_agent_text(rows_from_openai_messages(messages))
    if model not in ("arka", "auto", "auto-route"):
        text = f"[prefer skill: {model}] {text}".strip()
    return text, model, chat_id


def models_payload(*, limit: int = 32) -> dict[str, Any]:
    created = int(time.time())
    rows = [
        {
            "id": "arka",
            "object": "model",
            "created": created,
            "owned_by": "arka",
        }
    ]
    try:
        from pathlib import Path

        skill_dir = Path(__file__).resolve().parents[1] / "agent"
        names = sorted(path.stem for path in skill_dir.glob("*.py") if not path.stem.startswith("_"))
        for skill in names[: max(0, int(limit))]:
            rows.append(
                {
                    "id": skill,
                    "object": "model",
                    "created": created,
                    "owned_by": "arka",
                }
            )
    except OSError:
        pass
    return {"object": "list", "data": rows}


def chat_completion_payload(answer: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "arka",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": max(1, len(answer.split())),
            "total_tokens": max(1, len(answer.split())),
        },
    }


def openai_chunk(
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    *,
    finish: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model or "arka",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def iter_openai_sse_chunks(
    text: str,
    *,
    model: str,
    channel: str = OPENAI_CHANNEL,
    chat_id: str = "default",
) -> Iterator[str]:
    """Yield OpenAI-style SSE lines for a streamed agent reply."""
    from arka.integrations.remote_server import iter_agent_remote, strip_ansi

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    first = True

    def emit(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    yield emit(openai_chunk(completion_id, created, model, {"role": "assistant"}))
    for piece, _exit_code in iter_agent_remote(text, channel=channel, chat_id=chat_id):
        if not piece:
            continue
        cleaned = strip_ansi(piece).replace("\r", "")
        if not cleaned:
            continue
        delta: dict[str, Any] = {"content": cleaned}
        if first:
            delta["role"] = "assistant"
            first = False
        yield emit(openai_chunk(completion_id, created, model, delta))
    yield emit(openai_chunk(completion_id, created, model, {}, finish="stop"))
    yield "data: [DONE]\n\n"
