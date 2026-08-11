"""Tests for symbolic parallel decomposition."""

from __future__ import annotations

import json
from unittest.mock import patch

from arka.agent.parallel import main as parallel_main
from arka.agent.parallel_plan import (
    decompose_parallel,
    format_plan,
    run_parallel_subagents,
)
from arka.routing.symbolic import route_offline_extras, route_parallel_plan


def test_single_task_no_split():
    plan = decompose_parallel("fix the login bug")
    assert len(plan.tasks) == 1
    assert plan.mode == "sequential"
    assert plan.tasks[0].rule == "single_task"


def test_frontend_backend_domain_pair():
    plan = decompose_parallel("update frontend and backend auth")
    assert len(plan.tasks) == 2
    assert plan.mode == "parallel"
    assert plan.tasks[0].rule == "domain_pair:frontend/backend"
    assert "frontend" in plan.tasks[0].goal.lower()
    assert "backend" in plan.tasks[1].goal.lower()


def test_and_targets_split():
    plan = decompose_parallel("fix tests in module_a and module_b")
    assert len(plan.tasks) == 2
    assert plan.tasks[0].rule == "and_targets"
    assert "module_a" in plan.tasks[0].goal
    assert "module_b" in plan.tasks[1].goal


def test_file_path_disjoint():
    plan = decompose_parallel("fix tests/foo.py and tests/bar.py")
    assert len(plan.tasks) == 2
    assert plan.tasks[0].rule == "file_path_disjoint"
    assert "foo.py" in plan.tasks[0].goal
    assert "bar.py" in plan.tasks[1].goal


def test_comma_clauses():
    plan = decompose_parallel("lint src/app.py, update docs/readme.md")
    assert len(plan.tasks) == 2
    assert plan.tasks[0].rule == "comma_clauses"


def test_explicit_parallel_marker():
    plan = decompose_parallel("fix frontend and backend in parallel")
    assert len(plan.tasks) == 2
    assert any("explicit_parallel" in task.rule for task in plan.tasks)


def test_sequential_then_marker():
    plan = decompose_parallel("fix frontend then deploy backend")
    assert len(plan.tasks) == 2
    assert plan.mode in {"mixed", "sequential"}
    assert plan.tasks[1].depends_on == ("t1",)
    assert any("sequential_marker" in line for line in plan.reasoning)


def test_quoted_jobs():
    plan = decompose_parallel('run "ci" and "route audit" in parallel')
    assert len(plan.tasks) == 2
    assert plan.tasks[0].goal == "ci"
    assert plan.tasks[1].goal == "route audit"


def test_reasoning_trace_present():
    plan = decompose_parallel("update frontend and backend")
    text = format_plan(plan)
    assert "Reasoning:" in text
    assert "rule=" in text


def test_route_parallel_plan_nl():
    assert route_parallel_plan("parallel plan fix frontend and backend") == (
        "parallel plan fix frontend and backend"
    )
    assert route_offline_extras("decompose into parallel subagents fix A and B") == (
        "parallel plan fix A and B"
    )


def test_parallel_cli_plan(capsys):
    assert parallel_main(["plan", "update frontend and backend"]) == 0
    out = capsys.readouterr().out
    assert "frontend" in out.lower()
    assert "backend" in out.lower()


def test_run_parallel_subagents_spawns(tmp_path, monkeypatch):
    from arka.agent import parallel_plan
    from arka.integrations import subagent

    monkeypatch.setattr(parallel_plan, "RUNS_FILE", tmp_path / "parallel-runs.json")
    monkeypatch.setattr(subagent, "subagents_root", lambda: tmp_path / "subagents")

    plan = decompose_parallel("fix tests/a.py and tests/b.py")
    with patch("arka.integrations.subagent._run_agent", return_value=("done", 0)):
        record = run_parallel_subagents(plan, sync=True, plan_id="demo123")
    assert record["plan_id"] == "demo123"
    assert len(record["agents"]) == 2
    assert all(row.get("status") == "done" for row in record["agents"])


def test_handle_arka_parallel_plan_and_run(tmp_path, monkeypatch):
    from arka.agent import parallel_plan
    from arka.integrations import subagent
    from arka.integrations.mcp_server import _handle_arka_parallel

    monkeypatch.setattr(parallel_plan, "RUNS_FILE", tmp_path / "parallel-runs.json")
    monkeypatch.setattr(subagent, "subagents_root", lambda: tmp_path / "subagents")

    payload = json.loads(
        _handle_arka_parallel({"action": "plan", "goal": "update frontend and backend"})
    )
    assert payload["mode"] == "parallel"
    assert len(payload["tasks"]) == 2
    assert payload["reasoning"]

    with patch("arka.integrations.subagent._run_agent", return_value=("ok", 0)):
        run_payload = json.loads(
            _handle_arka_parallel(
                {"action": "run", "goal": "fix tests/a.py and tests/b.py", "sync": True}
            )
        )
    assert run_payload["plan_id"]
    assert len(run_payload["agents"]) == 2

    status_payload = json.loads(
        _handle_arka_parallel({"action": "status", "plan_id": run_payload["plan_id"]})
    )
    assert status_payload["plan_id"] == run_payload["plan_id"]
