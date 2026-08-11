"""Tests for dub_video — NL parsing, routing, translate/TTS/mux integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from arka.integrations.mcp_server import _handle_arka_dub_video
from arka.media.dub_video import dub_video, nl_to_argv, target_bcp47
from arka.routing.symbolic import route_dub_video


def test_nl_to_argv_dub():
    assert nl_to_argv("dub reel.mp4 to hindi") == ["dub", "reel.mp4", "--target", "hindi"]
    assert nl_to_argv("translate and dub clip.mp4 into tamil") == [
        "dub",
        "clip.mp4",
        "--target",
        "tamil",
    ]


def test_route_dub_video():
    hit = route_dub_video("dub talk.mp4 to spanish")
    assert hit == "dub_video dub talk.mp4 --target spanish"


def test_target_bcp47():
    assert target_bcp47("hi") == "hi-IN"
    assert target_bcp47("es") == "es"


def test_dub_video_mocked(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    out = tmp_path / "clip-dub-hi.mp4"
    audio = tmp_path / "clip-dub-hi.dub.mp3"
    audio.write_bytes(b"mp3")

    def fake_mux(v, a, o, **kw):
        Path(o).write_bytes(b"dubbed")
        return Path(o)

    with mock.patch("arka.media.dub_video.transcribe_file", return_value="Hello world"), mock.patch(
        "arka.media.dub_video.google_translate", return_value="Namaste duniya"
    ), mock.patch(
        "arka.media.dub_video.synthesize_dub_audio", return_value=(audio, "edge-tts (hi-IN)")
    ), mock.patch("arka.media.dub_video.mux_audio", side_effect=fake_mux):
        result = dub_video(src, "hindi", out, save_transcript=False)

    assert result["output"] == str(out)
    assert result["target_lang"] == "hi"
    assert result["tts_provider"] == "edge-tts (hi-IN)"
    assert out.is_file()


def test_mcp_parse_and_check():
    parsed = json.loads(_handle_arka_dub_video({"action": "parse", "text": "dub reel.mp4 to hindi"}))
    assert parsed["argv"] == ["dub", "reel.mp4", "--target", "hindi"]

    checked = json.loads(_handle_arka_dub_video({"action": "check"}))
    assert "exit_code" in checked
