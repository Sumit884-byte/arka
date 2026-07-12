"""Tests for github_repo MCP payload helpers."""

from __future__ import annotations

from arka.agent.github_repo import resolve_repo_payload


def test_resolve_repo_payload_owner_repo():
    payload = resolve_repo_payload("https://github.com/Sumit884-byte/arka")
    assert payload["ok"] is True
    assert payload["owner"] == "Sumit884-byte"
    assert payload["repo"] == "arka"


def test_resolve_repo_payload_invalid():
    payload = resolve_repo_payload("not a repo at all")
    assert payload["ok"] is False
