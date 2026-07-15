from pathlib import Path

from arka.agent import ultra_fast
from arka.routing.symbolic import route_offline_extras


def test_priority_one_checks_each_iteration_and_zero_once(monkeypatch, tmp_path: Path):
    calls = []
    states = iter([set(), {"src/a.py"}, {"src/a.py"}, {"src/a.py"}])
    monkeypatch.setattr(ultra_fast, "changed_files", lambda root: next(states, {"src/a.py"}))
    monkeypatch.setattr(ultra_fast, "run_command", lambda command, root: calls.append(command) or 0)
    tasks = [ultra_fast.Task("fast", "build-fast", 1, ("src",), "test-fast"), ultra_fast.Task("slow", "build-slow", 0, ("src",), "test-slow")]
    result = ultra_fast.run(tasks, 2, root=tmp_path)
    assert calls.count("test-fast") == 1
    assert calls.count("test-slow") == 1
    assert result["priority_mode"] is True


def test_ultra_fast_route():
    assert route_offline_extras("ultra fast development with priority 1 testing") .startswith("ultra_fast ")
    assert "--auto-priority" in route_offline_extras("enable auto priority for ultra fast development")
    assert "--auto-priority" in route_offline_extras("multitask these prompts with automatic priority")


def test_auto_priority_promotes_all_tasks(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(ultra_fast, "changed_files", lambda root: {"src/a.py"})
    monkeypatch.setattr(ultra_fast, "run_command", lambda command, root: 0)
    result = ultra_fast.run([ultra_fast.Task("slow", "build", 0, ("src",), "test")], 1, root=tmp_path, auto_priority=True)
    assert result["auto_priority"] is True
