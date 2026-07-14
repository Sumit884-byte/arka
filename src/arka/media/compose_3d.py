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
SHAPE_COMMANDS = (
    "cube",
    "sphere",
    "cylinder",
    "cone",
    "gear",
    "vase",
    "torus",
    "boy",
    "girl",
    "person",
    "robot",
    "tree",
    "house",
    "car",
)
HUMANOID_STYLES = ("boy", "girl", "person", "man", "woman", "child", "kid")
QUALITY_SETTINGS: dict[str, dict[str, int]] = {
    "low": {"segments": 16, "rings": 12},
    "medium": {"segments": 32, "rings": 24},
    "high": {"segments": 64, "rings": 48},
}
MAX_LLM_VERTICES = 8000
MAX_LLM_FACES = 16000

_VIEWER_LINK = "https://gltf-viewer.donmccurdy.com/"
_VIEWER_LINK_OBJ = "https://3dviewer.net/#model="


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


def _has_trimesh() -> bool:
    try:
        import trimesh  # noqa: F401
    except ImportError:
        return False
    return True


def _quality_params(quality: str) -> dict[str, int]:
    return dict(QUALITY_SETTINGS.get(quality, QUALITY_SETTINGS["medium"]))


def _trimesh_to_raw(mesh: object) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    import numpy as np

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    vertices = [tuple(v) for v in verts]
    tris = [(int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1) for f in faces]
    return vertices, tris


def merge_meshes(
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for part_verts, part_faces in parts:
        offset = len(vertices)
        vertices.extend(part_verts)
        for f in part_faces:
            faces.append((f[0] + offset, f[1] + offset, f[2] + offset))
    return vertices, faces


def translate_mesh(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    moved = [(v[0] + dx, v[1] + dy, v[2] + dz) for v in vertices]
    return moved, list(faces)


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
    radius: float = 1.0, segments: int = 32, rings: int = 24
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    if _has_trimesh():
        import trimesh

        subdiv = max(2, min(5, segments // 8))
        mesh = trimesh.creation.icosphere(subdivisions=subdiv, radius=radius)
        return _trimesh_to_raw(mesh)
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
    radius: float = 1.0, height: float = 2.0, segments: int = 32
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    if _has_trimesh():
        import trimesh

        mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=max(3, segments))
        return _trimesh_to_raw(mesh)
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


def generate_hemisphere(
    radius: float = 1.0,
    segments: int = 24,
    rings: int = 12,
    upper: bool = True,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Half-sphere cap for capsule ends."""
    segments = max(3, segments)
    rings = max(2, rings // 2)
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, radius if upper else -radius)]
    pole = 1
    for i in range(1, rings + 1):
        theta = i * (math.pi / 2.0) / rings
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)
        z = radius * cos_theta if upper else -radius * cos_theta
        for j in range(segments):
            phi = j * 2.0 * math.pi / segments
            vertices.append((radius * sin_theta * math.cos(phi), radius * sin_theta * math.sin(phi), z))
    faces: list[tuple[int, int, int]] = []
    ring_count = rings
    for j in range(segments):
        next_j = (j + 1) % segments
        if upper:
            faces.append((pole, 2 + j, 2 + next_j))
        else:
            faces.append((pole, 2 + next_j, 2 + j))
    for r in range(ring_count - 1):
        ring_start = 2 + r * segments
        next_ring = ring_start + segments
        for j in range(segments):
            next_j = (j + 1) % segments
            v1, v2 = ring_start + j, ring_start + next_j
            v3, v4 = next_ring + next_j, next_ring + j
            if upper:
                faces.append((v1, v2, v3))
                faces.append((v1, v3, v4))
            else:
                faces.append((v1, v3, v2))
                faces.append((v1, v4, v3))
    return vertices, faces


def generate_capsule(
    radius: float = 0.05,
    height: float = 0.3,
    segments: int = 24,
    rings: int = 12,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    if _has_trimesh():
        import trimesh

        mesh = trimesh.creation.capsule(radius=radius, height=height, count=[max(3, segments), max(3, rings)])
        return _trimesh_to_raw(mesh)
    segments = max(8, segments)
    rings = max(4, rings)
    cyl_height = max(0.0, height - 2.0 * radius)
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = []
    if cyl_height > 1e-6:
        cyl, cyl_faces = generate_cylinder(radius, cyl_height, segments)
        parts.append((cyl, cyl_faces))
    top_cap, top_faces = generate_hemisphere(radius, segments, rings, upper=True)
    top_cap, top_faces = translate_mesh(top_cap, top_faces, dz=cyl_height / 2.0)
    bot_cap, bot_faces = generate_hemisphere(radius, segments, rings, upper=False)
    bot_cap, bot_faces = translate_mesh(bot_cap, bot_faces, dz=-cyl_height / 2.0)
    parts.append((top_cap, top_faces))
    parts.append((bot_cap, bot_faces))
    return merge_meshes(parts)


def generate_rounded_box(
    width: float,
    height: float,
    depth: float,
    segments: int = 8,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    if _has_trimesh():
        import trimesh

        mesh = trimesh.creation.box(extents=(width, depth, height))
        mesh = mesh.subdivide()
        return _trimesh_to_raw(mesh)
    return generate_cube(width, height, depth)


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


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _gear_tooth_radius(
    theta: float,
    teeth: int,
    outer_radius: float,
    root_radius: float,
) -> float:
    """Simplified involute-like tooth with smooth fillets."""
    phase = (theta * teeth / (2.0 * math.pi)) % 1.0
    tooth_width = 0.42
    fillet = 0.08
    if phase < fillet:
        t = phase / fillet
        return root_radius + (outer_radius - root_radius) * _smoothstep(t)
    if phase < tooth_width - fillet:
        return outer_radius
    if phase < tooth_width:
        t = (phase - (tooth_width - fillet)) / fillet
        return outer_radius + (root_radius - outer_radius) * _smoothstep(t)
    return root_radius


def generate_gear(
    outer_radius: float = 1.0,
    inner_radius: float = 0.2,
    height: float = 0.3,
    teeth: int = 12,
    segments: int = 128,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    teeth = max(6, teeth)
    segments = max(teeth * 8, segments)
    h2 = height / 2.0
    root_radius = outer_radius * 0.82
    profile: list[tuple[float, float]] = []
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        r = _gear_tooth_radius(theta, teeth, outer_radius, root_radius)
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


def _vase_profile_radius(t: float, max_radius: float, neck_radius: float) -> float:
    """Smooth lathe profile with curved belly, shoulder, and neck."""
    if t < 0.1:
        return max_radius * 0.35 * _smoothstep(t / 0.1)
    if t < 0.32:
        u = (t - 0.1) / 0.22
        return max_radius * (0.35 + 0.65 * math.sin(u * math.pi * 0.5))
    if t < 0.68:
        u = (t - 0.32) / 0.36
        bulge = 1.0 + 0.08 * math.sin(u * math.pi)
        return max_radius * bulge
    if t < 0.86:
        u = (t - 0.68) / 0.18
        return max_radius * (1.0 - 0.5 * _smoothstep(u))
    u = (t - 0.86) / 0.14
    return neck_radius + (max_radius * 0.5 - neck_radius) * (1.0 - _smoothstep(u))


def generate_vase(
    height: float = 0.2,
    max_radius: float = 0.06,
    neck_radius: float = 0.03,
    segments: int = 48,
    rings: int = 36,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    segments = max(16, segments)
    rings = max(16, rings)
    profile: list[tuple[float, float]] = []
    for i in range(rings + 1):
        t = i / rings
        z = -height / 2.0 + height * t
        r = _vase_profile_radius(t, max_radius, neck_radius)
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


def _humanoid_style(prompt: str) -> str:
    t = prompt.lower()
    if re.search(r"\b(?:girl|woman|girlfriend)\b", t):
        return "girl"
    if re.search(r"\b(?:boy|man|boyfriend)\b", t):
        return "boy"
    return "person"


def generate_humanoid(
    style: str = "person",
    height: float = 1.0,
    segments: int = 24,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    style = style.lower()
    if style in ("man", "woman"):
        style = "boy" if style == "man" else "girl"
    if style in ("child", "kid"):
        style = "boy"
        height *= 0.72

    head_scale = 1.15 if style == "boy" else 1.05 if style == "girl" else 1.08
    torso_h = height * 0.34
    leg_h = height * 0.42
    arm_h = height * 0.30
    head_r = height * 0.09 * head_scale
    torso_w = height * 0.20
    torso_d = height * 0.12
    limb_r = height * 0.045

    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = []
    z_base = -height / 2.0

    # Legs
    leg_spread = torso_w * 0.22
    for side in (-1.0, 1.0):
        leg, leg_faces = generate_capsule(limb_r, leg_h, segments, segments // 2)
        leg, leg_faces = translate_mesh(leg, leg_faces, dx=side * leg_spread, dz=z_base + leg_h / 2.0)
        parts.append((leg, leg_faces))

    # Torso
    torso, torso_faces = generate_rounded_box(torso_w, torso_h, torso_d, segments // 4)
    torso, torso_faces = translate_mesh(torso, torso_faces, dz=z_base + leg_h + torso_h / 2.0)
    parts.append((torso, torso_faces))

    # Arms
    arm_z = z_base + leg_h + torso_h * 0.72
    for side in (-1.0, 1.0):
        arm, arm_faces = generate_capsule(limb_r * 0.85, arm_h, segments, segments // 2)
        arm, arm_faces = translate_mesh(
            arm, arm_faces, dx=side * (torso_w / 2.0 + limb_r * 1.2), dz=arm_z
        )
        parts.append((arm, arm_faces))

    # Head
    head, head_faces = generate_sphere(head_r, segments, segments // 2)
    head, head_faces = translate_mesh(head, head_faces, dz=z_base + leg_h + torso_h + head_r * 0.9)
    parts.append((head, head_faces))

    # Girl skirt flare
    if style == "girl":
        skirt_h = height * 0.12
        skirt, skirt_faces = generate_cylinder(torso_w * 0.55, skirt_h, segments)
        skirt, skirt_faces = translate_mesh(skirt, skirt_faces, dz=z_base + leg_h + skirt_h / 2.0)
        parts.append((skirt, skirt_faces))

    return merge_meshes(parts)


def generate_robot(
    height: float = 1.0,
    segments: int = 24,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = []
    z_base = -height / 2.0
    body_w = height * 0.28
    body_h = height * 0.38
    head_s = height * 0.16

    for side in (-1.0, 1.0):
        leg, lf = generate_capsule(height * 0.05, height * 0.34, segments, segments // 2)
        leg, lf = translate_mesh(leg, lf, dx=side * body_w * 0.25, dz=z_base + height * 0.17)
        parts.append((leg, lf))

    body, bf = generate_rounded_box(body_w, body_h, body_w * 0.55, segments // 4)
    body, bf = translate_mesh(body, bf, dz=z_base + height * 0.34 + body_h / 2.0)
    parts.append((body, bf))

    head, hf = generate_cube(head_s, head_s * 0.85, head_s * 0.7)
    head, hf = translate_mesh(head, hf, dz=z_base + height * 0.34 + body_h + head_s / 2.0)
    parts.append((head, hf))

    for side in (-1.0, 1.0):
        arm, af = generate_capsule(height * 0.04, height * 0.28, segments, segments // 2)
        arm, af = translate_mesh(arm, af, dx=side * (body_w / 2.0 + height * 0.06), dz=z_base + height * 0.58)
        parts.append((arm, af))

    antenna, ant_f = generate_cylinder(height * 0.012, height * 0.08, 8)
    antenna, ant_f = translate_mesh(
        antenna, ant_f, dz=z_base + height * 0.34 + body_h + head_s + height * 0.04
    )
    parts.append((antenna, ant_f))
    return merge_meshes(parts)


def generate_tree(
    height: float = 1.0,
    segments: int = 24,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = []
    trunk_h = height * 0.35
    trunk, tf = generate_cylinder(height * 0.06, trunk_h, segments)
    trunk, tf = translate_mesh(trunk, tf, dz=-height / 2.0 + trunk_h / 2.0)
    parts.append((trunk, tf))

    for i, scale in enumerate((1.0, 0.72, 0.48)):
        cone_h = height * 0.22
        foliage, ff = generate_cone(height * 0.22 * scale, cone_h, segments)
        foliage, ff = translate_mesh(
            foliage, ff, dz=-height / 2.0 + trunk_h + cone_h / 2.0 + i * cone_h * 0.55
        )
        parts.append((foliage, ff))
    return merge_meshes(parts)


def generate_house(
    width: float = 1.0,
    segments: int = 16,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    depth = width * 0.7
    wall_h = width * 0.45
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = []
    base, bf = generate_cube(width, wall_h, depth)
    base, bf = translate_mesh(base, bf, dz=-width / 2.0 + wall_h / 2.0)
    parts.append((base, bf))

    roof_h = width * 0.35
    roof, rf = generate_cone(width * 0.62, roof_h, segments)
    roof, rf = translate_mesh(roof, rf, dz=-width / 2.0 + wall_h + roof_h / 2.0)
    parts.append((roof, rf))

    door_w = width * 0.18
    door_h = wall_h * 0.55
    door, df = generate_cube(door_w, door_h, depth * 0.05)
    door, df = translate_mesh(door, df, dy=depth / 2.0 + 0.01, dz=-width / 2.0 + door_h / 2.0)
    parts.append((door, df))
    return merge_meshes(parts)


def generate_car(
    length: float = 1.0,
    segments: int = 24,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    width = length * 0.42
    body_h = length * 0.18
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = []
    body, bf = generate_rounded_box(length * 0.75, body_h, width, segments // 4)
    body, bf = translate_mesh(body, bf, dz=-length / 2.0 + body_h / 2.0 + length * 0.08)
    parts.append((body, bf))

    cabin, cf = generate_rounded_box(length * 0.38, body_h * 0.9, width * 0.85, segments // 4)
    cabin, cf = translate_mesh(cabin, cf, dx=-length * 0.05, dz=-length / 2.0 + body_h * 1.35 + length * 0.08)
    parts.append((cabin, cf))

    wheel_r = length * 0.1
    wheel_w = width * 0.22
    for dx, dy in (
        (length * 0.22, width / 2.0),
        (length * 0.22, -width / 2.0),
        (-length * 0.22, width / 2.0),
        (-length * 0.22, -width / 2.0),
    ):
        wheel, wf = generate_cylinder(wheel_r, wheel_w, segments)
        wheel = [(v[2], v[1], v[0]) for v in wheel]
        wheel, wf = translate_mesh(wheel, wf, dx=dx, dy=dy, dz=-length / 2.0 + wheel_r + length * 0.08)
        parts.append((wheel, wf))
    return merge_meshes(parts)


def post_process_mesh(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]] | None:
    if not _has_trimesh():
        return vertices, faces
    try:
        import numpy as np
        import trimesh

        verts = np.array(vertices, dtype=np.float64)
        tris = np.array([[f[0] - 1, f[1] - 1, f[2] - 1] for f in faces], dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=verts, faces=tris, process=True)
        mesh.merge_vertices()
        mesh.remove_duplicate_faces()
        mesh.remove_degenerate_faces()
        mesh.fix_normals()
        if mesh.is_empty or len(mesh.faces) == 0:
            return None
        return _trimesh_to_raw(mesh)
    except Exception:
        return vertices, faces


def validate_llm_mesh(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> bool:
    if not _mesh_indices_valid(vertices, faces):
        return False
    if len(vertices) > MAX_LLM_VERTICES or len(faces) > MAX_LLM_FACES:
        return False
    if _has_trimesh():
        try:
            import numpy as np
            import trimesh

            verts = np.array(vertices, dtype=np.float64)
            tris = np.array([[f[0] - 1, f[1] - 1, f[2] - 1] for f in faces], dtype=np.int64)
            mesh = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
            if mesh.is_empty:
                return False
        except Exception:
            return False
    return True


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
        formats = {"obj", "stl"}
        if _has_trimesh():
            formats.add("glb")
        return formats
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
    elif re.search(r"\brobot\b", clean, re.I):
        shape = "robot"
    elif re.search(r"\btree\b", clean, re.I):
        shape = "tree"
    elif re.search(r"\bhouse\b", clean, re.I):
        shape = "house"
    elif re.search(r"\b(?:car|automobile|vehicle)\b", clean, re.I):
        shape = "car"
    elif _is_human_figure_request(clean):
        shape = _humanoid_style(clean)
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

    system_prompt = (
        "You are a 3D modeling expert. Generate a complete Wavefront OBJ file for:\n"
        f"'{prompt}'\n\n"
        "Output vertices ('v x y z') and triangular faces ('f v1 v2 v3'). "
        "Use meters, centered near origin, printable proportions.\n"
        "Rules:\n"
        "1. ONLY raw OBJ text — no markdown fences or explanations.\n"
        "2. Face indices are 1-based and must reference valid vertex numbers.\n"
        "3. Never use zero-based indices.\n"
        f"4. Maximum {MAX_LLM_VERTICES} vertices and {MAX_LLM_FACES} triangular faces.\n"
        "5. Manifold watertight mesh with consistent outward-facing triangles.\n"
        "6. Prefer simple clean low-poly geometry over noisy vertex soup.\n"
    )
    obj_content = llm_complete(
        system=system_prompt,
        user=f"Create a 3D model of: {prompt}",
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
    method: str = "",
) -> None:
    print("━━━ 3D Model Created ━━━")
    print(f"Shape: {shape}")
    if method:
        print(f"Method: {method}")
    elif used_llm:
        print("Method: AI-generated geometry (LLM OBJ)")
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
    print("  Online viewers:")
    print(f"    GLB: {_VIEWER_LINK} (drag & drop)")
    print("    OBJ/STL: https://3dviewer.net (drag & drop)")
    if "glb" in saved:
        print(f"  GLB viewer: {_VIEWER_LINK}")
    if "obj" in saved:
        print(f"  OBJ viewer: {_VIEWER_LINK_OBJ}{saved['obj']}")


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


def _resolve_mesh_resolution(args: argparse.Namespace) -> tuple[int, int]:
    quality = _quality_params(getattr(args, "quality", "medium"))
    segments = args.segments if args.segments is not None else quality["segments"]
    rings = args.rings if args.rings is not None else quality["rings"]
    return segments, rings


def _shape_from_args(args: argparse.Namespace) -> tuple[str, str, list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    cmd = args.shape.lower()
    segments, rings = _resolve_mesh_resolution(args)
    height = args.height if args.height != 1.0 else 1.0

    if cmd in ("cube", "box"):
        return "cube", args.name or "cube", *generate_cube(args.width, args.height, args.depth)
    if cmd == "sphere":
        return "sphere", args.name or "sphere", *generate_sphere(args.radius, segments, rings)
    if cmd == "cylinder":
        return "cylinder", args.name or "cylinder", *generate_cylinder(args.radius, args.height, segments)
    if cmd == "cone":
        return "cone", args.name or "cone", *generate_cone(args.radius, args.height, segments)
    if cmd == "gear":
        return "gear", args.name or "gear", *generate_gear(
            args.radius, args.inner_radius, args.height, args.teeth, segments
        )
    if cmd == "vase":
        return "vase", args.name or "vase", *generate_vase(
            args.height, args.max_radius, args.neck_radius, segments, rings
        )
    if cmd == "torus":
        return "torus", args.name or "torus", *generate_torus(
            args.major_radius, args.minor_radius, segments, rings
        )
    if cmd in HUMANOID_STYLES:
        style = _humanoid_style(cmd)
        return style, args.name or style, *generate_humanoid(style, height, segments)
    if cmd == "robot":
        return "robot", args.name or "robot", *generate_robot(height, segments)
    if cmd == "tree":
        return "tree", args.name or "tree", *generate_tree(height, segments)
    if cmd == "house":
        return "house", args.name or "house", *generate_house(args.width, segments)
    if cmd == "car":
        return "car", args.name or "car", *generate_car(args.width, segments)
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
    style = _humanoid_style(prompt)
    print(
        "Tip: use the built-in humanoid template instead of LLM vertex soup:",
        file=sys.stderr,
    )
    print(f"  compose_3d {style}", file=sys.stderr)
    print("For GLB export: pip install -e '.[3d]'", file=sys.stderr)


def _save_humanoid_fallback(args: argparse.Namespace, prompt: str, formats: set[str]) -> int:
    style = _humanoid_style(prompt)
    segments, _rings = _resolve_mesh_resolution(args)
    height = args.height if args.height != 1.0 else 1.0
    vertices, faces = generate_humanoid(style, height, segments)
    processed = post_process_mesh(vertices, faces)
    if processed:
        vertices, faces = processed
    saved = save_mesh(vertices=vertices, faces=faces, name=style, formats=formats)
    _print_result(name=style, shape=style, saved=saved)
    return 0


def _backend_slug(args: argparse.Namespace) -> str:
    return (getattr(args, "backend", None) or _env("MODEL_3D_BACKEND", "auto") or "auto").strip().lower()


def _ai_prompt_from_args(args: argparse.Namespace) -> str:
    shape = args.shape.lower()
    if shape in SHAPE_COMMANDS:
        return f"a detailed 3D model of a {shape.replace('_', ' ')}"
    return _normalize_nl_text(args.shape)


def _try_external_backend(args: argparse.Namespace, prompt: str, formats: set[str]) -> int | None:
    backend = _backend_slug(args)
    if backend == "procedural":
        return None
    from arka.media.compose_3d_backends import generate_with_backend

    prefer_procedural = args.shape.lower() in SHAPE_COMMANDS and backend == "auto"
    if prefer_procedural:
        return None
    if backend == "llm":
        return None
    try:
        mesh = generate_with_backend(
            prompt,
            backend,
            output_dir(),
            prefer_procedural=prefer_procedural,
        )
    except RuntimeError as exc:
        if backend != "auto":
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return None
    processed = post_process_mesh(mesh.vertices, mesh.faces)
    if processed:
        mesh.vertices, mesh.faces = processed
    name = args.name or slugify(prompt)
    saved = save_mesh(vertices=mesh.vertices, faces=mesh.faces, name=name, formats=formats)
    _print_result(name=name, shape=prompt, saved=saved, method=mesh.method)
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    formats = parse_formats_arg(args.format)
    backend = _backend_slug(args)
    is_template = args.shape.lower() in SHAPE_COMMANDS

    if is_template and backend in {"auto", "procedural"}:
        shape, name, vertices, faces = _shape_from_args(args)
        processed = post_process_mesh(vertices, faces)
        if processed:
            vertices, faces = processed
        saved = save_mesh(vertices=vertices, faces=faces, name=name, formats=formats)
        _print_result(name=name, shape=shape, saved=saved)
        return 0

    prompt = _ai_prompt_from_args(args)
    ai_hit = _try_external_backend(args, prompt, formats)
    if ai_hit is not None:
        return ai_hit

    if is_template:
        shape, name, vertices, faces = _shape_from_args(args)
        processed = post_process_mesh(vertices, faces)
        if processed:
            vertices, faces = processed
        saved = save_mesh(vertices=vertices, faces=faces, name=name, formats=formats)
        _print_result(name=name, shape=shape, saved=saved, method="procedural mesh (AI backends unavailable)")
        return 0

    prompt = _normalize_nl_text(args.shape)
    if _is_human_figure_request(prompt) and backend in {"auto", "procedural"}:
        return _save_humanoid_fallback(args, prompt, formats)

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
    if not validate_llm_mesh(vertices, faces):
        if _is_human_figure_request(prompt):
            print("LLM mesh invalid — falling back to humanoid template.", file=sys.stderr)
            return _save_humanoid_fallback(args, prompt, formats)
        reason = "could not parse faces" if not vertices or not faces else "invalid mesh"
        return _save_obj_only(obj_content, prompt, reason=reason)

    processed = post_process_mesh(vertices, faces)
    if processed is None:
        if _is_human_figure_request(prompt):
            print("LLM mesh cleanup failed — falling back to humanoid template.", file=sys.stderr)
            return _save_humanoid_fallback(args, prompt, formats)
        return _save_obj_only(obj_content, prompt, reason="mesh cleanup failed")
    vertices, faces = processed

    try:
        saved = save_mesh(vertices=vertices, faces=faces, name=prompt, formats=formats)
    except (IndexError, ValueError):
        if _is_human_figure_request(prompt):
            return _save_humanoid_fallback(args, prompt, formats)
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
    print("\n3D generation backends (--backend auto|tripo|hf-shap-e|…):")
    try:
        from arka.media.compose_3d_backends import backend_catalog

        for info in backend_catalog():
            icon = "✓" if info.available else "○"
            print(f"  {icon} {info.label:<28} {info.detail}")
            if not info.available and info.env_vars:
                print(f"      env: {', '.join(info.env_vars)}")
    except ImportError as exc:
        print(f"  ○ backend module unavailable ({exc})")
    print(f"\nOutput directory: {output_dir()}")
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
    p_compose.add_argument("--segments", type=int, default=None)
    p_compose.add_argument("--rings", type=int, default=None)
    p_compose.add_argument("--teeth", type=int, default=12)
    p_compose.add_argument("--name", default="")
    p_compose.add_argument(
        "--quality",
        default="medium",
        choices=tuple(QUALITY_SETTINGS),
        help="Mesh resolution preset (low, medium, high)",
    )
    p_compose.add_argument(
        "--backend",
        default="auto",
        choices=(
            "auto",
            "procedural",
            "shap-e",
            "hf-shap-e",
            "tripo",
            "meshy",
            "openscad",
            "llm",
        ),
        help="Generation backend (auto tries free APIs/local models, then LLM OBJ)",
    )
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
