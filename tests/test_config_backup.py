"""Tests for Arka config backup and unified config root."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def cfg_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CACHE_DIR", str(cache))
    monkeypatch.setenv("ARKA_HUB_DIR", str(cfg / "hub"))
    return {"config": cfg, "cache": cache}


def test_config_dir_respects_arka_config_dir(tmp_path, monkeypatch):
    custom = tmp_path / "my-arka"
    custom.mkdir()
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(custom))

    from importlib import reload

    import arka.paths as paths

    reload(paths)
    assert paths.config_dir() == custom.resolve()


def test_iter_config_entries(cfg_env):
    from arka.core.config_backup import iter_config_entries

    cfg_env["config"].joinpath(".env").write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
    cfg_env["config"].joinpath("mcp.json").write_text("{}", encoding="utf-8")

    rows = {r["label"]: r for r in iter_config_entries()}
    assert rows["env"]["exists"] is True
    assert rows["mcp"]["exists"] is True
    assert rows["hub"]["path"].endswith("hub")


def test_backup_and_restore_roundtrip(cfg_env):
    from arka.core.config_backup import create_backup, restore_backup

    cfg = cfg_env["config"]
    cfg.joinpath(".env").write_text("ROUTE_MODE=symbolic\n", encoding="utf-8")
    cfg.joinpath("personalize.json").write_text('{"interests": []}\n', encoding="utf-8")
    cfg_env["cache"].joinpath("memory.json").write_text("[]\n", encoding="utf-8")

    archive = cfg / "backup-test.tar.gz"
    result = create_backup(archive)
    assert result["ok"] is True
    assert archive.is_file()

    cfg.joinpath(".env").unlink()
    cfg.joinpath("personalize.json").unlink()

    restored = restore_backup(archive, force=True)
    assert restored["ok"] is True
    assert cfg.joinpath(".env").is_file()
    assert "symbolic" in cfg.joinpath(".env").read_text(encoding="utf-8")
    assert cfg.joinpath("personalize.json").is_file()


def test_backup_manifest_and_archive_layout(cfg_env):
    from arka.core.config_backup import MANIFEST_NAME, create_backup

    cfg = cfg_env["config"]
    cfg.joinpath("mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    archive = create_backup(cfg / "snap.tar.gz")["archive"]

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert MANIFEST_NAME in names
        assert any(n.startswith("config/mcp.json") for n in names)

        manifest = json.loads(tar.extractfile(MANIFEST_NAME).read().decode("utf-8"))
        assert manifest["version"] == 1
        assert manifest["files"]["config"] >= 1


def test_init_config_creates_layout(cfg_env, tmp_path):
    from arka.core.config_backup import export_snippet, init_config

    target = tmp_path / "new-config"
    result = init_config(target)
    assert result["ok"] is True
    assert target.is_dir()
    assert (target / ".env").is_file()
    snippet = export_snippet(target)
    assert "ARKA_CONFIG_DIR" in snippet
    assert str(target.resolve()) in snippet


def test_init_config_migrate(cfg_env, tmp_path):
    from arka.core.config_backup import init_config

    cfg = cfg_env["config"]
    cfg.joinpath("mcp.json").write_text('{"mcpServers": {"x": {}}}\n', encoding="utf-8")

    target = tmp_path / "migrated"
    result = init_config(target, migrate=True)
    assert result["ok"] is True
    assert result["migrated_from"] == str(cfg.resolve())
    assert (target / "mcp.json").is_file()


def test_restore_cancelled_without_force(cfg_env):
    from arka.core.config_backup import create_backup, restore_backup

    archive = Path(create_backup(cfg_env["config"] / "x.tar.gz")["archive"])
    with patch("builtins.input", return_value="n"):
        result = restore_backup(archive, force=False)
    assert result.get("cancelled") is True


def test_maybe_backup_before_unify_disabled(cfg_env, monkeypatch):
    from arka.core.config_backup import maybe_backup_before_unify

    monkeypatch.setenv("ARKA_CONFIG_BACKUP_ON_UNIFY", "0")
    assert maybe_backup_before_unify() is None


def test_maybe_backup_before_unify_enabled(cfg_env):
    from arka.core.config_backup import maybe_backup_before_unify

    result = maybe_backup_before_unify()
    assert result is not None
    assert result["ok"] is True
    assert Path(result["archive"]).is_file()


def test_format_list(cfg_env):
    from arka.core.config_backup import format_list

    text = format_list()
    assert "config_root\t" in text
    assert str(cfg_env["config"]) in text


def test_cli_main_list(cfg_env, capsys):
    from arka.core.config_backup import main

    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "config_root" in out
