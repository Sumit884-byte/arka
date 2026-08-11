"""Tests for AI music generation routing, MCP, skill manifest, and backends."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest

from arka.integrations.mcp_server import _handle_arka_music_generate
from arka.media.music_generate import (
    _compose_input,
    _synth_note_sequence,
    generate,
    generate_synthesize,
    nl_to_argv,
)
from arka.routing.symbolic import route_generate_music


class TestGenerateMusicRouting:
    def test_route_instrumental(self) -> None:
        routed = route_generate_music("generate music upbeat jazz --instrumental")
        assert routed is not None
        assert routed.startswith("generate_music ")
        assert "--instrumental" in routed
        assert "upbeat jazz" in routed

    def test_route_with_lyrics(self) -> None:
        routed = route_generate_music('compose a song indie folk with lyrics "hello world"')
        assert routed is not None
        assert "--lyrics" in routed

    def test_route_not_video(self) -> None:
        assert route_generate_music("generate video of a cat") is None

    def test_route_trailing_track_noun(self) -> None:
        routed = route_generate_music("create a summer pop track")
        assert routed is not None
        assert "summer pop" in routed

    def test_route_duration_flag(self) -> None:
        routed = route_generate_music("generate music jazz piano --instrumental for 45 seconds")
        assert routed is not None
        assert "-d" in routed
        assert "45" in routed

    def test_compose_input(self) -> None:
        assert "Lyrics:" in _compose_input("indie folk", "line one", instrumental=False)
        assert _compose_input("ambient", "", instrumental=True) == "ambient"


class TestGenerateMusicCli:
    def test_cli_generate_music_subcommand(self) -> None:
        from arka.cli import main

        with patch("arka.media.music_generate.main", return_value=0) as music_main:
            code = main(["generate", "music", "lo-fi", "--instrumental"])
        assert code == 0
        music_main.assert_called_once_with(["lo-fi", "--instrumental"])

    def test_cli_music_generate_alias(self) -> None:
        from arka.cli import main

        with patch("arka.media.music_generate.main", return_value=0) as music_main:
            code = main(["music_generate", "ambient", "-d", "20"])
        assert code == 0
        music_main.assert_called_once_with(["ambient", "-d", "20"])

    def test_cli_help(self) -> None:
        from arka.cli import main

        code = main(["generate", "music", "--help"])
        assert code == 0


def test_music_generate_manifest():
    manifest = json.loads(
        (Path(__file__).parents[1] / "src/arka/skills/music_generate/skill.json").read_text()
    )
    assert manifest["name"] == "music_generate"
    assert "generate music" in manifest["triggers"]


def test_nl_to_argv_about_phrase():
    assert nl_to_argv("generate music about summer nights") == ["summer nights"]


def test_synth_note_sequence_respects_duration():
    notes = _synth_note_sequence("calm ambient", 10)
    total = sum(d for _, d in notes)
    assert 9.5 <= total <= 10.5
    assert len(notes) >= 4


def test_generate_synthesize_mocked(tmp_path: Path):
    out = tmp_path / "tone.mp3"
    with mock.patch("arka.media.music_generate._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.music_generate.subprocess.run",
        side_effect=lambda cmd, **kwargs: mock.Mock(returncode=0),
    ):
        saved = generate_synthesize("test prompt", out, duration=6)
    assert saved == out


def test_generate_auto_synthesize_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "auto.mp3"
    monkeypatch.delenv("POLLINATIONS_API_KEY", raising=False)
    monkeypatch.delenv("POLLINATIONS_KEY", raising=False)
    monkeypatch.setenv("MUSIC_BACKEND", "auto")

    with mock.patch(
        "arka.media.music_generate.generate_synthesize",
        return_value=out,
    ) as synth:
        saved, provider = generate("ambient", out, model="elevenmusic", duration=8, lyrics="", instrumental=True)
    assert saved == out
    assert provider == "synthesize"
    synth.assert_called_once()


def test_mcp_parse():
    payload = json.loads(
        _handle_arka_music_generate({"action": "parse", "text": "create a song indie folk --instrumental"})
    )
    assert "--instrumental" in payload["argv"]
    assert payload["command"].startswith("music_generate ")


def test_mcp_generate_mocked(tmp_path: Path):
    out = tmp_path / "song.mp3"
    out.write_bytes(b"ID3")
    with mock.patch(
        "arka.media.music_generate.music_generate_result",
        return_value={"prompt": "jazz", "output": str(out), "provider": "synthesize", "duration": 10},
    ):
        payload = json.loads(_handle_arka_music_generate({"action": "generate", "prompt": "jazz", "duration": 10}))
    assert payload["provider"] == "synthesize"
    assert payload["output"] == str(out)
