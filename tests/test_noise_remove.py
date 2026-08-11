"""Tests for noise_remove — NL parsing, routing, and ffmpeg integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.integrations.mcp_server import _handle_arka_noise_remove
from arka.media.noise_remove import (
    default_output_path,
    detect_av_kind,
    nl_to_argv,
    remove_noise,
)
from arka.routing.symbolic import route_noise_remove


def test_nl_to_argv_audio_and_video():
    assert nl_to_argv("remove noise from interview.wav") == ["interview.wav"]
    assert nl_to_argv("denoise clip.mp4") == ["clip.mp4"]
    assert nl_to_argv("noise remove podcast.mp3") == ["podcast.mp3"]
    assert nl_to_argv("clean background noise from webinar.mp4 audio only") == [
        "webinar.mp4",
        "--audio-only",
    ]


def test_nl_to_argv_strength_and_ignores_headphones():
    assert nl_to_argv("remove noise from call.wav strength 20") == ["call.wav", "--strength", "20"]
    assert nl_to_argv("should I get noise cancelling headphones") == []


def test_route_noise_remove():
    hit = route_noise_remove("denoise interview.mp3")
    assert hit == "noise_remove interview.mp3"


def test_route_noise_remove_natural_language():
    hit = route_noise_remove("remove background noise from clip.mp4")
    assert hit == "noise_remove clip.mp4"


def test_noise_remove_manifest():
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/noise_remove/skill.json").read_text())
    assert manifest["name"] == "noise_remove"
    assert "ffmpeg" in manifest["requires"]["bins"]


def test_detect_av_kind(tmp_path: Path):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assert detect_av_kind(audio) == "audio"
    assert detect_av_kind(video) == "video"


def test_default_output_path():
    src = Path("talk.mp4")
    assert default_output_path(src).name == "talk-denoised.mp4"
    assert default_output_path(src, audio_only=True).name == "talk-denoised.wav"


def test_remove_noise_audio_mocked(tmp_path: Path):
    src = tmp_path / "raw.wav"
    src.write_bytes(b"RIFF")
    out = tmp_path / "clean.wav"

    with mock.patch("arka.media.noise_remove._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.noise_remove._ffmpeg_run", side_effect=lambda cmd: out.write_bytes(b"RIFF-clean")
    ):
        saved = remove_noise(src, out, strength=15)
    assert saved == out
    assert out.is_file()


def test_remove_noise_video_mocked(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    out = tmp_path / "clip-denoised.mp4"
    calls: list[list[str]] = []

    def fake_run(cmd):
        calls.append(cmd)
        out.write_bytes(b"denoised-video")

    with mock.patch("arka.media.noise_remove._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.noise_remove._require_ffprobe", return_value="ffprobe"
    ), mock.patch("arka.media.noise_remove._has_audio_stream", return_value=True), mock.patch(
        "arka.media.noise_remove._ffmpeg_run", side_effect=fake_run
    ):
        saved = remove_noise(src, out, strength=12)

    assert saved == out
    assert len(calls) == 1
    assert "-c:v" in calls[0] and "copy" in calls[0]
    assert "afftdn" in " ".join(calls[0])


def test_remove_noise_missing_ffmpeg(tmp_path: Path):
    src = tmp_path / "raw.wav"
    src.write_bytes(b"RIFF")
    with mock.patch("arka.media.noise_remove._require_ffmpeg", side_effect=SystemExit("need ffmpeg")):
        with pytest.raises(SystemExit, match="need ffmpeg"):
            remove_noise(src)


def test_mcp_parse_and_detect(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    parsed = json.loads(_handle_arka_noise_remove({"action": "parse", "text": "denoise clip.mp4"}))
    assert parsed["argv"] == ["clip.mp4"]

    with mock.patch("arka.media.noise_remove._require_ffprobe", return_value="ffprobe"), mock.patch(
        "arka.media.noise_remove._has_audio_stream", return_value=True
    ):
        detected = json.loads(_handle_arka_noise_remove({"action": "detect", "path": str(src)}))
    assert detected["media_kind"] == "video"
