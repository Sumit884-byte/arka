"""Tests for calendar MCP payload helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from arka.integrations import macos_calendar as cal_mod


def test_today_payload_serializes_events(monkeypatch):
    start = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 12, 10, 30, tzinfo=timezone.utc)

    def fake_fetch():
        return (
            [
                {
                    "summary": "Demo",
                    "calendar": "Home",
                    "when": "when",
                    "start": start,
                    "end": end,
                    "source": "macos",
                }
            ],
            None,
        )

    monkeypatch.setattr(cal_mod, "fetch_today_events", fake_fetch)
    monkeypatch.setattr(cal_mod, "_available", lambda: True)
    payload = cal_mod.today_payload()
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["events"][0]["start"] == start.isoformat()


def test_today_payload_reports_error(monkeypatch):
    monkeypatch.setattr(cal_mod, "fetch_today_events", lambda: ([], "macOS only"))
    monkeypatch.setattr(cal_mod, "_available", lambda: False)
    payload = cal_mod.today_payload()
    assert payload["ok"] is False
    assert payload["error"] == "macOS only"
