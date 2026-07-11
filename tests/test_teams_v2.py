"""Tests for Agent Teams v2 — round-robin, retries, and per-step MCP."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def team_paths(tmp_path, monkeypatch):
    teams = tmp_path / "teams"
    workflows = tmp_path / "workflows"
    monkeypatch.setenv("ARKA_TEAMS_DIR", str(teams))
    monkeypatch.setenv("ARKA_WORKFLOWS_DIR", str(workflows))
    monkeypatch.setattr("arka.paths.config_dir", lambda: tmp_path)
    return {"teams": teams, "workflows": workflows, "root": tmp_path}


def _write_yaml(path: Path, data: dict) -> None:
    try:
        import yaml

        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except ImportError:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


RESEARCH_TEAM = {
    "name": "research",
    "description": "Test research team",
    "members": [
        {"kind": "agent", "id": "claude", "role": "lead"},
        {"kind": "model", "id": "gemini-2.0-flash", "provider": "gemini", "role": "analyst"},
        {"kind": "provider", "id": "ollama", "role": "local-fallback"},
    ],
    "defaults": {"memory": "off", "mcp": False, "retries": 0},
}

BRAINSTORM_WORKFLOW = {
    "name": "brainstorm",
    "team": "research",
    "mode": "round_robin",
    "max_turns": 4,
    "prompt": "Brainstorm: {task} | prev={last_result}",
    "members": ["lead", "analyst", "local-fallback"],
    "defaults": {"retries": 1, "mcp": False},
}

RETRY_WORKFLOW = {
    "name": "retry-demo",
    "team": "research",
    "defaults": {"retries": 2, "retry_delay": 0},
    "steps": [
        {
            "member": "lead",
            "action": "attempt",
            "prompt": "Do: {task}",
            "retries": 2,
            "retry_delay": 0,
        }
    ],
}


def test_parse_round_robin_workflow():
    from arka.teams.schema import parse_workflow

    wf = parse_workflow(BRAINSTORM_WORKFLOW)
    assert wf.mode == "round_robin"
    assert wf.max_turns == 4
    assert wf.members == ["lead", "analyst", "local-fallback"]
    assert wf.steps == []


def test_parse_step_retry_and_mcp_fields():
    from arka.teams.schema import parse_workflow

    data = {
        "name": "mcp-step",
        "team": "research",
        "steps": [
            {
                "member": "analyst",
                "action": "fetch",
                "prompt": "Use tools",
                "retries": 3,
                "retry_delay": 2,
                "mcp": True,
                "mcp_servers": ["github", "notion"],
            }
        ],
    }
    wf = parse_workflow(data)
    step = wf.steps[0]
    assert step.retries == 3
    assert step.retry_delay == 2
    assert step.mcp is True
    assert step.mcp_servers == ["github", "notion"]


def test_round_robin_rotates_members(team_paths):
    from arka.teams.executor import StepResult, execute_workflow
    from arka.teams.schema import parse_team, parse_workflow

    calls: list[str] = []

    def fake_runner(member, prompt, system):
        calls.append(member.role)
        return StepResult(
            role=member.role,
            action="turn",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=f"idea-{member.role}",
            ok=True,
        )

    team = parse_team(RESEARCH_TEAM)
    wf = parse_workflow(BRAINSTORM_WORKFLOW)
    result = execute_workflow(wf, "edge caching", team=team, runner=fake_runner)

    assert result["mode"] == "round_robin"
    assert result["ok"] is True
    assert calls == ["lead", "analyst", "local-fallback", "lead"]
    assert len(result["steps"]) == 4


def test_round_robin_transcript_vars(team_paths):
    from arka.teams.executor import RunContext, StepResult, _execute_round_robin
    from arka.teams.resolve import resolve_team
    from arka.teams.schema import parse_team, parse_workflow

    team = parse_team(RESEARCH_TEAM)
    wf = parse_workflow(BRAINSTORM_WORKFLOW)
    members = resolve_team(team)
    ctx = RunContext(task="auth v2", team=team, workflow=wf, members=members)

    prompts: list[str] = []

    def fake_runner(member, prompt, system):
        prompts.append(prompt)
        return StepResult(
            role=member.role,
            action="turn",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=f"out-{len(prompts)}",
            ok=True,
        )

    _execute_round_robin(ctx, wf, runner=fake_runner)
    assert "auth v2" in prompts[0]
    assert "out-1" in prompts[1]


def test_retries_on_failure(team_paths, monkeypatch):
    from arka.teams.executor import StepResult, execute_workflow
    from arka.teams.schema import parse_team, parse_workflow

    monkeypatch.setenv("TEAM_RETRY_BACKOFF", "0")
    attempts = {"count": 0}

    def fake_runner(member, prompt, system):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return StepResult(
                role=member.role,
                action="attempt",
                member_kind=member.member_kind,
                member_id=member.member_id,
                output="",
                ok=False,
                error="transient",
            )
        return StepResult(
            role=member.role,
            action="attempt",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output="success",
            ok=True,
        )

    team = parse_team(RESEARCH_TEAM)
    wf = parse_workflow(RETRY_WORKFLOW)
    result = execute_workflow(wf, "retry me", team=team, runner=fake_runner)

    assert result["ok"] is True
    assert attempts["count"] == 3
    step = result["steps"][0]
    assert step["retries"] == 2
    assert step["attempts"] == 3


def test_retry_exhaustion_marks_failure(team_paths):
    from arka.teams.executor import StepResult, execute_workflow
    from arka.teams.schema import parse_team, parse_workflow

    def fake_runner(member, prompt, system):
        return StepResult(
            role=member.role,
            action="attempt",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output="",
            ok=False,
            error="always fails",
        )

    team = parse_team(RESEARCH_TEAM)
    wf = parse_workflow(RETRY_WORKFLOW)
    result = execute_workflow(wf, "fail", team=team, runner=fake_runner)

    assert result["ok"] is False
    assert result["steps"][0]["retries"] == 2
    assert result["steps"][0]["attempts"] == 3


@patch("arka.teams.executor.build_mcp_context")
@patch("arka.teams.executor.resolve_step_mcp")
def test_mcp_injected_into_system(mock_resolve, mock_build, team_paths):
    from arka.teams.executor import RunContext, StepResult, execute_member
    from arka.teams.resolve import resolve_team
    from arka.teams.schema import parse_team, parse_workflow, WorkflowStep

    mock_resolve.return_value = (True, ["github"])
    mock_build.return_value = "MCP: github tools listed"

    team = parse_team({**RESEARCH_TEAM, "defaults": {"memory": "off", "mcp": True}})
    wf = parse_workflow(
        {
            "name": "one",
            "team": "research",
            "steps": [{"member": "analyst", "action": "scan", "prompt": "Go"}],
        }
    )
    members = resolve_team(team)
    ctx = RunContext(task="issue 42", team=team, workflow=wf, members=members)
    step = wf.steps[0]

    systems: list[str] = []

    def fake_runner(member, prompt, system):
        systems.append(system)
        return StepResult(
            role=member.role,
            action="scan",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output="done",
            ok=True,
        )

    execute_member(ctx, "analyst", "scan", "Go", step=step, runner=fake_runner)
    assert "MCP: github tools listed" in systems[0]


def test_ensure_layout_seeds_brainstorm(team_paths):
    from arka.teams.io import ensure_layout, list_workflows

    ensure_layout()
    assert "brainstorm" in list_workflows()


def test_v1_workflow_still_parses():
    from arka.teams.schema import parse_workflow

    wf = parse_workflow(
        {
            "name": "review-and-ship",
            "team": "research",
            "steps": [{"member": "lead", "action": "plan", "prompt": "{task}"}],
        }
    )
    assert wf.mode == "sequential"
    assert len(wf.steps) == 1
