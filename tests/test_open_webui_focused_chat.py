"""Focused Open WebUI chat: Arka-only UI defaults and thanks-is-not-code."""

from __future__ import annotations

from pathlib import Path

from arka.core import chat_context_gate as gate
from arka.web.frontend.cli import _open_webui_docker_cmd


def test_docker_cmd_disables_arena_and_controls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARKA_OPEN_WEBUI_NAME", raising=False)
    monkeypatch.delenv("WEBUI_NAME", raising=False)
    branding = tmp_path / "branding"
    branding.mkdir()
    (branding / "docker-entrypoint.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    cmd = _open_webui_docker_cmd(
        host="127.0.0.1",
        ui_port=3000,
        bridge_port=8769,
        token="secret",
        container="arka-open-webui",
        volume="open-webui-arka",
        image="ghcr.io/open-webui/open-webui:main",
        branding=branding,
    )
    assert "DEFAULT_MODELS=arka" in cmd
    assert "ENABLE_EVALUATION_ARENA_MODELS=false" in cmd
    assert "USER_PERMISSIONS_CHAT_CONTROLS=false" in cmd


def test_thanks_after_app_preview_is_not_more_code() -> None:
    rows = [
        ("user", "build an shopping app"),
        (
            "assistant",
            "Here is a working shopping storefront.\n```html\n<div>Store</div>\n```\nWant a cart next?",
        ),
        ("user", "ok great thank"),
    ]
    assert gate.is_acknowledgment("ok great thank")
    assert gate.needs_past_chat("ok great thank", rows) is False
    assert gate.is_answer_to_assistant_question("ok great thank", rows) is False
    assert gate.is_build_followup("ok great thank") is False
    assert gate.build_web_agent_text(rows) == "ok great thank"


def test_acknowledgment_skips_llm_in_web_chat() -> None:
    from arka.integrations.remote_server import iter_python_chat

    parts: list[str] = []
    for chunk, code in iter_python_chat("ok great thank", channel="open-webui", chat_id="ack-pr"):
        if code is not None:
            break
        if chunk:
            parts.append(chunk)
    assert "welcome" in "".join(parts).lower()
