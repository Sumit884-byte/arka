import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "argv, expected",
    [
        (("--version",), "arka "),
        (("help",), "Cross-platform AI agent"),
        (("plugin", "doctor"), "Plugins checked:"),
        (("background", "agent", "tasks"), "Arka background processes"),
    ],
)
def test_cli_offline_smoke(monkeypatch, capsys, argv, expected):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", "/tmp/arka-smoke-config")
    monkeypatch.setenv("CACHE_DIR", "/tmp/arka-smoke-cache")
    assert cli.main(list(argv)) == 0
    assert expected in capsys.readouterr().out


def test_cli_signoz_setup_routes_to_python_cli(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    code = cli.main(["signoz", "setup", "--check-only"])
    captured = capsys.readouterr()
    assert "docker_cli" in captured.out
    assert "foundryctl" in captured.out
    assert "integration setup" not in captured.out.lower()
    assert "Paste SIGNOZ_API_KEY" not in captured.out
    assert code in (0, 1)


def test_cli_signoz_status_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["signoz", "status"]) == 0
    output = capsys.readouterr().out
    assert "signoz_setup" in output


def test_route_integration_setup_skips_signoz_cli_commands():
    from arka.routing.symbolic import route_integration_setup

    assert route_integration_setup("signoz setup -y") is None
    assert route_integration_setup("signoz status") is None
    assert route_integration_setup("setup signoz api key") == "integration setup signoz"


def test_route_observability_skips_signoz_cli_commands():
    from arka.routing.symbolic import route_observability

    assert route_observability("signoz setup -y") is None
    assert route_observability("signoz status") is None
    assert route_observability("check signoz observability") == "observability doctor"


def test_cli_route_preview_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["route", "check repo health"]) == 0
    output = capsys.readouterr().out
    assert "repo_health" in output


def test_cli_three_js_model_search_is_portable(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["three_js_model", "search", "satellite", "--no-mcp"]) == 0
    output = capsys.readouterr().out
    assert "Three.js asset search" in output
    assert "Do not invent model URLs" in output


def test_coding_tui_start_and_quit_smoke(monkeypatch, capsys, tmp_path):
    from arka.agent import coding_tui
    from arka.core import code_project

    config = tmp_path / "arka-config"
    config.mkdir()
    monkeypatch.setattr(code_project, "config_dir", lambda: config)
    code_project.clear_project()

    commands = iter(["/help", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    assert "Commands:" in capsys.readouterr().out


def test_plugin_inspect_missing_is_clean(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["plugin", "inspect", "does_not_exist"]) == 1
    assert "Plugin not found" in capsys.readouterr().err


def test_coding_tui_declined_plan_does_not_run(monkeypatch, capsys, tmp_path):
    from arka.agent import coding_tui
    from arka.core import code_project

    config = tmp_path / "arka-config"
    config.mkdir()
    monkeypatch.setattr(code_project, "config_dir", lambda: config)
    code_project.clear_project()

    commands = iter(["/plan inspect the project", "n", "/run", "/quit"])
    called = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr("arka.agent.core.code_agent", lambda *args, **kwargs: called.append(args))
    assert coding_tui.run(str(tmp_path)) == 0
    assert not called
    assert "Plan has not been approved" in capsys.readouterr().out


@pytest.mark.parametrize("route_mode", ["symbolic", "symbolic_only", "ai_only"])
def test_plugin_and_background_smoke_across_route_modes(monkeypatch, capsys, route_mode):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("ROUTE_MODE", route_mode)
    assert cli.main(["plugin", "doctor"]) in (0, 1)
    assert cli.main(["background", "agent", "tasks"]) == 0
    output = capsys.readouterr().out
    assert "Plugins checked:" in output
    assert "background processes" in output.lower()


@pytest.mark.parametrize("hosted", ["0", "1"])
def test_cli_smoke_across_hosted_profiles(monkeypatch, capsys, hosted):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("ARKA_HOSTED_MODE", hosted)
    assert cli.main(["plugin", "doctor"]) in (0, 1)
    assert cli.main(["background", "agent", "tasks"]) == 0
    assert "agent" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("argv, marker", [
    (("mode",), "mode"),
    (("config", "show"), "status"),
])
def test_cli_read_only_diagnostics_smoke(monkeypatch, capsys, argv, marker):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(list(argv)) == 0
    assert marker.lower() in capsys.readouterr().out.lower()


def test_plugin_install_refresh_inspect_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "demo_plugin"
    source.mkdir()
    (source / "skill.json").write_text(
        '{"name":"demo_plugin","type":"python","entry":"run.py","triggers":["demo plugin"]}',
        encoding="utf-8",
    )
    (source / "run.py").write_text("print('ok')\n", encoding="utf-8")
    assert cli.main(["plugin", "install", str(source)]) == 0
    capsys.readouterr()
    assert cli.main(["plugin", "run", "demo_plugin"]) == 0
    capsys.readouterr()
    assert cli.main(["plugin", "inspect", "demo_plugin"]) == 0
    output = capsys.readouterr().out
    assert '"adapter": "arka-manifest"' in output
    assert '"health": "ok"' in output


def test_module_entrypoint_subprocess_smoke(tmp_path):
    env = os.environ.copy()
    env.update({
        "ARKA_AUTO_REFETCH": "0",
        "CONFIG_DIR": str(tmp_path / "config"),
        "CACHE_DIR": str(tmp_path / "cache"),
    })
    proc = subprocess.run(
        [sys.executable, "-m", "arka", "background", "agent", "tasks"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0
    assert "background processes" in proc.stdout.lower()


def test_module_entrypoint_expected_failure_smoke(tmp_path):
    env = os.environ.copy()
    env.update({
        "ARKA_AUTO_REFETCH": "0",
        "CONFIG_DIR": str(tmp_path / "config"),
        "CACHE_DIR": str(tmp_path / "cache"),
    })
    proc = subprocess.run(
        [sys.executable, "-m", "arka", "plugin", "inspect", "missing_plugin"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 1
    assert "Plugin not found" in proc.stderr


def test_background_agent_invalid_usage_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["background", "agent"]) == 1
    assert "Usage: arka background agent tasks" in capsys.readouterr().err


def test_plugins_alias_search_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["plugins", "search", "definitely-not-installed"]) == 0
    assert capsys.readouterr().out == ""


def test_invalid_mode_failure_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["mode", "not-a-mode"]) == 1
    assert "Unknown mode" in capsys.readouterr().err


def test_plugin_help_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["plugin", "--help"]) == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_plugin_invalid_subcommand_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["plugins", "not-a-command"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_plugin_install_missing_source_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    assert cli.main(["plugin", "install", str(tmp_path / "missing")]) == 1
    assert "Not a directory" in capsys.readouterr().err


def test_external_skill_install_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "claude_style"
    source.mkdir()
    (source / "SKILL.md").write_text("# Instructions\n", encoding="utf-8")
    assert cli.main(["plugin", "install", str(source)]) == 0
    capsys.readouterr()
    assert cli.main(["plugin", "inspect", "claude_style"]) == 0
    assert '"adapter": "claude-skill"' in capsys.readouterr().out


def test_mcp_plugin_missing_tool_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    # A missing tool argument must fail locally, before any network call.
    from arka.agent import skills

    monkeypatch.setattr(skills, "get_skill", lambda name: {
        "name": name, "enabled": True, "gate_ok": True, "type": "mcp",
        "entry": "http://127.0.0.1:9/mcp", "root": "",
    })
    assert cli.main(["plugin", "run", "demo_mcp"]) == 1
    assert "requires a tool name" in capsys.readouterr().err


def test_external_prompt_plugin_run_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "prompt_plugin"
    source.mkdir()
    (source / "SKILL.md").write_text("Use the project conventions.\n", encoding="utf-8")
    assert cli.main(["plugin", "install", str(source)]) == 0
    capsys.readouterr()
    assert cli.main(["plugin", "run", "prompt_plugin"]) == 0
    capsys.readouterr()


def test_plugin_run_unknown_is_clean_failure(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["plugin", "run", "missing_plugin"]) == 1
    assert "Unknown or disabled" in capsys.readouterr().err


def test_plugin_doctor_help_smoke(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    assert cli.main(["plugin", "doctor", "--help"]) == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_plugin_list_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "list"]) == 0
    assert "plugin" in capsys.readouterr().out.lower()


def test_plugin_list_names_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "list-names", "--all"]) == 0
    assert capsys.readouterr().err == ""


def test_plugin_fish_sources_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "fish-sources"]) == 0
    assert capsys.readouterr().err == ""


def test_plugin_match_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "match", "what star is Betelgeuse"]) == 0
    assert "astronomy" in capsys.readouterr().out


def test_plugin_voice_ack_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "voice-ack", "what star is Betelgeuse"]) == 0
    assert "sky" in capsys.readouterr().out.lower()


def test_plugin_info_alias_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "info", "missing_plugin"]) == 1
    assert "Plugin not found" in capsys.readouterr().err


def test_plugin_match_no_match_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "match", "an unrelated phrase"]) == 0
    assert capsys.readouterr().out == ""


def test_plugin_voice_ack_no_match_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "voice-ack", "an unrelated phrase"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_plugin_match_case_insensitive_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "match", "WHAT STAR IS BETELGEUSE"]) == 0
    assert "astronomy" in capsys.readouterr().out


def test_plugin_match_preserves_arguments_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "match", "moon phase tonight in Delhi"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("astronomy")
    assert "Delhi" in output


def test_plugin_match_normalizes_whitespace_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "match", "  moon   phase   tonight  "]) == 0
    assert capsys.readouterr().out.startswith("astronomy")


def test_plugin_match_empty_input_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "match", ""]) == 0
    assert capsys.readouterr().out == ""


def test_plugin_voice_ack_empty_input_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "voice-ack", ""]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_plugin_refresh_smoke(monkeypatch, capsys, tmp_path):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["plugin", "refresh"]) == 0
    assert "Skill registry refreshed." in capsys.readouterr().out
