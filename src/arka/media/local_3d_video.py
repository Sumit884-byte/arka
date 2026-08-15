"""Fully local text -> 3D -> video pipeline. No cloud APIs.

Stage 1: generate a 3D mesh from a text prompt using diffusers'
ShapEPipeline (runs on local CPU/GPU via torch — same dependency
already used by compose_3d_backends.py's Shap-E integration).

Stage 2: reuse the existing local Blender-based turntable renderer
(arka.media.model_video, action=render) to turn that mesh into an
.mp4, entirely on-machine.

Requires: pip install -e '.[3d-ai]'  (installs torch + diffusers)
and a local Blender executable on PATH for stage 2.

CLI:
    python -m arka.media.local_3d_video "a red sports car" --output out.mp4
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def check_available() -> tuple[bool, str]:
    try:
        from diffusers import ShapEPipeline  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False, "Missing deps — run: pip install -e '.[3d-ai]' + CUDA/CPU PyTorch"
    return True, "torch + diffusers installed"


def generate_mesh_locally(prompt: str, dest_dir: Path, guidance_scale: float = 15.0) -> Path:
    """Generate a 3D mesh from a text prompt entirely on-device via Shap-E."""
    import torch
    from diffusers import ShapEPipeline
    from diffusers.utils import export_to_ply

    device = "cuda" if torch.cuda.is_available() else "cpu"
    pipe = ShapEPipeline.from_pretrained("openai/shap-e", torch_dtype=torch.float32)
    pipe = pipe.to(device)

    result = pipe(
        prompt,
        guidance_scale=guidance_scale,
        num_inference_steps=64,
        frame_size=256,
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    slug = "_".join(prompt.lower().split())[:40]
    ply_path = dest_dir / f"{slug}.ply"
    export_to_ply(result.images[0], str(ply_path))
    return ply_path


def generate_3d_video_locally(
    prompt: str,
    output: Path,
    work_dir: Path | None = None,
    frames: int = 120,
    fps: int = 30,
) -> Path:
    """End-to-end: text prompt -> local mesh -> local turntable .mp4."""
    work_dir = work_dir or Path("./local_3d_work")
    mesh_path = generate_mesh_locally(prompt, work_dir)

    cmd = [
        sys.executable, "-m", "arka.media.model_video", "render",
        "--source", str(mesh_path),
        "--output", str(output),
        "--frames", str(frames),
        "--fps", str(fps),
        "--backend", "blender",
    ]
    subprocess.run(cmd, check=True)
    return output


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arka-local-3d-video")
    p.add_argument("prompt", help="Text description, e.g. 'a red sports car'")
    p.add_argument("--output", default="./local_3d_video.mp4")
    p.add_argument("--work-dir", default="./local_3d_work")
    p.add_argument("--frames", type=int, default=120)
    p.add_argument("--fps", type=int, default=30)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ok, msg = check_available()
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    out = generate_3d_video_locally(
