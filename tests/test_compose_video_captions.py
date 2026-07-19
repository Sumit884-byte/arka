"""Tests for progressive slide captions in compose_video."""

from __future__ import annotations

from pathlib import Path

from arka.media.compose_video import (
    Scene,
    _custom_script_api,
    _default_output,
    _estimate_caption_beats,
    _llm_script,
    _max_caption_beats,
    _schedule_caption_beats,
    _schedule_scene_timeline,
    _script_needs_shortening,
    _split_caption_beats,
    caption_beats_for_scene,
    nl_to_argv,
    load_config,
    prepare_slide_body,
    render_slide,
)


def test_split_caption_beats_limits_each_chunk():
    narration = " ".join(["word"] * 200)
    beats = _split_caption_beats(narration)
    assert len(beats) >= 4
    for beat in beats:
        assert len(beat) <= 100
        assert len(prepare_slide_body(beat)) <= 2


def test_schedule_caption_beats_sums_to_duration():
    beats = ["Cloud spend is rising fast.", "AI adoption drives hiring shifts."]
    segments = _schedule_caption_beats("ignored", beats, 12.0)
    total = sum(duration for duration, _ in segments)
    assert abs(total - 12.0) < 0.05
    assert len(segments) == 2


def test_schedule_scene_timeline_merges_caption_and_broll():
    narration = (
        "Modern teams rely on developer productivity tools. "
        "Coding assistants and laptop workflows are reshaping daily work."
    )
    timeline = _schedule_scene_timeline(
        narration,
        "developer coding laptop",
        12.0,
        fallback_query="technology",
    )
    total = sum(item[0] for item in timeline)
    assert abs(total - 12.0) < 0.05
    assert all(item[2] for item in timeline)
    assert len(timeline) >= 2


def test_script_needs_shortening_when_too_many_beats(monkeypatch=None):
    import os

    old = os.environ.get("VIDEO_MAX_CAPTION_BEATS")
    os.environ["VIDEO_MAX_CAPTION_BEATS"] = "3"
    try:
        long_narration = ". ".join([f"Sentence number {i} adds more detail" for i in range(20)])
        scene = Scene(title="Test", narration=long_narration)
        assert _estimate_caption_beats(scene) > _max_caption_beats()
        assert _script_needs_shortening([scene])
    finally:
        if old is None:
            os.environ.pop("VIDEO_MAX_CAPTION_BEATS", None)
        else:
            os.environ["VIDEO_MAX_CAPTION_BEATS"] = old


def test_scene_captions_override_auto_split():
    scene = Scene(
        title="Trends",
        narration="This long narration would normally split into many beats.",
        captions=["Cloud growth", "AI hiring"],
    )
    assert caption_beats_for_scene(scene) == ["Cloud growth", "AI hiring"]


def test_render_slide_body_override(tmp_path: Path):
    cfg = load_config()
    scene = Scene(title="IT Sector Trends", body="ignored")
    out = tmp_path / "slide.png"
    render_slide(None, scene, out, cfg, body_override="Cloud and AI reshape hiring.")
    assert out.is_file()
    assert out.stat().st_size > 5000


def test_default_output_uses_configured_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path))
    out = _default_output("AI infrastructure")
    assert out.parent == tmp_path
    assert out.suffix == ".mp4"


def test_llm_script_reports_invalid_json(monkeypatch):
    monkeypatch.setattr("arka.llm.fallback.llm_complete", lambda *args, **kwargs: "", raising=False)
    try:
        _llm_script("AI infrastructure")
        raise AssertionError("Expected SystemExit")
    except SystemExit as exc:
        assert "invalid scene JSON" in str(exc)


def test_nl_to_argv_accepts_arka_video_request():
    assert nl_to_argv("arka make an video on ai") == ["compose", "--topic", "ai"]


def test_custom_script_api_accepts_scenes_object(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"scenes":[{"title":"Intro","narration":"Hello","captions":["Hello"],"image_keywords":["robot lab"]}]}'

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode()
        seen["auth"] = req.headers.get("Authorization")
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("VIDEO_SCRIPT_API_KEY", "demo-key")
    scenes = _custom_script_api("ai", api_url="https://example.test/video-script")
    assert scenes[0].title == "Intro"
    assert scenes[0].image_keywords == ["robot lab"]
    assert seen["url"] == "https://example.test/video-script"
    assert seen["auth"] == "Bearer demo-key"
    assert '"topic": "Artificial Intelligence"' in seen["body"]


def test_custom_script_api_requires_url(monkeypatch):
    monkeypatch.delenv("VIDEO_SCRIPT_API_URL", raising=False)
    monkeypatch.delenv("ARKA_VIDEO_SCRIPT_API_URL", raising=False)
    try:
        _custom_script_api("ai", api_url="")
        raise AssertionError("Expected SystemExit")
    except SystemExit as exc:
        assert "requires --api-url" in str(exc)


if __name__ == "__main__":
    test_split_caption_beats_limits_each_chunk()
    test_schedule_caption_beats_sums_to_duration()
    test_schedule_scene_timeline_merges_caption_and_broll()
    test_script_needs_shortening_when_too_many_beats()
    test_scene_captions_override_auto_split()
    test_render_slide_body_override(Path("/tmp/arka-caption-slide-test"))
    print("All tests passed")
