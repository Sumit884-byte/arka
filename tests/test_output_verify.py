"""Tests for output quality verification and response timing."""

from __future__ import annotations

import json
import time
from unittest import mock

import pytest

from arka.core import output_verify as ov


@pytest.fixture(autouse=True)
def _clean_verify_env(monkeypatch):
    monkeypatch.delenv("ARKA_OUTPUT_VERIFY", raising=False)
    monkeypatch.delenv("ARKA_OUTPUT_VERIFY_BLOCK", raising=False)
    monkeypatch.delenv("ARKA_OUTPUT_VERIFY_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("ARKA_OUTPUT_SLOW_MS", raising=False)
    monkeypatch.delenv("ARKA_OUTPUT_SHOW_VERIFY", raising=False)
    ov.reset_output_metrics()


def test_output_verify_disabled_by_default():
    assert ov.output_verify_enabled() is False


def test_output_verify_enabled_via_env(monkeypatch):
    monkeypatch.setenv("ARKA_OUTPUT_VERIFY", "1")
    assert ov.output_verify_enabled() is True


def test_response_timer_tracks_total_and_ttfa():
    timer = ov.ResponseTimer()
    time.sleep(0.01)
    timer.mark_first_token()
    time.sleep(0.01)
    timing = timer.finish()
    assert timing.ttfa_ms is not None
    assert timing.total_ms is not None
    assert timing.total_ms >= timing.ttfa_ms
    assert ov.output_timing() is timing


def test_slow_flag_when_above_threshold(monkeypatch):
    monkeypatch.setenv("ARKA_OUTPUT_SLOW_MS", "1")
    timer = ov.ResponseTimer()
    time.sleep(0.005)
    timing = timer.finish()
    assert timing.slow is True


def test_evaluate_verdict_pass_fail():
    passed = ov.evaluate_verdict(
        {
            "accuracy": 5,
            "completeness": 4,
            "helpfulness": 5,
            "safety": 5,
            "summary": "Strong answer.",
            "passed": True,
        }
    )
    assert passed.overall == 4.75
    assert passed.passed is True

    failed = ov.evaluate_verdict(
        {
            "accuracy": 2,
            "completeness": 2,
            "helpfulness": 2,
            "safety": 4,
            "summary": "Weak answer.",
        }
    )
    assert failed.passed is False


def test_parse_judge_json_from_fenced_text():
    raw = 'Here is the result:\n{"accuracy":4,"completeness":4,"helpfulness":5,"safety":5,"summary":"Good","passed":true}'
    data = ov._parse_judge_json(raw)
    assert data is not None
    assert data["accuracy"] == 4


def test_verify_output_mock_judge(monkeypatch):
    payload = {
        "accuracy": 4,
        "completeness": 4,
        "helpfulness": 5,
        "safety": 5,
        "summary": "Clear and accurate.",
        "passed": True,
    }

    def _fake_llm(system, user, temperature=0.0, task=None, skill=None, chain=None):
        assert task == "judge"
        return json.dumps(payload)

    monkeypatch.setattr("arka.llm.fallback.llm_complete", _fake_llm)
    monkeypatch.setattr("arka.llm.fallback.llm_last_model", lambda: ("gemini", "gemini-2.5-flash"))

    verdict = ov.verify_output("What is Python?", "Python is a programming language.")
    assert verdict is not None
    assert verdict.passed is True
    assert verdict.judge_model == "gemini/gemini-2.5-flash"
    assert verdict.verify_ms is not None
    assert ov.quality_verdict() is verdict


def test_maybe_verify_output_non_blocking_timeout(monkeypatch):
    monkeypatch.setenv("ARKA_OUTPUT_VERIFY", "1")
    monkeypatch.setenv("ARKA_OUTPUT_VERIFY_TIMEOUT_MS", "10")

    def _slow_llm(*args, **kwargs):
        time.sleep(0.05)
        return json.dumps(
            {
                "accuracy": 5,
                "completeness": 5,
                "helpfulness": 5,
                "safety": 5,
                "summary": "ok",
                "passed": True,
            }
        )

    monkeypatch.setattr("arka.llm.fallback.llm_complete", _slow_llm)
    result = ov.maybe_verify_output("q", "a", blocking=False)
    assert result is None


def test_maybe_verify_output_blocking(monkeypatch):
    monkeypatch.setenv("ARKA_OUTPUT_VERIFY", "1")

    monkeypatch.setattr(
        "arka.llm.fallback.llm_complete",
        lambda *a, **k: json.dumps(
            {
                "accuracy": 5,
                "completeness": 5,
                "helpfulness": 5,
                "safety": 5,
                "summary": "ok",
                "passed": True,
            }
        ),
    )
    monkeypatch.setattr("arka.llm.fallback.llm_last_model", lambda: ("groq", "llama-3.3-70b-versatile"))

    result = ov.maybe_verify_output("q", "a", blocking=True)
    assert result is not None
    assert result.passed is True


def test_format_output_metrics_footer():
    timing = ov.OutputTiming(ttfa_ms=120.0, total_ms=840.0, slow=False)
    verdict = ov.QualityVerdict.from_scores(
        accuracy=4,
        completeness=4,
        helpfulness=5,
        safety=5,
        summary="Good",
        passed=True,
    )
    line = ov.format_output_metrics_footer(timing=timing, verdict=verdict)
    assert "TTFA 120ms" in line
    assert "total 840ms" not in line
    assert "quality 4.5/5 (pass)" in line


def test_print_block_shows_quality_footer(capsys, monkeypatch):
    from arka.output import print_block, set_answer_duration_ms

    monkeypatch.setenv("SHOW_MODEL", "0")
    ov.set_output_timing(ov.OutputTiming(total_ms=500.0))
    ov.set_quality_verdict(
        ov.QualityVerdict.from_scores(
            accuracy=5,
            completeness=5,
            helpfulness=5,
            safety=5,
            summary="Excellent",
            passed=True,
        )
    )
    set_answer_duration_ms(500.0)
    print_block("Answer", "[FROM MEMORY] Hello world.")
    out = capsys.readouterr().out
    assert "Quality:" in out
    assert "quality 5.0/5 (pass)" in out


def test_answer_question_records_timing(monkeypatch):
    from arka.agent.chat import answer_question

    monkeypatch.setattr(
        "arka.output.is_model_identity_question",
        lambda q: True,
    )
    monkeypatch.setattr(
        "arka.output.model_identity_answer",
        lambda: "[FROM MEMORY] I am Arka.",
    )

    prov, answer = answer_question("which model are you", use_session=False)
    assert prov == "memory"
    assert "Arka" in answer
    timing = ov.output_timing()
    assert timing is not None
    assert timing.total_ms is not None


def test_judge_task_profile_registered():
    from arka.llm.skill_profiles import TASK_PROFILES, known_task_profiles

    assert "judge" in known_task_profiles()
    assert "quality" in TASK_PROFILES["judge"]["description"].lower()
