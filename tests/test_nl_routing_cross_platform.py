"""Cross-platform natural-language routing cases and verification tests."""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stderr
from unittest import mock

import pytest

from arka.router import route, route_preview

# (natural language phrase, expected skill prefix or exact skill start)
SYMBOLIC_NL_CASES: list[tuple[str, str]] = [
    # CLI connector / shared context
    ("connect shared context", "connector connect"),
    ("wire terminal to shared context", "connector connect"),
    ("cli connector status", "connector status"),
    ("attach terminal to shared context", "connector connect"),
    ("show shared context for deployment", "connector context"),
    ("mac shared context cli connector", "connector connect"),
    ("windows shared context cli connector", "connector connect"),
    ("linux shared context cli connector", "connector connect"),
    ("suggest cli to connect", "connector suggest"),
    ("how to connect cli", "connector suggest"),
    # Agent hub
    ("sync agent hub", "agent_hub sync"),
    ("shared mcp for agents", "agent_hub status"),
    ("unify agent hub mcp", "agent_hub sync --unify"),
    ("launch openclaw", "agent_hub launch openclaw"),
    ("agent hub doctor", "agent_hub doctor"),
    ("detect agent hub configs", "agent_hub detect"),
    # Docker
    ("show docker containers", "docker_status ps"),
    ("list running docker containers", "docker_status ps"),
    ("is docker running", "docker_status health"),
    ("check docker daemon", "docker_status health"),
    ("show docker images", "docker_status images"),
    # MCP
    ("mcp status", "mcp status"),
    ("mcp doctor", "mcp doctor"),
    ("list mcp servers", "mcp list"),
    ("install arka mcp", "mcp install"),
    ("serve arka mcp", "mcp serve"),
    ("show arka mcp tools", "mcp self-tools"),
    # Edit guard
    ("edit guard status", "edit_guard status"),
    ("list blocked edit paths", "edit_guard list"),
    # Local image generation (exact skill line enforced in test_local_image_routing.py)
    ("generate image locally of a moonlit forest", "image generate 'a moonlit forest'"),
    ("generate image locally of a lighthouse", "image generate 'a lighthouse'"),
    ("create picture with stable diffusion of a robot", "image generate 'a robot'"),
    # Service autostart
    ("service autostart list", "service_autostart list"),
    ("show autostart services", "service_autostart list"),
    # CodeRabbit
    ("coderabbit review", "coderabbit review"),
    ("trigger coderabbit on this pr", "coderabbit trigger"),
    # Existing high-value routes
    ("what can arka do", "capabilities"),
    ("check repo health", "repo_health"),
]

MODULE_NL_CASES: list[tuple[str, str, list[str]]] = [
    ("cli_connector", "connect shared context", ["connect"]),
    ("cli_connector", "connector doctor", ["doctor"]),
    ("cli_connector", "suggest cli to connect", ["suggest"]),
    ("agent_hub", "unify shared mcp into agents", ["sync", "--unify"]),
    ("agent_hub", "launch hermes", ["launch", "hermes"]),
    ("docker_status", "is docker running", ["health"]),
    ("mcp_manager", "mcp doctor", ["doctor"]),
    ("mcp_manager", "install arka mcp for claude", ["install", "--agent", "claude"]),
    ("edit_guard", "edit guard list", ["list"]),
    ("service_autostart", "show autostart services", ["list"]),
    ("local_image_gen", "generate image locally of a forest", ["generate", "a forest"]),
]


@pytest.mark.parametrize("phrase,expected", SYMBOLIC_NL_CASES)
def test_symbolic_route_cross_platform(phrase: str, expected: str) -> None:
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route(phrase)
    assert result is not None, f"no route for {phrase!r}"
    skill = result.skill.strip()
    if skill.startswith("image generate "):
        assert skill == expected, f"phrase={phrase!r} got={skill!r} expected={expected!r}"
        return
    assert skill == expected or skill.startswith(expected.split()[0] + " "), (
        f"phrase={phrase!r} got={skill!r} expected={expected!r}"
    )


@pytest.mark.parametrize("phrase,expected", SYMBOLIC_NL_CASES)
def test_route_preview_cross_platform(phrase: str, expected: str) -> None:
    with redirect_stderr(io.StringIO()):
        preview = route_preview(phrase)
    assert preview is not None, f"no preview for {phrase!r}"
    assert preview.skill.strip().startswith(expected.split()[0])


@pytest.mark.parametrize("module,phrase,argv", MODULE_NL_CASES)
def test_module_nl_to_argv(module: str, phrase: str, argv: list[str]) -> None:
    if module == "cli_connector":
        from arka.integrations.cli_connector import nl_to_argv
    elif module == "agent_hub":
        from arka.integrations.agent_hub import nl_to_argv
    elif module == "mcp_manager":
        from arka.integrations.mcp_manager import nl_to_argv
    elif module == "edit_guard":
        from arka.core.edit_guard import nl_to_argv
    elif module == "service_autostart":
        from arka.integrations.service_autostart import nl_to_argv
    elif module == "docker_status":
        from arka.integrations.docker_status import route_command

        parts = route_command(phrase).split()
        assert parts[0] == "docker_status"
        assert parts[1:] == argv
        return
    elif module == "local_image_gen":
        from arka.agent.local_image_gen import nl_to_argv
    else:
        pytest.skip(f"unknown module {module}")
    assert nl_to_argv(phrase) == argv


def test_docker_status_route_command_cross_platform() -> None:
    from arka.integrations.docker_status import route_command

    assert route_command("what containers are running") == "docker_status ps"
    assert route_command("is docker running") == "docker_status health"


def test_cli_route_command_smoke(monkeypatch, capsys) -> None:
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("ROUTE_MODE", "symbolic_only")
    assert cli.main(["route", "connect shared context"]) == 0
    out = capsys.readouterr().out
    assert "connector" in out


@pytest.mark.parametrize("platform_name", ["darwin", "win32", "linux"])
def test_nl_routing_has_no_platform_specific_paths(platform_name: str) -> None:
    """Routing modules must not hardcode OS-specific path separators in NL patterns."""
    with mock.patch.object(sys, "platform", platform_name):
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("connect shared context")
    assert result is not None
    assert result.skill.startswith("connector")


def test_route_suggest_cli_not_web_answer() -> None:
    """Regression: connector suggest must not fall through to Gemini web_answer."""
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic"}, clear=False):
        result = route("suggest cli to connect")
    assert result is not None
    assert result.skill == "connector suggest"
    assert result.skill.split()[0] != "web_answer"


def test_route_preview_suggest_cli() -> None:
    preview = route_preview("suggest cli to connect")
    assert preview is not None
    assert preview.skill == "connector suggest"


def test_agent_hub_doc_phrases() -> None:
    """Phrases documented in agent-hub guide should route."""
    phrases = [
        "sync agent hub",
        "shared mcp for agents",
        "detect agent hub configs",
    ]
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        for phrase in phrases:
            result = route(phrase)
            assert result is not None, phrase
            assert result.skill.startswith("agent_hub")
