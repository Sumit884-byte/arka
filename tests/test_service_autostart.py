"""Tests for generic service autostart script generation and registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock


def test_service_add_with_command(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    registry = tmp_path / "service_autostart.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    wrapper = cache / "my-api-autostart.sh"
    monkeypatch.setattr(sa, "_registry_file", lambda: registry)
    monkeypatch.setattr(sa, "_security_gate_action", lambda _cmd: True)
    monkeypatch.setattr(
        sa,
        "_service_paths",
        lambda _id: {
            "script": wrapper,
            "log": cache / "my-api-autostart.log",
            "launchd": tmp_path / "agent.plist",
            "systemd": cache / "unit.service",
        },
    )

    entry = sa.service_add(service_id="my-api", name="My API", command="npm start", workdir=str(tmp_path))

    assert entry["id"] == "my-api"
    assert entry["command"] == "npm start"
    assert entry["workdir"] == str(tmp_path.resolve())
    rows = sa.list_services()
    assert len(rows) == 1


def test_service_add_with_script(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    registry = tmp_path / "service_autostart.json"
    script = tmp_path / "start.sh"
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    wrapper = cache / "postgres-autostart.sh"
    monkeypatch.setattr(sa, "_registry_file", lambda: registry)
    monkeypatch.setattr(
        sa,
        "_service_paths",
        lambda _id: {
            "script": wrapper,
            "log": cache / "postgres-autostart.log",
            "launchd": tmp_path / "agent.plist",
            "systemd": cache / "unit.service",
        },
    )

    entry = sa.service_add(service_id="postgres", script=str(script))

    assert entry["script"] == str(script.resolve())
    assert entry["workdir"] == str(tmp_path.resolve())


def test_generate_start_script_command(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    sid = "my-api"
    log = tmp_path / f"{sid}-autostart.log"
    monkeypatch.setattr(sa, "_service_paths", lambda _id: {
        "script": tmp_path / f"{sid}-autostart.sh",
        "log": log,
        "launchd": tmp_path / "agent.plist",
        "systemd": tmp_path / "unit.service",
    })

    service = {
        "id": sid,
        "command": "npm start",
        "script": "",
        "workdir": str(tmp_path),
        "env": {"PORT": "3000"},
    }
    rendered = sa.generate_start_script(service)

    assert "#!/usr/bin/env bash" in rendered
    assert "npm start" in rendered
    assert f'cd "{tmp_path}"' in rendered or "WORKDIR=" in rendered
    assert "export PORT=" in rendered and "3000" in rendered


def test_generate_start_script_script(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    sid = "worker"
    script = tmp_path / "worker.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    log = tmp_path / f"{sid}-autostart.log"
    monkeypatch.setattr(sa, "_service_paths", lambda _id: {
        "script": tmp_path / f"{sid}-autostart.sh",
        "log": log,
        "launchd": tmp_path / "agent.plist",
        "systemd": tmp_path / "unit.service",
    })

    service = {
        "id": sid,
        "command": "",
        "script": str(script),
        "workdir": str(tmp_path),
        "env": {},
    }
    rendered = sa.generate_start_script(service)

    assert str(script) in rendered
    assert 'bash "$SCRIPT"' in rendered


def test_generate_launchd_plist(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    script = tmp_path / "my-api-autostart.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    log = tmp_path / "my-api-autostart.log"
    monkeypatch.setattr(sa, "_service_paths", lambda _id: {
        "script": script,
        "log": log,
        "launchd": tmp_path / "agent.plist",
        "systemd": tmp_path / "unit.service",
    })

    plist = sa.generate_launchd_plist(service_id="my-api", script=script)

    assert "com.arka.service.my-api" in plist
    assert "<key>RunAtLoad</key><true/>" in plist
    assert str(script) in plist


def test_generate_systemd_unit(tmp_path: Path):
    from arka.integrations import service_autostart as sa

    script = tmp_path / "my-api-autostart.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    unit = sa.generate_systemd_unit(service_id="my-api", script=script)

    assert "[Unit]" in unit
    assert str(script) in unit
    assert "WantedBy=default.target" in unit


def test_install_autostart_writes_wrapper_and_plist(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    registry = tmp_path / "service_autostart.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    sid = "my-api"
    wrapper = cache / f"{sid}-autostart.sh"
    plist = tmp_path / "Library" / "LaunchAgents" / f"com.arka.service.{sid}.plist"

    monkeypatch.setattr(sa, "_registry_file", lambda: registry)
    monkeypatch.setattr(sa, "_security_gate_action", lambda _cmd: True)
    monkeypatch.setattr(
        sa,
        "_service_paths",
        lambda _id: {
            "script": wrapper,
            "log": cache / f"{sid}-autostart.log",
            "launchd": plist,
            "systemd": cache / f"arka-service-{sid}.service",
        },
    )
    monkeypatch.setattr(sa.sys, "platform", "darwin")
    monkeypatch.setattr(sa, "supported_platform", lambda: True)
    monkeypatch.setattr(sa.shutil, "which", lambda name: f"/usr/bin/{name}")

    sa.service_add(service_id=sid, command="npm start", workdir=str(tmp_path))

    with mock.patch.object(sa, "_launchctl", return_value=mock.Mock(returncode=0)):
        code = sa.install_autostart(sid)

    assert code == 0
    assert wrapper.is_file()
    assert plist.is_file()
    assert "npm start" in wrapper.read_text(encoding="utf-8")


def test_route_command_matches_autostart_phrase():
    from arka.integrations.service_autostart import route_command

    assert route_command("autostart service list") == "service_autostart list"
    assert route_command("service autostart status my-api") == "service_autostart status my-api"


def test_nl_to_argv_add_script():
    from arka.integrations.service_autostart import nl_to_argv

    argv = nl_to_argv('add autostart service worker script ~/bin/start-worker.sh')
    assert argv == ["add", "worker", "--script", "~/bin/start-worker.sh"]


def test_service_add_writes_wrapper_on_add(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    registry = tmp_path / "service_autostart.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    wrapper = cache / "my-api-autostart.sh"
    monkeypatch.setattr(sa, "_registry_file", lambda: registry)
    monkeypatch.setattr(sa, "_security_gate_action", lambda _cmd: True)
    monkeypatch.setattr(
        sa,
        "_service_paths",
        lambda _id: {
            "script": wrapper,
            "log": cache / "my-api-autostart.log",
            "launchd": tmp_path / "agent.plist",
            "systemd": cache / "unit.service",
        },
    )

    entry = sa.service_add(service_id="my-api", command="npm start", workdir=str(tmp_path))

    assert entry["wrapper_script"] == str(wrapper)
    assert wrapper.is_file()
    assert "npm start" in wrapper.read_text(encoding="utf-8")


def test_service_add_from_description_uses_llm(tmp_path: Path, monkeypatch):
    from arka.integrations import service_autostart as sa

    registry = tmp_path / "service_autostart.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    wrapper = cache / "postgres-autostart.sh"
    monkeypatch.setattr(sa, "_registry_file", lambda: registry)
    monkeypatch.setattr(sa, "_security_gate_action", lambda _cmd: True)
    monkeypatch.setattr(
        sa,
        "_service_paths",
        lambda _id: {
            "script": wrapper,
            "log": cache / "postgres-autostart.log",
            "launchd": tmp_path / "agent.plist",
            "systemd": cache / "unit.service",
        },
    )
    monkeypatch.setattr(
        sa,
        "infer_service_from_description",
        lambda description, **kwargs: {
            "command": "docker start postgres",
            "workdir": str(tmp_path),
            "env": {"PGDATA": "/data"},
        },
    )

    entry = sa.service_add(
        service_id="postgres",
        description="start local postgres docker container on login",
    )

    assert entry["command"] == "docker start postgres"
    assert entry["inferred"] is True
    assert wrapper.is_file()
    assert "docker start postgres" in wrapper.read_text(encoding="utf-8")


def test_main_list_empty(tmp_path: Path, monkeypatch, capsys):
    from arka.integrations import service_autostart as sa

    monkeypatch.setattr(sa, "_registry_file", lambda: tmp_path / "service_autostart.json")
    code = sa.main(["list"])
    assert code == 0
    assert "No services registered" in capsys.readouterr().out


def test_main_add_and_list(tmp_path: Path, monkeypatch, capsys):
    from arka.integrations import service_autostart as sa

    cache = tmp_path / "cache"
    cache.mkdir()
    wrapper = cache / "api-autostart.sh"
    monkeypatch.setattr(sa, "_registry_file", lambda: tmp_path / "service_autostart.json")
    monkeypatch.setattr(sa, "_security_gate_action", lambda _cmd: True)
    monkeypatch.setattr(
        sa,
        "_service_paths",
        lambda _id: {
            "script": wrapper,
            "log": cache / "api-autostart.log",
            "launchd": tmp_path / "agent.plist",
            "systemd": cache / "unit.service",
        },
    )

    code = sa.main(["add", "api", "--command", "npm start", "--workdir", str(tmp_path)])
    assert code == 0

    capsys.readouterr()
    code = sa.main(["list"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["id"] == "api"
