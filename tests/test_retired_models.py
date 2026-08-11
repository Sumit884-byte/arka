"""Tests for retired LLM model auto-remediation."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from arka.llm import retired_models as rm


@pytest.fixture(autouse=True)
def _temp_retired_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "llm-retired-models.json"
    monkeypatch.setattr(rm, "_cache_path", lambda: store)
    monkeypatch.setenv("LLM_AUTO_RETIRED_FIX", "1")
    yield


def test_known_retired_minimax():
    assert rm.is_retired("ollama", "minimax-m2.5:cloud")
    assert rm.is_retired("ollama", "minimax-m2.5")


def test_record_and_filter_chain():
    rm.record_retired("groq", "old-model", reason="HTTP 410 retired")
    assert rm.is_retired("groq", "old-model")
    chain = rm.filter_chain([("groq", "old-model"), ("groq", "llama-3.1-8b-instant")])
    assert chain == [("groq", "llama-3.1-8b-instant")]


def test_auto_remediate_updates_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_path = tmp_path / ".env"
    env_path.write_text("AI_PREFERRED_PROVIDER=ollama\nOLLAMA_CHAT_MODEL=minimax-m2.5:cloud\n", encoding="utf-8")
    monkeypatch.setattr("arka.llm.provider_select.env_file", lambda: env_path)
    monkeypatch.setattr("arka.llm.provider_select.config_dir", lambda: tmp_path)

    def fake_detect(provider: str, **kwargs):
        assert provider == "ollama"
        return ["qwen3:8b", "llama3.2:1b"], "test"

    monkeypatch.setattr("arka.llm.provider_select.detect_provider_models", fake_detect)
    monkeypatch.setattr("arka.llm.provider_select.pick_default_model", lambda _p, models: models[0])

    with mock.patch.dict(
        "os.environ",
        {
            "AI_PREFERRED_PROVIDER": "ollama",
            "AI_PREFERRED_MODEL": "minimax-m2.5:cloud",
            "OLLAMA_CHAT_MODEL": "minimax-m2.5:cloud",
        },
        clear=False,
    ):
        hit = rm.auto_remediate_config("ollama", "minimax-m2.5:cloud", reason="retired")

    assert hit is not None
    assert hit["to"] == "qwen3:8b"
    text = env_path.read_text(encoding="utf-8")
    assert "OLLAMA_CHAT_MODEL=qwen3:8b" in text
    assert "AI_PREFERRED_MODEL=qwen3:8b" in text


def test_handle_retired_model_error_marks_store(capsys: pytest.CaptureFixture[str]):
    from arka.llm.fallback import ExhaustionStore

    store = ExhaustionStore()
    with mock.patch.object(rm, "auto_remediate_config", return_value={"from": "x", "to": "y", "env_keys": ["AI_PREFERRED_MODEL"]}):
        rm.handle_retired_model_error(
            "ollama",
            "minimax-m2.5:cloud",
            "minimax-m2.5 was retired (status code: 410)",
            store=store,
            verbose=True,
        )
    assert store.exhausted("ollama", "minimax-m2.5:cloud")
    assert "auto-replaced retired model" in capsys.readouterr().err


def test_exhaustion_store_marks_retired_without_retryable():
    from arka.llm.fallback import ExhaustionStore

    store = ExhaustionStore()
    store.mark("ollama", "minimax-m2.5:cloud", RuntimeError("HTTP 410: model was retired"))
    assert store.exhausted("ollama", "minimax-m2.5:cloud")


def test_build_chain_skips_known_retired(monkeypatch: pytest.MonkeyPatch):
    from arka.llm import fallback as fb

    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "ollama")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "minimax-m2.5:cloud")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    chain = fb.build_default_chain()
    assert ("ollama", "minimax-m2.5:cloud") not in chain
    assert any(p == "ollama" for p, _m in chain)
