"""Tests for email alert classification, delivery, and MCP integration."""

from __future__ import annotations

import json
from unittest import mock

import pytest


def test_classify_event_categories():
    from arka.integrations.email_alert import classify_event

    assert classify_event("You were selected into the cohort") == "selection"
    assert classify_event("500 credits awarded to your account") == "credits"
    assert classify_event("Devpost hackathon submission deadline") == "hackathon"
    assert classify_event("Final exam on Friday") == "studies"
    assert classify_event("Payment failed on your subscription") == "billing"
    assert classify_event("CI failed on main branch") == "ci"
    assert classify_event("Something random") == "general"


def test_auto_alert_enabled_default(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.delenv("ALERT_AUTO", raising=False)
    assert alerts.auto_alert_enabled() is True


def test_auto_alert_disabled_by_env(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_AUTO", "0")
    assert alerts.auto_alert_enabled() is False


def test_auto_alert_disabled_by_config(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(alerts, "_config_path", lambda: cfg_path)
    cfg_path.write_text(json.dumps({"auto": False}), encoding="utf-8")
    monkeypatch.delenv("ALERT_AUTO", raising=False)
    assert alerts.auto_alert_enabled() is False


def test_detect_auto_alert_patterns():
    from arka.integrations.email_alert import detect_auto_alert

    assert detect_auto_alert("You were accepted into the summer cohort")["category"] == "selection"
    assert detect_auto_alert("500 credits awarded to your account")["category"] == "credits"
    assert detect_auto_alert("Devpost hackathon submission deadline is Friday")["category"] == "hackathon"
    assert detect_auto_alert("Final exam due tomorrow at 9am")["category"] == "studies"
    assert detect_auto_alert("Invoice #1234 is ready")["category"] == "billing"
    assert detect_auto_alert("CI failed on pull request #42")["category"] == "ci"
    assert detect_auto_alert("What is a hackathon?") is None
    assert detect_auto_alert("search hackathon events") is None


def test_maybe_auto_alert_sends_when_enabled(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_EMAIL_TO", "user@example.com")
    monkeypatch.delenv("ALERT_AUTO", raising=False)

    with mock.patch("arka.integrations.email_send.send_email", return_value={"ok": True, "provider": "resend"}):
        with mock.patch("arka.integrations.remind._notify", lambda *_a, **_k: None):
            row = alerts.maybe_auto_alert("You got hired at Acme Corp", quiet=True)

    assert row is not None
    assert row["category"] == "selection"
    assert row.get("source") == "auto" or "email" in row.get("channels", [])


def test_maybe_auto_alert_skips_when_disabled(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_AUTO", "0")

    row = alerts.maybe_auto_alert("You were accepted into YC", quiet=True)
    assert row is None
    assert alerts.list_history() == []


def test_maybe_auto_alert_deduplicates(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_EMAIL_TO", "user@example.com")
    monkeypatch.delenv("ALERT_AUTO", raising=False)

    with mock.patch("arka.integrations.email_send.send_email", return_value={"ok": True, "provider": "resend"}):
        with mock.patch("arka.integrations.remind._notify", lambda *_a, **_k: None):
            first = alerts.maybe_auto_alert("Payment failed on subscription", quiet=True)
            second = alerts.maybe_auto_alert("Payment failed on subscription", quiet=True)

    assert first is not None
    assert second is None
    assert len(alerts.list_history()) == 1


def test_status_payload_includes_auto(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_EMAIL_TO", "user@example.com")
    payload = alerts.status_payload()
    assert payload["auto"] is True
    assert "selection" in payload["active_categories"]


def test_set_auto_alert_config(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(alerts, "_config_path", lambda: cfg_path)
    alerts.set_auto_alert(False)
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["auto"] is False
    alerts.set_auto_alert(True)
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["auto"] is True


def test_send_alert_email_and_os(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_EMAIL_TO", "user@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    os_calls: list[tuple[str, str]] = []

    def fake_notify(title, body):
        os_calls.append((title, body))

    with mock.patch("arka.integrations.email_send.send_email", return_value={"ok": True, "provider": "resend"}):
        with mock.patch("arka.integrations.remind._notify", fake_notify):
            row = alerts.send_alert("Selected", "You got into the program", category="selection")

    assert row["ok"] is True
    assert "email" in row["channels"]
    assert "os" in row["channels"]
    assert os_calls
    history = alerts.list_history(limit=5)
    assert len(history) == 1
    assert history[0]["category"] == "selection"


def test_send_alert_skips_disabled_category(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts

    monkeypatch.setattr(alerts, "_history_path", lambda: tmp_path / "history.json")
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(alerts, "_config_path", lambda: cfg_path)
    cfg_path.write_text(
        json.dumps({"to": "user@example.com", "categories": {"credits": False}}),
        encoding="utf-8",
    )

    row = alerts.send_alert("Credits", "You got 100 credits", category="credits")
    assert row["skipped"] is True
    assert alerts.list_history() == []


def test_schedule_alert_sets_email_flag(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts
    from arka.integrations import remind

    monkeypatch.setattr(remind, "_reminders_file", lambda: tmp_path / "reminders.json")
    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_EMAIL_TO", "user@example.com")
    monkeypatch.setattr(remind, "start_daemon", lambda: 0)

    row, err = alerts.schedule_alert("Hackathon deadline", in_spec="2h", category="hackathon", start=False)
    assert err is None
    assert row is not None
    assert row["email"] is True
    assert row["category"] == "hackathon"

    stored = json.loads((tmp_path / "reminders.json").read_text(encoding="utf-8"))
    assert stored[0]["email"] is True
    assert stored[0]["category"] == "hackathon"


def test_nl_to_argv_and_route():
    from arka.integrations.email_alert import nl_to_argv, route_command

    assert nl_to_argv("email alert I was selected into YC") == ["send", "email alert I was selected into YC"]
    assert nl_to_argv("list my email alerts") == ["list"]
    assert nl_to_argv("test email alert") == ["test"]
    route = route_command("notify me by email I got 50 credits")
    assert route and route.startswith("alert send")


def test_handle_arka_alert_send_and_status(tmp_path, monkeypatch):
    from arka.integrations import email_alert as alerts
    from arka.integrations.mcp_server import _handle_arka_alert

    monkeypatch.setattr(alerts, "_history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(alerts, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("ALERT_EMAIL_TO", "user@example.com")

    status = json.loads(_handle_arka_alert({"action": "status"}))
    assert status["to"] == "user@example.com"

    with mock.patch("arka.integrations.email_send.send_email", return_value={"ok": True, "provider": "resend"}):
        with mock.patch("arka.integrations.remind._notify", lambda *_a, **_k: None):
            sent = json.loads(
                _handle_arka_alert(
                    {
                        "action": "send",
                        "text": "Accepted to hackathon",
                        "category": "selection",
                    }
                )
            )
    assert sent["category"] == "selection"
    assert "email" in sent["channels"]


def test_email_send_resend(monkeypatch):
    from arka.integrations.email_send import send_email

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    captured: dict = {}

    def fake_http(url, *, headers, payload, timeout=30.0):
        captured["url"] = url
        captured["payload"] = payload
        return {"id": "msg_123"}

    with mock.patch("arka.integrations.email_send._http_json", fake_http):
        result = send_email("user@example.com", "Hello", "Body text")

    assert result["provider"] == "resend"
    assert captured["payload"]["to"] == ["user@example.com"]


def test_email_send_requires_provider(monkeypatch):
    from arka.integrations.email_send import EmailSendError, send_email

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with pytest.raises(EmailSendError):
        send_email("user@example.com", "Hello", "Body")
