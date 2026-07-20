from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from arka.agent import coding_tui
from arka.agent.post_scaffold import (
    SCAFFOLD_3D_TEMPLATE,
    NpmInstallResult,
    parse_package_count,
    parse_vite_local_url,
    post_scaffold_hook,
    run_trusted_npm_install,
    template_created_package_json,
)


def test_template_created_package_json_requires_trusted_template():
    assert template_created_package_json(SCAFFOLD_3D_TEMPLATE, ["package.json"])
    assert not template_created_package_json("custom", ["package.json"])
    assert not template_created_package_json(SCAFFOLD_3D_TEMPLATE, ["README.md"])


def test_parse_package_count():
    assert parse_package_count("added 142 packages, and audited 143 packages in 12s") == 142
    assert parse_package_count("audited 9 packages in 1s") == 9
    assert parse_package_count("nothing useful") is None


def test_parse_vite_local_url():
    assert parse_vite_local_url("  ➜  Local:   http://localhost:5173/") == "http://localhost:5173/"
    assert parse_vite_local_url("http://127.0.0.1:4173") == "http://127.0.0.1:4173/"


def test_run_trusted_npm_install_success(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "added 142 packages, and audited 143 packages in 12s\n"
        proc.stderr = ""
        return proc

    monkeypatch.setattr("arka.agent.post_scaffold.subprocess.run", fake_run)
    result = run_trusted_npm_install(tmp_path)
    assert result.ok
    assert result.package_count == 142
    assert calls == [["npm", "install"]]


def test_run_trusted_npm_install_offline(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "npm ERR! network ENOTFOUND registry.npmjs.org\n"
        return proc

    monkeypatch.setattr("arka.agent.post_scaffold.subprocess.run", fake_run)
    result = run_trusted_npm_install(tmp_path)
    assert not result.ok
    assert "network unavailable" in result.message


def test_post_scaffold_hook_runs_npm_install(monkeypatch, tmp_path, capsys):
    install_calls: list[Path] = []

    def fake_install(cwd):
        install_calls.append(cwd)
        return NpmInstallResult(ok=True, package_count=142)

    monkeypatch.setattr("arka.agent.post_scaffold.run_trusted_npm_install", fake_install)
    monkeypatch.setattr("arka.agent.post_scaffold.run_npm_audit_warn", lambda cwd: None)
    monkeypatch.setattr("arka.agent.post_scaffold.shutil.which", lambda name: "/usr/bin/npm")

    post_scaffold_hook(
        SCAFFOLD_3D_TEMPLATE,
        tmp_path,
        created=["package.json", "src/App.jsx"],
        prompt_dev=False,
    )
    output = capsys.readouterr().out
    assert install_calls == [tmp_path]
    assert "Installing dependencies" in output
    assert "npm install complete (142 packages)" in output
    assert "Next: `npm run dev`" in output


def test_post_scaffold_hook_npm_failure_still_reports_next_steps(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "arka.agent.post_scaffold.run_trusted_npm_install",
        lambda cwd: NpmInstallResult(ok=False, message="network unavailable"),
    )
    monkeypatch.setattr("arka.agent.post_scaffold.shutil.which", lambda name: "/usr/bin/npm")

    post_scaffold_hook(
        SCAFFOLD_3D_TEMPLATE,
        tmp_path,
        created=["package.json"],
        prompt_dev=False,
    )
    output = capsys.readouterr().out
    assert "npm install failed" in output
    assert "Scaffold files were created" in output


def test_run_3d_scaffold_calls_post_hook(monkeypatch, tmp_path, capsys):
    hook_calls: list[dict] = []

    def fake_hook(template, repo, *, created, run_dev=False, prompt_dev=True):
        hook_calls.append(
            {"template": template, "repo": repo, "created": created, "run_dev": run_dev}
        )

    monkeypatch.setattr("arka.agent.coding_tui._post_scaffold_hook", fake_hook)
    rc = coding_tui._run_3d_scaffold(tmp_path, goal="beautiful 3D space", prompt_dev=False)
    output = capsys.readouterr().out
    assert rc == 0
    assert hook_calls
    assert hook_calls[0]["template"] == SCAFFOLD_3D_TEMPLATE
    assert "package.json" in hook_calls[0]["created"]
    assert "3D space scaffold created" in output


def test_run_3d_scaffold_npm_failure_keeps_created_files(monkeypatch, tmp_path, capsys):
    def fake_hook(template, repo, *, created, run_dev=False, prompt_dev=True):
        print("✗ npm install failed — network unavailable")
        print("Scaffold files were created; run `npm install` manually when ready.")

    monkeypatch.setattr("arka.agent.coding_tui._post_scaffold_hook", fake_hook)
    rc = coding_tui._run_3d_scaffold(tmp_path, prompt_dev=False)
    output = capsys.readouterr().out
    assert rc == 0
    assert "3D space scaffold created" in output
    assert (tmp_path / "package.json").is_file()
    assert "npm install failed" in output
    assert "Scaffold files were created" in output


def test_parse_scaffold_3d_command():
    assert coding_tui._parse_scaffold_3d_command("/scaffold 3d") == ("beautiful 3D space", False)
    assert coding_tui._parse_scaffold_3d_command("/scaffold 3d --run") == ("beautiful 3D space", True)
    assert coding_tui._parse_scaffold_3d_command("/scaffold 3d moon scene --run") == (
        "moon scene",
        True,
    )


def test_coding_tui_scaffold_run_flag(monkeypatch, tmp_path, capsys):
    calls: list[bool] = []

    def fake_scaffold(repo, *, goal="", run_dev=False, prompt_dev=True):
        calls.append(run_dev)
        return 0

    monkeypatch.setattr("arka.agent.coding_tui._run_3d_scaffold", fake_scaffold)
    commands = iter(["/scaffold 3d --run", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == [True]
