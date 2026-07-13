"""Tests for disk MCP payload helpers."""

from __future__ import annotations


from arka.core.disk import breakdown_payload, usage_payload


def test_usage_payload_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.core.disk.HOME", tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    payload = usage_payload(tmp_path)
    assert payload["path"] == str(tmp_path.resolve())
    assert payload["total"] != "?"


def test_breakdown_payload_empty_home(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.core.disk.HOME", tmp_path)
    payload = breakdown_payload(tmp_path)
    assert payload["home"] == str(tmp_path.resolve())
    assert "categories" in payload
    assert isinstance(payload["categories"], list)
