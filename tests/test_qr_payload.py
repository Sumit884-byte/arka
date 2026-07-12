"""Tests for QR MCP payload helpers."""

from __future__ import annotations

import pytest

from arka.integrations.qr_code import ascii_payload


def test_ascii_payload_basic():
    payload = ascii_payload("https://arka.dev")
    assert payload["text"] == "https://arka.dev"
    assert payload["engine"] == "qrcode"
    assert payload["modules"] >= 21
    assert isinstance(payload["ascii"], str)
    assert len(payload["ascii"]) > 10


def test_ascii_payload_requires_text():
    with pytest.raises(ValueError):
        ascii_payload("   ")
