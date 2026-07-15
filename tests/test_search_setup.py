from arka.agent import search_setup


def test_search_setup_writes_provider_key(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr(search_setup, "env_file", lambda: target)
    assert search_setup.main(["setup", "serper", "--key", "demo"]) == 0
    assert target.read_text() == "SERPER_API_KEY=demo\n"


def test_search_setup_status_lists_providers(monkeypatch, capsys):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert search_setup.main(["status"]) == 0
    assert "serper\tmissing" in capsys.readouterr().out
