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
