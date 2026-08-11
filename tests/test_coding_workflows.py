"""Tests for coding workflow executor."""

from __future__ import annotations

from arka.agent.coding_workflows import WORKFLOWS, build_workflow_goal, execute_workflow


def test_build_workflow_goal_lists_steps() -> None:
    goal = build_workflow_goal(WORKFLOWS["bugfix"], "fix login bug")
    assert "bugfix" in goal
    assert "repo_health" in goal
    assert "fix login bug" in goal


def test_execute_workflow_calls_goal(monkeypatch) -> None:
    captured: list[str] = []

    def fake_goal(goal: str, **kwargs: object) -> int:
        captured.append(goal)
        return 0

    monkeypatch.setattr("arka.agent.goal.run_goal", fake_goal)
    rc = execute_workflow(WORKFLOWS["feature"], "add endpoint")
    assert rc == 0
    assert captured and "feature" in captured[0]
