"""Tests for agentic verification-script discovery."""

from __future__ import annotations

import textwrap
from pathlib import Path

from arka.agent import repo_health as rh
from arka.agent import script_discovery as sd


def test_discovers_verification_scripts_in_arka_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    names = {probe.path.name for probe in sd.discover_verification_scripts(root)}
    assert "verify_features.py" in names
    assert "check_docs.py" in names
    assert "sync_doc_icons.py" in names
    assert "publish_pypi.sh" not in names
    assert "sync_bundled.py" not in names


def test_probe_scores_test_functions_without_hardcoded_names(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "run_quality_gate.py"
    script.parent.mkdir()
    script.write_text(
        textwrap.dedent(
            '''
            """Smoke verification for the service layer."""

            def test_login_flow() -> None:
                assert True

            def test_logout_flow() -> None:
                assert True

            if __name__ == "__main__":
                test_login_flow()
                test_logout_flow()
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    probe = sd.probe_script(script)
    assert probe.category == "test"
    assert probe.test_function_count == 2
    assert probe.score >= 4


def test_probe_detects_check_mode_validator(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "sync_metadata.py"
    script.parent.mkdir()
    script.write_text(
        textwrap.dedent(
            '''
            """Ensure metadata files stay valid."""
            import argparse

            def main() -> int:
                parser = argparse.ArgumentParser(description="Validate metadata files")
                parser.add_argument("root", nargs="?", default="docs")
                parser.add_argument(
                    "--check",
                    action="store_true",
                    help="Fail if any file would change",
                )
                return 0

            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    probe = sd.probe_script(script)
    assert probe.category == "lint"
    assert "--check" in sd.build_script_command(probe, tmp_path)


def test_repo_health_includes_discovered_script_checks() -> None:
    root = Path(__file__).resolve().parents[1]
    checks = rh.detect_checks(root)
    script_names = [check.name for check in checks if check.name.startswith("script:")]
    assert "script:verify_features.py" in script_names
    assert "script:check_docs.py" in script_names
    assert any(check.detail for check in checks if check.name.startswith("script:"))


def test_coding_tui_runs_discovered_scripts_scope(monkeypatch, tmp_path, capsys) -> None:
    from arka.agent import coding_tui

    script = tmp_path / "scripts" / "verify_widget.py"
    script.parent.mkdir()
    script.write_text(
        textwrap.dedent(
            '''
            """Verify widget exports."""

            def test_widget() -> None:
                assert True

            if __name__ == "__main__":
                raise SystemExit(0 if test_widget() is None else 1)
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    commands = iter(["/test scripts", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Verification scripts (1 discovered)" in output
    assert "verify_widget.py" in output
