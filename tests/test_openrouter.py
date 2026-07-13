import os
from unittest.mock import patch

import pytest


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(
            (
                "LLM_",
                "SKILL_MODEL",
                "ROUTE_MODEL",
                "ROUTING_MODEL",
                "AI_PREFERRED",
                "LLM_PROVIDER",
                "LLM_MODEL",
                "OPENROUTER_",
                "GEMINI_",
                "GROQ_",
                "OPENAI_",
                "ANTHROPIC_",
                "GOOGLE_API_KEY",
            )
        ):
            monkeypatch.delenv(key, raising=False)


def test_provider_available_with_openrouter_key(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    assert fb.provider_available("openrouter") is True
    assert fb._has_openrouter() is True
    assert fb._has_primary_cloud_keys() is False


def test_build_default_chain_openrouter_only(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert chain[0][0] == "openrouter"
    assert chain[0][1] == "meta-llama/llama-3.3-70b-instruct"


def test_build_default_chain_prefers_openrouter_when_set(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "anthropic/claude-sonnet-4")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert chain[0] == ("openrouter", "anthropic/claude-sonnet-4")


def test_llm_doctor_lines_lists_openrouter(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    lines = fb.llm_doctor_lines()
    assert any("openrouter" in line for line in lines)
    assert any("only cloud key" in line for line in lines)


def test_model_advisor_uses_openrouter_fallback(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

    from importlib import reload

    import arka.llm.fallback as fb
    import arka.llm.model_advisor as ma

    reload(fb)
    reload(ma)

    assert ma._cloud_chat_model() == "openrouter/meta-llama/llama-3.3-70b-instruct"
    assert ma._cloud_route_model() == "openrouter/meta-llama/llama-3.3-70b-instruct"


def test_openrouter_model_ids_skips_stale_preferred(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "anthropic/claude-3.5-sonnet")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    with patch.object(
        fb,
        "fetch_openrouter_models_live",
        return_value=["meta-llama/llama-3.3-70b-instruct", "anthropic/claude-sonnet-4"],
    ):
        models = fb.openrouter_model_ids()

    assert models[0] == "meta-llama/llama-3.3-70b-instruct"
    assert "anthropic/claude-3.5-sonnet" not in models


def test_openrouter_model_ids_skips_stale_catalog_when_live(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    with patch.object(
        fb,
        "fetch_openrouter_models_live",
        return_value=["meta-llama/llama-3.3-70b-instruct", "anthropic/claude-sonnet-4"],
    ):
        models = fb.openrouter_model_ids()

    assert "anthropic/claude-3.5-sonnet" not in models
    assert "openai/gpt-4o-mini" not in models


def test_openrouter_no_endpoints_marks_exhausted(monkeypatch: pytest.MonkeyPatch):
    _clear_llm_env(monkeypatch)

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb.EXHAUSTION.reset()

    fb.EXHAUSTION.mark(
        "openrouter",
        "anthropic/claude-3.5-sonnet",
        RuntimeError("No endpoints found for anthropic/claude-3.5-sonnet."),
    )

    assert fb.EXHAUSTION.exhausted("openrouter", "anthropic/claude-3.5-sonnet")
    assert fb.is_retryable_error("No endpoints found for anthropic/claude-3.5-sonnet.")
    assert fb._looks_like_error("No endpoints found for anthropic/claude-3.5-sonnet.")


def test_resolve_max_tokens_openrouter_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb._OPENROUTER_META_CACHE = (
        0.0,
        {
            "x-ai/grok-4.20-multi-agent": {
                "completion_price": 0.00005,
                "max_completion_tokens": 65536,
                "context_length": 131072,
            }
        },
    )

    assert fb.resolve_max_tokens("openrouter", "x-ai/grok-4.20-multi-agent", task="chat", user="hi") == 512
    assert (
        fb.resolve_max_tokens(
            "openrouter",
            "x-ai/grok-4.20-multi-agent",
            task="chat",
            user="Write a long essay about climate change with citations.",
        )
        == 4096
    )

    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "2048")
    assert (
        fb.resolve_max_tokens(
            "openrouter",
            "x-ai/grok-4.20-multi-agent",
            task="chat",
            user="Write a long essay about climate change with citations.",
        )
        == 2048
    )


def test_rank_openrouter_deprioritizes_expensive_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb._OPENROUTER_META_CACHE = (
        0.0,
        {
            "x-ai/grok-4.20-multi-agent": {"completion_price": 0.00005, "max_completion_tokens": 65536},
            "meta-llama/llama-3.3-70b-instruct": {"completion_price": 0.0000002, "max_completion_tokens": 8192},
            "google/gemini-2.0-flash-exp:free": {"completion_price": 0.0, "max_completion_tokens": 8192},
        },
    )

    models = [
        "x-ai/grok-4.20-multi-agent",
        "meta-llama/llama-3.3-70b-instruct",
        "google/gemini-2.0-flash-exp:free",
    ]
    ranked = fb._filter_openrouter_chat_models(models)
    assert ranked[0] == "meta-llama/llama-3.3-70b-instruct"
    assert ranked[-1] == "x-ai/grok-4.20-multi-agent"
    assert fb.pick_openrouter_default_model(models) == "meta-llama/llama-3.3-70b-instruct"


def test_openrouter_credit_error_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    msg = (
        "This request requires more credits, or fewer max_tokens. "
        "You requested up to 65536 tokens, but can only afford 12975."
    )
    assert fb._is_openrouter_credit_error(msg)
    assert fb.is_retryable_error(msg)
    assert fb._parse_affordable_tokens(msg) == 12975
    assert fb._reduce_max_tokens_for_credit_error(65536, msg) == 12975
    assert fb._is_openrouter_credit_error("insufficient credits to complete request")
    assert fb.is_retryable_error("insufficient credits to complete request")
    assert fb._is_openrouter_account_credit_failure(msg, 4096)
    assert fb._reduce_max_tokens_for_credit_error(4096, "requires more credits") == 2048


def test_openrouter_credit_error_retries_with_lower_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_AUTO_FALLBACK", "0")

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb

    reload(fb)
    fb.EXHAUSTION.reset()

    credit_msg = (
        "This request requires more credits, or fewer max_tokens. "
        "You requested up to 4096 tokens, but can only afford 2048."
    )
    calls: list[int | None] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            calls.append(kwargs_holder["max_tokens"])
            if len(calls) == 1:
                return SimpleNamespace(content=credit_msg)
            return SimpleNamespace(content="Hello there!")

    kwargs_holder = {"max_tokens": None}

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None):
        kwargs_holder["max_tokens"] = max_tokens
        return object()

    engine = fb.LlmFallbackEngine(
        chain=[("openrouter", "x-ai/grok-4.20-multi-agent")],
        store=fb.ExhaustionStore(),
    )
    long_user = "Write a detailed essay about renewable energy trends and policy."

    with patch.object(fb, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", long_user, temperature=0.2)

    assert result.text == "Hello there!"
    assert calls[0] == 4096
    assert calls[1] == 2048


def test_openrouter_credit_error_falls_back_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("LLM_AUTO_FALLBACK", "1")

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb

    reload(fb)
    fb.EXHAUSTION.reset()

    credit_msg = (
        "This request requires more credits, or fewer max_tokens. "
        "You requested up to 4096 tokens, but can only afford 12975."
    )
    calls: list[tuple[str, str]] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            provider, model_id = calls[-1]
            if provider == "openrouter":
                return SimpleNamespace(content=credit_msg)
            return SimpleNamespace(content="Fallback answer from Gemini.")

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None):
        calls.append((provider, model_id))
        return object()

    engine = fb.LlmFallbackEngine(
        chain=[
            ("openrouter", "x-ai/grok-4.20-multi-agent"),
            ("gemini", "gemini-2.0-flash"),
        ],
        store=fb.ExhaustionStore(),
    )

    with patch.object(fb, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", "Tell me something interesting.")

    assert result.text == "Fallback answer from Gemini."
    assert calls[0][0] == "openrouter"
    assert calls[-1][0] == "gemini"
    assert fb._is_openrouter_account_credit_failure(credit_msg, 4096)
