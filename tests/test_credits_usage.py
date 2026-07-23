"""Tests for arka credits usage reporting."""

from __future__ import annotations

import io
import time
from unittest import mock

import pytest

from arka.llm.credits_usage import (
    fallback_chain_summary,
    is_credits_usage_request,
    offline_model_candidates,
    route_command,
    run_report,
    session_exhausted_lines,
)
from arka.routing.symbolic import route_credits_usage


@pytest.mark.parametrize(
    "cmd",
    [
        "credits usage",
        "credit usage",
        "ai credits usage",
        "show my arka credits",
        "llm credits usage",
        "check my ai credits usage",
    ],
)
def test_is_credits_usage_request(cmd: str) -> None:
    assert is_credits_usage_request(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "free credits",
        "how to get free ai credits",
        "usage dashboard",
        "free shipping on shoes",
    ],
)
def test_is_not_credits_usage_request(cmd: str) -> None:
    assert not is_credits_usage_request(cmd)


def test_route_command() -> None:
    assert route_command("ai credits usage") == "credits usage"
    assert route_command("how to get free ai credits") is None


def test_route_symbolic() -> None:
    assert route_credits_usage("show my arka credits") == "credits usage"


def _patch_fast_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arka.llm.credits_usage._provider_configured_offline",
        lambda slug: slug == "gemini",
    )
    monkeypatch.setattr(
        "arka.llm.credits_usage.collect_provider_keys",
        lambda slug: ["key"] if slug == "gemini" else [],
    )
    monkeypatch.setattr(
        "arka.llm.credits_usage.llm_settings_lines",
        lambda **_: ["  LLM providers:  gemini", "  Auto failover:  1"],
    )


def test_run_report_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fast_report(monkeypatch)

    buf = io.StringIO()
    code = run_report(stream=buf)
    text = buf.getvalue()
    assert code == 0
    assert "Arka credits usage" in text
    assert "Configured providers" in text
    assert "Session-exhausted models" in text
    assert "Fallback chain" not in text
    assert "arka credits usage --live" in text
    assert "arka doctor" in text
    assert "reset" in text


def test_run_report_live_includes_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fast_report(monkeypatch)
    monkeypatch.setattr(
        "arka.llm.credits_usage.ordered_model_candidates",
        lambda **_: [("gemini", "gemini-2.0-flash")],
    )
    monkeypatch.setattr("arka.llm.credits_usage.provider_available", lambda slug: slug == "gemini")
    monkeypatch.setattr("arka.llm.credits_usage.openrouter_balance_line", lambda **_: None)

    buf = io.StringIO()
    run_report(stream=buf, include_chain=True, live=True)
    text = buf.getvalue()
    assert "Fallback chain" in text
    assert "gemini-2.0-flash" in text


def test_run_report_chain_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arka.llm.credits_usage._provider_configured_offline",
        lambda slug: slug == "gemini",
    )
    monkeypatch.setattr(
        "arka.llm.credits_usage.offline_model_candidates",
        lambda: [("gemini", "gemini-2.0-flash")],
    )
    monkeypatch.setattr("arka.llm.credits_usage.llm_settings_lines", lambda **_: [])

    buf = io.StringIO()
    run_report(stream=buf, include_chain=True, live=False)
    text = buf.getvalue()
    assert "Fallback chain (offline)" in text
    assert "gemini-2.0-flash" in text


def test_session_exhausted_lines() -> None:
    store = mock.Mock(list_exhausted=lambda: [("gemini", "gemini-2.0-flash"), ("groq", "llama-3.3-70b-versatile")])
    with mock.patch("arka.llm.credits_usage.EXHAUSTION", store):
        lines = session_exhausted_lines()
    assert any("gemini/gemini-2.0-flash" in line for line in lines)
    assert any("groq/llama-3.3-70b-versatile" in line for line in lines)


def test_fallback_chain_summary_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arka.llm.credits_usage._provider_configured_offline",
        lambda provider: provider == "gemini",
    )
    monkeypatch.setattr(
        "arka.llm.credits_usage.offline_model_candidates",
        lambda: [
            ("gemini", "gemini-2.0-flash"),
            ("groq", "llama-3.3-70b-versatile"),
        ],
    )
    monkeypatch.setattr("arka.llm.credits_usage.EXHAUSTION", mock.Mock(exhausted=lambda p, m: False))

    _, counts = fallback_chain_summary(live=False)
    assert counts["ready"] == 1
    assert counts["exhausted"] == 0
    assert counts["skip"] == 1


def test_offline_model_candidates_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "gemini")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "gemini-2.0-flash")
    monkeypatch.setattr("arka.llm.credits_usage._provider_configured_offline", lambda slug: slug == "gemini")

    candidates = offline_model_candidates()
    assert ("gemini", "gemini-2.0-flash") in candidates


def test_credits_usage_completes_quickly(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fast_report(monkeypatch)

    def _slow_network(*args, **kwargs):
        raise AssertionError("default credits usage must not perform network I/O")

    monkeypatch.setattr("arka.llm.credits_usage.fetch_openrouter_balance", _slow_network)
    monkeypatch.setattr("arka.llm.credits_usage.ordered_model_candidates", _slow_network)

    start = time.perf_counter()
    buf = io.StringIO()
    assert run_report(stream=buf) == 0
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"run_report took {elapsed:.2f}s"
    assert "Arka credits usage" in buf.getvalue()


def test_cli_credits_usage_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr("arka.llm.credits_usage._provider_configured_offline", lambda slug: False)
    monkeypatch.setattr("arka.llm.credits_usage.llm_settings_lines", lambda **_: ["  Auto failover:  1"])

    assert cli.main(["credits", "usage"]) == 0
    assert "Arka credits usage" in capsys.readouterr().out


def test_cli_credits_usage_balance_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr("arka.llm.credits_usage._provider_configured_offline", lambda slug: slug == "openrouter")
    monkeypatch.setattr(
        "arka.llm.credits_usage.fetch_openrouter_balance",
        lambda **_: {"usage": 1.25, "limit": 10.0, "is_free_tier": False},
    )
    monkeypatch.setattr("arka.llm.credits_usage.llm_settings_lines", lambda **_: [])

    assert cli.main(["credits", "usage", "--balance"]) == 0
    out = capsys.readouterr().out
    assert "OpenRouter balance" in out
    assert "usage $1.2500" in out


def test_cli_skill_usage_alias(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    from arka import cli
    from arka.core import skill_usage

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(skill_usage, "_path", lambda: tmp_path / "usage.json")
    skill_usage.record("web_answer", 0, 1.0)

    assert cli.main(["skill", "usage"]) == 0
    out = capsys.readouterr().out
    assert "Arka skill usage" in out
    assert "web_answer" in out
