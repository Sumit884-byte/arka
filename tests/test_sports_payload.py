"""Tests for sports MCP payload helpers."""

from __future__ import annotations

from arka.integrations.sports import leagues_payload, scores_payload


def test_leagues_payload_includes_ipl():
    payload = leagues_payload()
    assert payload["count"] >= 5
    labels = {row["label"] for row in payload["leagues"]}
    assert "IPL" in labels
    assert "NFL" in labels


def test_scores_payload_unknown_league():
    payload = scores_payload("not-a-real-league-xyz")
    # resolve_leagues may fall back to defaults; still structured
    assert "ok" in payload
    assert "events" in payload
    assert isinstance(payload["leagues"], list)
