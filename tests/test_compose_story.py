"""Tests for labeled story video mode (compose_story / compose_video --story)."""

from __future__ import annotations

import json

import pytest

from arka.media.compose_story import nl_to_argv
from arka.media.compose_video import (
    Scene,
    VideoConfig,
    _build_ai_image_prompt,
    _parse_scenes_json,
    _resolve_auto_fill_gaps,
    _resolve_show_labels,
    load_config,
)


@pytest.fixture(autouse=True)
def _clear_story_env(monkeypatch):
    for name in ("VIDEO_SHOW_LABELS", "VIDEO_LABELED", "VIDEO_AUTO_FILL", "VIDEO_AUTO_FILL_GAPS"):
        monkeypatch.delenv(name, raising=False)


def test_parse_story_scene_json():
    raw = json.dumps(
        [
            {
                "title": "The beginning",
                "label": "intro",
                "narration": "Once upon a time…",
                "visual_prompt": "misty forest at dawn, cinematic",
                "captions": ["Once upon a time"],
                "image_keywords": ["forest dawn"],
            }
        ]
    )
    scenes = _parse_scenes_json(raw)
    assert len(scenes) == 1
    assert scenes[0].label == "intro"
    assert "misty forest" in scenes[0].visual_prompt


def test_visual_prompt_overrides_ai_prompt():
    scene = Scene(title="Hook", visual_prompt="neon city rain, cyberpunk")
    prompt = _build_ai_image_prompt(scene, "fallback query", "topic")
    assert "neon city rain" in prompt
    assert "cyberpunk" in prompt


def test_story_env_flags():
    assert _resolve_show_labels() is False
    assert _resolve_auto_fill_gaps() is False


def test_story_load_config():
    cfg = load_config(show_labels=True, auto_fill_gaps=True)
    assert cfg.show_labels is True
    assert cfg.auto_fill_gaps is True


def test_nl_to_story_argv():
    argv = nl_to_argv("tell a story about a robot who learns to paint")
    assert argv[:4] == ["compose", "--story", "--llm", "--topic"]
    assert "robot" in argv[4].lower()


def test_nl_to_story_argv_portrait_hint(monkeypatch):
    monkeypatch.delenv("VIDEO_ORIENTATION", raising=False)
    nl_to_argv("story video for reels about friendship")
    import os

    assert os.environ.get("VIDEO_ORIENTATION") == "portrait"


def test_story_mode_config_burns_text():
    cfg = load_config(burn_text=True, show_labels=True, auto_fill_gaps=True)
    assert cfg.burn_text is True
    assert isinstance(cfg, VideoConfig)
