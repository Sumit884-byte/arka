"""Tests for create_video — NL parsing, routing, transparency, and ffmpeg integration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest import mock

import pytest

from arka.integrations.mcp_server import _handle_arka_create_video
from arka.media.create_video import (
    VideoSettings,
    collect_images,
    create_slideshow,
    default_output_path,
    nl_to_argv,
    resolve_output_format,
    _settings_from_args,
)
from arka.routing.symbolic import route_compose_video, route_create_video


def test_nl_to_argv_slideshow_and_image_audio():
    assert nl_to_argv("create video from images in ./photos") == ["slideshow", "./photos"]
    assert nl_to_argv("make slideshow from a.jpg b.png") == ["slideshow", "a.jpg", "b.png"]
    assert nl_to_argv("create video from cover.jpg with audio narration.mp3") == [
        "image-audio",
        "--image",
        "cover.jpg",
        "--audio",
        "narration.mp3",
    ]


def test_nl_to_argv_duration_and_audio():
    assert nl_to_argv("create slideshow from ./pics 4 seconds per slide") == [
        "slideshow",
        "./pics",
        "--duration",
        "4",
    ]
    assert nl_to_argv("create video from images in ./photos with audio track.mp3") == [
        "slideshow",
        "./photos",
        "--audio",
        "track.mp3",
    ]


def test_nl_to_argv_avoids_compose_video_topics():
    assert nl_to_argv("create a 5 minute video on artificial intelligence") == []
    assert route_compose_video("create video about rust") == "compose_video compose --topic rust"


def test_nl_to_argv_transparent():
    assert nl_to_argv("create transparent video from logo.png") == [
        "slideshow",
        "logo.png",
        "--transparent",
    ]
    assert nl_to_argv("make video from a.png format webm-alpha") == [
        "slideshow",
        "a.png",
        "--format",
        "webm-alpha",
    ]


def test_resolve_output_format_transparent():
    key, spec = resolve_output_format(transparent=True)
    assert key == "webm-alpha"
    assert spec["ext"] == ".webm"
    assert spec["pix_fmt"] == "yuva420p"

    key, spec = resolve_output_format(format_name="mov-prores", output=Path("out.mov"))
    assert key == "mov-prores"
    assert spec["vcodec"] == "prores_ks"

    with pytest.raises(SystemExit, match="Unsupported output format"):
        resolve_output_format(format_name="bogus")


def test_settings_from_args():
    args = argparse.Namespace(transparent=True, format=None)
    cfg = _settings_from_args(args)
    assert cfg.transparent is True
    assert cfg.format == "webm-alpha"

    args = argparse.Namespace(transparent=False, format="gif")
    cfg = _settings_from_args(args)
    assert cfg.format == "gif"
    assert cfg.transparent is True


def test_route_create_video():
    hit = route_create_video("create video from images in ./photos")
    assert hit == "create_video slideshow ./photos"


def test_create_video_manifest():
    manifest = json.loads(
        (Path(__file__).parents[1] / "src/arka/skills/create_video/skill.json").read_text()
    )
    assert manifest["name"] == "create_video"
    assert "ffmpeg" in manifest["requires"]["bins"]


def test_collect_images_from_dir(tmp_path: Path):
    for name in ("a.png", "b.jpg", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    images = collect_images(tmp_path)
    assert [p.name for p in images] == ["a.png", "b.jpg"]


def test_default_output_path(tmp_path: Path):
    with mock.patch("arka.media.create_video.Path.home", return_value=tmp_path):
        out = default_output_path(mode="slideshow", stem="My Photos")
    assert out.suffix == ".mp4"
    assert "my-photos" in out.name


def test_create_slideshow_mocked(tmp_path: Path):
    img = tmp_path / "slide.png"
    img.write_bytes(b"PNG")
    out = tmp_path / "out.mp4"
    calls: list[list[str]] = []

    def fake_run(cmd):
        calls.append(cmd)
        if "-f" in cmd and "concat" in cmd:
            (tmp_path / "silent.mp4").write_bytes(b"video")
        Path(cmd[-1]).write_bytes(b"video")

    with mock.patch("arka.media.create_video._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.create_video._ffmpeg_run", side_effect=fake_run
    ):
        saved = create_slideshow(img, output=out, slide_duration=2.0)
    assert saved == out
    assert out.is_file()
    assert any("-loop" in " ".join(c) for c in calls)


def test_create_slideshow_transparent_mocked(tmp_path: Path):
    img = tmp_path / "logo.png"
    img.write_bytes(b"PNG")
    out = tmp_path / "out.webm"
    calls: list[list[str]] = []

    def fake_run(cmd):
        calls.append(cmd)
        if "-f" in cmd and "concat" in cmd:
            (tmp_path / "silent.webm").write_bytes(b"video")
        Path(cmd[-1]).write_bytes(b"video")

    with mock.patch("arka.media.create_video._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.create_video._ffmpeg_run", side_effect=fake_run
    ), mock.patch("arka.media.create_video._image_has_alpha", return_value=True):
        saved = create_slideshow(
            img,
            output=out,
            slide_duration=2.0,
            cfg=VideoSettings(transparent=True, format="webm-alpha"),
        )
    assert saved == out
    joined = " ".join(" ".join(c) for c in calls)
    assert "libvpx-vp9" in joined
    assert "yuva420p" in joined


def test_create_slideshow_missing_ffmpeg(tmp_path: Path):
    img = tmp_path / "slide.png"
    img.write_bytes(b"PNG")
    out = tmp_path / "out.mp4"
    with mock.patch("arka.media.create_video._require_ffmpeg", side_effect=SystemExit("need ffmpeg")):
        with pytest.raises(SystemExit, match="need ffmpeg"):
            create_slideshow(img, output=out)


def test_mcp_parse_and_create(tmp_path: Path):
    parsed = json.loads(
        _handle_arka_create_video({"action": "parse", "text": "make slideshow from a.jpg b.jpg"})
    )
    assert parsed["argv"] == ["slideshow", "a.jpg", "b.jpg"]

    img = tmp_path / "slide.png"
    img.write_bytes(b"PNG")
    out = tmp_path / "created.mp4"

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"video")

    with mock.patch("arka.media.create_video._require_ffmpeg", return_value="ffmpeg"), mock.patch(
        "arka.media.create_video._ffmpeg_run", side_effect=fake_run
    ):
        result = json.loads(
            _handle_arka_create_video(
                {
                    "action": "create",
                    "mode": "slideshow",
                    "sources": [str(img)],
                    "output": str(out),
                    "slide_duration": 2,
                    "transparent": True,
                    "format": "webm-alpha",
                }
            )
        )
    assert result["output"] == str(out)
    assert result["transparent"] is True
    assert result["format"] == "webm-alpha"
    assert out.is_file()
