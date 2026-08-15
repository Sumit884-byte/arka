"""Tests for prompt_coach skill — routing and coaching helpers."""

from __future__ import annotations

from unittest import mock

import pytest

from arka.routing.prompt_coach import (
    extract_focus,
    is_prompt_coach_request,
    nl_to_argv,
    route_command,
)
from arka.routing.symbolic import route_prompt_coach


@pytest.mark.parametrize(
    "phrase",
    [
        "help me write better prompts",
        "prompt coaching",
        "how to write a good prompt",
        "teach me prompt engineering",
        "prompt writing help",
        "write a better prompt for summarizing PDFs",
        "coach this prompt: summarize the doc and list action items",
    ],
)
def test_is_prompt_coach_request(phrase: str) -> None:
    assert is_prompt_coach_request(phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "optimize this prompt: summarize the doc",
        "rewrite this prompt: explain the bug",
        "improve this prompt: fix my code",
    ],
)
def test_prompt_coach_not_rewrite_paths(phrase: str) -> None:
    assert not is_prompt_coach_request(phrase)


def test_route_prompt_coach() -> None:
    hit = route_prompt_coach("help me write better prompts")
    assert hit is not None
    assert hit.startswith("prompt_coach ")


def test_route_command_exact() -> None:
    assert route_command("help me write better prompts") == "prompt_coach 'help me write better prompts'"


def test_nl_to_argv_general() -> None:
    assert nl_to_argv("help me write better prompts") == ["coach"]


def test_nl_to_argv_with_focus() -> None:
    argv = nl_to_argv("write a better prompt for code review comments")
    assert argv == ["coach", "code review comments"]


def test_extract_focus_draft() -> None:
    focus = extract_focus("coach this prompt: summarize quarterly reports")
    assert focus == "summarize quarterly reports"


def test_route_preview_and_offline() -> None:
    from arka.router import route, route_preview

    phrase = "help me write better prompts"
    preview = route_preview(phrase)
    assert preview is not None
    assert preview.skill.startswith("prompt_coach ")

    with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
        routed = route(phrase)
    assert routed is not None
    assert routed.skill.startswith("prompt_coach ")


def test_coach_prompts_mock_llm() -> None:
    from arka.agent.prompt_coach import coach_prompts

    with mock.patch("arka.llm.cli.llm_complete", return_value="Use role, task, constraints."):
        answer = coach_prompts("help me write better prompts")
    assert "role" in answer.lower()
