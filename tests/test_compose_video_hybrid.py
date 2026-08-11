"""Tests for hybrid compose_video mode (video + image B-roll, no text by default)."""

from __future__ import annotations

import json

import pytest

from arka.media.compose_video import (
    Scene,
    VideoConfig,
    _heuristic_media_type,
    _normalize_media_type,
    _parse_scenes_json,
    _resolve_burn_text,
    _resolve_use_only_ai_generated_images,
    _resolve_video_mode,
    _scene_wants_video,
    load_config,
    render_slide,
)


@pytest.fixture(autouse=True)
def _clear_video_env(monkeypatch):
    for name in (
        "VIDEO_MODE",
        "VIDEO_BURN_TEXT",
        "VIDEO_NO_TEXT",
        "VIDEO_USE_STOCK_VIDEO",
        "VIDEO_AI_IMAGES_ONLY",
        "VIDEO_USE_ONLY_AI_GENERATED_IMAGES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_hybrid_is_default_video_mode():
    assert _resolve_video_mode() == "hybrid"
    cfg = load_config()
    assert cfg.video_mode == "hybrid"


def test_no_text_by_default_in_hybrid():
    assert _resolve_burn_text(video_mode="hybrid") is False
    cfg = load_config()
    assert cfg.burn_text is False


def test_photos_mode_burns_text_by_default():
    assert _resolve_burn_text(video_mode="photos") is True
    cfg = load_config(video_mode="photos")
    assert cfg.burn_text is True


def test_video_burn_text_env_restores_text(monkeypatch):
    monkeypatch.setenv("VIDEO_BURN_TEXT", "1")
    assert _resolve_burn_text(video_mode="hybrid") is True


def test_video_no_text_env_disables_text(monkeypatch):
    monkeypatch.setenv("VIDEO_NO_TEXT", "1")
    assert _resolve_burn_text(video_mode="photos") is False


def test_video_ai_images_only_env(monkeypatch):
    monkeypatch.setenv("VIDEO_AI_IMAGES_ONLY", "1")
    assert _resolve_use_only_ai_generated_images() is True


def test_video_use_only_ai_generated_images_env(monkeypatch):
    monkeypatch.setenv("VIDEO_USE_ONLY_AI_GENERATED_IMAGES", "true")
    assert _resolve_use_only_ai_generated_images() is True


def test_legacy_stock_video_env_maps_to_video_mode(monkeypatch):
    monkeypatch.setenv("VIDEO_USE_STOCK_VIDEO", "1")
    assert _resolve_video_mode() == "video"


def test_parse_media_type_from_scene_json():
    raw = json.dumps(
        [
            {
                "title": "Golden peaks",
                "narration": "Mountains glow at sunset.",
                "media_type": "video",
            },
            {
                "title": "Market share",
                "narration": "This chart shows adoption.",
                "media": "image",
            },
        ]
    )
    scenes = _parse_scenes_json(raw)
    assert scenes[0].media_type == "video"
    assert scenes[1].media_type == "image"


def test_normalize_media_type_aliases():
    assert _normalize_media_type("clip") == "video"
    assert _normalize_media_type("still") == "image"
    assert _normalize_media_type("") == ""


def test_heuristic_prefers_video_for_landscapes():
    scene = Scene(
        title="Mountain vista",
        narration="Cinematic mountains at golden hour stretch across the horizon.",
        image_keywords=["mountain sunset", "golden hour"],
    )
    assert _heuristic_media_type(scene) == "video"


def test_heuristic_prefers_image_for_charts():
    scene = Scene(
        title="Growth chart",
        narration="This bar chart compares quarterly revenue.",
        chart={"type": "bar", "title": "Revenue", "data": "Q1:10,Q2:20"},
    )
    assert _heuristic_media_type(scene) == "image"


def test_scene_wants_video_respects_mode_and_media_type(monkeypatch):
    monkeypatch.setattr(
        "arka.media.compose_video.any_video_source_available",
        lambda: True,
    )
    cfg = VideoConfig(video_mode="hybrid")
    video_scene = Scene(title="Drone flight", media_type="video")
    image_scene = Scene(title="Concept map", media_type="image")
    assert _scene_wants_video(video_scene, cfg) is True
    assert _scene_wants_video(image_scene, cfg) is False

    photos_cfg = VideoConfig(video_mode="photos")
    assert _scene_wants_video(video_scene, photos_cfg) is False

    video_cfg = VideoConfig(video_mode="video")
    assert _scene_wants_video(image_scene, video_cfg) is True


def test_render_slide_skips_text_when_burn_text_disabled(tmp_path):
    cfg = load_config(burn_text=False)
    scene = Scene(title="Hidden title", body="Hidden body")
    out = tmp_path / "no-text.png"
    render_slide(None, scene, out, cfg, body_override="Should not appear")
    assert out.is_file()

    out_with_text = tmp_path / "with-text.png"
    render_slide(None, scene, out_with_text, cfg, body_override="Should appear", show_text=True)
    assert out_with_text.stat().st_size > out.stat().st_size

def test_nl_to_argv_no_text_and_video_broll():
    from arka.media.compose_video import nl_to_argv

    assert "--no-text" in nl_to_argv("make a video about mountains with no text")
    assert "--video-broll" in nl_to_argv("create video about travel with stock video broll")
    assert "--no-text" in nl_to_argv("compose video about AI voice only")

