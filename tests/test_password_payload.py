"""Tests for password generate MCP payload."""

from __future__ import annotations

from arka.integrations.password_vault import generate_payload


def test_generate_payload_defaults():
    payload = generate_payload()
    assert payload["ok"] is True
    assert payload["stored"] is False
    assert payload["length"] == 16
    assert any(c.islower() for c in payload["password"])
    assert any(c.isupper() for c in payload["password"])
    assert any(c.isdigit() for c in payload["password"])


def test_generate_payload_length_and_no_symbols():
    payload = generate_payload(length=20, symbols=False)
    assert payload["length"] == 20
    assert payload["symbols"] is False
