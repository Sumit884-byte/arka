"""Cross-platform vLLM defaults, provider registry, and fallback chain."""

from __future__ import annotations

import os
from unittest import mock

import pytest


def _clear_vllm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "VLLM_HOST",
        "VLLM_API_URL",
        "VLLM_START_CMD",
        "VLLM_MODEL",
        "VLLM_MODELS",
        "DESCRIBE_IMAGE_VLLM_START_CMD",
        "DESCRIBE_IMAGE_MODEL",
        "VLLM_CLOUD_URL",
        "VLLM_CLOUD_API_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_vllm_provider_in_registry():
    from arka.llm.providers import get_provider

    spec = get_provider("vllm")
    assert spec is not None
    assert spec.slug == "vllm"
    assert spec.kind == "local_openai"


def test_build_default_chain_includes_vllm_when_start_cmd_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_vllm_env(monkeypatch)
    monkeypatch.setenv("VLLM_START_CMD", "vllm serve demo-model --port 8000")
    monkeypatch.setenv("GEMINI_LIST", "0")
    monkeypatch.setenv("GROQ_LIST", "0")
    monkeypatch.setenv("OLLAMA_LIST", "0")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert ("vllm", "demo-model") in chain


def test_build_default_chain_includes_vllm_when_host_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_vllm_env(monkeypatch)
    monkeypatch.setenv("VLLM_HOST", "127.0.0.1:9000")
    monkeypatch.setenv("VLLM_MODEL", "hosted-model")
    monkeypatch.setenv("GEMINI_LIST", "0")
    monkeypatch.setenv("GROQ_LIST", "0")
    monkeypatch.setenv("OLLAMA_LIST", "0")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert ("vllm", "hosted-model") in chain


def test_apply_vllm_defaults_linux_sets_start_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_vllm_env(monkeypatch)
    from arka.llm import servers

    with (
        mock.patch.object(servers, "host_os", return_value="linux"),
        mock.patch.object(servers.shutil, "which", return_value="/usr/bin/vllm"),
    ):
        servers.apply_vllm_defaults(vision=True)
    assert os.environ.get("VLLM_HOST") == "127.0.0.1:8000"
    assert os.environ.get("VLLM_START_CMD", "").startswith("vllm serve")
    assert os.environ.get("LLM_SERVER_START_TIMEOUT") == "600"


def test_apply_vllm_defaults_windows_skips_start_without_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_vllm_env(monkeypatch)
    from arka.llm import servers

    with (
        mock.patch.object(servers, "host_os", return_value="windows"),
        mock.patch.object(servers.shutil, "which", return_value=None),
    ):
        servers.apply_vllm_defaults(vision=False)
    assert "VLLM_HOST" not in os.environ
    assert "VLLM_START_CMD" not in os.environ


def test_apply_vllm_defaults_macos_vision_uses_metal_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_vllm_env(monkeypatch)
    from arka.llm import servers

    with (
        mock.patch.object(servers, "host_os", return_value="macos"),
        mock.patch.object(servers.shutil, "which", return_value="/opt/vllm/bin/vllm"),
    ):
        servers.apply_vllm_defaults(vision=True)
    cmd = os.environ.get("VLLM_START_CMD", "")
    assert "mlx-community" in cmd or "Qwen" in cmd


def test_build_default_chain_skips_vllm_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_vllm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_LIST", "0")
    monkeypatch.setenv("GROQ_LIST", "0")
    monkeypatch.setenv("OLLAMA_LIST", "0")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert not any(provider == "vllm" for provider, _ in chain)
    # Second call must not pollute env and add vllm after apply_vllm_defaults side effects.
    chain_again = fb.build_default_chain(task="chat")
    assert not any(provider == "vllm" for provider, _ in chain_again)


def test_vllm_prepare_silent_when_not_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_vllm_env(monkeypatch)
    from arka.llm.servers import MANAGER

    with mock.patch("arka.llm.servers.is_reachable", return_value=False):
        assert MANAGER.prepare("vllm") is False
    captured = capsys.readouterr()
    assert "Starting vLLM" not in captured.err
    assert "vLLM not reachable" not in captured.err
