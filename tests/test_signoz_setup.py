"""Tests for SigNoz prerequisite detection and setup helpers."""

from __future__ import annotations

from pathlib import Path
from unittest import mock



def test_docker_status_missing_cli():
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup.shutil, "which", return_value=None):
        assert signoz_setup.docker_status() == {
            "docker_cli": "missing",
            "docker_daemon": "missing",
        }


def test_docker_status_daemon_running():
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup.shutil, "which", return_value="/usr/bin/docker"):
        with mock.patch.object(signoz_setup, "docker_daemon_running", return_value=True):
            assert signoz_setup.docker_status() == {
                "docker_cli": "ok",
                "docker_daemon": "running",
            }


def test_docker_status_cli_without_daemon():
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup.shutil, "which", return_value="/usr/bin/docker"):
        with mock.patch.object(signoz_setup, "docker_daemon_running", return_value=False):
            assert signoz_setup.docker_status() == {
                "docker_cli": "ok",
                "docker_daemon": "stopped",
            }


def test_foundryctl_prefers_path(monkeypatch, tmp_path: Path):
    from arka.telemetry import signoz_setup

    fake = tmp_path / "foundryctl"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)

    with mock.patch.object(signoz_setup.shutil, "which", return_value=str(fake)):
        assert signoz_setup.foundryctl_path() == str(fake)


def test_foundryctl_falls_back_to_foundry_bin(monkeypatch, tmp_path: Path):
    from arka.telemetry import signoz_setup

    fake = tmp_path / "foundryctl"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)

    with mock.patch.object(signoz_setup.shutil, "which", return_value=None):
        with mock.patch.object(signoz_setup, "FOUNDRY_BIN_DIRS", (tmp_path,)):
            assert signoz_setup.foundryctl_path() == str(fake)


def test_resolve_casting_yaml_from_checkout_root(monkeypatch, tmp_path: Path):
    from arka.telemetry import signoz_setup

    casting = tmp_path / "casting.yaml"
    casting.write_text("kind: Installation\n", encoding="utf-8")

    with mock.patch("arka.paths.checkout_root", return_value=tmp_path):
        with mock.patch("arka.paths.arka_home", return_value=tmp_path / "other"):
            assert signoz_setup.resolve_casting_yaml() == casting.resolve()


def test_docker_install_plan_macos_brew():
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup, "platform_label", return_value="macos"):
        with mock.patch.object(signoz_setup.shutil, "which", side_effect=lambda name: "/opt/brew/bin/brew" if name == "brew" else None):
            plan = signoz_setup._docker_install_plan()
            assert plan == [("Homebrew (Docker Desktop)", ["brew", "install", "--cask", "docker"])]


def test_confirm_respects_auto_yes():
    from arka.telemetry import signoz_setup

    assert signoz_setup._confirm("Install?", auto_yes=True) is True


def test_confirm_non_interactive_without_auto_yes(capsys):
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup.sys.stdin, "isatty", return_value=False):
        assert signoz_setup._confirm("Install?", auto_yes=False) is False
    assert "non-interactive" in capsys.readouterr().err


def test_cmd_setup_check_only_reports_status(monkeypatch):
    from arka.telemetry import signoz_setup

    args = argparse_namespace(check_only=True, yes=False, skip_cast=False)

    with mock.patch.object(signoz_setup, "docker_daemon_running", return_value=False):
        with mock.patch.object(signoz_setup, "foundryctl_path", return_value=None):
            with mock.patch.object(signoz_setup, "resolve_casting_yaml", return_value=Path("/tmp/casting.yaml")):
                rc = signoz_setup.cmd_setup(args)
    assert rc == 1


def test_ensure_docker_skips_when_running():
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup, "docker_daemon_running", return_value=True):
        assert signoz_setup.ensure_docker(auto_yes=False) is True


def test_ensure_docker_declined_install():
    from arka.telemetry import signoz_setup

    with mock.patch.object(signoz_setup, "docker_daemon_running", return_value=False):
        with mock.patch.object(signoz_setup.shutil, "which", return_value=None):
            with mock.patch.object(signoz_setup, "_docker_install_plan", return_value=[("brew", ["brew", "install", "--cask", "docker"])]):
                with mock.patch.object(signoz_setup, "_confirm", return_value=False):
                    assert signoz_setup.ensure_docker(auto_yes=False) is False


def argparse_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)
