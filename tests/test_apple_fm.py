"""Tests for Apple Foundation Models (apple-fm) provider — mock-based, no real SDK required."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import arka.llm.apple_fm as apple_fm
import arka.llm.fallback as fallback
import arka.llm.providers as providers


@pytest.fixture(autouse=True)
def _reset_apple_fm_sdk_cache() -> None:
    apple_fm._SDK_MODULE = None
    apple_fm._SDK_IMPORT_TRIED = False


def test_provider_registered() -> None:
    spec = providers.get_provider("apple-fm")
    assert spec is not None
    assert spec.slug == "apple-fm"
    assert spec.kind == "native"
    assert spec.env_keys == ()

    alias = providers.get_provider("apple_fm")
    assert alias is not None
    assert alias.slug == "apple-fm"


def test_unavailable_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apple_fm.platform, "system", lambda: "Linux")
    status = apple_fm.check_availability()
    assert not status.platform_ok
    assert not status.available
    assert not apple_fm.provider_available()


def test_unavailable_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apple_fm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple_fm, "macos_version_tuple", lambda: (26, 0))
    monkeypatch.setenv("APPLE_FM_ENABLED", "0")
    assert not apple_fm.apple_fm_enabled()
    assert not apple_fm.provider_available()


def test_sdk_availability_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apple_fm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple_fm, "macos_version_tuple", lambda: (26, 0))
    monkeypatch.setenv("APPLE_FM_ENABLED", "1")

    fake_fm = ModuleType("apple_fm_sdk")

    class FakeModel:
        def is_available(self):
            return True, None

    fake_fm.SystemLanguageModel = FakeModel
    fake_fm.GenerationOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    fake_fm.LanguageModelSession = MagicMock()

    monkeypatch.setitem(sys.modules, "apple_fm_sdk", fake_fm)
    apple_fm._SDK_IMPORT_TRIED = False
    apple_fm._SDK_MODULE = None

    status = apple_fm.check_availability()
    assert status.sdk_installed
    assert status.model_available
    assert status.backend == "sdk"
    assert apple_fm.provider_available()


def test_sdk_unavailable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apple_fm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple_fm, "macos_version_tuple", lambda: (26, 0))
    monkeypatch.setenv("APPLE_FM_ENABLED", "1")

    fake_fm = ModuleType("apple_fm_sdk")

    class FakeModel:
        def is_available(self):
            return False, SimpleNamespace(name="DEVICE_NOT_ELIGIBLE")

    fake_fm.SystemLanguageModel = FakeModel

    monkeypatch.setitem(sys.modules, "apple_fm_sdk", fake_fm)
    apple_fm._SDK_IMPORT_TRIED = False
    apple_fm._SDK_MODULE = None

    status = apple_fm.check_availability()
    assert not status.model_available
    assert "DEVICE_NOT_ELIGIBLE" in status.unavailable_reason


def test_cli_fallback_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apple_fm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple_fm, "macos_version_tuple", lambda: (26, 0))
    monkeypatch.setenv("APPLE_FM_ENABLED", "1")
    monkeypatch.setattr(apple_fm, "sdk_installed", lambda: False)
    monkeypatch.setattr(apple_fm, "_http_ok", lambda url, timeout=2.0: True)

    status = apple_fm.check_availability()
    assert status.cli_reachable
    assert status.backend == "cli"
    assert apple_fm.provider_available()


def test_parse_chain_apple_fm() -> None:
    assert fallback.parse_chain("apple-fm:apple-fm-system") == [
        ("apple-fm", "apple-fm-system"),
    ]


def test_build_model_native_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apple_fm,
        "check_availability",
        lambda force=False: apple_fm.AppleFmStatus(
            platform_ok=True,
            macos_version="26.0",
            enabled=True,
            sdk_installed=True,
            model_available=True,
            backend="sdk",
        ),
    )
    model = fallback.build_model("apple-fm", "apple-fm-system", 0.2, max_tokens=512)
    assert isinstance(model, apple_fm.AppleFmModel)
    assert model.model_id == "apple-fm-system"
    assert model.max_tokens == 512


def test_build_model_cli_openai_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apple_fm,
        "check_availability",
        lambda force=False: apple_fm.AppleFmStatus(
            platform_ok=True,
            macos_version="26.0",
            enabled=True,
            sdk_installed=False,
            model_available=False,
            cli_reachable=True,
            cli_base_url="http://127.0.0.1:8765/v1",
            backend="cli",
        ),
    )
    monkeypatch.setattr(apple_fm, "cli_base_url", lambda: "http://127.0.0.1:8765/v1")

    agno_openai = MagicMock()
    with patch.dict("sys.modules", {"agno.models.openai": SimpleNamespace(OpenAIChat=agno_openai)}):
        model = fallback.build_model("apple-fm", "apple-fm-system", 0.2)
    agno_openai.assert_called_once()
    kwargs = agno_openai.call_args.kwargs
    assert kwargs["base_url"] == "http://127.0.0.1:8765/v1"


def test_apple_fm_in_fallback_chain_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith(("LLM_", "AI_PREFERRED", "SKILL_MODEL", "GEMINI", "GROQ", "OPENROUTER")):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(apple_fm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple_fm, "macos_version_tuple", lambda: (26, 0))
    monkeypatch.setenv("APPLE_FM_ENABLED", "1")
    monkeypatch.setattr(apple_fm, "provider_available", lambda: True)
    monkeypatch.setattr(apple_fm, "apple_fm_model_ids", lambda: ["apple-fm-system"])
    monkeypatch.setattr(fallback, "_has_gemini", lambda: False)
    monkeypatch.setattr(fallback, "_has_groq", lambda: False)
    monkeypatch.setattr(fallback, "_has_openrouter", lambda: False)
    monkeypatch.setattr(fallback, "_ollama_reachable", lambda: False)

    chain = fallback.build_default_chain(task="chat")
    assert ("apple-fm", "apple-fm-system") in chain


def test_complete_via_apple_fm_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apple_fm,
        "complete",
        lambda system, user, temperature=0.2, max_tokens=None: "hello from apple",
    )
    engine = fallback.LlmFallbackEngine(
        task="chat",
        chain=[("apple-fm", "apple-fm-system")],
    )
    monkeypatch.setattr(
        fallback,
        "build_model",
        lambda provider, model_id, temperature, max_tokens=None, session=None: apple_fm.AppleFmModel(
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )
    monkeypatch.setattr(fallback, "provider_available", lambda provider: provider == "apple-fm")

    result = engine.complete("You are helpful.", "Hi")
    assert result.text == "hello from apple"
    assert result.provider == "apple-fm"
