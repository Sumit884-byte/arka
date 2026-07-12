"""Tests for offline jsonkit helpers."""

from __future__ import annotations

import pytest

from arka.core.jsonkit import get_payload, minify_payload, pretty_payload, validate_payload


def test_validate_ok_and_bad():
    assert validate_payload('{"a":1}')["valid"] is True
    assert validate_payload("{")["valid"] is False


def test_pretty_and_minify():
    pretty = pretty_payload('{"b":1,"a":2}', indent=2)
    assert '"b": 1' in pretty["json"]
    mini = minify_payload(pretty["json"])
    assert mini["json"] == '{"b":1,"a":2}'


def test_get_nested_path():
    payload = get_payload('{"a":{"b":[10,20]}}', "a.b[1]")
    assert payload["value"] == 20


def test_get_missing_key():
    with pytest.raises(ValueError):
        get_payload('{"a":1}', "missing")
