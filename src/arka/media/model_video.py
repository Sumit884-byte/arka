#!/usr/bin/env python3
"""Create turntable videos from 3D models — Blender headless render or slideshow fallback."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from arka.agent.model_to_image import ANGLE_PRESETS, choose_angle
from arka.core.compute import ffmpeg_thread_args
from arka.media.compose_video import _require_ffmpeg, _which
from arka.media.create_video import (
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    VideoSettings,
    collect_images,
    create_slideshow,
    default_output_path,
)

MODEL_EXTS = {".obj", ".stl", ".glb", ".gltf", ".fbx"}
ANIMATION_EXTS = {".fbx", ".glb", ".gltf"}
MODEL_VIDEO_SUBCOMMANDS = frozenset({"render", "animate", "parse", "check"})
MODEL_VIDEO_CLI_HEADS = frozenset(
    {
        "model_video",
        "model-video",
        "3d_model_video",
        "turntable_video",
        "3d-video",
    }
)
DEFAULT_FRAMES = 120
DEFAULT_DURATION = 4.0
DEFAULT_SIZE = 1024


def _normalize_argv(argv: list[str]) -> list[str]:
    """Strip fish/legacy ``--`` prefixes and leading skill names."""
    args = list(argv)
    while args and args[0] == "--":
        args.pop(0)
    if args and args[0] in MODEL_VIDEO_CLI_HEADS:
        args = args[1:]
    return args


def _is_subcommand(argv: list[str]) -> bool:
    return bool(argv) and argv[0] in MODEL_VIDEO_SUBCOMMANDS


def is_model_video_cli_argv(argv: list[str]) -> bool:
    """True for ``arka model_video …`` style argv (first token is a model_video alias)."""
    return bool(argv) and argv[0] in MODEL_VIDEO_CLI_HEADS


def run_model_video_cli(argv: list[str]) -> int:
    """Execute ``arka model_video …`` from argv like ['model_video', 'render', 'chair.obj']."""
    return main(argv[1:])


def _explicit_cli_argv(text: str) -> list[str]:
    """Parse explicit ``model_video render … -o out.mp4`` without NL video keywords."""
    t = text.strip()
    if not t:
        return []
    match = re.match(
        r"(?i)(?:(?P<head>model[-_]?video)\s+)?(?P<sub>render|animate|parse|check)\b(?P<rest>.*)$",
        t,
    )
    if not match:
        return []
    sub = match.group("sub").lower()
    if sub == "render" and _is_animation_request(t):
        return []
    rest = match.group("rest").strip()
    if not rest:
        return [sub]
    try:
        argv = [sub, *shlex.split(rest)]
    except ValueError:
        argv = [sub, *rest.split()]
    if match.group("head") or sub in {"parse", "check"}:
        return argv
    if _model_path(t) or re.search(
        r"(?:^|\s)(?:-o|--output|--frames|--fps|--backend|--renders|--angle|--size)\b",
        t,
    ):
        return argv
    return []


def _backend() -> str:
    return os.environ.get("MODEL_VIDEO_BACKEND", "auto").strip().lower() or "auto"


def _default_frames() -> int:
    raw = os.environ.get("MODEL_VIDEO_FRAMES", str(DEFAULT_FRAMES)).strip()
    try:
        return max(12, min(int(raw), 600))
    except ValueError:
        return DEFAULT_FRAMES


def _default_fps() -> int:
    raw = os.environ.get("MODEL_VIDEO_FPS", str(DEFAULT_FPS)).strip()
    try:
        return max(12, min(int(raw), 60))
    except ValueError:
        return DEFAULT_FPS


def _output_dir() -> Path:
    raw = os.environ.get("MODEL_VIDEO_OUTPUT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Videos" / "arka-3d"


def _find_blender() -> str | None:
    found = shutil.which("blender")
    if found:
        return found
    for candidate in (
        Path("/Applications/Blender.app/Contents/MacOS/Blender"),
        Path("/Applications/Blender.app/Contents/MacOS/blender"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _model_path(text: str) -> str | None:
    match = re.search(
        r"(?:~|/|\./|\.\./)?[^\s]+\.(?:obj|stl|glb|gltf|fbx)\b",
        text,
        re.I,
    )
    return match.group(0) if match else None


def _is_model_video_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if not re.search(
        r"(?i)\b(?:video|animation|animated|animate|movie|clip|turntable|rotate|spinning|"
        r"rigged|run[\s-]?cycle|walk[\s-]?cycle)\b",
        t,
    ):
        return False
    if re.search(
        r"(?i)\b(?:3d|three[\s-]?d|model|mesh|turntable|glb|gltf|obj|stl|fbx)\b",
        t,
    ):
        return True
    return bool(_model_path(t))


def default_output_path_for_model(source: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{source.stem}-turntable-{stamp}.mp4"


def default_output_path_for_animation(source: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{source.stem}-animation-{stamp}.mp4"


def _is_animation_request(text: str) -> bool:
    t = text.strip()
    if re.search(r"(?i)\b(?:turntable|rotate|spinning|360)\b", t):
        return False
    if re.search(
        r"(?i)\b(?:animate|animated|rigged|run[\s-]?cycle|walk[\s-]?cycle|"
        r"character\s+animation|armature|skeletal)\b",
        t,
    ):
        return True
    if re.search(r"(?i)\bfbx\b", t) and re.search(
        r"(?i)\b(?:run|walk|cycle|animation|animated|rigged)\b",
        t,
    ):
        return True
    return False


def _blender_turntable_script(
    src: Path,
    frames_dir: Path,
    *,
    frames: int,
    size: int,
    angle: str = "three-quarter",
) -> str:
    src_q = repr(str(src))
    frames_dir_q = repr(str(frames_dir))
    camera_location, camera_rotation = ANGLE_PRESETS.get(angle, ANGLE_PRESETS["three-quarter"])
    return f'''import bpy, math, os
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
path={src_q}
ext=path.lower().rsplit('.',1)[-1]
if ext == 'obj': bpy.ops.wm.obj_import(filepath=path)
elif ext == 'stl': bpy.ops.wm.stl_import(filepath=path)
elif ext in ('glb','gltf'): bpy.ops.import_scene.gltf(filepath=path)
elif ext == 'fbx': bpy.ops.import_scene.fbx(filepath=path)
else: raise RuntimeError('Unsupported mesh format: '+ext)
objs=[o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs: raise RuntimeError('model contains no mesh')
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active=objs[0]
bpy.ops.object.join()
obj=bpy.context.object
obj.location=(0,0,0)
obj.rotation_euler=(math.radians(8),0,0)
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
obj.dimensions=(2.8,2.8,2.8)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
mat=bpy.data.materials.new('ArkaMaterial'); mat.diffuse_color=(0.18,0.42,0.95,1); obj.data.materials.append(mat)
camera_data=bpy.data.cameras.new('Camera'); camera=bpy.data.objects.new('Camera', camera_data); bpy.context.collection.objects.link(camera); bpy.context.scene.camera=camera
camera.location={camera_location!r}; camera.rotation_euler=tuple(math.radians(v) for v in {camera_rotation!r})
light_data=bpy.data.lights.new('Key','AREA'); light_data.energy=900; light_data.shape='DISK'; light_data.size=5; light=bpy.data.objects.new('Key',light_data); bpy.context.collection.objects.link(light); light.location=(3,-4,5)
scene=bpy.context.scene
_engines={{e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}}
scene.render.engine=next((e for e in ('BLENDER_EEVEE_NEXT','BLENDER_EEVEE','CYCLES') if e in _engines), 'BLENDER_EEVEE')
scene.render.resolution_x={size}
scene.render.resolution_y={size}
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.film_transparent=False
frames={frames}
out_dir={frames_dir_q}
os.makedirs(out_dir, exist_ok=True)
scene.frame_start=1
scene.frame_end=frames
for f in range(1, frames+1):
    scene.frame_set(f)
    obj.rotation_euler=(math.radians(8), 0, math.radians(360.0*(f-1)/frames))
    scene.render.filepath=os.path.join(out_dir, f'frame-{{f:04d}}.png')
    bpy.ops.render.render(write_still=True)
'''


def _blender_animation_script(
    src: Path,
    frames_dir: Path,
    *,
    frames: int,
    size: int,
    background: bool = True,
) -> str:
    src_q = repr(str(src))
    frames_dir_q = repr(str(frames_dir))
    return f'''import bpy, math, os
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
path={src_q}
ext=path.lower().rsplit('.',1)[-1]
if ext == 'fbx':
    bpy.ops.import_scene.fbx(filepath=path)
elif ext in ('glb','gltf'):
    bpy.ops.import_scene.gltf(filepath=path)
else:
    raise RuntimeError('Animation mode supports .fbx, .glb, .gltf — got: '+ext)
armatures=[o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
meshes=[o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes and not armatures:
    raise RuntimeError('model contains no mesh or armature')
anim_start=1
anim_end=1
for obj in bpy.context.scene.objects:
    ad=obj.animation_data
    if ad and ad.action:
        anim_start=int(ad.action.frame_range[0])
        anim_end=int(ad.action.frame_range[1])
        break
anim_len=max(1, anim_end-anim_start+1)
render_frames={frames}
bpy.ops.object.select_all(action='DESELECT')
targets=[o for o in bpy.context.scene.objects if o.type in ('MESH','ARMATURE')]
for o in targets:
    o.select_set(True)
if targets:
    mins=Vector((1e9,1e9,1e9))
    maxs=Vector((-1e9,-1e9,-1e9))
    for o in targets:
        for corner in o.bound_box:
            world=o.matrix_world @ Vector(corner)
            mins.x=min(mins.x,world.x); mins.y=min(mins.y,world.y); mins.z=min(mins.z,world.z)
            maxs.x=max(maxs.x,world.x); maxs.y=max(maxs.y,world.y); maxs.z=max(maxs.z,world.z)
    center=(mins+maxs)*0.5
    height=max(maxs.z-mins.z, 0.001)
    scale=1.8/height
    for o in targets:
        o.location=(o.location-center)*scale
        o.scale=[s*scale for s in o.scale]
if {background!r}:
    bpy.ops.mesh.primitive_plane_add(size=24, location=(0,0,0))
    ground=bpy.context.object
    gmat=bpy.data.materials.new('Ground'); gmat.diffuse_color=(0.12,0.14,0.16,1)
    ground.data.materials.append(gmat)
camera_data=bpy.data.cameras.new('Camera')
camera=bpy.data.objects.new('Camera', camera_data)
bpy.context.collection.objects.link(camera)
bpy.context.scene.camera=camera
camera.location=(0,-5.5,1.6)
camera.rotation_euler=(math.radians(82),0,0)
key_data=bpy.data.lights.new('Key','AREA'); key_data.energy=1200; key_data.shape='DISK'; key_data.size=6
key=bpy.data.objects.new('Key', key_data); bpy.context.collection.objects.link(key); key.location=(4,-3,6)
fill_data=bpy.data.lights.new('Fill','AREA'); fill_data.energy=350; fill_data.shape='DISK'; fill_data.size=8
fill=bpy.data.objects.new('Fill', fill_data); bpy.context.collection.objects.link(fill); fill.location=(-4,-2,3)
scene=bpy.context.scene
_engines={{e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}}
scene.render.engine=next((e for e in ('BLENDER_EEVEE_NEXT','BLENDER_EEVEE','CYCLES') if e in _engines), 'BLENDER_EEVEE')
scene.render.resolution_x={size}
scene.render.resolution_y={size}
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.film_transparent=False
out_dir={frames_dir_q}
os.makedirs(out_dir, exist_ok=True)
scene.frame_start=1
scene.frame_end=render_frames
for f in range(1, render_frames+1):
    anim_f=anim_start+((f-1) % anim_len)
    scene.frame_set(anim_f)
    scene.render.filepath=os.path.join(out_dir, f'frame-{{f:04d}}.png')
    bpy.ops.render.render(write_still=True)
'''


def _ffmpeg_run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
        raise RuntimeError(f"ffmpeg failed: {detail}")


def _frames_to_video(
    frames_dir: Path,
    output: Path,
    *,
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> Path:
    ffmpeg = _require_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / "frame-%04d.png"
    if not any(frames_dir.glob("frame-*.png")):
        raise FileNotFoundError(f"No rendered frames found in {frames_dir}")
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(pattern),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        str(output),
    ]
    _ffmpeg_run(cmd)
    return output


def render_turntable(
    source: str | Path,
    output: str | Path | None = None,
    *,
    frames: int | None = None,
    fps: int | None = None,
    size: int = DEFAULT_SIZE,
    angle: str = "auto",
    task: str = "",
) -> tuple[Path, str]:
    """Render a turntable video from a 3D model using Blender."""
    src = Path(source).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"3D model not found: {src}")
    if src.suffix.lower() not in MODEL_EXTS:
        raise ValueError(f"Unsupported model format: {src.suffix}. Use {', '.join(sorted(MODEL_EXTS))}")

    blender = _find_blender()
    if not blender:
        raise RuntimeError(
            "3D model video requires Blender on PATH. "
            "Install Blender or pass --renders with existing preview frames."
        )

    frame_count = frames if frames is not None else _default_frames()
    video_fps = fps if fps is not None else _default_fps()
    selected_angle = choose_angle(task or src.stem, requested=angle)
    dest = Path(output).expanduser() if output else default_output_path_for_model(src)

    with tempfile.TemporaryDirectory(prefix="arka-model-video-") as tmp:
        work = Path(tmp)
        frames_dir = work / "frames"
        frames_dir.mkdir()
        script = work / "turntable.py"
        script.write_text(
            _blender_turntable_script(
                src,
                frames_dir,
                frames=frame_count,
                size=max(256, min(size, 4096)),
                angle=selected_angle,
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [blender, "--background", "--python", str(script)],
            capture_output=True,
            text=True,
            timeout=max(300, frame_count * 3),
            check=False,
        )
        if proc.returncode != 0 or not any(frames_dir.glob("frame-*.png")):
            detail = (proc.stderr or proc.stdout or "")[-1000:]
            raise RuntimeError(f"Blender turntable render failed: {detail}")
        saved = _frames_to_video(frames_dir, dest, fps=video_fps)
    return saved, "blender"


def render_animation(
    source: str | Path,
    output: str | Path | None = None,
    *,
    frames: int | None = None,
    fps: int | None = None,
    size: int = DEFAULT_SIZE,
    background: bool = True,
) -> tuple[Path, str]:
    """Render a rigged character animation video from FBX/GLB using Blender."""
    src = Path(source).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"3D model not found: {src}")
    if src.suffix.lower() not in ANIMATION_EXTS:
        raise ValueError(
            f"Animation mode supports {', '.join(sorted(ANIMATION_EXTS))}; got {src.suffix}"
        )

    blender = _find_blender()
    if not blender:
        raise RuntimeError(
            "Animated character video requires Blender on PATH. "
            "Install Blender (https://www.blender.org) or use a Mixamo FBX with "
            "mixamo.com → character + run animation → Download FBX."
        )

    frame_count = frames if frames is not None else _default_frames()
    video_fps = fps if fps is not None else _default_fps()
    dest = Path(output).expanduser() if output else default_output_path_for_animation(src)

    with tempfile.TemporaryDirectory(prefix="arka-model-animate-") as tmp:
        work = Path(tmp)
        frames_dir = work / "frames"
        frames_dir.mkdir()
        script = work / "animate.py"
        script.write_text(
            _blender_animation_script(
                src,
                frames_dir,
                frames=frame_count,
                size=max(256, min(size, 4096)),
                background=background,
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [blender, "--background", "--python", str(script)],
            capture_output=True,
            text=True,
            timeout=max(300, frame_count * 5),
            check=False,
        )
        if proc.returncode != 0 or not any(frames_dir.glob("frame-*.png")):
            detail = (proc.stderr or proc.stdout or "")[-1000:]
            raise RuntimeError(f"Blender animation render failed: {detail}")
        saved = _frames_to_video(frames_dir, dest, fps=video_fps)
    return saved, "blender-animation"


def render_slideshow_from_renders(
    renders: str | Path,
    output: str | Path | None = None,
    *,
    slide_duration: float = 0.5,
    audio: str | Path | None = None,
) -> tuple[Path, str]:
    """Build a video from existing model preview images."""
    images = collect_images(renders)
    dest = (
        Path(output).expanduser()
        if output
        else default_output_path(mode="slideshow", stem=images[0].stem)
    )
    saved = create_slideshow(
        *images,
        output=dest,
        slide_duration=slide_duration,
        audio=audio,
        cfg=VideoSettings(),
    )
    return saved, "slideshow"


def create_model_video(
    source: str | Path,
    output: str | Path | None = None,
    *,
    backend: str | None = None,
    frames: int | None = None,
    fps: int | None = None,
    size: int = DEFAULT_SIZE,
    angle: str = "auto",
    task: str = "",
    renders: str | Path | None = None,
    slide_duration: float = 0.5,
    audio: str | Path | None = None,
) -> tuple[Path, str]:
    chosen = (backend or _backend()).strip().lower() or "auto"

    if renders:
        return render_slideshow_from_renders(
            renders,
            output,
            slide_duration=slide_duration,
            audio=audio,
        )

    if chosen == "slideshow":
        src = Path(source).expanduser()
        sibling = src.parent if src.is_file() else src
        if sibling.is_dir():
            try:
                return render_slideshow_from_renders(
                    sibling,
                    output,
                    slide_duration=slide_duration,
                    audio=audio,
                )
            except SystemExit:
                pass
        raise RuntimeError(
            "slideshow backend needs --renders with preview images, "
            "or a directory of PNG/JPG frames next to the model."
        )

    if chosen in {"blender", "turntable"}:
        return render_turntable(
            source,
            output,
            frames=frames,
            fps=fps,
            size=size,
            angle=angle,
            task=task,
        )

    # auto: Blender turntable when available, else try sibling renders directory
    if _find_blender():
        return render_turntable(
            source,
            output,
            frames=frames,
            fps=fps,
            size=size,
            angle=angle,
            task=task,
        )

    src = Path(source).expanduser().resolve()
    sibling = src.parent
    pngs = sorted(sibling.glob("*.png")) + sorted(sibling.glob("*.jpg"))
    if pngs:
        return render_slideshow_from_renders(
            sibling,
            output,
            slide_duration=slide_duration,
            audio=audio,
        )

    raise RuntimeError(
        "No Blender on PATH and no preview images found. "
        "Install Blender for turntable rendering, or pass --renders with existing frames."
    )


def model_video_result(
    source: str,
    *,
    output: str | None = None,
    backend: str | None = None,
    frames: int | None = None,
    fps: int | None = None,
    size: int = DEFAULT_SIZE,
    angle: str = "auto",
    task: str = "",
    renders: str | None = None,
    slide_duration: float = 0.5,
    audio: str | None = None,
) -> dict[str, object]:
    saved, provider = create_model_video(
        source,
        output,
        backend=backend,
        frames=frames,
        fps=fps,
        size=size,
        angle=angle,
        task=task,
        renders=renders,
        slide_duration=slide_duration,
        audio=audio,
    )
    return {
        "source": source,
        "output": str(saved),
        "provider": provider,
        "backend": backend or _backend(),
        "frames": frames or _default_frames(),
        "fps": fps or _default_fps(),
    }


def animation_video_result(
    source: str,
    *,
    output: str | None = None,
    frames: int | None = None,
    fps: int | None = None,
    size: int = DEFAULT_SIZE,
    background: bool = True,
) -> dict[str, object]:
    saved, provider = render_animation(
        source,
        output,
        frames=frames,
        fps=fps,
        size=size,
        background=background,
    )
    return {
        "source": source,
        "output": str(saved),
        "provider": provider,
        "mode": "animation",
        "frames": frames or _default_frames(),
        "fps": fps or _default_fps(),
        "background": background,
    }


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    # Avoid stealing compose_3d ("create 3d model of X" without video).
    if re.search(r"(?i)\b(?:create|make|generate|build)\s+(?:a\s+)?3d\s+model\b", t):
        if not re.search(r"(?i)\b(?:video|animation|turntable|movie|clip)\b", t):
            return []

    # Avoid model_to_image ("render model.obj as png").
    if re.search(r"(?i)\b(?:image|png|picture|photo|still)\b", t) and not re.search(
        r"(?i)\b(?:video|animation|turntable|movie|clip)\b", t
    ):
        return []

    explicit = _explicit_cli_argv(t)
    if explicit:
        return explicit
    if not _is_model_video_request(t):
        return []

    model = _model_path(t)
    sub = "animate" if _is_animation_request(t) else "render"
    argv: list[str] = [sub]
    if model:
        argv.append(model)

    if sub == "render" and re.search(r"(?i)\b(?:turntable|rotate|spinning|360)\b", t):
        argv.extend(["--backend", "blender"])

    frames = re.search(r"(?i)\b(\d+)\s*(?:frames?)\b", t)
    if frames:
        argv.extend(["--frames", frames.group(1)])

    dur = re.search(r"(?i)\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", t)
    if dur:
        argv.extend(["--duration", dur.group(1)])

    fps = re.search(r"(?i)\b(\d+)\s*fps\b", t)
    if fps:
        argv.extend(["--fps", fps.group(1)])

    out_flag = re.search(r"(?:^|\s)(?:-o|--output)\s+(\S+)", t)
    if out_flag:
        argv.extend(["-o", out_flag.group(1)])
    else:
        out = re.search(
            r"(?i)\b(?:to|into|save\s+to|output(?:\s+to)?)\s+([^\s]+\.(?:mp4|mov|webm))\b",
            t,
        )
        if out:
            argv.extend(["-o", out.group(1)])

    renders = re.search(
        r"(?i)\b(?:from|using)\s+(?:renders?\s+in\s+)?(?P<dir>(?:~|/|\./|\.\./)?[^\s]+/?)\b",
        t,
    )
    if renders and not model:
        argv.extend(["--renders", renders.group("dir")])

    if not argv or len(argv) == 1:
        return []
    return argv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Create turntable or animated character videos from 3D models "
            "(Blender) or preview-image slideshows"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  model_video render chair.obj\n"
            "  model_video render gear.glb --frames 180 --fps 30 -o out.mp4\n"
            "  model_video animate character_run.fbx -o playground-run.mp4 --frames 90 --fps 30\n"
            "  model_video render --renders ./preview-frames/ -o spin.mp4\n"
            "  model_video check\n"
            "\n"
            "Animated characters: use `animate` with a rigged FBX from Mixamo "
            "(mixamo.com → pick character → add run/walk animation → Download FBX).\n"
            "\n"
            "Backends: auto (Blender turntable, else preview slideshow), blender, slideshow.\n"
            "Requires Blender on PATH for .obj/.glb/.fbx rendering.\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_render = sub.add_parser("render", help="Render a turntable video from a 3D model")
    p_render.add_argument("source", nargs="?", help="3D model path (.obj, .glb, .fbx, .stl)")
    p_render.add_argument("-o", "--output", help="Output MP4 path")
    p_render.add_argument(
        "--backend",
        choices=["auto", "blender", "turntable", "slideshow"],
        default="auto",
        help="Render backend (default: auto)",
    )
    p_render.add_argument(
        "--frames",
        type=int,
        default=None,
        help=f"Turntable frame count (default: {DEFAULT_FRAMES} or MODEL_VIDEO_FRAMES)",
    )
    p_render.add_argument(
        "--fps",
        type=int,
        default=None,
        help=f"Output video FPS (default: {DEFAULT_FPS} or MODEL_VIDEO_FPS)",
    )
    p_render.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Target video duration in seconds (sets frames from fps when --frames omitted)",
    )
    p_render.add_argument("--size", type=int, default=DEFAULT_SIZE, help="Render resolution (square)")
    p_render.add_argument(
        "--angle",
        choices=["auto", *ANGLE_PRESETS],
        default="auto",
        help="Camera angle preset",
    )
    p_render.add_argument("--task", default="", help="Visual purpose for camera selection")
    p_render.add_argument(
        "--renders",
        help="Directory of existing preview PNG/JPG frames (slideshow backend)",
    )
    p_render.add_argument(
        "--slide-duration",
        type=float,
        default=0.5,
        help="Seconds per preview image in slideshow mode",
    )
    p_render.add_argument("--audio", help="Optional background audio for slideshow mode")
    p_render.add_argument(
        "--mode",
        choices=["turntable", "animation"],
        default="turntable",
        help="Render mode (animation redirects to animate pipeline)",
    )
    p_render.set_defaults(func=cmd_render)

    p_animate = sub.add_parser(
        "animate",
        help="Render rigged character animation from FBX/GLB (.fbx run cycles from Mixamo)",
    )
    p_animate.add_argument("source", help="Rigged model with animation (.fbx, .glb, .gltf)")
    p_animate.add_argument("-o", "--output", help="Output MP4 path")
    p_animate.add_argument(
        "--frames",
        type=int,
        default=None,
        help=f"Frame count to render (default: {DEFAULT_FRAMES} or MODEL_VIDEO_FRAMES)",
    )
    p_animate.add_argument(
        "--fps",
        type=int,
        default=None,
        help=f"Output video FPS (default: {DEFAULT_FPS} or MODEL_VIDEO_FPS)",
    )
    p_animate.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Target video duration in seconds (sets frames from fps when --frames omitted)",
    )
    p_animate.add_argument("--size", type=int, default=DEFAULT_SIZE, help="Render resolution (square)")
    p_animate.add_argument(
        "--background",
        dest="background",
        action="store_true",
        default=True,
        help="Add ground plane scene (default: on)",
    )
    p_animate.add_argument(
        "--no-background",
        dest="background",
        action="store_false",
        help="Transparent/minimal scene without ground plane",
    )
    p_animate.set_defaults(func=cmd_animate)

    p_parse = sub.add_parser("parse", help="Parse natural language → model_video args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify Blender and ffmpeg availability")
    p_check.set_defaults(func=cmd_check)

    return p


def cmd_check(_args: argparse.Namespace) -> int:
    from arka.core.output_layout import error, info, section, success, table

    ok = True
    section("Model video check")
    blender = _find_blender()
    if blender:
        success(f"blender ({blender})")
    else:
        error("blender — install Blender and add `blender` to PATH for turntable rendering")
        ok = False
    try:
        _require_ffmpeg()
        success("ffmpeg")
    except SystemExit:
        error("ffmpeg — brew install ffmpeg  or  sudo apt install ffmpeg")
        ok = False
    if _which("ffprobe"):
        success("ffprobe")
    table(
        ["Setting", "Value"],
        [
            ("Backends", "auto, blender, slideshow"),
            ("Default frames", str(_default_frames())),
            ("Default fps", str(_default_fps())),
            ("Supported models", ", ".join(sorted(MODEL_EXTS))),
            ("Animation formats", ", ".join(sorted(ANIMATION_EXTS))),
        ],
    )
    if not ok:
        info("Install missing tools above, then rerun: arka model_video check")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    if getattr(args, "mode", "turntable") == "animation":
        if not args.source:
            print("source model path is required for animation mode", file=sys.stderr)
            return 1
        return cmd_animate(args)

    frames = args.frames
    fps = args.fps or _default_fps()
    if frames is None and args.duration is not None:
        frames = max(12, int(args.duration * fps))

    if args.renders and not args.source:
        source = args.renders
    elif args.source:
        source = args.source
    else:
        print("source model path or --renders is required", file=sys.stderr)
        return 1

    from arka.core.output_layout import error, info, result_box, success

    info(f"Creating 3D model video from {source}")
    try:
        saved, provider = create_model_video(
            source,
            args.output,
            backend=args.backend,
            frames=frames,
            fps=fps,
            size=max(256, min(args.size, 4096)),
            angle=args.angle,
            task=args.task,
            renders=args.renders,
            slide_duration=args.slide_duration,
            audio=args.audio,
        )
    except (FileNotFoundError, RuntimeError, ValueError, SystemExit) as exc:
        error(str(exc))
        return 1
    result_box("Model video saved", f"Provider: {provider}\nPath: {saved}")
    success(f"Saved ({provider}): {saved}")
    print(saved)
    return 0


def cmd_animate(args: argparse.Namespace) -> int:
    frames = args.frames
    fps = args.fps or _default_fps()
    if frames is None and args.duration is not None:
        frames = max(12, int(args.duration * fps))

    source = getattr(args, "source", None)
    if not source:
        print("source model path is required", file=sys.stderr)
        return 1

    from arka.core.output_layout import error, info, result_box, success

    info(f"Rendering animated character from {source}")
    try:
        saved, provider = render_animation(
            source,
            args.output,
            frames=frames,
            fps=fps,
            size=max(256, min(args.size, 4096)),
            background=getattr(args, "background", True),
        )
    except (FileNotFoundError, RuntimeError, ValueError, SystemExit) as exc:
        error(str(exc))
        return 1
    result_box("Animation saved", f"Provider: {provider}\nPath: {saved}")
    success(f"Saved ({provider}): {saved}")
    print(saved)
    return 0


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    argv = _normalize_argv(list(argv if argv is not None else sys.argv[1:]))
    if not argv:
        build_parser().print_help()
        return 0
    if argv in (["-h"], ["--help"]):
        build_parser().print_help()
        return 0
    if _is_subcommand(argv):
        parser = build_parser()
        args = parser.parse_args(argv)
        return int(args.func(args))
    nl = nl_to_argv(" ".join(argv))
    if nl:
        argv = nl
    elif Path(argv[0]).suffix.lower() in MODEL_EXTS and Path(argv[0]).expanduser().is_file():
        argv = ["render", *argv]
    else:
        build_parser().print_help()
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
