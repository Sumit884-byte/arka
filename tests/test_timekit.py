"""Tests for offline timekit helpers."""

from __future__ import annotations

import pytest

from arka.core.timekit import convert_payload, now_payload, relative_payload


def test_now_payload_utc():
    payload = now_payload(tz="UTC")
    assert payload["ok"] is True
    assert payload["timezone"] == "UTC"
    assert "T" in payload["iso"]


def test_convert_payload_utc_to_kolkata():
    payload = convert_payload("2026-07-12T10:00:00+00:00", to_tz="Asia/Kolkata")
    assert payload["to_timezone"] == "Asia/Kolkata"
    assert payload["iso"].endswith("+05:30")


def test_relative_payload_hours():
    payload = relative_payload(
        "2h",
        tz="UTC",
        base="2026-07-12T10:00:00+00:00",
    )
    assert payload["unit"] == "hours"
    assert payload["iso"] == "2026-07-12T12:00:00+00:00"


def test_relative_invalid():
    with pytest.raises(ValueError):
        relative_payload("soon")
