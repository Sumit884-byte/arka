"""Fish shell must route `arka signoz` to Python CLI, not web_answer."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FISH_CFG = REPO / "src" / "arka" / "fish" / "config.fish"
BUNDLED_CFG = REPO / "src" / "arka" / "bundled" / "config.fish"


def test_fish_config_has_signoz_python_delegate():
    text = FISH_CFG.read_text(encoding="utf-8")
    assert "case signoz observability otel telemetry" in text
    assert "$py -m arka signoz $argv[2..-1]" in text


def test_bundled_config_has_signoz_python_delegate():
    assert BUNDLED_CFG.is_file(), "run: python scripts/sync_bundled.py"
    text = BUNDLED_CFG.read_text(encoding="utf-8")
    assert "case signoz observability otel telemetry" in text
    assert "$py -m arka signoz $argv[2..-1]" in text


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ARKA_AUTO_REFETCH"] = "0"
    env["INSTALL_HOME"] = str(REPO)
    env["CONFIG_DIR"] = "/tmp/arka-signoz-fish-test"
    env["PYTHONPATH"] = str(REPO / "src")
    return env


def _run_fish_arka(*args: str) -> subprocess.CompletedProcess[str]:
    cfg = shlex.quote(str(FISH_CFG))
    cmd = " ".join(["arka", *args])
    inner = f"source {cfg}; {cmd}"
    return subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=_fish_env(),
        timeout=60,
        check=False,
    )


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_arka_signoz_status_hits_python_cli():
    proc = _run_fish_arka("signoz", "status")
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, combined
    assert "signoz_setup" in combined
    assert "web_answer" not in combined.lower()
    assert "Factual question" not in combined
    assert "🔎" not in combined


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_arka_signoz_setup_not_web_answer():
    proc = _run_fish_arka("signoz", "setup", "--check-only")
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert "docker_cli" in combined or "foundryctl" in combined, combined
    assert "web_answer" not in combined.lower()
    assert "🔎" not in combined
    assert "Paste SIGNOZ_API_KEY" not in combined


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_agent_signoz_status_hits_python_cli():
    """Fallback when arka subcommand switch misses and agent receives signoz first."""
    cfg = shlex.quote(str(FISH_CFG))
    inner = f"source {cfg}; agent signoz status"
    proc = subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=_fish_env(),
        timeout=60,
        check=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, combined
    assert "signoz_setup" in combined
    assert "web_answer" not in combined.lower()


def test_python_module_signoz_status_not_integration_setup(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["signoz", "status"]) == 0
    output = capsys.readouterr().out
    assert "signoz_setup" in output
    assert "integration setup" not in output.lower()
