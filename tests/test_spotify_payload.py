"""Tests for Spotify MCP search payload."""

from __future__ import annotations

import pytest

from arka.integrations import spotify as spotify_mod


def test_search_payload_found(monkeypatch):
    monkeypatch.setattr(
        spotify_mod,
        "search_track",
        lambda query: {
            "id": "xyz",
            "name": "Track",
            "artist": "Band",
            "uri": "spotify:track:xyz",
        },
    )
    monkeypatch.setattr(
        spotify_mod,
        "_spotify_web_url",
        lambda uri: "https://open.spotify.com/track/xyz",
    )
    payload = spotify_mod.search_payload("Track Band")
    assert payload["ok"] is True
    assert payload["track"]["id"] == "xyz"
    assert "open.spotify.com" in payload["track"]["url"]


def test_search_payload_requires_query():
    with pytest.raises(ValueError):
        spotify_mod.search_payload("  ")


def test_search_payload_not_found(monkeypatch):
    monkeypatch.setattr(spotify_mod, "search_track", lambda query: None)
    payload = spotify_mod.search_payload("obscure song")
    assert payload["found"] is False
