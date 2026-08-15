"""Fish agent must route connector NL offline — not web_answer / Gemini."""

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


def test_fish_config_has_connector_routing():
    text = FISH_CFG.read_text(encoding="utf-8")
    assert "function _agent_build_connector_cmd" in text
    assert "function _agent_is_connector_request" in text
    assert "_agent_is_connector_request" in text


def test_bundled_config_has_connector_routing():
    assert BUNDLED_CFG.is_file(), "run: python scripts/sync_bundled.py"
    text = BUNDLED_CFG.read_text(encoding="utf-8")
    assert "function _agent_build_connector_cmd" in text
    assert "_agent_is_connector_request" in text


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ARKA_AUTO_REFETCH"] = "0"
    env["INSTALL_HOME"] = str(REPO)
    env["CONFIG_DIR"] = "/tmp/arka-connector-fish-test"
    env["PYTHONPATH"] = str(REPO / "src")
    return env


def _run_fish(cmd: str) -> subprocess.CompletedProcess[str]:
    cfg = shlex.quote(str(FISH_CFG))
    inner = f"source {cfg}; {cmd}"
    return subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=_fish_env(),
        timeout=30,
        check=False,
    )


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_guess_route_connector_suggest():
    proc = _run_fish("_agent_guess_route 'suggest cli to connect'")
    out = proc.stdout.strip()
    assert proc.returncode == 0, proc.stderr
    assert "connector suggest" in out
    assert "web_answer" not in out


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_is_general_chat_excludes_connector_suggest():
    proc = _run_fish("_agent_is_general_chat 'suggest cli to connect'; echo status=$status")
    assert "status=1" in proc.stdout.strip()


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_arka_suggest_cli_routes_offline():
    proc = _run_fish("agent_route 'suggest cli to connect'")
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, combined
    assert "connector suggest" in combined
    assert "web_answer" not in combined.lower()
