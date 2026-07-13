"""Tests for Sakana Fugu orchestrator integration."""

from __future__ import annotations

from unittest import mock


from arka.integrations import fugu as fg


def test_sakana_provider_registered():
    from arka.llm.providers import get_provider

    spec = get_provider("sakana")
    assert spec is not None
    assert spec.slug == "sakana"
    assert spec.default_model == "fugu"
    assert "fugu-ultra" in spec.default_models
    assert spec.default_base_url == "https://api.sakana.ai/v1"


def test_fugu_provider_alias():
    from arka.llm.providers import get_provider

    assert get_provider("fugu") is get_provider("sakana")


def test_sakana_configured_with_key(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "sk-test")
    assert fg.sakana_configured() is True


def test_sakana_not_configured(monkeypatch):
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    with mock.patch("arka.llm.api_keys.provider_has_keys", return_value=False):
        assert fg.sakana_configured() is False


def test_wants_fugu_variants():
    assert fg.wants_fugu("arka fugu status")
    assert fg.wants_fugu("fugu explain TLS")
    assert fg.wants_fugu("ask fugu to summarize this")
    assert not fg.wants_fugu("explain TLS")


def test_route_command_prompt():
    assert fg.route_command("arka fugu explain TLS") == "fugu 'explain TLS'"
    assert fg.route_command("fugu status") == "fugu status"
    assert fg.route_command("ask fugu to plan a migration") == "fugu 'plan a migration'"


def test_nl_to_argv():
    assert fg.nl_to_argv("fugu status") == ["status"]
    assert fg.nl_to_argv("fugu sync") == ["sync"]


def test_resolve_model_default():
    assert fg._resolve_model(["hello", "world"]) == ("fugu", ["hello", "world"])


def test_resolve_model_ultra():
    assert fg._resolve_model(["ultra", "deep", "task"]) == ("fugu-ultra", ["deep", "task"])


def test_fugu_complete_sets_fallback(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "sk-test")
    captured: list[str] = []

    def fake_complete(system, user, **kwargs):
        import os

        captured.append(os.environ.get("LLM_FALLBACK", ""))
        return "ok"

    with mock.patch("arka.llm.cli.llm_complete", side_effect=fake_complete):
        result = fg.fugu_complete("hi", model="fugu-ultra")

    assert result == "ok"
    assert captured == ["sakana:fugu-ultra"]


def test_cmd_status_configured(capsys, monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "sk-test")
    rc = fg.cmd_status(mock.Mock())
    out = capsys.readouterr().out
    assert rc == 0
    assert "fugu\tconfigured" in out
    assert "provider\tsakana" in out


def test_cmd_status_not_configured(capsys, monkeypatch):
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    with mock.patch("arka.llm.api_keys.provider_has_keys", return_value=False):
        rc = fg.cmd_status(mock.Mock())
    out = capsys.readouterr().out
    assert rc == 1
    assert "fugu\tnot_configured" in out


def test_main_missing_key(capsys, monkeypatch):
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    with mock.patch("arka.llm.api_keys.provider_has_keys", return_value=False):
        rc = fg.main(["explain", "TLS"])
    assert rc == 1
    assert "Sakana Fugu is not configured" in capsys.readouterr().err


def test_main_prompt(capsys, monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "sk-test")
    with mock.patch("arka.integrations.fugu.fugu_complete", return_value="answer"):
        rc = fg.main(["explain", "TLS"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "answer"


def test_main_ultra_prompt(capsys, monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "sk-test")
    with mock.patch("arka.integrations.fugu.fugu_complete", return_value="deep") as complete:
        rc = fg.main(["ultra", "design", "system"])
    assert rc == 0
    complete.assert_called_once()
    assert complete.call_args.kwargs["model"] == "fugu-ultra"
    assert capsys.readouterr().out.strip() == "deep"


def test_route_fugu_symbolic():
    from arka.routing.symbolic import route_fugu

    assert route_fugu("fugu status") == "fugu status"
    assert route_fugu("explain TLS") is None


def test_agent_hub_fugu_entry():
    from arka.integrations.agent_hub import AGENTS, _resolve_agent

    assert "fugu" in AGENTS
    assert AGENTS["fugu"]["name"] == "Sakana Fugu"
    assert _resolve_agent("sakana fugu")[0] == "fugu"
    assert "~/.codex/mcp.json" in AGENTS["fugu"]["mcp_paths"][0]


def test_teams_resolve_sakana_provider():
    from arka.teams.resolve import resolve_member
    from arka.teams.schema import TeamMember

    member = TeamMember(role="lead", kind="provider", id="sakana")
    resolved = resolve_member(member)
    assert resolved.provider == "sakana"
    assert resolved.model_id == "fugu"


def test_teams_resolve_fugu_model():
    from arka.teams.resolve import resolve_member
    from arka.teams.schema import TeamMember

    member = TeamMember(role="lead", kind="model", id="fugu-ultra", provider="sakana")
    resolved = resolve_member(member)
    assert resolved.provider == "sakana"
    assert resolved.model_id == "fugu-ultra"
