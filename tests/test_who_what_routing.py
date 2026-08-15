"""Routing and intent for basic who/what encyclopedic questions."""

from __future__ import annotations

from unittest import mock

from arka.agent import chat
from arka.router import route


def test_route_who_is_elon_to_web_answer() -> None:
    hit = route("who is elon")
    assert hit is not None
    assert hit.skill.startswith("web_answer ")


def test_route_what_is_python_prefers_contextual_answer() -> None:
    hit = route("what is python")
    assert hit is not None
    assert hit.skill.startswith("contextual_answer ")


def test_get_intent_who_is_elon_is_llm_only() -> None:
    action, data = chat.get_intent("who is elon")
    assert action == "ANSWER"
    assert data == "who is elon"


def test_get_intent_who_is_elon_musk_is_llm_only() -> None:
    action, _ = chat.get_intent("who is elon musk")
    assert action == "ANSWER"


def test_get_intent_what_is_python_is_llm_only() -> None:
    action, _ = chat.get_intent("what is python")
    assert action == "ANSWER"


def test_get_intent_current_events_still_search() -> None:
    assert chat.get_intent("who won election 2024")[0] == "SEARCH"
    assert chat.get_intent("latest news about elon")[0] == "SEARCH"
    assert chat.get_intent("who won IPL 2026")[0] == "SEARCH"


def test_get_intent_short_definitional_still_answers() -> None:
    with mock.patch("arka.agent.chat.llm_complete", return_value="ANSWER:"):
        action, _ = chat.get_intent("who elon")
    assert action == "ANSWER"
