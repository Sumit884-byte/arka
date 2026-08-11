"""Tests for skill requirement / API key messaging."""

from __future__ import annotations

import os
from unittest import mock

from arka.core.skill_requirements import (
    check_requires,
    format_gate_reason,
    hint_for_env,
    preflight_skill,
)


def test_check_requires_missing_env():
    with mock.patch.dict(os.environ, {}, clear=True):
        ok, msg = check_requires({"env": ["GROQ_API_KEY"]}, skill="test_skill")
    assert not ok
    assert "GROQ_API_KEY" in msg
    assert "Cannot run test_skill" in msg
    assert "console.groq.com" in msg


def test_check_requires_env_any():
    with mock.patch.dict(os.environ, {}, clear=True):
        ok, msg = check_requires({"env_any": ["GEMINI_API_KEY", "GROQ_API_KEY"]}, skill="llm_skill")
    assert not ok
    assert "at least one" in msg.lower()


def test_check_requires_bins():
    ok, msg = check_requires({"bins": ["definitely-not-a-real-binary-xyz"]}, skill="demo")
    assert not ok
    assert "definitely-not-a-real-binary-xyz" in msg


def test_format_gate_reason():
    msg = format_gate_reason("dub_video", "missing env: GROQ_API_KEY")
    assert "dub_video" in msg
    assert "GROQ_API_KEY" in msg


def test_preflight_dub_video_stt_check():
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
        "arka.core.skill_requirements.stt_backend_available", return_value=False
    ), mock.patch("arka.core.skill_requirements.tts_backend_available", return_value=True):
        ok, msg = preflight_skill("dub_video", extra={"checks": ["stt", "tts"]})
    assert not ok
    assert "speech-to-text" in msg.lower()


def test_hint_for_env_known():
    assert "aistudio.google.com" in hint_for_env("GEMINI_API_KEY")
