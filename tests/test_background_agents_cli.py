def test_background_agent_tasks_lists_running(monkeypatch, capsys):
    from arka import cli
    from arka.agent import background

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(background, "collect_status", lambda: {
        "active_count": 1,
        "subagents": {
            "summary": {"running": 1, "total": 2},
            "active": [{"id": "abc123", "status": "running", "task": "run tests"}],
        },
        "routines": {"enabled": [], "all": []},
        "servers": {"webhook": {}, "mcp": {"configured": [], "active_processes": []}, "processes": []},
    })
    assert cli.main(["background", "agent", "tasks"]) == 0
    out = capsys.readouterr().out
    assert "Arka background processes" in out
    assert "abc123" in out
    assert "done1" not in out


def test_background_agent_tasks_empty(monkeypatch, capsys):
    from arka import cli
    from arka.agent import background

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(background, "collect_status", lambda: {
        "active_count": 0,
        "subagents": {"summary": {"running": 0, "total": 0}, "active": []},
        "routines": {"enabled": [], "all": []},
        "servers": {"webhook": {}, "mcp": {"configured": [], "active_processes": []}, "processes": []},
    })
    assert cli.main(["background", "agent", "tasks"]) == 0
    assert "No active Arka background" in capsys.readouterr().out


def test_background_processes_collects_routines_and_servers(monkeypatch, tmp_path):
    from arka.agent import background

    monkeypatch.setattr("arka.integrations.subagent.list_agents", lambda limit=200: [
        {"id": "abc123", "status": "running", "task": "run tests"},
        {"id": "done1", "status": "done", "task": "old task"},
    ])
    monkeypatch.setattr("arka.integrations.subagent.status_summary", lambda: {"running": 1, "total": 2})
    monkeypatch.setattr("arka.integrations.routines.list_routines", lambda enabled_only=False: [
        {"id": "daily", "schedule": "daily 9am", "action": "repo health", "enabled": True},
        {"id": "off", "schedule": "hourly", "action": "disabled", "enabled": False},
    ])
    monkeypatch.setattr(
        "arka.integrations.webhook.status_info",
        lambda: {"enabled": True, "pid": 123, "inbox_url": "http://127.0.0.1:8787/inbox"},
    )
    monkeypatch.setattr("arka.integrations.mcp_manager.list_server_names", lambda: ["threejs"])
    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: tmp_path / "mcp.json")
    monkeypatch.setattr(background, "_pid_alive", lambda pid: str(pid) == "123")
    monkeypatch.setattr(background, "_arka_processes", lambda: [
        {"pid": 456, "kind": "server", "command": "arka mcp serve"},
    ])

    data = background.collect_status()
    rendered = background.format_status(data)

    assert data["subagents"]["active"][0]["id"] == "abc123"
    assert data["routines"]["enabled"][0]["id"] == "daily"
    assert data["servers"]["mcp"]["configured"] == ["threejs"]
    assert "arka mcp serve" in rendered
    assert "done1" not in rendered


def test_background_processes_route_phrase():
    from arka.agent.background import route_command
    from arka.routing.symbolic import route_offline_extras

    phrase = "arka tell your background process should show me all subagent routines server currently active due to arka"
    assert route_command(phrase) == "background processes"
    assert route_offline_extras(phrase) == "background processes"
