"""Tests for contextual answer framing."""

from __future__ import annotations

from arka.core.contextual_answer import (
    answer_instructions,
    compare_context_instructions,
    context_for,
    nudge_context_instructions,
    route_command,
    wants_contextual_framing,
)
from arka.routing.symbolic import route_contextual_answer


def test_wants_contextual_explain():
    assert wants_contextual_framing("what is a standing desk")
    assert wants_contextual_framing("should I buy a standing desk")


def test_skips_weather():
    assert not wants_contextual_framing("what is the weather in Kolkata")


def test_explicit_with_context():
    assert wants_contextual_framing("explain Kubernetes with context")


def test_answer_instructions_includes_sections():
    text = answer_instructions("what is rust programming language", force=True)
    assert "Context" in text
    assert "Related options" in text


def test_nudge_context_instructions():
    assert "You might also consider" in nudge_context_instructions()


def test_compare_context_instructions():
    assert "Background" in compare_context_instructions()


def test_context_for_auto():
    assert context_for("what is graphql")


def test_route_contextual_answer():
    hit = route_contextual_answer("explain postgres with context")
    assert hit is not None
    assert hit.startswith("contextual_answer ")


def test_route_command():
    assert route_command("tell me about redis with context") is not None
