from unittest import mock

from arka.agent import sandbox


def test_create_run_and_destroy(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARKA_SANDBOX_DIR", str(tmp_path / "sandboxes"))
    assert sandbox.create("demo")["name"] == "demo"
    assert sandbox.run("demo", ["python", "-c", "print('ok')"]) == 0
    assert "ok" in capsys.readouterr().out
    sandbox.destroy("demo", confirmed=True)
    assert not (tmp_path / "sandboxes" / "demo").exists()


def test_destroy_requires_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKA_SANDBOX_DIR", str(tmp_path))
    sandbox.create("demo")
    try:
        sandbox.destroy("demo")
    except ValueError as exc:
        assert "--yes" in str(exc)
    else:
        raise AssertionError("destroy should require confirmation")


def test_invalid_name(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKA_SANDBOX_DIR", str(tmp_path))
    try:
        sandbox.create("../unsafe")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid sandbox name accepted")


def test_bootstrap_python(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARKA_SANDBOX_DIR", str(tmp_path / "sandboxes"))
    sandbox.create("demo")
    pip = tmp_path / "sandboxes" / "demo" / ".venv" / "bin" / "pip"

    def _fake_run(name, command, timeout=60):
        if len(command) >= 3 and command[1:3] == ["-m", "venv"]:
            pip.parent.mkdir(parents=True, exist_ok=True)
            pip.write_text("#!/bin/sh\n", encoding="utf-8")
        return 0

    with mock.patch.object(sandbox, "run", side_effect=_fake_run) as run:
        out = sandbox.bootstrap_python("demo", ["rembg[cpu]", "Pillow"])
    assert out["name"] == "demo"
    assert out["packages"] == ["rembg[cpu]", "Pillow"]
    assert run.call_count == 2

