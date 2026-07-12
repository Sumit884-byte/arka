"""Tests for personalize MCP payload helpers."""

from __future__ import annotations

from arka.core.personalize import quickstart_payload, recommend_payload, status_payload


def test_status_payload_structure(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.core.personalize.profile_path", lambda: tmp_path / "personalize.json")
    payload = status_payload()
    assert "interests" in payload
    assert "experience" in payload
    assert "summary" in payload


def test_recommend_payload_structure(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.core.personalize.profile_path", lambda: tmp_path / "personalize.json")
    payload = recommend_payload(limit=5)
    assert "skills" in payload
    assert isinstance(payload["skills"], list)


def test_quickstart_payload_has_steps(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.core.personalize.profile_path", lambda: tmp_path / "personalize.json")
    payload = quickstart_payload()
    assert len(payload["steps"]) >= 4
