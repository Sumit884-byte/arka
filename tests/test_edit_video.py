"""Tests for edit_video — NL parsing, routing, and ffmpeg integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.integrations.mcp_server import _handle_arka_edit_video
from arka.media.edit_video import (
    default_output_path,
    nl_to_argv,
    trim_video,
)
from arka.routing.symbolic import route_edit_video


def test_nl_to_argv_trim():
    assert nl_to_argv("trim clip.mp4 from 10 to 30") == [
        "trim",
        "clip.mp4",
        "--start",
        "10",
        "--end",
        "30",
    ]
    assert nl_to_argv("cut first 5 seconds of intro.mp4") == [
        "trim",
        "intro.mp4",
        "--start",
        "0",
        "--duration",
        "5",
    ]
    assert nl_to_argv("trim reel.mp4 starting at 2 for 8 seconds") == [
        "trim",
        "reel.mp4",
        "--start",
        "2",
        "--duration",
        "8",
    ]


def test_nl_to_argv_concat():
    assert nl_to_argv("concat part1.mp4 part2.mp4") == ["concat", "part1.mp4", "part2.mp4"]
    assert nl_to_argv("join a.mp4 b.mp4 c.mp4") == ["concat", "a.mp4", "b.mp4", "c.mp4"]


def test_nl_to_argv_overlay():
    assert nl_to_argv('add text "Subscribe!" to reel.mp4') == [
        "overlay-text",
        "reel.mp4",
        "--text",
        "Subscribe!",
    ]
    assert nl_to_argv('overlay "Hello" on clip.mp4') == [
        "overlay-text",
        "clip.mp4",
        "--text",
        "Hello",
    ]


def test_nl_to_argv_extract_and_crop_resize():
    assert nl_to_argv("extract audio from talk.mp4") == ["extract-audio", "talk.mp4"]
    assert nl_to_argv("crop video.mp4 to 1080x1920") == [
        "crop",
        "video.mp4",
        "--width",
        "1080",
        "--height",
        "1920",
    ]
    assert nl_to_argv("resize clip.mp4 to 1280x720") == [
        "resize",
        "clip.mp4",
        "--width",
        "1280",
        "--height",
        "720",
    ]
    assert nl_to_argv("add audio voice.mp3 to clip.mp4") == [
        "mux-audio",
        "clip.mp4",
        "--audio",
        "voice.mp3",
    ]


def test_route_edit_video():
    hit = route_edit_video("trim clip.mp4 from 5 to 15")
    assert hit == "edit_video trim clip.mp4 --start 5 --end 15"


def test_edit_video_manifest():
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/edit_video/skill.json").read_text())
    assert manifest["name"] == "edit_video"
    assert "ffmpeg" in manifest["requires"]["bins"]


def test_default_output_path():
    src = Path("clip.mp4")
    assert default_output_path(src, "trimmed").name == "clip-trimmed.mp4"
    assert default_output_path(src, "audio", ext=".mp3").name == "clip-audio.mp3"


def test_trim_video_mocked(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    out = tmp_path / "clip-trimmed.mp4"
    calls: list[list[str]] = []

    def fake_run(cmd):
        calls.append(cmd)
        out.write_bytes(b"trimmed")

    with mock.patch("arka.media.edit_video._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.edit_video._ffmpeg_run", side_effect=fake_run
    ):
        saved = trim_video(src, out, start=5.0, duration=10.0)

    assert saved == out
    assert len(calls) == 1
    assert "-ss" in calls[0] and "-t" in calls[0]


def test_trim_video_missing_duration(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    with mock.patch("arka.media.edit_video._require_ffmpeg", return_value="ffmpeg"):
        with pytest.raises(SystemExit, match="duration or end is required"):
            trim_video(src, start=0)


def test_mcp_parse_and_detect(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    parsed = json.loads(_handle_arka_edit_video({"action": "parse", "text": "trim clip.mp4 from 1 to 5"}))
    assert parsed["argv"] == ["trim", "clip.mp4", "--start", "1", "--end", "5"]

    with mock.patch("arka.media.edit_video._ffprobe_duration", return_value=60.0):
        detected = json.loads(_handle_arka_edit_video({"action": "detect", "path": str(src)}))
    assert detected["media_kind"] == "video"
    assert detected["duration_sec"] == 60.0
