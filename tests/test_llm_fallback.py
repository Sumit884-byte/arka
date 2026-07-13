import json
import os

import pytest


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
    assert DEFAULT_CHAIN[-1] == ("ollama", "llama3.2:1b")


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

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None):
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

    def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None):
        return object()

    engine = fb.LlmFallbackEngine(chain=_fake_llm_engine_chain(), store=fb.ExhaustionStore())

    with patch.object(fb, "build_model", side_effect=fake_build_model):
        with patch("agno.agent.Agent", FakeAgent):
            result = engine.complete("You are helpful.", "Hello")

    assert result.text == "Groq answer"
    captured = capsys.readouterr()
    assert "arka_llm: fallback ok" in captured.err
