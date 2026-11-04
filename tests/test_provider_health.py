"""Provider health: reaction budgets, config warnings, timeouts."""

from __future__ import annotations

import time

import pytest

from arka.llm import provider_health as health


def test_chat_attempt_budget_is_human_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARKA_LLM_ATTEMPT_MS", raising=False)
    assert health.attempt_timeout_s("chat") == pytest.approx(3.5)
    assert health.attempt_timeout_s("route") == pytest.approx(2.0)
    monkeypatch.setenv("ARKA_LLM_ATTEMPT_MS", "900")
    assert health.attempt_timeout_s("chat") == pytest.approx(0.9)


def test_ttft_is_tiered_by_model(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ARKA_LLM_ATTEMPT_MS",
        "ARKA_LLM_TTFT_FAST_MS",
        "ARKA_LLM_TTFT_STANDARD_MS",
        "ARKA_LLM_TTFT_REASONING_MS",
    ):
        monkeypatch.delenv(name, raising=False)
    assert health.ttft_tier("gemini-2.0-flash") == "fast"
    assert health.ttft_tier("claude-3.5-haiku") == "fast"
    assert health.ttft_tier("gpt-4o-mini") == "fast"
    assert health.ttft_tier("gemini-robotics-er-2-preview") == "standard"
    assert health.ttft_tier("gemini-2.5-pro") == "standard"
    assert health.ttft_tier("claude-3.5-sonnet") == "standard"
    assert health.ttft_tier("openai/o3") == "reasoning"
    assert health.ttft_tier("deepseek-r1") == "reasoning"
    assert health.first_token_timeout_s("chat", model_id="gemini-2.0-flash") == pytest.approx(4.0)
    assert health.first_token_timeout_s("chat", model_id="gemini-robotics-er-2-preview") == pytest.approx(9.0)
    assert health.first_token_timeout_s("chat", model_id="openai/o3") == pytest.approx(25.0)
    assert health.first_token_timeout_s("route", model_id="gemini-2.5-pro") == pytest.approx(2.0)
    assert health.first_token_timeout_s("route", model_id="openai/o1") == pytest.approx(8.0)


def test_ttft_grows_with_prefill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARKA_LLM_ATTEMPT_MS", raising=False)
    short = health.first_token_timeout_s("chat", model_id="gemini-2.5-pro", prompt_chars=8_000)
    long = health.first_token_timeout_s("chat", model_id="gemini-2.5-pro", prompt_chars=80_000)
    assert short == pytest.approx(9.0)
    assert long > short
    assert long == pytest.approx(10.333, abs=0.05)


def test_ttft_miss_does_not_rotate_keys() -> None:
    from arka.llm.api_keys import rotate_provider_key

    assert health.is_first_token_timeout("no first token in 9.0s")
    assert not rotate_provider_key("gemini", "no first token in 9.0s")


def test_call_with_timeout_fails_over() -> None:
    def hang() -> str:
        time.sleep(1.0)
        return "late"

    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="no first token"):
        health.call_with_timeout(hang, 0.15)
    assert (time.perf_counter() - started) < 0.8


def test_first_token_then_slow_finish_is_kept() -> None:
    class FakeEvent:
        def __init__(self, content: str) -> None:
            self.event = "RunContent"
            self.content = content

    class FakeAgent:
        def run(self, _user, stream=False):
            if not stream:
                time.sleep(2.0)
                return type("Run", (), {"content": "full answer"})()
            yield FakeEvent("Nirmala")
            time.sleep(0.25)
            yield FakeEvent("Nirmala Sitharaman")

    started = time.perf_counter()
    run = health.run_with_first_token_budget(FakeAgent(), "who", 0.4)
    elapsed = time.perf_counter() - started
    assert "Sitharaman" in (run.content or "")
    assert elapsed < 1.2


def test_no_first_token_fails_over() -> None:
    class SlowAgent:
        def run(self, _user, stream=False):
            time.sleep(1.0)
            if stream:
                return
            return type("Run", (), {"content": "late"})()

    with pytest.raises(TimeoutError, match="no first token"):
        health.run_with_first_token_budget(SlowAgent(), "who", 0.15)


def test_inspect_config_warns_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AI_PREFERRED_PROVIDER",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    warnings = health.inspect_config()
    assert any("only gemini" in item for item in warnings)


def test_is_retryable_includes_reaction_budget() -> None:
    from arka.llm.fallback import is_retryable_error

    assert is_retryable_error("gemini/flash no first token in 3.5s")
