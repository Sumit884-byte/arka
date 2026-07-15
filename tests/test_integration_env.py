from pathlib import Path

from arka.agent.search_setup import load_saved_env


def test_load_saved_env_handles_export_and_quotes(tmp_path: Path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("export DEMO_TOKEN='quoted-value'\n")
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    load_saved_env(target)
    assert __import__("os").environ["DEMO_TOKEN"] == "quoted-value"
