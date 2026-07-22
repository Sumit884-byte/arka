"""Tests for SigNoz dashboard install helpers."""

from __future__ import annotations

from pathlib import Path
from unittest import mock


def test_bundled_dashboard_loads():
    from arka.telemetry.signoz_dashboards import (
        dashboard_title,
        list_dashboard_templates,
        load_dashboard,
    )

    templates = list_dashboard_templates()
    assert "arka-agent-observability" in templates
    payload = load_dashboard("arka-agent-observability")
    assert dashboard_title(payload) == "Arka Agent Observability"
    assert len(payload.get("widgets") or []) >= 10
    widget_ids = {widget.get("id") for widget in payload.get("widgets") or []}
    assert "skill-dispatch-latency" in widget_ids
    assert "llm-failover-events" in widget_ids
    assert "routing-decisions" in widget_ids
    assert "llm-model-mix" in widget_ids
    assert "correlated-logs" in widget_ids

    widgets = {widget["id"]: widget for widget in payload.get("widgets") or []}
    routing_pie = widgets["routing-decisions"]
    routing_group_by = routing_pie["query"]["builder"]["queryData"][0]["groupBy"]
    assert [item["key"] for item in routing_group_by] == ["arka.route.decision"]
    assert routing_pie["panelTypes"] == "bar"
    assert routing_pie["query"]["builder"]["queryData"][0]["legend"] == "{{arka.route.decision}}"

    logs_panel = widgets["correlated-logs"]
    logs_query = logs_panel["query"]["builder"]["queryData"][0]
    assert logs_query["aggregateOperator"] == "noop"
    assert logs_query["groupBy"] == []
    assert logs_query.get("pageSize") == 100
    assert logs_panel.get("selectedLogFields")


def test_normalize_dashboard_fills_builder_defaults():
    from arka.telemetry.signoz_dashboards import normalize_dashboard

    payload = normalize_dashboard(
        {
            "widgets": [
                {
                    "panelTypes": "list",
                    "query": {
                        "builder": {
                            "queryData": [
                                {
                                    "dataSource": "logs",
                                    "aggregateOperator": "noop",
                                    "limit": 50,
                                }
                            ]
                        }
                    },
                }
            ]
        }
    )
    row = payload["widgets"][0]["query"]["builder"]["queryData"][0]
    assert row["legend"] == ""
    assert row["pageSize"] == 50
    assert row["offset"] == 0
    assert payload["widgets"][0]["selectedLogFields"]


def test_install_dashboard_dry_run():
    from arka.telemetry.signoz_dashboards import install_dashboard

    result = install_dashboard("arka-agent-observability", dry_run=True)
    assert result["dry_run"] is True
    assert result["widgets"] >= 10


def test_install_dashboard_skips_existing():
    from arka.telemetry.signoz_dashboards import install_dashboard

    with mock.patch(
        "arka.telemetry.signoz_dashboards.find_existing_dashboard",
        return_value={"id": "dash-1", "title": "Arka Agent Observability"},
    ):
        result = install_dashboard("arka-agent-observability", api_key="test-key")
    assert result["skipped"] is True
    assert result["id"] == "dash-1"


def test_install_dashboard_posts_payload():
    from arka.telemetry.signoz_dashboards import install_dashboard, load_dashboard

    payload = load_dashboard("arka-agent-observability")
    captured: dict[str, object] = {}

    def fake_request(method, path, *, payload=None, api_key=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return 201, {"data": {"id": "new-dash", "title": payload.get("title")}}

    with (
        mock.patch("arka.telemetry.signoz_dashboards.find_existing_dashboard", return_value=None),
        mock.patch("arka.telemetry.signoz_dashboards._request", side_effect=fake_request),
    ):
        result = install_dashboard("arka-agent-observability", api_key="test-key")

    assert result["created"] is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/dashboards"
    assert captured["payload"] == payload


def test_install_observability_bundle_dry_run():
    from arka.telemetry.signoz_dashboards import install_observability_bundle

    with mock.patch(
        "arka.telemetry.signoz_alerts.create_alert_rule",
        side_effect=lambda slug, **kwargs: {"dry_run": True, "alert": slug},
    ):
        bundle = install_observability_bundle(dry_run=True, alerts=True)
    assert bundle["dashboard"]["dry_run"] is True
    assert len(bundle["alerts"]) == 3


def test_cmd_dashboard_install_dry_run(capsys):
    from argparse import Namespace

    from arka.telemetry.signoz_dashboards import cmd_dashboard_install

    code = cmd_dashboard_install(
        Namespace(name="arka-agent-observability", dry_run=True, replace=False, alerts=False, mcp=False)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "dry_run" in out


def test_cmd_dashboard_list_bundled(capsys):
    from argparse import Namespace

    from arka.telemetry.signoz_dashboards import cmd_dashboard_list

    with mock.patch("arka.telemetry.signoz_dashboards.signoz_api_key", return_value=""):
        code = cmd_dashboard_list(Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "arka-agent-observability" in out


def test_signoz_cli_dashboard_subcommand_registered():
    from arka.telemetry.signoz_cli import main

    with mock.patch("arka.telemetry.signoz_dashboards.cmd_dashboard_install", return_value=0) as install_mock:
        code = main(["dashboard", "install", "--dry-run"])
    assert code == 0
    install_mock.assert_called_once()


def test_self_build_observability_plan_only(tmp_path):
    from arka.agent import self_build

    root = Path(__file__).resolve().parents[1]
    audit = self_build.McpAudit(
        scan={"count": 1},
        run={"ok": True, "passed": 1, "failed": 0, "skipped": 0, "results": []},
    )

    with (
        mock.patch("arka.agent.self_build.self_build_root", return_value=tmp_path),
        mock.patch("arka.agent.self_improve.ensure_arka_project", return_value=root),
        mock.patch("arka.agent.self_build.mcp_audit", return_value=audit),
        mock.patch(
            "arka.agent.self_build.apply_observability_improvements",
            return_value=(0, {"planned": True}),
        ) as apply_mock,
    ):
        code = self_build.run_self_build("observability", apply=False)

    assert code == 0
    apply_mock.assert_called_once_with(apply=False, use_mcp=False, with_alerts=True)


def test_is_observability_target():
    from arka.agent.self_build import _is_observability_target

    assert _is_observability_target("observability")
    assert _is_observability_target("dashboard")
    assert _is_observability_target("signoz dashboards")
    assert not _is_observability_target("routing")
