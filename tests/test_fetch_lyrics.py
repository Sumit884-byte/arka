"""Tests for fetch_lyrics — parsing, routing, MCP, and mocked providers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.integrations.mcp_server import _handle_arka_fetch_lyrics
from arka.media.fetch_lyrics import (
    fetch_lyrics,
    fetch_lyrics_result,
    nl_to_argv,
    parse_song_query,
    translate_lyrics,
)
from arka.routing.symbolic import route_fetch_lyrics


class TestParseSongQuery:
    def test_title_by_artist(self) -> None:
        artist, title = parse_song_query("Bohemian Rhapsody by Queen")
        assert artist == "Queen"
        assert title == "Bohemian Rhapsody"

    def test_dash_separator(self) -> None:
        artist, title = parse_song_query("Queen - Bohemian Rhapsody")
        assert artist == "Queen"
        assert title == "Bohemian Rhapsody"


class TestFetchLyricsRouting:
    def test_route_fetch(self) -> None:
        routed = route_fetch_lyrics("fetch lyrics for Bohemian Rhapsody by Queen")
        assert routed is not None
        assert routed.startswith("fetch_lyrics fetch ")
        assert "Queen" in routed

    def test_route_translate_and_generate(self) -> None:
        routed = route_fetch_lyrics(
            "translate lyrics of Shape of You by Ed Sheeran to hindi and generate a new song"
        )
        assert routed is not None
        assert "translate" in routed
        assert "--target" in routed
        assert "hindi" in routed
        assert "--generate" in routed

    def test_nl_to_argv_fetch(self) -> None:
        argv = nl_to_argv("get lyrics for Blinding Lights by The Weeknd")
        assert argv == ["fetch", "The Weeknd", "Blinding Lights"]


def test_fetch_lyrics_lrclib_mocked() -> None:
    hit = {
        "artistName": "Queen",
        "trackName": "Bohemian Rhapsody",
        "plainLyrics": "Is this the real life?",
        "albumName": "A Night at the Opera",
        "duration": 355,
    }
    with mock.patch("arka.media.fetch_lyrics.search_lrclib", return_value=hit):
        result = fetch_lyrics("Queen", "Bohemian Rhapsody")
    assert result["provider"] == "lrclib"
    assert "real life" in str(result["lyrics"])
    assert result["artist"] == "Queen"


def test_fetch_lyrics_ovh_fallback_mocked() -> None:
    with mock.patch("arka.media.fetch_lyrics.search_lrclib", return_value=None), mock.patch(
        "arka.media.fetch_lyrics.fetch_lyrics_ovh",
        return_value="Fallback lyrics line",
    ):
        result = fetch_lyrics("Artist", "Song")
    assert result["provider"] == "lyrics.ovh"
    assert result["lyrics"] == "Fallback lyrics line"


def test_translate_lyrics_mocked() -> None:
    with mock.patch(
        "arka.media.fetch_lyrics.google_translate",
        side_effect=lambda text, target, source="auto": f"[{target}] {text}",
    ):
        result = translate_lyrics("Hello\n\nWorld", target_lang="hindi")
    assert result["target_lang"] == "hi"
    assert "[hi]" in str(result["lyrics"])


def test_fetch_lyrics_result_translate_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LYRICS_OUTPUT_DIR", str(tmp_path))
    with mock.patch(
        "arka.media.fetch_lyrics.fetch_lyrics",
        return_value={
            "artist": "Queen",
            "title": "Song",
            "album": "",
            "duration": None,
            "provider": "lrclib",
            "lyrics": "Original line",
            "char_count": 13,
            "line_count": 1,
        },
    ), mock.patch(
        "arka.media.fetch_lyrics.translate_lyrics",
        return_value={
            "target_lang": "hi",
            "source_lang": "auto",
            "lyrics": "Translated line",
            "char_count": 15,
            "line_count": 1,
            "chunks": 1,
        },
    ):
        result = fetch_lyrics_result("Queen", "Song", target_lang="hindi")
    assert "translation" in result
    assert Path(str(result["translated_file"])).exists()


def test_mcp_fetch_mocked() -> None:
    with mock.patch(
        "arka.media.fetch_lyrics.fetch_lyrics",
        return_value={"artist": "Queen", "title": "Song", "lyrics": "Line one"},
    ):
        payload = json.loads(
            _handle_arka_fetch_lyrics({"action": "fetch", "artist": "Queen", "title": "Song"})
        )
    assert payload["lyrics"] == "Line one"


def test_mcp_parse() -> None:
    payload = json.loads(
        _handle_arka_fetch_lyrics(
            {"action": "parse", "text": "fetch lyrics for Bohemian Rhapsody by Queen"}
        )
    )
    assert payload["argv"][0] == "fetch"
    assert "Queen" in payload["argv"]
