def test_background_agent_tasks_lists_running(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(
        "arka.integrations.subagent.list_agents",
        lambda limit=200: [
            {"id": "abc123", "status": "running", "task": "run tests"},
            {"id": "done1", "status": "done", "task": "old task"},
        ],
    )
    assert cli.main(["background", "agent", "tasks"]) == 0
    out = capsys.readouterr().out
    assert "abc123" in out
    assert "done1" not in out


def test_background_agent_tasks_empty(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr("arka.integrations.subagent.list_agents", lambda limit=200: [])
    assert cli.main(["background", "agent", "tasks"]) == 0
    assert "No running" in capsys.readouterr().out
