import json

import pytest


def test_webhook_cli_status(monkeypatch, capsys, tmp_path):
    from arka import cli
    from arka.integrations import webhook

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(webhook, "PID_PATH", tmp_path / "arka_webhook.pid")
    monkeypatch.setenv("WEBHOOK_ENABLED", "1")
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-token")

    assert cli.main(["webhook", "status"]) == 0
    out = capsys.readouterr().out
    assert "Webhook: on" in out
    assert "8767" in out
    assert "Token configured: True" in out


def test_webhook_cli_status_json(monkeypatch, capsys, tmp_path):
    from arka import cli
    from arka.integrations import webhook

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(webhook, "PID_PATH", tmp_path / "arka_webhook.pid")
    monkeypatch.setenv("WEBHOOK_ENABLED", "0")

    assert cli.main(["webhook", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["port"] == 8767
    assert "inbox_url" in data


def test_webhook_dispatch_status(monkeypatch, capsys, tmp_path):
    from arka.dispatch import run_skill
    from arka.integrations import webhook

    monkeypatch.setattr(webhook, "PID_PATH", tmp_path / "arka_webhook.pid")
    monkeypatch.setenv("WEBHOOK_ENABLED", "1")
    monkeypatch.setenv("WEBHOOK_TOKEN", "tok")

    assert run_skill("webhook status") == 0
    out = capsys.readouterr().out
    assert "Listen:" in out


def test_n8n_cli_status(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("API_URL", "http://example.test:8765")
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setenv("WEBHOOK_ENABLED", "1")

    assert cli.main(["n8n", "status"]) == 0
    out = capsys.readouterr().out
    assert "Arka n8n integration" in out
    assert "http://example.test:8765/v1/agent" in out
    assert "8767" in out


def test_n8n_cli_example_json(monkeypatch, capsys):
    from arka import cli

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setenv("REMOTE_TOKEN", "secret")

    assert cli.main(["n8n", "example", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "n8n_http_request_agent" in data
    assert "n8n_http_request_inbox" in data
    assert "/v1/agent" in data["curl"]
    assert "/v1/inbox" in data["curl"]


def test_n8n_status_without_token_returns_nonzero(monkeypatch, capsys):
    from arka.integrations import n8n

    monkeypatch.setattr(n8n, "_backend_token", lambda: "")
    monkeypatch.setenv("WEBHOOK_ENABLED", "0")

    assert n8n.main(["status"]) == 1
    out = capsys.readouterr().out
    assert "Token configured: no" in out


@pytest.mark.parametrize(
    "text, expected",
    [
        ("n8n status", "n8n status"),
        ("arka n8n example", "n8n example"),
        ("connect arka to n8n", "n8n status"),
        ("n8n workflow automation", "n8n status"),
    ],
)
def test_route_n8n(text, expected):
    from arka.routing.symbolic import route_n8n

    assert route_n8n(text) == expected


def test_route_n8n_ignores_unrelated(text="check repo health"):
    from arka.routing.symbolic import route_n8n

    assert route_n8n(text) is None
