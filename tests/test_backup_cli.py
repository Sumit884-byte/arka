"""Tests for arka backup all CLI."""

from __future__ import annotations

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


def test_cli_backup_all(cfg_env, capsys):
    from arka.cli import main

    cfg = cfg_env["config"]
    cfg.joinpath(".env").write_text("KEY=1\n", encoding="utf-8")
    with patch("arka.core.config_backup.create_backup") as create:
        create.return_value = {
            "ok": True,
            "archive": str(cfg / "backups" / "test.tar.gz"),
            "bytes": 1234,
            "manifest": {"files": {"config": 2, "cache": 1}},
        }
        code = main(["backup", "all"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Backup saved" in out
    create.assert_called_once()


def test_cli_config_backup_routes_to_config_backup(cfg_env):
    from arka.cli import main

    with patch("arka.core.config_backup.main") as config_backup_main:
        config_backup_main.return_value = 0
        code = main(["config", "backup"])
    assert code == 0
    config_backup_main.assert_called_once_with(["backup"])


def test_route_backup_all():
    from arka.routing.symbolic import route_backup

    assert route_backup("backup all arka files") == "backup all"
    assert route_backup("arka backup everything") == "backup all"
