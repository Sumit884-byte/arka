import json
import os

import pytest
import arka.llm.fallback as fb


def _clear_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(
            (
                "LLM_FALLBACK",
                "SKILL_MODEL",
                "SKILL_MODELS",
                "ROUTE_MODEL",
                "ROUTING_MODEL",
                "LLM_SKILL_MODELS",
                "AI_PREFERRED",
                "LLM_PROVIDER",
                "LLM_MODEL",
            )
        ):
            monkeypatch.delenv(key, raising=False)


def test_parse_chain_colon_and_slash():
    from arka.llm.fallback import parse_chain

    assert parse_chain("gemini:gemini-2.0-flash,groq/llama-3.3-70b-versatile") == [
        ("gemini", "gemini-2.0-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ]


def test_parse_chain_bare_model_infers_provider(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    assert fb.parse_chain("gemini-2.5-flash") == [("gemini", "gemini-2.5-flash")]
    assert fb.parse_chain("llama-3.3-70b-versatile") == [("groq", "llama-3.3-70b-versatile")]


def test_llm_fallback_chain_alias(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("LLM_FALLBACK_CHAIN", "groq:llama-3.1-8b-instant,gemini:gemini-2.0-flash")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert chain[:2] == [
        ("groq", "llama-3.1-8b-instant"),
        ("gemini", "gemini-2.0-flash"),
    ]


def test_task_override_beats_global(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("LLM_FALLBACK", "gemini:gemini-2.0-flash")
    monkeypatch.setenv("LLM_FALLBACK_ROUTE", "groq:llama-3.1-8b-instant")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    assert fb.build_default_chain(task="route") == [("groq", "llama-3.1-8b-instant")]
    assert fb.build_default_chain(task="chat") == [("gemini", "gemini-2.0-flash")]


def test_route_model_prepends(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ROUTE_MODEL", "groq/llama-3.1-8b-instant")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="route")
    assert chain[0] == ("groq", "llama-3.1-8b-instant")
    assert len(chain) > 1


def test_routing_model_alias(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ROUTING_MODEL", "groq/llama-3.1-8b-instant")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="route")
    assert chain[0] == ("groq", "llama-3.1-8b-instant")


def test_skill_model_beats_route_model(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ROUTE_MODEL", "groq/llama-3.1-8b-instant")
    monkeypatch.setenv("SKILL_MODEL_ROUTE", "gemini/gemini-2.5-flash")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="route")
    assert chain[0] == ("gemini", "gemini-2.5-flash")
    assert ("groq", "llama-3.1-8b-instant") in chain


def test_skill_model_task_prepend(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("SKILL_MODEL_CHAT", "groq:llama-3.3-70b-versatile")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="chat")
    assert chain[0] == ("groq", "llama-3.3-70b-versatile")


def test_llm_fallback_guidance_prepends(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("LLM_FALLBACK_GUIDANCE", "openai:gpt-4o-mini")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert chain[0] == ("openai", "gpt-4o-mini")


def test_llm_skill_models_json(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    cfg = tmp_path / "skill-models.json"
    cfg.write_text(
        json.dumps(
            {
                "route": "groq/llama-3.1-8b-instant",
                "summarize": ["gemini/gemini-2.5-flash", "groq/llama-3.3-70b-versatile"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_SKILL_MODELS", str(cfg))

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb._SKILL_MODELS_CACHE = None

    route_chain = fb.build_default_chain(task="route")
    assert route_chain[0] == ("groq", "llama-3.1-8b-instant")

    summarize_chain = fb.build_default_chain(task="summarize")
    assert summarize_chain[:2] == [
        ("gemini", "gemini-2.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ]


def test_skill_models_inline_json(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv(
        "SKILL_MODELS",
        json.dumps({"chat": "gemini-2.5-flash", "route": "groq/llama-3.1-8b-instant"}),
    )

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb._SKILL_MODELS_CACHE = None

    chat_chain = fb.build_default_chain(task="chat")
    assert chat_chain[0] == ("gemini", "gemini-2.5-flash")

    route_chain = fb.build_default_chain(task="route")
    assert route_chain[0] == ("groq", "llama-3.1-8b-instant")


def test_per_skill_model_prepend(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("SKILL_MODEL_WEB_ANSWER", "groq/llama-3.3-70b-versatile")
    monkeypatch.setenv("SKILL_MODEL_CHAT", "gemini/gemini-2.5-flash")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    skill_chain = fb.build_default_chain(task="chat", skill="web_answer")
    assert skill_chain[0] == ("groq", "llama-3.3-70b-versatile")

    chat_chain = fb.build_default_chain(task="chat", skill="talk")
    assert chat_chain[0] == ("gemini", "gemini-2.5-flash")


def test_skill_models_file_per_skill(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    cfg = tmp_path / "skill-models.json"
    cfg.write_text(
        json.dumps(
            {
                "_profiles": {"chat": "gemini/gemini-2.0-flash"},
                "pdf_ask": "anthropic/claude-sonnet-4-20250514",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_SKILL_MODELS", str(cfg))

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)
    fb._SKILL_MODELS_CACHE = None

    pdf_chain = fb.build_default_chain(task="pdf", skill="pdf_ask")
    assert pdf_chain[0] == ("anthropic", "claude-sonnet-4-20250514")

    chat_chain = fb.build_default_chain(task="chat", skill="web_answer")
    assert chat_chain[0] == ("gemini", "gemini-2.0-flash")


def test_resolve_llm_context_from_skill(monkeypatch: pytest.MonkeyPatch):
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_SKILL", "pdf_ask")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    task, skill = fb.resolve_llm_context()
    assert task == "pdf"
    assert skill == "pdf_ask"


def test_builtin_tail_chain_matches_default():
    from arka.llm.fallback import DEFAULT_CHAIN, builtin_tail_chain

    assert builtin_tail_chain() == list(DEFAULT_CHAIN)
    assert DEFAULT_CHAIN[0] == ("gemini", "gemini-2.5-flash")
    assert DEFAULT_CHAIN[-1] == ("ollama", "minimax-m2:cloud")


def _fake_llm_engine_chain() -> list[tuple[str, str]]:
    return [
        ("gemini", "gemini-2.0-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ]


def test_llm_fallback_trace_suppressed_in_normal_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_MODE", "agent")
    monkeypatch.setenv("LLM_FALLBACK_NOTIFY", "1")
    monkeypatch.delenv("LLM_VERBOSE", raising=False)

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb

    reload(fb)
    fb.EXHAUSTION.reset()

    calls: list[int] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("gemini unavailable")
            return SimpleNamespace(content="Groq answer")

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None, **kwargs):
        return object()

    engine = fb.LlmFallbackEngine(chain=_fake_llm_engine_chain(), store=fb.ExhaustionStore())

    with patch.object(fb, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", "Hello")

    assert result.text == "Groq answer"
    captured = capsys.readouterr()
    assert "arka_llm:" not in captured.err


def test_llm_fallback_trace_visible_in_debug_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_MODE", "debug")
    monkeypatch.setenv("LLM_FALLBACK_NOTIFY", "1")
    monkeypatch.delenv("LLM_VERBOSE", raising=False)

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb

    reload(fb)
    fb.EXHAUSTION.reset()

    calls: list[int] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("gemini unavailable")
            return SimpleNamespace(content="Groq answer")

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None, **kwargs):
        return object()

    engine = fb.LlmFallbackEngine(chain=_fake_llm_engine_chain(), store=fb.ExhaustionStore())

    with patch.object(fb, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", "Hello")

    assert result.text == "Groq answer"
    captured = capsys.readouterr()
    assert "arka_llm: fallback ok" in captured.err


def test_retired_model_error_is_permanent():
    assert fb._is_retired_model_error("HTTP 410: minimax-m2 was retired")
    assert fb._is_retired_model_error("model deprecated")
    assert not fb._is_retired_model_error("temporary timeout")


def test_retired_response_body_is_treated_as_error():
    assert fb._looks_like_error("minimax-m2.5 was retired (status code: 410)")


def test_connection_error_is_treated_as_failure():
    assert fb._looks_like_error("Connection error.")
    assert fb._looks_like_error("Connection error")
    assert fb.is_retryable_error("Connection error.")


def test_connection_error_does_not_stop_fallback_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_MODE", "debug")

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb_mod

    reload(fb_mod)
    fb_mod.EXHAUSTION.reset()

    chain = [
        ("openrouter", "test-model"),
        ("groq", "llama-3.3-70b-versatile"),
        ("huggingface", "meta-llama/Meta-Llama-3-8B-Instruct"),
        ("gemini", "gemini-2.0-flash"),
    ]

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            provider = FakeAgent.last_provider
            if provider == "openrouter":
                raise RuntimeError("429 rate limit")
            if provider == "groq":
                return SimpleNamespace(content="quota exceeded")
            if provider == "huggingface":
                return SimpleNamespace(content="Connection error.")
            return SimpleNamespace(content="Rust is a systems programming language focused on safety and performance.")

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None, **kwargs):
        FakeAgent.last_provider = provider
        return object()

    FakeAgent.last_provider = ""
    engine = fb_mod.LlmFallbackEngine(chain=chain, store=fb_mod.ExhaustionStore())

    with patch.object(fb_mod, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", "what is Rust?")

    assert result.text == "Rust is a systems programming language focused on safety and performance."
    assert result.provider == "gemini"
    assert result.attempts == 4
    captured = capsys.readouterr()
    assert "huggingface" in captured.err
    assert "Connection error" in captured.err or "fail huggingface" in captured.err


def test_format_llm_failure_lists_providers():
    msg = fb.format_llm_failure(
        tried=[
            "openrouter/x-ai/grok (max_tokens=512)",
            "groq/llama-3.3-70b-versatile",
            "huggingface/meta-llama/Meta-Llama-3-8B-Instruct",
        ],
        last_error="huggingface/meta-llama/Meta-Llama-3-8B-Instruct: Connection error.",
        attempts=3,
    )
    assert "All configured LLM providers failed." in msg
    assert "openrouter" in msg
    assert "groq" in msg
    assert "huggingface" in msg
    assert "arka doctor" in msg
    assert "Connection error" in msg


def test_llm_complete_returns_formatted_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_fallback_env(monkeypatch)

    from importlib import reload
    from unittest.mock import patch

    import arka.llm.fallback as fb_mod

    reload(fb_mod)

    with patch.object(fb_mod.LlmFallbackEngine, "complete") as mock_complete:
        mock_complete.return_value = fb_mod.CompletionResult(
            error=fb_mod.format_llm_failure(
                tried=["gemini/gemini-2.0-flash"],
                last_error="gemini/gemini-2.0-flash: quota exceeded",
                attempts=1,
            ),
            attempts=1,
            tried=["gemini/gemini-2.0-flash"],
        )
        text = fb_mod.llm_complete("sys", "user", task="chat")

    assert "All configured LLM providers failed." in text
    assert "arka doctor" in text


def test_exhaustion_notification_is_best_effort(monkeypatch):
    monkeypatch.setattr(fb, "_EXHAUSTION_NOTIFIED", False)
    monkeypatch.setattr(fb, "_truthy", lambda *args: True)
    fb._notify_total_exhaustion("all exhausted")
    assert fb._EXHAUSTION_NOTIFIED is True


def test_gemini_429_exhausts_all_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash,gemini-2.0-flash-lite")

    from importlib import reload

    import arka.llm.fallback as fb_mod

    reload(fb_mod)
    store = fb_mod.ExhaustionStore()
    store.mark("gemini", "gemini-2.5-flash", RuntimeError("429 RESOURCE_EXHAUSTED"))

    for mid in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"):
        assert store.exhausted("gemini", mid)


def test_gemini_rate_limit_error_is_case_insensitive() -> None:
    assert fb._is_gemini_rate_limit_error("status: resource_exhausted")


def test_exhaustion_cooldown_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_EXHAUSTION_COOLDOWN", "60")

    from importlib import reload

    import arka.llm.fallback as fb_mod

    reload(fb_mod)
    store = fb_mod.ExhaustionStore()
    past = fb_mod.time.time() - 120
    store._mark_timed("gemini", "gemini-2.0-flash", now=past)

    assert store.exhausted("gemini", "gemini-2.0-flash") is False


def test_gemini_429_skips_remaining_models_in_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_MODE", "debug")
    monkeypatch.setenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash,gemini-2.0-flash-lite")

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb_mod

    reload(fb_mod)
    store = fb_mod.ExhaustionStore()

    chain = [
        ("gemini", "gemini-2.5-flash"),
        ("gemini", "gemini-2.0-flash"),
        ("gemini", "gemini-2.0-flash-lite"),
        ("groq", "llama-3.3-70b-versatile"),
    ]
    calls: list[tuple[str, str]] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            provider, model_id = calls[-1]
            if provider == "gemini":
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return SimpleNamespace(content="ok from groq")

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None, **kwargs):
        calls.append((provider, model_id))
        return object()

    engine = fb_mod.LlmFallbackEngine(chain=chain, store=store)

    with patch.object(fb_mod, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", "hello")

    assert result.provider == "groq"
    assert len([c for c in calls if c[0] == "gemini"]) == 1


def test_gemini_rate_limit_skips_key_rotation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_MODE", "debug")
    monkeypatch.setenv("GEMINI_API_KEY", "key-a")
    monkeypatch.setenv("GEMINI_API_KEY_2", "key-b")

    from importlib import reload
    from types import SimpleNamespace
    from unittest.mock import patch

    import arka.llm.fallback as fb_mod

    reload(fb_mod)
    store = fb_mod.ExhaustionStore()
    chain = [
        ("gemini", "gemini-2.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ]
    calls: list[tuple[str, str]] = []
    rotate_calls: list[str] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, _user):
            provider, model_id = calls[-1]
            if provider == "gemini":
                raise RuntimeError("429 RESOURCE_EXHAUSTED free_tier quota exceeded")
            return SimpleNamespace(content="ok from groq")

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None, **kwargs):
        calls.append((provider, model_id))
        return object()

    def fake_rotate(provider, exc):
        rotate_calls.append(str(exc))
        return True

    engine = fb_mod.LlmFallbackEngine(chain=chain, store=store)

    with patch.object(fb_mod, "build_model", side_effect=fake_build_model):
        with patch.object(fb_mod, "rotate_provider_key", side_effect=fake_rotate):
            with patch("agno.agent.Agent", FakeAgent):
                result = engine.complete("You are helpful.", "hello")

    assert result.provider == "groq"
    assert rotate_calls == []
    assert len([c for c in calls if c[0] == "gemini"]) == 1
    assert store.exhausted("gemini", "gemini-2.5-flash")


def test_local_first_policy_puts_ollama_before_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("ARKA_MODEL_POLICY", "local-first")
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "gemini")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_MODELS", "gemini-2.5-flash")
    monkeypatch.setenv("OLLAMA_MODELS", "qwen3:8b")

    from importlib import reload
    from unittest.mock import patch

    import arka.llm.fallback as fb_mod

    reload(fb_mod)

    with patch.object(fb_mod, "provider_available", side_effect=lambda slug: slug in {"gemini", "ollama", "groq"}):
        chain = fb_mod.build_default_chain(task="chat")

    assert chain[0][0] == "ollama"
    assert ("gemini", "gemini-2.5-flash") in chain


def test_alert_model_exhaustion_wires_email_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fb, "_EXHAUSTION_NOTIFIED", False)
    monkeypatch.setenv("ARKA_ALERT_MODEL_EXHAUSTED", "1")
    captured: list[dict] = []

    def capture(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "channels": ["os"], "skipped": False}

    monkeypatch.setattr("arka.integrations.email_alert.maybe_model_exhausted_alert", capture)

    chain = [
        ("gemini", "gemini-2.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ]
    store = fb.ExhaustionStore()
    store.mark("gemini", "gemini-2.5-flash", RuntimeError("429 RESOURCE_EXHAUSTED"))
    store.mark("groq", "llama-3.3-70b-versatile", RuntimeError("429 rate limit"))

    fb._alert_model_exhaustion(
        tried=["gemini/gemini-2.5-flash", "groq/llama-3.3-70b-versatile"],
        failures={
            "gemini/gemini-2.5-flash": "429 RESOURCE_EXHAUSTED",
            "groq/llama-3.3-70b-versatile": "429 rate limit",
        },
        task="chat",
        skill="",
        last_error="groq/llama-3.3-70b-versatile: 429 rate limit",
        chain=chain,
        store=store,
    )

    assert len(captured) == 1
    assert captured[0]["tried"]
    assert "429" in captured[0]["failures"]["gemini/gemini-2.5-flash"]


def test_preferred_chain_entries_honors_explicit_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_fallback_env(monkeypatch)
    monkeypatch.setenv("LLM_FALLBACK", "gemini:gemini-2.5-flash,groq:llama-3.3-70b-versatile")

    from importlib import reload

    import arka.llm.fallback as fb_mod

    reload(fb_mod)
    preferred = fb_mod.preferred_chain_entries(task="chat")
    assert preferred == [
        ("gemini", "gemini-2.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ]


def test_preferred_all_failed_requires_every_preferred_tried() -> None:
    preferred = [("gemini", "gemini-2.5-flash"), ("groq", "llama-3.3-70b-versatile")]
    store = fb.ExhaustionStore()
    tried = ["gemini/gemini-2.5-flash"]
    assert fb._preferred_all_failed(preferred, tried=tried, store=store) is False
    tried.append("groq/llama-3.3-70b-versatile")
    assert fb._preferred_all_failed(preferred, tried=tried, store=store) is True


def test_resolve_max_tokens_no_short_query_cap() -> None:
    assert fb.resolve_max_tokens("groq", "llama-3.1-8b-instant", task="chat", user="hi") == 4096
    assert (
        fb.resolve_max_tokens(
            "groq",
            "llama-3.1-8b-instant",
            task="chat",
            user="design plan for an food website",
        )
        == 4096
    )
