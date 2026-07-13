"""Tests for arka provider selection and live model autodetection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(
            (
                "AI_PREFERRED",
                "LLM_PROVIDER",
                "LLM_MODEL",
                "OPENROUTER_",
                "GROQ_",
                "GEMINI_",
                "GOOGLE_API_KEY",
                "CONFIG_DIR",
            )
        ):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def arka_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "arka"
    cfg.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(cfg))

    def _cfg() -> Path:
        return cfg

    monkeypatch.setattr("arka.paths.config_dir", _cfg)
    monkeypatch.setattr("arka.llm.provider_select.config_dir", _cfg)
    monkeypatch.setattr("arka.llm.provider_select.env_file", lambda: cfg / ".env")
    return cfg


def test_set_preferred_provider_persists_env(arka_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from importlib import reload

    import arka.llm.fallback as fb
    import arka.llm.provider_select as ps

    reload(fb)
    reload(ps)

    with patch.object(ps, "detect_provider_models", return_value=(["meta-llama/llama-3.3-70b-instruct"], "live")):
        slug, model, path = ps.set_preferred_provider("openrouter")

    assert slug == "openrouter"
    assert model == "meta-llama/llama-3.3-70b-instruct"
    assert path == arka_config / ".env"
    text = path.read_text(encoding="utf-8")
    assert "AI_PREFERRED_PROVIDER=openrouter" in text
    assert "AI_PREFERRED_MODEL=meta-llama/llama-3.3-70b-instruct" in text
    assert "sk-or-test" not in text


def test_set_preferred_with_explicit_model(arka_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)

    from importlib import reload

    import arka.llm.provider_select as ps

    reload(ps)

    slug, model, _path = ps.set_preferred_provider(
        "openrouter",
        model="anthropic/claude-sonnet-4",
        autodetect=False,
    )
    assert slug == "openrouter"
    assert model == "anthropic/claude-sonnet-4"


def test_fetch_openrouter_models_live_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    payload = {
        "data": [
            {
                "id": "meta-llama/llama-3.3-70b-instruct",
                "architecture": {"modality": "text->text"},
                "top_provider": {"context_length": 131072},
            },
            {
                "id": "openai/text-embedding-3-small",
                "architecture": {"modality": "text->embedding"},
                "top_provider": {"context_length": 8192},
            },
            {
                "id": "google/gemini-2.0-flash-001",
                "architecture": {"modality": "text->text"},
                "top_provider": {},
            },
            {
                "id": "anthropic/claude-sonnet-4",
                "architecture": {"modality": "text->text"},
                "top_provider": {"context_length": 200000},
            },
        ]
    }

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb._OPENROUTER_LIVE_CACHE = None

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        models = fb.fetch_openrouter_models_live(force=True)

    assert models == [
        "meta-llama/llama-3.3-70b-instruct",
        "anthropic/claude-sonnet-4",
    ]


def test_detect_provider_models_falls_back_to_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)

    from importlib import reload

    import arka.llm.fallback as fb
    import arka.llm.provider_select as ps

    reload(fb)
    reload(ps)

    with patch.object(fb, "fetch_groq_models_live", return_value=[]):
        models, source = ps.detect_provider_models("groq", include_live=True)

    assert source == "catalog"
    assert "llama-3.3-70b-versatile" in models


def test_auto_pick_model_if_needed(arka_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "groq")

    from importlib import reload

    import arka.llm.provider_select as ps

    reload(ps)

    with patch.object(ps, "detect_provider_models", return_value=(["llama-3.3-70b-versatile"], "live")):
        chosen = ps.auto_pick_model_if_needed("groq")

    assert chosen == "llama-3.3-70b-versatile"
    env_text = (arka_config / ".env").read_text(encoding="utf-8")
    assert "AI_PREFERRED_MODEL=llama-3.3-70b-versatile" in env_text


def test_auto_pick_replaces_stale_openrouter_model(
    arka_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "anthropic/claude-3.5-sonnet")

    from importlib import reload

    import arka.llm.provider_select as ps

    reload(ps)

    with patch.object(
        ps,
        "fetch_openrouter_models_live",
        return_value=["meta-llama/llama-3.3-70b-instruct", "anthropic/claude-sonnet-4"],
    ):
        chosen = ps.auto_pick_model_if_needed("openrouter", force=True)

    assert chosen == "meta-llama/llama-3.3-70b-instruct"
    env_text = (arka_config / ".env").read_text(encoding="utf-8")
    assert "AI_PREFERRED_MODEL=meta-llama/llama-3.3-70b-instruct" in env_text


def test_nl_to_argv_patterns() -> None:
    from arka.llm.provider_select import is_provider_select_query, nl_to_argv

    assert is_provider_select_query("set preferred provider to openrouter")
    assert nl_to_argv("set preferred provider to openrouter") == ["set", "openrouter"]

    assert is_provider_select_query("what models are available on groq")
    assert nl_to_argv("what models are available on groq") == ["models", "groq"]

    assert nl_to_argv("list llm providers") == ["list"]
    assert nl_to_argv("show my preferred ai provider") == ["show"]


def test_llm_doctor_shows_model_count(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "meta-llama/llama-3.3-70b-instruct")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    with patch.object(fb, "provider_detected_model_count", return_value=42):
        lines = fb.llm_doctor_lines()

    assert any("42 models detected" in line for line in lines)


def test_cli_provider_list_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from arka.llm.provider_select import main

    assert main(["list"]) == 0


def test_detect_provider_models_hides_stale_openrouter_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from importlib import reload

    import arka.llm.fallback as fb
    import arka.llm.provider_select as ps

    reload(fb)
    reload(ps)

    with patch.object(
        ps,
        "fetch_openrouter_models_live",
        return_value=["meta-llama/llama-3.3-70b-instruct", "anthropic/claude-sonnet-4"],
    ):
        models, source = ps.detect_provider_models("openrouter", include_live=True)

    assert source == "live"
    assert "anthropic/claude-3.5-sonnet" not in models
    assert "meta-llama/llama-3.3-70b-instruct" in models


def test_detect_provider_models_include_all_merges_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from importlib import reload

    import arka.llm.fallback as fb
    import arka.llm.provider_select as ps

    reload(fb)
    reload(ps)

    with patch.object(
        ps,
        "fetch_openrouter_models_live",
        return_value=["meta-llama/llama-3.3-70b-instruct"],
    ):
        models, source = ps.detect_provider_models(
            "openrouter",
            include_live=True,
            include_all=True,
        )

    assert source == "live+catalog"
    assert "meta-llama/llama-3.3-70b-instruct" in models
    assert "openai/gpt-4o-mini" in models


def test_detect_provider_models_excludes_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from importlib import reload

    import arka.llm.fallback as fb
    import arka.llm.provider_select as ps

    reload(fb)
    reload(ps)
    fb.EXHAUSTION.reset()
    fb.EXHAUSTION.mark(
        "openrouter",
        "anthropic/claude-sonnet-4",
        RuntimeError("No endpoints found for anthropic/claude-sonnet-4."),
    )

    with patch.object(
        fb,
        "fetch_openrouter_models_live",
        return_value=["meta-llama/llama-3.3-70b-instruct", "anthropic/claude-sonnet-4"],
    ):
        models, _source = ps.detect_provider_models("openrouter", include_live=True)

    assert "anthropic/claude-sonnet-4" not in models
    assert "meta-llama/llama-3.3-70b-instruct" in models


def test_groq_model_ids_hides_stale_defaults_when_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    with patch.object(
        fb,
        "fetch_groq_models_live",
        return_value=["llama-3.3-70b-versatile"],
    ):
        models = fb.groq_model_ids()

    assert models == ["llama-3.3-70b-versatile"]
    assert "llama-3.1-8b-instant" not in models
