"""Tests for offline textkit utilities."""

from __future__ import annotations

import hashlib

import pytest

from arka.core.textkit import base64_payload, hash_payload, uuid_payload


def test_uuid_v4():
    payload = uuid_payload()
    assert payload["ok"] is True
    assert payload["version"] == 4
    assert len(payload["uuid"]) == 36


def test_uuid_v5_stable():
    a = uuid_payload(version=5, name="https://arka.dev", namespace="url")
    b = uuid_payload(version=5, name="https://arka.dev", namespace="url")
    assert a["uuid"] == b["uuid"]


def test_hash_sha256():
    payload = hash_payload("arka", algorithm="sha256")
    expected = hashlib.sha256(b"arka").hexdigest()
    assert payload["hex"] == expected


def test_base64_roundtrip():
    encoded = base64_payload("hello", action="encode")
    decoded = base64_payload(encoded["result"], action="decode")
    assert decoded["result"] == "hello"


def test_base64_invalid():
    with pytest.raises(ValueError):
        base64_payload("!!!", action="decode")
