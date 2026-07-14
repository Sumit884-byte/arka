#!/usr/bin/env python3
"""Compose 3D models — procedural meshes (OBJ/STL) and LLM-planned geometry."""

from __future__ import annotations

import argparse
import math
import os
import re
import shlex
import sys
from pathlib import Path

SUPPORTED_FORMATS = ("obj", "stl", "glb", "all")
SHAPE_COMMANDS = ("cube", "sphere", "cylinder", "cone", "gear", "vase", "torus")

_VIEWER_LINK = "https://3dviewer.net/#model="


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def output_dir() -> Path:
    override = _env("MODEL_3D_OUTPUT_DIR")
    if override:
        base = Path(override).expanduser()
    else:
        base = Path.home() / "Models" / "arka-generated"
    base.mkdir(parents=True, exist_ok=True)
    return base


def compute_normal(
    v1: tuple[float, float, float],
    v2: tuple[float, float, float],
    v3: tuple[float, float, float],
) -> tuple[float, float, float]:
    ax, ay, az = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
    bx, by, bz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length > 1e-8:
        return nx / length, ny / length, nz / length
    return 0.0, 0.0, 0.0


def generate_cube(
    width: float = 1.0, height: float = 1.0, depth: float = 1.0
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    x, y, z = width / 2.0, height / 2.0, depth / 2.0
    vertices = [
        (-x, -y, -z),
        (x, -y, -z),
        (x, y, -z),
        (-x, y, -z),
        (-x, -y, z),
        (x, -y, z),
        (x, y, z),
        (-x, y, z),
    ]
    faces = [
        (5, 6, 7),
        (5, 7, 8),
        (2, 1, 4),
        (2, 4, 3),
        (6, 2, 3),
        (6, 3, 7),
        (1, 5, 8),
        (1, 8, 4),
        (6, 5, 1),
        (6, 1, 2),
        (8, 7, 3),
        (8, 3, 4),
    ]
    return vertices, faces


def generate_sphere(
    radius: float = 1.0, segments: int = 16, rings: int = 16
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    segments = max(3, segments)
    rings = max(3, rings)
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, radius)]
    for i in range(1, rings):
        theta = i * math.pi / rings
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)
        for j in range(segments):
            phi = j * 2.0 * math.pi / segments
            vertices.append(
                (
                    radius * sin_theta * math.cos(phi),
                    radius * sin_theta * math.sin(phi),
                    radius * cos_theta,
                )
            )
    vertices.append((0.0, 0.0, -radius))
    south_pole_idx = len(vertices)
    faces: list[tuple[int, int, int]] = []
    for j in range(segments):
        next_j = (j + 1) % segments
        faces.append((1, 2 + next_j, 2 + j))
    for r in range(rings - 2):
        ring_start = 2 + r * segments
        next_ring_start = ring_start + segments
        for j in range(segments):
            next_j = (j + 1) % segments
            v1 = ring_start + j
            v2 = ring_start + next_j
            v3 = next_ring_start + next_j
            v4 = next_ring_start + j
            faces.append((v1, v2, v3))
            faces.append((v1, v3, v4))
    last_ring_start = 2 + (rings - 2) * segments
    for j in range(segments):
        next_j = (j + 1) % segments
        faces.append((south_pole_idx, last_ring_start + j, last_ring_start + next_j))
    return vertices, faces


def generate_cylinder(
    radius: float = 1.0, height: float = 2.0, segments: int = 16
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    segments = max(3, segments)
    h2 = height / 2.0
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, h2), (0.0, 0.0, -h2)]
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), h2))
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), -h2))
    faces: list[tuple[int, int, int]] = []
    top_ring_start = 3
    bottom_ring_start = 3 + segments
    for i in range(segments):
        next_i = (i + 1) % segments
        faces.append((1, top_ring_start + next_i, top_ring_start + i))
        faces.append((2, bottom_ring_start + i, bottom_ring_start + next_i))
        v1 = top_ring_start + i
        v2 = top_ring_start + next_i
        v3 = bottom_ring_start + next_i
        v4 = bottom_ring_start + i
        faces.append((v1, v2, v3))
        faces.append((v1, v3, v4))
    return vertices, faces


def generate_cone(
    radius: float = 1.0, height: float = 2.0, segments: int = 16
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    segments = max(3, segments)
    h2 = height / 2.0
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, h2), (0.0, 0.0, -h2)]
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), -h2))
    faces: list[tuple[int, int, int]] = []
    ring_start = 3
    for i in range(segments):
        next_i = (i + 1) % segments
        faces.append((1, ring_start + i, ring_start + next_i))
        faces.append((2, ring_start + next_i, ring_start + i))
    return vertices, faces


def generate_torus(
    major_radius: float = 1.0,
    minor_radius: float = 0.3,
    segments: int = 24,
    rings: int = 16,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    segments = max(3, segments)
    rings = max(3, rings)
    vertices: list[tuple[float, float, float]] = []
    for i in range(rings):
        u = i * 2.0 * math.pi / rings
        cos_u, sin_u = math.cos(u), math.sin(u)
        for j in range(segments):
            v = j * 2.0 * math.pi / segments
            cos_v, sin_v = math.cos(v), math.sin(v)
            x = (major_radius + minor_radius * cos_v) * cos_u
            y = (major_radius + minor_radius * cos_v) * sin_u
            z = minor_radius * sin_v
            vertices.append((x, y, z))
    faces: list[tuple[int, int, int]] = []
    for i in range(rings):
        next_i = (i + 1) % rings
        for j in range(segments):
            next_j = (j + 1) % segments
            a = i * segments + j + 1
            b = i * segments + next_j + 1
            c = next_i * segments + next_j + 1
            d = next_i * segments + j + 1
            faces.append((a, b, c))
            faces.append((a, c, d))
    return vertices, faces


def generate_gear(
    outer_radius: float = 1.0,
    inner_radius: float = 0.2,
    height: float = 0.3,
    teeth: int = 12,
    segments: int = 64,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    teeth = max(6, teeth)
    segments = max(teeth * 4, segments)
    h2 = height / 2.0
    profile: list[tuple[float, float]] = []
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        tooth_phase = (theta * teeth / (2.0 * math.pi)) % 1.0
        if tooth_phase < 0.35:
            r = outer_radius
        elif tooth_phase < 0.5:
            t = (tooth_phase - 0.35) / 0.15
            r = outer_radius * (1.0 - 0.15 * t) + (outer_radius * 0.85) * t
        else:
            r = outer_radius * 0.85
        profile.append((r * math.cos(theta), r * math.sin(theta)))

    vertices: list[tuple[float, float, float]] = []
    for x, y in profile:
        vertices.append((x, y, h2))
    for x, y in profile:
        vertices.append((x, y, -h2))
    vertices.append((0.0, 0.0, h2))
    vertices.append((0.0, 0.0, -h2))
    top_center = len(vertices) - 1
    bottom_center = len(vertices)

    faces: list[tuple[int, int, int]] = []
    n = len(profile)
    for i in range(n):
        next_i = (i + 1) % n
        top_a = i + 1
        top_b = next_i + 1
        bot_a = i + 1 + n
        bot_b = next_i + 1 + n
        faces.append((top_a, top_b, bot_b))
        faces.append((top_a, bot_b, bot_a))
        faces.append((top_center, top_b, top_a))
        faces.append((bottom_center, bot_a, bot_b))

    if inner_radius > 0:
        hole_segments = max(12, teeth)
        hole_top_start = len(vertices) + 1
        for i in range(hole_segments):
            theta = i * 2.0 * math.pi / hole_segments
            vertices.append((inner_radius * math.cos(theta), inner_radius * math.sin(theta), h2))
        hole_bot_start = len(vertices) + 1
        for i in range(hole_segments):
            theta = i * 2.0 * math.pi / hole_segments
            vertices.append((inner_radius * math.cos(theta), inner_radius * math.sin(theta), -h2))
        for i in range(hole_segments):
            next_i = (i + 1) % hole_segments
            faces.append((hole_top_start + next_i, hole_top_start + i, hole_bot_start + i))
            faces.append((hole_top_start + next_i, hole_bot_start + i, hole_bot_start + next_i))
    return vertices, faces


def generate_vase(
    height: float = 0.2,
    max_radius: float = 0.06,
    neck_radius: float = 0.03,
    segments: int = 32,
    rings: int = 24,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    segments = max(8, segments)
    rings = max(8, rings)
    profile: list[tuple[float, float]] = []
    for i in range(rings + 1):
        t = i / rings
        z = -height / 2.0 + height * t
        if t < 0.08:
            r = max_radius * (t / 0.08) * 0.6
        elif t < 0.35:
            r = max_radius * (0.6 + 0.4 * ((t - 0.08) / 0.27))
        elif t < 0.7:
            r = max_radius
        elif t < 0.88:
            r = max_radius * (1.0 - 0.55 * ((t - 0.7) / 0.18))
        else:
            r = neck_radius + (max_radius * 0.45 - neck_radius) * ((t - 0.88) / 0.12)
        profile.append((r, z))

    vertices: list[tuple[float, float, float]] = []
    for r, z in profile:
        for j in range(segments):
            theta = j * 2.0 * math.pi / segments
            vertices.append((r * math.cos(theta), r * math.sin(theta), z))

    faces: list[tuple[int, int, int]] = []
    for i in range(rings):
        for j in range(segments):
            next_j = (j + 1) % segments
            a = i * segments + j + 1
            b = i * segments + next_j + 1
            c = (i + 1) * segments + next_j + 1
            d = (i + 1) * segments + j + 1
            faces.append((a, b, c))
            faces.append((a, c, d))

    bottom_center = len(vertices) + 1
    vertices.append((0.0, 0.0, profile[0][1]))
    for j in range(segments):
        next_j = (j + 1) % segments
        faces.append((bottom_center, next_j + 1, j + 1))
    return vertices, faces


def write_obj(
    vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]
) -> str:
    lines = ["# Generated by Arka compose_3d", ""]
    for v in vertices:
        lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    lines.append("")
    for f in faces:
        lines.append(f"f {f[0]} {f[1]} {f[2]}")
    return "\n".join(lines) + "\n"


def write_stl(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    name: str = "arka_model",
) -> str:
    clean_name = re.sub(r"[^\w.-]+", "_", name)
    lines = [f"solid {clean_name}"]
    for f in faces:
        v1 = vertices[f[0] - 1]
        v2 = vertices[f[1] - 1]
        v3 = vertices[f[2] - 1]
        nx, ny, nz = compute_normal(v1, v2, v3)
        lines.extend(
            [
                f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}",
                "    outer loop",
                f"      vertex {v1[0]:.6f} {v1[1]:.6f} {v1[2]:.6f}",
                f"      vertex {v2[0]:.6f} {v2[1]:.6f} {v2[2]:.6f}",
                f"      vertex {v3[0]:.6f} {v3[1]:.6f} {v3[2]:.6f}",
                "    endloop",
                "  endfacet",
            ]
        )
    lines.append(f"endsolid {clean_name}")
    return "\n".join(lines) + "\n"


def write_glb(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    path: Path,
) -> bool:
    try:
        import numpy as np
        import trimesh
    except ImportError:
        return False
    verts = np.array(vertices, dtype=np.float64)
    tris = np.array([[f[0] - 1, f[1] - 1, f[2] - 1] for f in faces], dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    mesh.export(path)
    return True


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]+", "", name.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug or "model"


def unique_paths(base: Path, name: str, formats: set[str]) -> dict[str, Path]:
    slug = slugify(name)
    counter = 0
    while True:
        suffix = f"_{counter}" if counter else ""
        candidate = {fmt: base / f"{slug}{suffix}.{fmt}" for fmt in formats}
        if not any(p.exists() for p in candidate.values()):
            return candidate
        counter += 1


def parse_obj(
    obj_text: str,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line in obj_text.splitlines():
        line = line.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    pass
        elif line.startswith("f "):
            parts = line.split()
            if len(parts) >= 4:
                face_vertices: list[int] = []
                for part in parts[1:]:
                    try:
                        face_vertices.append(int(part.split("/")[0]))
                    except ValueError:
                        pass
                if len(face_vertices) == 3:
                    faces.append((face_vertices[0], face_vertices[1], face_vertices[2]))
                elif len(face_vertices) == 4:
                    faces.append((face_vertices[0], face_vertices[1], face_vertices[2]))
                    faces.append((face_vertices[0], face_vertices[2], face_vertices[3]))
                elif len(face_vertices) > 4:
                    for i in range(1, len(face_vertices) - 1):
                        faces.append(
                            (face_vertices[0], face_vertices[i], face_vertices[i + 1])
                        )
    return vertices, faces


def normalize_format(raw: str | None) -> str:
    fmt = (raw or _env("MODEL_3D_DEFAULT_FORMAT", "all")).strip().lower()
    return fmt if fmt in SUPPORTED_FORMATS else "all"


def parse_formats_arg(raw: str | None) -> set[str]:
    fmt = normalize_format(raw)
    if fmt == "all":
        return {"obj", "stl"}
    return {fmt}


def _strip_wrapping_quotes(text: str) -> str:
    t = (text or "").strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t


def _normalize_nl_text(text: str) -> str:
    return _strip_wrapping_quotes(text.strip())


_HUMAN_FIGURE_RE = re.compile(
    r"\b(?:boy|girl|man|woman|person|people|human|character|figure|child|kid|boyfriend|girlfriend)\b",
    re.I,
)


def _is_human_figure_request(prompt: str) -> bool:
    return bool(_HUMAN_FIGURE_RE.search(prompt))


def _any_llm_available() -> bool:
    try:
        from arka.llm.fallback import provider_available, provider_specs
    except ImportError:
        return False
    return any(provider_available(spec.slug) for spec in provider_specs())


def _mesh_indices_valid(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> bool:
    if not vertices or not faces:
        return False
    limit = len(vertices)
    return all(1 <= idx <= limit for face in faces for idx in face)


def _parse_length_cm(text: str, default_m: float) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b", text, re.I)
    if m:
        return float(m.group(1)) / 100.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)\b", text, re.I)
    if m:
        return float(m.group(1)) / 1000.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\b", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:in|inches?)\b", text, re.I)
    if m:
        return float(m.group(1)) * 0.0254
    m = re.search(r"\b(?:height|tall|size)\s+(\d+(?:\.\d+)?)\b", text, re.I)
    if m:
        return float(m.group(1)) / 100.0
    return default_m


def _is_compose_3d_request(text: str) -> bool:
    t = _normalize_nl_text(text).lower()
    if not t:
        return False
    if re.match(r"^(?:arka\s+)?(?:compose_3d|three_d|3d|3d_model)\b", t):
        return True
    if re.search(
        r"\b(?:"
        r"3d\s+model|"
        r"create\s+(?:a|an|the)\s+3d|"
        r"generate\s+(?:a|an|the)\s+3d|"
        r"make\s+(?:a|an|the)\s+3d|"
        r"compose\s+(?:a|an|the)\s+3d|"
        r"create\s+3d|"
        r"generate\s+3d|"
        r"make\s+3d|"
        r"compose\s+3d|"
        r"3d\s+cube|"
        r"3d\s+sphere|"
        r"3d\s+cylinder|"
        r"3d\s+cone|"
        r"3d\s+gear|"
        r"3d\s+vase|"
        r"generate\s+stl|"
        r"generate\s+obj"
        r")\b",
        t,
    ):
        return True
    return False


def nl_to_argv(text: str) -> list[str]:
    t = _normalize_nl_text(text)
    if not t or not _is_compose_3d_request(t):
        return []

    clean = re.sub(
        r"^(?:arka\s+)?(?:compose_3d|three_d|3d|3d_model|create|generate|make|compose)\s+"
        r"(?:a\s+|an\s+|the\s+)?(?:3d\s+)?(?:model\s+of\s+|shape\s+of\s+)?",
        "",
        t,
        flags=re.I,
    ).strip()
    clean = re.sub(r"^(?:a|an|the)\s+", "", clean, flags=re.I).strip()
    clean = re.sub(r"(?i)\b(?:as|in|to)\s+(?:stl|obj|glb)\b", "", clean).strip()

    fmt_match = re.search(
        r"(?i)\b(?:generate|as|in|to|format)\s+(stl|obj|glb|all)\b", t
    )
    argv: list[str] = []
    if fmt_match:
        argv.extend(["--format", fmt_match.group(1).lower()])

    shape = None
    if re.search(r"\b(?:cube|box|block)\b", clean, re.I):
        shape = "cube"
    elif re.search(r"\b(?:sphere|ball|globe)\b", clean, re.I):
        shape = "sphere"
    elif re.search(r"\b(?:cylinder|tube)\b", clean, re.I):
        shape = "cylinder"
    elif re.search(r"\bcone\b", clean, re.I):
        shape = "cone"
    elif re.search(r"\b(?:gear|cog)\b", clean, re.I):
        shape = "gear"
    elif re.search(r"\bvase\b", clean, re.I):
        shape = "vase"
    elif re.search(r"\btorus\b", clean, re.I):
        shape = "torus"
    elif re.search(r"\b(?:mug|cup|coffee\s+mug)\b", clean, re.I):
        shape = "cylinder"
        argv.extend(["--radius", "0.04", "--height", "0.1"])
    elif re.search(r"\b(?:phone\s+stand|stand)\b", clean, re.I):
        shape = "cube"
        argv.extend(["--width", "0.08", "--height", "0.12", "--depth", "0.05"])

    if shape:
        argv = [shape, *argv]
        rad_m = re.search(r"\bradius\s+(\d+(?:\.\d+)?)\b", clean, re.I)
        if rad_m:
            argv.extend(["--radius", rad_m.group(1)])
        w_m = re.search(r"\bwidth\s+(\d+(?:\.\d+)?)\b", clean, re.I)
        if w_m:
            argv.extend(["--width", w_m.group(1)])
        h_m = re.search(r"\bheight\s+(\d+(?:\.\d+)?)\b", clean, re.I)
        if h_m:
            argv.extend(["--height", h_m.group(1)])
        d_m = re.search(r"\bdepth\s+(\d+(?:\.\d+)?)\b", clean, re.I)
        if d_m:
            argv.extend(["--depth", d_m.group(1)])
        seg_m = re.search(r"\bsegments\s+(\d+)\b", clean, re.I)
        if seg_m:
            argv.extend(["--segments", seg_m.group(1)])
        teeth_m = re.search(r"\bteeth\s+(\d+)\b", clean, re.I)
        if teeth_m:
            argv.extend(["--teeth", teeth_m.group(1)])
        name_m = re.search(r"\bname(?:d)?\s+([A-Za-z0-9_-]+)\b", clean, re.I)
        if name_m:
            argv.extend(["--name", name_m.group(1)])
        elif shape == "vase":
            height = _parse_length_cm(clean, 0.2)
            argv.extend(["--height", str(height)])
            argv.extend(["--name", "vase"])
        elif shape == "gear":
            argv.extend(["--name", "gear"])
        return argv

    if re.search(r"(?i)\b(?:stl|obj|glb)\b", t) and not fmt_match:
        m = re.search(r"(?i)\b(?:stl|obj|glb)\b", t)
        if m:
            argv.extend(["--format", m.group(0).lower()])

    prompt = clean or t
    if prompt:
        return [prompt, *argv]
    return []


def route_command(text: str) -> str | None:
    argv = nl_to_argv(text.strip())
    if not argv:
        return None
    return "compose_3d " + " ".join(shlex.quote(a) for a in argv)


def generate_llm_model(prompt: str) -> str:
    from arka.llm.cli import llm_complete

    model_prompt = prompt
    if _is_human_figure_request(prompt):
        model_prompt = (
            f"a simple blocky stylized {prompt} built from basic geometric primitives "
            "(rectangular torso, cylindrical limbs, small cube head), centered at origin"
        )

    system_prompt = (
        "You are a 3D modeling expert. Generate a complete Wavefront OBJ file for:\n"
        f"'{model_prompt}'\n\n"
        "Output vertices ('v x y z') and triangular faces ('f v1 v2 v3'). "
        "Use meters, centered near origin, printable proportions.\n"
        "Rules:\n"
        "1. ONLY raw OBJ text.\n"
        "2. No markdown fences or explanations.\n"
        "3. Face indices must reference valid vertex numbers.\n"
    )
    obj_content = llm_complete(
        system=system_prompt,
        user=f"Create a 3D model of: {model_prompt}",
        temperature=0.2,
        task="create_3d_model",
        skill="compose_3d",
    )
    cleaned = [line for line in obj_content.splitlines() if not line.strip().startswith("```")]
    return "\n".join(cleaned).strip() + "\n"


def _print_result(
    *,
    name: str,
    shape: str,
    saved: dict[str, Path],
    used_llm: bool = False,
) -> None:
    print("━━━ 3D Model Created ━━━")
    print(f"Shape: {shape}")
    if used_llm:
        print("Method: AI-generated geometry")
    else:
        print("Method: procedural mesh")
    print("")
    print("Files:")
    for fmt, path in sorted(saved.items()):
        print(f"  {fmt.upper()}: {path}")
    print("")
    print("Open locally:")
    if sys.platform == "darwin":
        print("  macOS Preview: open the OBJ or STL file")
        print("  Blender: blender <file>")
    elif sys.platform.startswith("linux"):
        print("  Blender: blender <file>")
    print("  Online viewer: https://3dviewer.net (drag & drop your file)")
    if "obj" in saved:
        print(f"  Direct link: {_VIEWER_LINK}{saved['obj']}")


def save_mesh(
    *,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    name: str,
    formats: set[str],
) -> dict[str, Path]:
    if not vertices or not faces:
        raise ValueError("empty mesh")
    base = output_dir()
    paths = unique_paths(base, name, formats)
    saved: dict[str, Path] = {}
    if "obj" in formats:
        paths["obj"].write_text(write_obj(vertices, faces), encoding="utf-8")
        saved["obj"] = paths["obj"]
    if "stl" in formats:
        paths["stl"].write_text(write_stl(vertices, faces, name), encoding="utf-8")
        saved["stl"] = paths["stl"]
    if "glb" in formats:
        if write_glb(vertices, faces, paths["glb"]):
            saved["glb"] = paths["glb"]
    return saved


def _shape_from_args(args: argparse.Namespace) -> tuple[str, str, list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    cmd = args.shape.lower()
    if cmd in ("cube", "box"):
        return "cube", args.name or "cube", *generate_cube(args.width, args.height, args.depth)
    if cmd == "sphere":
        return "sphere", args.name or "sphere", *generate_sphere(args.radius, args.segments, args.rings)
    if cmd == "cylinder":
        return "cylinder", args.name or "cylinder", *generate_cylinder(args.radius, args.height, args.segments)
    if cmd == "cone":
        return "cone", args.name or "cone", *generate_cone(args.radius, args.height, args.segments)
    if cmd == "gear":
        return "gear", args.name or "gear", *generate_gear(
            args.radius, args.inner_radius, args.height, args.teeth, args.segments
        )
    if cmd == "vase":
        return "vase", args.name or "vase", *generate_vase(
            args.height, args.max_radius, args.neck_radius, args.segments, args.rings
        )
    if cmd == "torus":
        return "torus", args.name or "torus", *generate_torus(
            args.major_radius, args.minor_radius, args.segments, args.rings
        )
    raise ValueError(f"unknown shape: {cmd}")


def _save_obj_only(obj_content: str, prompt: str, *, reason: str) -> int:
    fallback_name = slugify(prompt)
    obj_path = output_dir() / f"{fallback_name}.obj"
    obj_path.write_text(obj_content, encoding="utf-8")
    print("━━━ 3D Model Created ━━━")
    print(f"Shape: {prompt}")
    print(f"Method: AI-generated OBJ (STL conversion skipped — {reason})")
    print(f"  OBJ: {obj_path}")
    return 0


def _human_figure_hint(prompt: str) -> None:
    print(
        f"Human figures like {prompt!r} need LLM compose_3d or external modeling tools.",
        file=sys.stderr,
    )
    print(
        "Configure an LLM in ~/.config/arka/.env (see `arka provider list`), "
        "or try procedural shapes: compose_3d gear, compose_3d cube, compose_3d vase.",
        file=sys.stderr,
    )
    print("For GLB export: pip install -e '.[3d]'", file=sys.stderr)


def cmd_compose(args: argparse.Namespace) -> int:
    formats = parse_formats_arg(args.format)
    if args.shape.lower() in SHAPE_COMMANDS:
        shape, name, vertices, faces = _shape_from_args(args)
        saved = save_mesh(vertices=vertices, faces=faces, name=name, formats=formats)
        _print_result(name=name, shape=shape, saved=saved)
        return 0

    prompt = _normalize_nl_text(args.shape)
    if _is_human_figure_request(prompt) and not _any_llm_available():
        _human_figure_hint(prompt)
        return 1

    print(f"Generating custom 3D model: {prompt!r}")
    try:
        obj_content = generate_llm_model(prompt)
    except Exception as exc:
        print(f"Error: LLM generation failed — {exc}", file=sys.stderr)
        if _is_human_figure_request(prompt):
            _human_figure_hint(prompt)
        else:
            print(
                "Tip: configure an LLM in .env, or request a basic shape (cube, gear, vase).",
                file=sys.stderr,
            )
        return 1

    vertices, faces = parse_obj(obj_content)
    if not _mesh_indices_valid(vertices, faces):
        reason = "could not parse faces" if not vertices or not faces else "invalid face indices"
        return _save_obj_only(obj_content, prompt, reason=reason)

    try:
        saved = save_mesh(vertices=vertices, faces=faces, name=prompt, formats=formats)
    except (IndexError, ValueError):
        return _save_obj_only(obj_content, prompt, reason="mesh validation failed")

    _print_result(name=prompt, shape=prompt, saved=saved, used_llm=True)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(_normalize_nl_text(" ".join(args.text)))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    print("✓ compose_3d core (no extra deps required for OBJ/STL)")
    try:
        import trimesh  # noqa: F401
        import numpy  # noqa: F401

        print("✓ trimesh + numpy (GLB export available)")
    except ImportError:
        print("○ trimesh not installed — GLB export unavailable")
        print("  Install: pip install -e '.[3d]'")
    try:
        from arka.llm.cli import llm_complete  # noqa: F401

        print("✓ LLM fallback available for custom shapes")
    except ImportError:
        print("○ LLM module unavailable — custom AI shapes disabled")
    print(f"Output directory: {output_dir()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compose 3D models — procedural meshes and AI shapes")
    sub = p.add_subparsers(dest="cmd")

    p_compose = sub.add_parser("compose", help="Generate a 3D model")
    p_compose.add_argument("shape", help="Shape command or natural-language prompt")
    p_compose.add_argument("--width", type=float, default=1.0)
    p_compose.add_argument("--height", type=float, default=1.0)
    p_compose.add_argument("--depth", type=float, default=1.0)
    p_compose.add_argument("--radius", type=float, default=1.0)
    p_compose.add_argument("--inner-radius", type=float, default=0.2)
    p_compose.add_argument("--major-radius", type=float, default=1.0)
    p_compose.add_argument("--minor-radius", type=float, default=0.3)
    p_compose.add_argument("--max-radius", type=float, default=0.06)
    p_compose.add_argument("--neck-radius", type=float, default=0.03)
    p_compose.add_argument("--segments", type=int, default=16)
    p_compose.add_argument("--rings", type=int, default=16)
    p_compose.add_argument("--teeth", type=int, default=12)
    p_compose.add_argument("--name", default="")
    p_compose.add_argument("-f", "--format", default="all", choices=SUPPORTED_FORMATS)
    p_compose.set_defaults(func=cmd_compose)

    p_parse = sub.add_parser("parse", help="Parse natural language → compose_3d args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify compose_3d dependencies")
    p_check.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] in {"-h", "--help", "help"}:
        build_parser().print_help()
        return 0
    if argv[0] == "parse":
        return cmd_parse(build_parser().parse_args(argv))
    if argv[0] == "check":
        return cmd_check(argparse.Namespace())

    nl = nl_to_argv(" ".join(argv))
    if nl:
        argv = ["compose", *nl]
    elif argv[0] not in {"compose", "check"}:
        argv = ["compose", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
