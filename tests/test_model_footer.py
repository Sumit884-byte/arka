"""Tests for model footer and model identity routing."""

from __future__ import annotations

from arka.output import (
    format_model_footer,
    is_model_identity_question,
    model_identity_answer,
    set_answer_duration_ms,
)


def test_is_model_identity_question():
    assert is_model_identity_question("which model are you")
    assert is_model_identity_question("what model am I using")
    assert not is_model_identity_question("what is Python")


def test_format_model_footer_with_timing():
    set_answer_duration_ms(842.0)
    line = format_model_footer(model="gemini/gemini-3.6-flash")
    assert line == "gemini/gemini-3.6-flash · 842ms"


def test_format_model_footer_seconds():
    set_answer_duration_ms(2400.0)
    line = format_model_footer(model="groq/llama-3.3-70b-versatile")
    assert line == "groq/llama-3.3-70b-versatile · 2.40s"


def test_model_identity_answer_mentions_arka():
    body = model_identity_answer()
    assert "Arka" in body
    assert "[FROM MEMORY]" in body
