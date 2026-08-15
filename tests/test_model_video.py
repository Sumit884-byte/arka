"""Tests for model_video — NL parsing, routing, Blender/ffmpeg integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.integrations.mcp_server import _handle_arka_model_video
from arka.media.model_video import (
    _blender_animation_script,
    _blender_turntable_script,
    _explicit_cli_argv,
    _is_animation_request,
    _is_model_video_request,
    _normalize_argv,
    create_model_video,
    is_model_video_cli_argv,
    main as model_video_main,
    nl_to_argv,
    render_animation,
    run_model_video_cli,
)
from arka.routing.symbolic import route_model_to_image, route_model_video, route_offline_extras


def test_is_model_video_request():
    assert _is_model_video_request("create turntable video from chair.obj")
    assert _is_model_video_request("make 3d model video of gear.glb")
    assert _is_model_video_request("video from 3d model robot.fbx")
    assert not _is_model_video_request("create 3d model of a gear")
    assert not _is_model_video_request("render model.obj as png")


def test_nl_to_argv_turntable():
    assert nl_to_argv("create turntable video from chair.obj") == [
        "render",
        "chair.obj",
        "--backend",
        "blender",
    ]
    assert nl_to_argv("make 3d model video from gear.glb 180 frames 24 fps") == [
        "render",
        "gear.glb",
        "--frames",
        "180",
        "--fps",
        "24",
    ]


def test_nl_to_argv_animation():
    assert nl_to_argv("render animated 3d character from hero.fbx") == [
        "animate",
        "hero.fbx",
    ]
    assert nl_to_argv("fbx run cycle video runner.fbx 90 frames 30 fps -o run.mp4") == [
        "animate",
        "runner.fbx",
        "--frames",
        "90",
        "--fps",
        "30",
        "-o",
        "run.mp4",
    ]
    assert nl_to_argv("rigged character animation video dancer.glb") == [
        "animate",
        "dancer.glb",
    ]


def test_is_animation_request():
    assert _is_animation_request("render animated 3d character hero.fbx")
    assert _is_animation_request("fbx run cycle video")
    assert not _is_animation_request("create turntable video from chair.obj")


def test_nl_to_argv_explicit_cli_with_output():
    assert nl_to_argv("model_video render chair.obj -o out.mp4") == [
        "render",
        "chair.obj",
        "-o",
        "out.mp4",
    ]
    assert nl_to_argv("render gear.glb --frames 180 -o spin.mp4") == [
        "render",
        "gear.glb",
        "--frames",
        "180",
        "-o",
        "spin.mp4",
    ]


def test_normalize_argv_strips_skill_head():
    assert _normalize_argv(["model_video", "render", "chair.obj", "-o", "out.mp4"]) == [
        "render",
        "chair.obj",
        "-o",
        "out.mp4",
    ]
    assert _normalize_argv(["--", "check"]) == ["check"]


def test_is_model_video_cli_argv():
    assert is_model_video_cli_argv(["model_video", "render", "chair.obj"])
    assert not is_model_video_cli_argv(["render", "chair.obj"])


def test_explicit_cli_argv():
    assert _explicit_cli_argv("model_video render chair.obj -o out.mp4") == [
        "render",
        "chair.obj",
        "-o",
        "out.mp4",
    ]
    assert _explicit_cli_argv("model_video animate runner.fbx -o run.mp4 --frames 90") == [
        "animate",
        "runner.fbx",
        "-o",
        "run.mp4",
        "--frames",
        "90",
    ]
    assert _explicit_cli_argv("render gear.glb -o spin.mp4") == [
        "render",
        "gear.glb",
        "-o",
        "spin.mp4",
    ]


def test_cli_model_video_with_output():
    from unittest.mock import patch

    from arka.cli import main

    with patch("arka.media.model_video.main", return_value=0) as model_video_main:
        code = main(["model_video", "render", "chair.obj", "-o", "/tmp/out.mp4"])
    assert code == 0
    model_video_main.assert_called_once_with(["render", "chair.obj", "-o", "/tmp/out.mp4"])


def test_run_model_video_cli():
    from unittest.mock import patch

    with patch("arka.media.model_video.main", return_value=0) as model_video_main:
        code = run_model_video_cli(["model_video", "check"])
    assert code == 0
    model_video_main.assert_called_once_with(["check"])


def test_main_with_model_video_prefix(tmp_path: Path):
    model = tmp_path / "chair.obj"
    model.write_text("obj")
    out = tmp_path / "out.mp4"
    with mock.patch("arka.media.model_video.create_model_video", return_value=(out, "blender")):
        code = model_video_main(["model_video", "render", str(model), "-o", str(out)])
    assert code == 0


def test_nl_to_argv_avoids_compose_3d_and_model_to_image():
    assert nl_to_argv("create 3d model of a chair") == []
    assert nl_to_argv("render model chair.obj as an image") == []


def test_route_model_video():
    hit = route_model_video("create turntable video from robot.glb")
    assert hit == "model_video render robot.glb --backend blender"
    hit = route_model_video("fbx run cycle video runner.fbx")
    assert hit == "model_video animate runner.fbx"


def test_route_model_to_image_skips_video_intents():
    assert route_model_to_image("create turntable video from robot.glb") is None
    assert route_offline_extras("render model chair.obj as an image") == (
        "model_to_image chair.obj --output chair-render.png"
    )


def test_route_offline_extras_model_video():
    result = route_offline_extras("create 3d model video from gear.obj")
    assert result == "model_video render gear.obj"


def test_blender_turntable_script(tmp_path: Path):
    script = _blender_turntable_script(
        tmp_path / "a.glb",
        tmp_path / "frames",
        frames=60,
        size=512,
        angle="three-quarter",
    )
    assert "import_scene.gltf" in script
    assert "frames=60" in script
    assert "frame-" in script
    assert "rotation_euler" in script


def test_blender_animation_script(tmp_path: Path):
    script = _blender_animation_script(
        tmp_path / "run.fbx",
        tmp_path / "frames",
        frames=90,
        size=512,
        background=True,
    )
    assert "import_scene.fbx" in script
    assert "render_frames=90" in script
    assert "anim_start" in script
    assert "primitive_plane_add" in script
    assert "frame-" in script


def test_render_animation_mocked(tmp_path: Path):
    model = tmp_path / "run.fbx"
    model.write_bytes(b"fbx")
    out = tmp_path / "run.mp4"

    def fake_run(cmd, **kwargs):
        script = Path(cmd[-1])
        frames_out = Path(script).parent / "frames"
        frames_out.mkdir(exist_ok=True)
        for i in range(3):
            (frames_out / f"frame-{i + 1:04d}.png").write_bytes(b"PNG")
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch("arka.media.model_video._find_blender", return_value="/usr/bin/blender"):
        with mock.patch("arka.media.model_video.subprocess.run", side_effect=fake_run):
            with mock.patch("arka.media.model_video._frames_to_video", return_value=out):
                saved, provider = render_animation(model, out, frames=90, fps=30)
    assert saved == out
    assert provider == "blender-animation"


def test_main_animate_subcommand(tmp_path: Path):
    model = tmp_path / "run.fbx"
    model.write_bytes(b"fbx")
    out = tmp_path / "run.mp4"
    with mock.patch("arka.media.model_video.render_animation", return_value=(out, "blender-animation")):
        code = model_video_main(["animate", str(model), "-o", str(out), "--frames", "90"])
    assert code == 0


def test_create_model_video_slideshow_mocked(tmp_path: Path):
    renders = tmp_path / "renders"
    renders.mkdir()
    for i in range(3):
        (renders / f"frame-{i:02d}.png").write_bytes(b"PNG")
    out = tmp_path / "out.mp4"

    with mock.patch(
        "arka.media.model_video.create_slideshow",
        return_value=out,
    ) as slideshow:
        saved, provider = create_model_video(
            str(renders / "frame-00.png"),
            out,
            backend="slideshow",
            renders=str(renders),
        )
    assert saved == out
    assert provider == "slideshow"
    slideshow.assert_called_once()


def test_create_model_video_blender_mocked(tmp_path: Path):
    model = tmp_path / "gear.glb"
    model.write_bytes(b"glb")
    out = tmp_path / "spin.mp4"

    with mock.patch(
        "arka.media.model_video.render_turntable",
        return_value=(out, "blender"),
    ) as render:
        saved, provider = create_model_video(model, out, backend="blender", frames=12)
    assert saved == out
    assert provider == "blender"
    render.assert_called_once()


def test_create_model_video_no_blender_no_renders(tmp_path: Path):
    model = tmp_path / "gear.glb"
    model.write_bytes(b"glb")
    with mock.patch("arka.media.model_video._find_blender", return_value=None):
        with pytest.raises(RuntimeError, match="No Blender"):
            create_model_video(model, backend="auto")


def test_mcp_parse():
    payload = json.loads(
        _handle_arka_model_video({"action": "parse", "text": "create turntable video from chair.obj"})
    )
    assert payload["argv"] == ["render", "chair.obj", "--backend", "blender"]
    assert "model_video" in payload["command"]


def test_mcp_render_mocked(tmp_path: Path):
    model = tmp_path / "chair.obj"
    model.write_text("obj")
    out = tmp_path / "out.mp4"
    with mock.patch(
        "arka.media.model_video.create_model_video",
        return_value=(out, "blender"),
    ):
        payload = json.loads(
            _handle_arka_model_video(
                {"action": "render", "source": str(model), "output": str(out), "backend": "blender"}
            )
        )
    assert payload["output"] == str(out)
    assert payload["provider"] == "blender"


def test_mcp_animate_mocked(tmp_path: Path):
    model = tmp_path / "run.fbx"
    model.write_bytes(b"fbx")
    out = tmp_path / "run.mp4"
    with mock.patch(
        "arka.media.model_video.render_animation",
        return_value=(out, "blender-animation"),
    ):
        payload = json.loads(
            _handle_arka_model_video(
                {
                    "action": "animate",
                    "source": str(model),
                    "output": str(out),
                    "frames": 90,
                    "fps": 30,
                    "background": True,
                }
            )
        )
    assert payload["output"] == str(out)
    assert payload["provider"] == "blender-animation"
    assert payload["mode"] == "animation"


def test_model_video_manifest():
    manifest = json.loads(
        (Path(__file__).parents[1] / "src/arka/skills/model_video/skill.json").read_text()
    )
    assert manifest["name"] == "model_video"
    assert "ffmpeg" in manifest["requires"]["bins"]
    assert "animated 3d character" in manifest["triggers"]
