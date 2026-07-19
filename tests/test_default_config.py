from __future__ import annotations

import json


def test_preview_is_non_mutating(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    from arka.core.default_config import main, path

    assert main(["configure", "--json"]) == 0
    assert not path().exists()


def test_apply_preserves_explicit_values(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTE_MODE", "ai")
    from arka.core.default_config import main, path

    assert main(["configure", "--apply"]) == 0
    data = json.loads(path().read_text())
    assert data["defaults"]["ROUTE_MODE"] == "ai"
    assert data["defaults"]["PROMPT_OPTIMIZE"] == "1"


def test_config_reset_only_removes_arka_config(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    from arka.core.default_config import main, path

    main(["configure", "--apply"])
    assert path().exists()
    assert main(["reset"]) == 0
    assert not path().exists()


def test_config_share_export_redacts_secrets(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=secret\nARKA_MODEL_MODE=offline\nAI_PREFERRED_MODEL=qwen3:8b\n")
    from arka.core.default_config import main

    assert main(["share", "export"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["kind"] == "arka-config-share"
    assert data["env"]["ARKA_MODEL_MODE"] == "offline"
    assert data["env"]["AI_PREFERRED_MODEL"] == "qwen3:8b"
    assert "OPENAI_API_KEY" not in data["env"]
    assert "OPENAI_API_KEY" in data["required_env"]


def test_config_share_import_preview_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"kind": "arka-config-share", "defaults": {"ROUTE_MODE": "symbolic"}, "env": {"ARKA_MODEL_MODE": "offline"}}))
    from arka.core.default_config import main, path

    assert main(["share", "import", str(bundle), "--json"]) == 0
    assert not path().exists()
    assert not (tmp_path / ".env").exists()


def test_config_share_import_apply_preserves_existing_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("AI_PREFERRED_MODEL", raising=False)
    (tmp_path / ".env").write_text("ARKA_MODEL_MODE=auto\n")
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"kind": "arka-config-share", "defaults": {"ROUTE_MODE": "symbolic"}, "env": {"ARKA_MODEL_MODE": "offline", "AI_PREFERRED_MODEL": "qwen3:8b"}}))
    from arka.core.default_config import main, path

    assert main(["share", "import", str(bundle), "--apply"]) == 0
    data = json.loads(path().read_text())
    assert data["defaults"]["ROUTE_MODE"] == "symbolic"
    env_text = (tmp_path / ".env").read_text()
    assert "ARKA_MODEL_MODE=auto" in env_text
    assert "AI_PREFERRED_MODEL=qwen3:8b" in env_text


def test_config_share_route():
    from arka.routing.symbolic import route_offline_extras

    assert route_offline_extras("share my arka config") == "config share export"
