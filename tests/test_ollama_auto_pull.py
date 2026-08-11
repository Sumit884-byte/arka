from __future__ import annotations

from unittest import mock

import pytest

from arka.llm import servers


@pytest.fixture(autouse=True)
def _reset_pull_state() -> None:
    servers.reset_ollama_pull_attempts()
    yield
    servers.reset_ollama_pull_attempts()


def test_is_ollama_model_missing_error() -> None:
    assert servers.is_ollama_model_missing_error("model 'qwen3:8b' not found")
    assert servers.is_ollama_model_missing_error("status code: 404")
    assert not servers.is_ollama_model_missing_error("connection refused")


def test_ensure_ollama_model_respects_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARKA_OLLAMA_AUTO_PULL", "0")
    with mock.patch.object(servers.subprocess, "run") as run:
        ok, msg = servers.ensure_ollama_model("llama3.2:1b")
    assert ok is False
    assert "disabled" in msg
    run.assert_not_called()


def test_ensure_ollama_model_pulls_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARKA_OLLAMA_AUTO_PULL", "1")
    monkeypatch.setenv("ARKA_OLLAMA_PULL_TIMEOUT", "30")
    with (
        mock.patch.object(servers.shutil, "which", return_value="/usr/bin/ollama"),
        mock.patch.object(servers.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")) as run,
        mock.patch("arka.llm.fallback.clear_ollama_live_cache") as clear_cache,
    ):
        ok, msg = servers.ensure_ollama_model("qwen3:8b", verbose=True)
        ok2, msg2 = servers.ensure_ollama_model("qwen3:8b")
    assert ok is True
    assert "pulled" in msg
    assert ok2 is False
    assert "already attempted" in msg2
    run.assert_called_once_with(
        ["/usr/bin/ollama", "pull", "qwen3:8b"],
        capture_output=True,
        text=True,
        timeout=30.0,
        env=mock.ANY,
    )
    clear_cache.assert_called_once()


def test_ensure_ollama_model_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARKA_OLLAMA_AUTO_PULL", "1")
    monkeypatch.setenv("ARKA_OLLAMA_PULL_TIMEOUT", "45")
    with (
        mock.patch.object(servers.shutil, "which", return_value="/usr/bin/ollama"),
        mock.patch.object(servers.subprocess, "run", side_effect=servers.subprocess.TimeoutExpired("ollama pull", 45)),
    ):
        ok, msg = servers.ensure_ollama_model("llama3.2:1b")
    assert ok is False
    assert "timed out" in msg


def test_try_ollama_auto_pull_retries_on_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.llm import fallback as fb

    monkeypatch.setenv("ARKA_OLLAMA_AUTO_PULL", "1")
    with mock.patch.object(fb, "ensure_ollama_model", return_value=(True, "pulled qwen3:8b")) as pull:
        assert fb._try_ollama_auto_pull("ollama", "qwen3:8b", "model not found", verbose=False) is True
        pull.assert_called_once_with("qwen3:8b", verbose=False)


def test_try_ollama_auto_pull_ignores_other_providers() -> None:
    from arka.llm import fallback as fb

    with mock.patch.object(servers, "ensure_ollama_model") as pull:
        assert fb._try_ollama_auto_pull("groq", "llama-3.3-70b-versatile", "model not found", verbose=False) is False
    pull.assert_not_called()
