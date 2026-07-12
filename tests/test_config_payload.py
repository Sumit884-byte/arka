"""Tests for config_backup MCP payload helpers."""

from __future__ import annotations

from arka.core.config_backup import list_payload, path_payload


def test_list_payload_structure():
    payload = list_payload()
    assert "config_dir" in payload
    assert "cache_dir" in payload
    assert isinstance(payload["entries"], list)
    assert payload["count"] == len(payload["entries"])


def test_path_payload_structure():
    payload = path_payload()
    assert payload["config_dir"]
    assert "export_snippet" in payload
    assert "ARKA_CONFIG_DIR" in payload["export_snippet"]
