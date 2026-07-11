"""Tests for Arka agent teams and workflows."""

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
    "defaults": {"memory": "unified", "workflow": "review-and-ship"},
}

REVIEW_WORKFLOW = {
    "name": "review-and-ship",
    "team": "research",
    "steps": [
        {"member": "lead", "action": "plan", "prompt": "Plan: {task}"},
        {
            "parallel": [
                {"member": "analyst", "action": "analyze", "prompt": "Analyze: {step_1}"},
                {"member": "local-fallback", "action": "verify", "prompt": "Verify: {step_1}"},
            ]
        },
        {"member": "lead", "action": "synthesize", "prompt": "Merge: {results}"},
    ],
}


def test_parse_team_schema():
    from arka.teams.schema import parse_team

    team = parse_team(RESEARCH_TEAM)
    assert team.name == "research"
    assert len(team.members) == 3
    assert team.members[0].kind == "agent"
    assert team.members[1].provider == "gemini"


def test_parse_team_duplicate_roles():
    from arka.teams.schema import parse_team

    bad = dict(RESEARCH_TEAM)
    bad["members"] = [
        {"kind": "agent", "id": "claude", "role": "lead"},
        {"kind": "agent", "id": "codex", "role": "lead"},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        parse_team(bad)


def test_parse_workflow_parallel():
    from arka.teams.schema import parse_workflow

    wf = parse_workflow(REVIEW_WORKFLOW)
    assert wf.team == "research"
    assert len(wf.steps) == 3
    assert wf.steps[1].parallel is not None
    assert len(wf.steps[1].parallel) == 2


def test_resolve_team_members():
    from arka.teams.resolve import resolve_team
    from arka.teams.schema import parse_team

    team = parse_team(RESEARCH_TEAM)
    resolved = resolve_team(team)
    assert resolved["lead"].kind == "agent"
    assert resolved["lead"].agent_key == "claude"
    assert resolved["analyst"].kind == "llm"
    assert resolved["analyst"].provider == "gemini"
    assert resolved["local-fallback"].provider == "ollama"


def test_ensure_layout_seeds_templates(team_paths):
    from arka.teams.io import ensure_layout, list_teams, list_workflows

    ensure_layout()
    assert "research" in list_teams()
    assert "review-and-ship" in list_workflows()


def test_workflow_step_ordering(team_paths):
    from arka.teams.executor import StepResult, execute_workflow
    from arka.teams.schema import parse_team, parse_workflow

    calls: list[str] = []

    def fake_runner(member, prompt, system):
        label = f"{member.role}:{member.member_id}"
        calls.append(label)
        return StepResult(
            role=member.role,
            action="test",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=f"out-{member.role}",
            ok=True,
        )

    team = parse_team(RESEARCH_TEAM)
    wf = parse_workflow(REVIEW_WORKFLOW)
    result = execute_workflow(
        wf,
        "demo task",
        team=team,
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert calls[0] == "lead:claude"
    assert "analyst:gemini-2.0-flash" in calls
    assert "local-fallback:ollama" in calls
    assert calls[-1] == "lead:claude"
    assert len(result["steps"]) == 4
    assert "out-lead" in result["final"]


def test_parallel_merge(team_paths):
    from arka.teams.executor import RunContext, StepResult, _execute_step
    from arka.teams.resolve import resolve_team
    from arka.teams.schema import parse_team, parse_workflow

    team = parse_team(RESEARCH_TEAM)
    members = resolve_team(team)
    ctx = RunContext(task="hello", team=team, members=members)

    def fake_runner(member, prompt, system):
        return StepResult(
            role=member.role,
            action="x",
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=f"{member.role}-done",
            ok=True,
        )

    wf = parse_workflow(REVIEW_WORKFLOW)
    parallel_step = wf.steps[1]
    results = _execute_step(ctx, parallel_step, workflow=wf, runner=fake_runner)
    outputs = {r.role: r.output for r in results}
    assert outputs["analyst"] == "analyst-done"
    assert outputs["local-fallback"] == "local-fallback-done"


def test_template_rendering():
    from arka.teams.executor import RunContext, StepResult
    from arka.teams.resolve import resolve_team
    from arka.teams.schema import parse_team

    team = parse_team(RESEARCH_TEAM)
    members = resolve_team(team)
    ctx = RunContext(task="build auth", team=team, members=members)
    ctx.results.append(
        StepResult(
            role="lead",
            action="plan",
            member_kind="agent",
            member_id="claude",
            output="step one plan",
            ok=True,
        )
    )
    rendered = ctx.render("Task={task} Last={last_result} All={results}")
    assert "build auth" in rendered
    assert "step one plan" in rendered


@patch("arka.teams.executor._run_agent")
@patch("arka.teams.executor._run_llm")
def test_run_team_default_workflow(mock_llm, mock_agent, team_paths):
    from arka.teams.executor import StepResult, run_team
    from arka.teams.io import ensure_layout

    ensure_layout()

    mock_agent.return_value = StepResult(
        role="lead",
        action="plan",
        member_kind="agent",
        member_id="claude",
        output="planned",
        ok=True,
    )
    mock_llm.return_value = StepResult(
        role="analyst",
        action="analyze",
        member_kind="model",
        member_id="gemini-2.0-flash",
        output="analyzed",
        ok=True,
    )

    result = run_team("research", "test task")
    assert result["team"] == "research"
    assert result["workflow"] == "review-and-ship"
    assert mock_agent.called


def test_cli_list(team_paths):
    from arka.integrations.teams_cli import main

    from arka.teams.io import ensure_layout

    ensure_layout()
    assert main(["team", "list"]) == 0


def test_cli_create_team(team_paths):
    from arka.integrations.teams_cli import main

    from arka.teams.io import load_team

    code = main(["team", "create", "my-team", "--template", "research"])
    assert code == 0
    team = load_team("my-team")
    assert team.name == "my-team"
    assert team.members[0].role == "lead"
