"""Tests for LLM response share bundles."""

from __future__ import annotations

import json
from unittest.mock import patch

from arka.llm import share as ls


def setup_function() -> None:
    ls._LAST = None


def test_capture_and_format_markdown() -> None:
    ls.capture_llm_completion(
        output="Hello from the model.",
        provider="gemini",
        model_id="gemini-2.5-flash",
        task="chat",
        skill="web_answer",
        user_prompt="What is Arka?",
        latency_ms=842.5,
        attempts=1,
    )
    record = ls.llm_last_completion()
    assert record is not None
    assert record.provider == "gemini"
    assert record.prompt_hash

    text = ls.format_llm_share_bundle(record)
    assert "# Arka LLM Response" in text
    assert "gemini/gemini-2.5-flash" in text
    assert "**Task:** chat" in text
    assert "**Skill:** web_answer" in text
    assert "**Latency:** 842.5 ms" in text
    assert "Hello from the model." in text


def test_format_json_bundle() -> None:
    ls.capture_llm_completion(
        output="42",
        provider="groq",
        model_id="llama-3.3-70b-versatile",
        task="default",
    )
    bundle = ls.build_share_bundle(ls.llm_last_completion())
    assert bundle["kind"] == "arka-llm-share"
    assert bundle["provider"] == "groq"
    assert bundle["output"] == "42"

    payload = json.loads(ls.format_llm_share_bundle(bundle, fmt="json"))
    assert payload["model"] == "llama-3.3-70b-versatile"


def test_route_command_matches_nl() -> None:
    assert ls.route_command("share last llm response") == "share last"
    assert ls.route_command("copy my ai answer") == "share last"
    assert ls.route_command("share my arka config") is None


def test_main_prints_and_copy(monkeypatch, capsys) -> None:
    ls.capture_llm_completion(
        output="Share me",
        provider="openrouter",
        model_id="meta-llama/llama-3.3-70b-instruct",
    )

    code = ls.main(["last", "--format", "json"])
    assert code == 0
    out = capsys.readouterr().out
    assert json.loads(out)["output"] == "Share me"

    with patch("arka.integrations.clipboard_history.write_clipboard", return_value=True) as copied:
        code = ls.main(["last", "--copy"])
    assert code == 0
    copied.assert_called_once()
    assert "Copied LLM share bundle" in capsys.readouterr().out


def test_main_requires_output_when_empty() -> None:
    assert ls.main(["last"]) == 2


def test_handle_arka_share_last_and_format() -> None:
    from arka.integrations.mcp_server import _handle_arka_share

    ls.capture_llm_completion(
        output="Cached answer",
        provider="gemini",
        model_id="gemini-2.0-flash",
        task="chat",
    )

    markdown = _handle_arka_share({"action": "last"})
    assert "Cached answer" in markdown
    assert "gemini/gemini-2.0-flash" in markdown

    payload = json.loads(_handle_arka_share({"action": "format", "output": "Fresh", "provider": "groq", "model": "x", "format": "json"}))
    assert payload["output"] == "Fresh"
    assert payload["provider"] == "groq"


def test_handle_arka_share_copy(monkeypatch) -> None:
    from arka.integrations.mcp_server import _handle_arka_share

    ls.capture_llm_completion(
        output="Clip this",
        provider="gemini",
        model_id="gemini-2.0-flash",
    )
    monkeypatch.setattr("arka.integrations.clipboard_history.write_clipboard", lambda text: bool(text))

    payload = json.loads(_handle_arka_share({"action": "last", "copy": True}))
    assert payload["copied"] is True
    assert "Clip this" in payload["text"]
