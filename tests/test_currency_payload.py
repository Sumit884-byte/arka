"""Tests for currency MCP payload helpers."""

from __future__ import annotations

from decimal import Decimal

from arka.integrations.currency import convert_payload


def test_convert_payload_identity():
    payload = convert_payload(Decimal("10"), "USD", "usd")
    assert payload["from"] == "USD"
    assert payload["to"] == "USD"
    assert payload["rate"] == "1"
    assert payload["result"] == "10"
    assert payload["source"] == "identity"
