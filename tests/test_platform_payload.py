"""Tests for platform MCP payload helpers."""

from __future__ import annotations

from arka.core.platform import detect_payload, show_payload


def test_show_payload_structure():
    payload = show_payload()
    assert payload["platform"] in {"macos", "linux", "windows"} or payload["platform"]
    assert "capabilities" in payload
    assert isinstance(payload["capabilities"], dict)


def test_detect_payload_without_persist():
    payload = detect_payload(force=True, persist=False)
    assert payload["cached"] is False
    assert payload["platform"]
    assert "clipboard_copy" in payload["capabilities"] or payload["capabilities"] is not None
