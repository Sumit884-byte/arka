"""Tests for SigNoz login autostart script and unit generation."""

from __future__ import annotations

from pathlib import Path
from unittest import mock


def test_generate_autostart_script_includes_casting_and_docker_wait(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    casting = tmp_path / "casting.yaml"
    casting.write_text("kind: Installation\n", encoding="utf-8")
    log = tmp_path / "signoz-autostart.log"
    script = tmp_path / "signoz-autostart.sh"

    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: log)
    monkeypatch.setattr(signoz_autostart, "autostart_script_path", lambda: script)

    rendered = signoz_autostart.generate_autostart_script(casting=casting)

    assert "#!/usr/bin/env bash" in rendered
    assert str(casting.resolve()) in rendered
    assert "CASTING_DIR" in rendered
    assert 'cd "$CASTING_DIR"' in rendered
    assert "docker info" in rendered
    assert "cast -f" in rendered
    assert "--no-gauge" in rendered
    assert "open -a Docker" in rendered


def test_generate_launchd_plist_contains_label_and_run_at_load(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    script = tmp_path / "signoz-autostart.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: tmp_path / "signoz-autostart.log")

    plist = signoz_autostart.generate_launchd_plist(script=script)

    assert signoz_autostart.AUTOSTART_LABEL in plist
    assert "<key>RunAtLoad</key><true/>" in plist
    assert str(script) in plist


def test_generate_systemd_unit_runs_script(tmp_path: Path):
    from arka.telemetry import signoz_autostart

    script = tmp_path / "signoz-autostart.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    unit = signoz_autostart.generate_systemd_unit(script=script)

    assert "[Unit]" in unit
    assert "docker.service" in unit
    assert str(script) in unit
    assert "WantedBy=default.target" in unit


def test_install_autostart_writes_script_and_plist(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    casting = tmp_path / "casting.yaml"
    casting.write_text("kind: Installation\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    script = cache / "signoz-autostart.sh"
    plist = tmp_path / "Library" / "LaunchAgents" / f"{signoz_autostart.AUTOSTART_LABEL}.plist"

    monkeypatch.setattr(signoz_autostart, "autostart_script_path", lambda: script)
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: cache / "signoz-autostart.log")
    monkeypatch.setattr(signoz_autostart, "launchd_plist_path", lambda: plist)
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "supported_platform", lambda: True)
    monkeypatch.setattr(signoz_autostart, "resolve_casting_yaml", lambda: casting)
    monkeypatch.setattr(signoz_autostart, "docker_cli_path", lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(signoz_autostart, "foundryctl_path", lambda: "/usr/local/bin/foundryctl")
    monkeypatch.setattr(signoz_autostart.shutil, "which", lambda name: f"/usr/bin/{name}")

    with mock.patch.object(signoz_autostart, "enable_docker_autostart", return_value={"docker_autostart": "enabled", "docker_autostart_detail": "ok"}), mock.patch.object(
        signoz_autostart, "launch_docker_desktop_if_needed"
    ), mock.patch.object(signoz_autostart, "_launchctl") as launchctl_mock:
        rc = signoz_autostart.install_autostart()

    assert rc == 0
    assert script.is_file()
    assert script.stat().st_mode & 0o111
    assert plist.is_file()
    assert launchctl_mock.call_count >= 1


def test_autostart_status_reports_missing_install(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(signoz_autostart, "autostart_script_path", lambda: cache / "signoz-autostart.sh")
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: cache / "signoz-autostart.log")
    monkeypatch.setattr(signoz_autostart, "launchd_plist_path", lambda: tmp_path / "missing.plist")
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "resolve_casting_yaml", lambda: None)
    monkeypatch.setattr(signoz_autostart, "docker_cli_path", lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(signoz_autostart, "foundryctl_path", lambda: None)
    monkeypatch.setattr(signoz_autostart.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "launchctl" else None)

    status = signoz_autostart.autostart_status()

    assert status["backend"] == "launchd"
    assert status["installed"] == "false"
    assert status["casting_yaml"] == "missing"
    assert status["foundryctl"] == "missing"


def test_cli_autostart_status_smoke(monkeypatch, capsys):
    from arka.telemetry import signoz_autostart
    from arka.telemetry.signoz_cli import main

    monkeypatch.setattr(signoz_autostart, "autostart_status", lambda: {"installed": "false", "backend": "launchd"})
    assert main(["autostart", "status"]) == 0
    output = capsys.readouterr().out
    assert "installed\tfalse" in output
    assert "backend\tlaunchd" in output


def test_generate_autostart_script_opens_docker_with_osascript(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    casting = tmp_path / "casting.yaml"
    casting.write_text("kind: Installation\n", encoding="utf-8")
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: tmp_path / "log")
    rendered = signoz_autostart.generate_autostart_script(casting=casting)
    assert "osascript" in rendered
    assert 'tell application "Docker"' in rendered


def test_generate_autostart_script_respects_signoz_autostart_env(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    casting = tmp_path / "casting.yaml"
    casting.write_text("kind: Installation\n", encoding="utf-8")
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: tmp_path / "log")

    rendered = signoz_autostart.generate_autostart_script(casting=casting)

    assert "_load_arka_env" in rendered
    assert "_signoz_autostart_disabled" in rendered
    assert "SIGNOZ_AUTOSTART" in rendered
    assert "disabled by SIGNOZ_AUTOSTART" in rendered


def test_signoz_autostart_enabled_defaults_true(monkeypatch):
    from arka.telemetry import signoz_autostart

    monkeypatch.delenv("SIGNOZ_AUTOSTART", raising=False)
    monkeypatch.delenv("ARKA_SIGNOZ_AUTOSTART", raising=False)
    assert signoz_autostart.signoz_autostart_enabled() is True


def test_signoz_autostart_enabled_respects_falsy_values(monkeypatch):
    from arka.telemetry import signoz_autostart

    for value in ("0", "false", "off", "no", "FALSE"):
        monkeypatch.setenv("SIGNOZ_AUTOSTART", value)
        assert signoz_autostart.signoz_autostart_enabled() is False


def test_signoz_autostart_enabled_respects_truthy_values(monkeypatch):
    from arka.telemetry import signoz_autostart

    for value in ("1", "true", "on", "yes", "TRUE"):
        monkeypatch.setenv("SIGNOZ_AUTOSTART", value)
        assert signoz_autostart.signoz_autostart_enabled() is True


def test_signoz_autostart_config_status_disabled_by_config(monkeypatch):
    from arka.telemetry import signoz_autostart

    monkeypatch.setenv("SIGNOZ_AUTOSTART", "off")
    status = signoz_autostart.signoz_autostart_config_status()
    assert status["config_enabled"] == "false"
    assert status["config_detail"] == "disabled-by-config"


def test_install_autostart_skips_when_disabled(tmp_path: Path, monkeypatch, capsys):
    from arka.telemetry import signoz_autostart

    monkeypatch.setenv("SIGNOZ_AUTOSTART", "0")
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "supported_platform", lambda: True)

    rc = signoz_autostart.install_autostart()

    assert rc == 0
    err = capsys.readouterr().err
    assert "disabled" in err.lower()
    assert "SIGNOZ_AUTOSTART" in err


def test_install_autostart_uninstalls_when_disabled_and_installed(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    cache = tmp_path / "cache"
    cache.mkdir()
    script = cache / "signoz-autostart.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    plist = tmp_path / "Library" / "LaunchAgents" / f"{signoz_autostart.AUTOSTART_LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist></plist>", encoding="utf-8")

    monkeypatch.setenv("SIGNOZ_AUTOSTART", "false")
    monkeypatch.setattr(signoz_autostart, "autostart_script_path", lambda: script)
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: cache / "signoz-autostart.log")
    monkeypatch.setattr(signoz_autostart, "launchd_plist_path", lambda: plist)
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "supported_platform", lambda: True)
    monkeypatch.setattr(signoz_autostart, "resolve_casting_yaml", lambda: None)
    monkeypatch.setattr(signoz_autostart, "docker_cli_path", lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(signoz_autostart, "foundryctl_path", lambda: "/usr/local/bin/foundryctl")
    monkeypatch.setattr(signoz_autostart.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "launchctl" else None)

    with mock.patch.object(signoz_autostart, "_launchctl") as launchctl_mock:
        rc = signoz_autostart.install_autostart()

    assert rc == 0
    assert not script.is_file()
    assert not plist.is_file()
    assert launchctl_mock.call_count >= 1


def test_autostart_status_includes_config_fields(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("SIGNOZ_AUTOSTART", "no")
    monkeypatch.setattr(signoz_autostart, "autostart_script_path", lambda: cache / "signoz-autostart.sh")
    monkeypatch.setattr(signoz_autostart, "autostart_log_path", lambda: cache / "signoz-autostart.log")
    monkeypatch.setattr(signoz_autostart, "launchd_plist_path", lambda: tmp_path / "missing.plist")
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "resolve_casting_yaml", lambda: None)
    monkeypatch.setattr(signoz_autostart, "docker_cli_path", lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(signoz_autostart, "foundryctl_path", lambda: None)
    monkeypatch.setattr(signoz_autostart.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "launchctl" else None)

    status = signoz_autostart.autostart_status()

    assert status["config_enabled"] == "false"
    assert status["config_detail"] == "disabled-by-config"


def test_enable_docker_desktop_autostart_writes_settings(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    settings = tmp_path / "settings-store.json"
    settings.write_text('{"AutoStart": false}\n', encoding="utf-8")
    monkeypatch.setattr(signoz_autostart, "DOCKER_DESKTOP_SETTINGS", settings)
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "docker_desktop_installed", lambda: True)

    result = signoz_autostart.enable_docker_autostart()

    assert result["docker_autostart"] == "enabled"
    import json

    assert json.loads(settings.read_text())["AutoStart"] is True


def test_docker_autostart_status_reads_settings(tmp_path: Path, monkeypatch):
    from arka.telemetry import signoz_autostart

    settings = tmp_path / "settings-store.json"
    settings.write_text('{"AutoStart": true}\n', encoding="utf-8")
    monkeypatch.setattr(signoz_autostart, "DOCKER_DESKTOP_SETTINGS", settings)
    monkeypatch.setattr(signoz_autostart.sys, "platform", "darwin")
    monkeypatch.setattr(signoz_autostart, "docker_desktop_installed", lambda: True)

    status = signoz_autostart.docker_autostart_status()

    assert status["docker_autostart"] == "enabled"

