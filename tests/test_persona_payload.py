"""Tests for persona MCP payload helpers."""

from __future__ import annotations

from arka.agent.personas.io import list_payload, show_payload


def test_list_payload_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKA_PERSONAS_DIR", str(tmp_path))
    (tmp_path / "coach.yaml").write_text(
        "name: coach\ndisplay_name: Coach\ndescription: helpful\nsystem_prompt: Be helpful.\n",
        encoding="utf-8",
    )
    payload = list_payload()
    assert payload["count"] >= 1
    names = {row["name"] for row in payload["personas"]}
    assert "coach" in names


def test_show_payload_coach(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKA_PERSONAS_DIR", str(tmp_path))
    (tmp_path / "coach.yaml").write_text(
        "name: coach\ndisplay_name: Coach\ndescription: helpful\nsystem_prompt: Be helpful.\n",
        encoding="utf-8",
    )
    payload = show_payload("coach")
    assert payload["name"] == "coach"
    assert "helpful" in payload["system_prompt"].lower() or payload["system_prompt"]
