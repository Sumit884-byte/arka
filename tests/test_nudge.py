"""Tests for Arka Nudge routing and mode detection."""

from __future__ import annotations

from unittest import mock

from arka.routing.nudge import (
    is_compare_mode,
    is_nudge_request,
    nudge_mode,
    nudge_system_prompt,
    route_command,
    strip_nudge_prefix,
)
from arka.routing.symbolic import route_nudge


def test_nudge_request_standing_desk():
    assert is_nudge_request("should I buy a standing desk")
    assert nudge_mode("should I buy a standing desk") == "nudge"


def test_compare_mode_already_exercise():
    q = "I already exercise — should I buy a standing desk"
    assert is_compare_mode(q)
    assert nudge_mode(q) == "compare"


def test_compare_mode_gym_or_desk():
    q = "standing desk or gym subscription which is better"
    assert is_compare_mode(q)
    assert nudge_mode(q) == "compare"


def test_explicit_arka_nudge():
    assert is_nudge_request("arka nudge should I get noise cancelling headphones")
    assert strip_nudge_prefix("arka nudge should I get noise cancelling headphones") == (
        "should I get noise cancelling headphones"
    )


def test_nudge_system_prompt_modes():
    assert "benefits" in nudge_system_prompt(mode="nudge").lower()
    assert "comparison" in nudge_system_prompt(mode="compare").lower() or "tradeoff" in nudge_system_prompt(mode="compare").lower()


def test_route_command():
    hit = route_command("should I buy a standing desk")
    assert hit is not None
    assert hit.startswith("nudge ")


def test_route_nudge_symbolic():
    hit = route_nudge("should I buy a standing desk")
    assert hit is not None
    assert "standing desk" in hit


def test_answer_nudge_mock():
    from arka.agent.nudge import answer_nudge

    with mock.patch("arka.llm.cli.llm_complete", return_value="Benefit one."):
        out = answer_nudge("should I buy a standing desk")
    assert "Benefit" in out


def test_skips_technical_should_i():
    assert not is_nudge_request("should I use docker or kubernetes for this api")
