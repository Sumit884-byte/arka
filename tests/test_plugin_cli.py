def test_plugin_commands_dispatch_without_ai(monkeypatch):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    calls = []
    monkeypatch.setattr("arka.agent.skills.main", lambda argv=None: calls.append(argv) or 0)
    assert cli.main(["plugin", "doctor"]) == 0
    assert cli.main(["plugins", "refresh"]) == 0
    assert calls == [["doctor"], ["refresh"]]
