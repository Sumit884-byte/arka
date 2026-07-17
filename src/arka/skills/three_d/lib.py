"""Library functions for 3D model mesh generation, OBJ/STL exporting, and LLM completions."""

from __future__ import annotations

import math
from pathlib import Path


def compute_normal(
    v1: tuple[float, float, float],
    v2: tuple[float, float, float],
    v3: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Compute the unit normal of a triangle face using cross product."""
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
    """Generate vertices and triangular faces for a centered box/cube."""
    x = width / 2.0
    y = height / 2.0
    z = depth / 2.0

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

    # Triangles with 1-based indices for OBJ compatibility
    faces = [
        (5, 6, 7),
        (5, 7, 8),  # Front
        (2, 1, 4),
        (2, 4, 3),  # Back
        (6, 2, 3),
        (6, 3, 7),  # Top
        (1, 5, 8),
        (1, 8, 4),  # Bottom
        (6, 5, 1),
        (6, 1, 2),  # Right
        (8, 7, 3),
        (8, 3, 4),  # Left
    ]
    return vertices, faces


def generate_sphere(
    radius: float = 1.0, segments: int = 16, rings: int = 16
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Generate vertices and triangular faces for a UV Sphere."""
    if segments < 3:
        segments = 3
    if rings < 3:
        rings = 3

    vertices: list[tuple[float, float, float]] = []
    # North pole (index 1)
    vertices.append((0.0, 0.0, radius))

    for i in range(1, rings):
        theta = i * math.pi / rings
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)
        for j in range(segments):
            phi = j * 2.0 * math.pi / segments
            x = radius * sin_theta * math.cos(phi)
            y = radius * sin_theta * math.sin(phi)
            z = radius * cos_theta
            vertices.append((x, y, z))

    # South pole (index len(vertices) + 1)
    vertices.append((0.0, 0.0, -radius))
    south_pole_idx = len(vertices)

    faces: list[tuple[int, int, int]] = []

    # Top cap (connecting pole idx 1 to first ring)
    # First ring starts at index 2
    for j in range(segments):
        next_j = (j + 1) % segments
        faces.append((1, 2 + next_j, 2 + j))

    # Inner rings
    for r in range(rings - 2):
        ring_start = 2 + r * segments
        next_ring_start = ring_start + segments
        for j in range(segments):
            next_j = (j + 1) % segments
            # Quad formed by:
            # v1 = ring_start + j
            # v2 = ring_start + next_j
            # v3 = next_ring_start + next_j
            # v4 = next_ring_start + j
            v1 = ring_start + j
            v2 = ring_start + next_j
            v3 = next_ring_start + next_j
            v4 = next_ring_start + j
            faces.append((v1, v2, v3))
            faces.append((v1, v3, v4))

    # Bottom cap (connecting last ring to south pole)
    last_ring_start = 2 + (rings - 2) * segments
    for j in range(segments):
        next_j = (j + 1) % segments
        faces.append((south_pole_idx, last_ring_start + j, last_ring_start + next_j))

    return vertices, faces


def generate_cylinder(
    radius: float = 1.0, height: float = 2.0, segments: int = 16
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Generate vertices and triangular faces for a closed cylinder."""
    if segments < 3:
        segments = 3

    h2 = height / 2.0
    vertices: list[tuple[float, float, float]] = []

    # 1. Top center (index 1)
    vertices.append((0.0, 0.0, h2))
    # 2. Bottom center (index 2)
    vertices.append((0.0, 0.0, -h2))

    # 3. Top ring (starts at index 3)
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), h2))

    # 4. Bottom ring (starts at index 3 + segments)
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), -h2))

    faces: list[tuple[int, int, int]] = []
    top_ring_start = 3
    bottom_ring_start = 3 + segments

    for i in range(segments):
        next_i = (i + 1) % segments

        # Top cap
        faces.append((1, top_ring_start + next_i, top_ring_start + i))

        # Bottom cap
        faces.append((2, bottom_ring_start + i, bottom_ring_start + next_i))

        # Sides
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
    """Generate vertices and triangular faces for a closed cone."""
    if segments < 3:
        segments = 3

    h2 = height / 2.0
    vertices: list[tuple[float, float, float]] = []

    # 1. Tip vertex (index 1)
    vertices.append((0.0, 0.0, h2))
    # 2. Bottom center (index 2)
    vertices.append((0.0, 0.0, -h2))

    # 3. Bottom ring (starts at index 3)
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        vertices.append((radius * math.cos(theta), radius * math.sin(theta), -h2))

    faces: list[tuple[int, int, int]] = []
    ring_start = 3

    for i in range(segments):
        next_i = (i + 1) % segments

        # Sides (Tip to ring)
        faces.append((1, ring_start + i, ring_start + next_i))

        # Bottom Cap (Center to ring)
        faces.append((2, ring_start + next_i, ring_start + i))

    return vertices, faces


def write_obj(
    vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]
) -> str:
    """Format vertices and faces into Wavefront OBJ format."""
    lines = ["# Generated by Arka 3D model skill", ""]
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
    """Format vertices and faces into ASCII STL format with correct face normals."""
    clean_name = name.replace(" ", "_")
    lines = [f"solid {clean_name}"]

    for f in faces:
        # faces are 1-based, convert to 0-based index
        v1 = vertices[f[0] - 1]
        v2 = vertices[f[1] - 1]
        v3 = vertices[f[2] - 1]
        nx, ny, nz = compute_normal(v1, v2, v3)

        lines.append(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v1[0]:.6f} {v1[1]:.6f} {v1[2]:.6f}")
        lines.append(f"      vertex {v2[0]:.6f} {v2[1]:.6f} {v2[2]:.6f}")
        lines.append(f"      vertex {v3[0]:.6f} {v3[1]:.6f} {v3[2]:.6f}")
        lines.append("    endloop")
        lines.append("  endfacet")

    lines.append(f"endsolid {clean_name}")
    return "\n".join(lines) + "\n"


def get_output_paths(name: str) -> tuple[Path, Path]:
    """Return the output file paths for OBJ and STL under ~/arka-generated/models."""
    try:
        from arka.paths import generated_data_dir

        base = generated_data_dir() / "models"
    except ImportError:
        base = Path.home() / "arka-generated" / "models"

    base.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "_")
    # Avoid filename conflicts by checking existence
    obj_path = base / f"{slug}.obj"
    stl_path = base / f"{slug}.stl"
    counter = 1
    while obj_path.exists() or stl_path.exists():
        obj_path = base / f"{slug}_{counter}.obj"
        stl_path = base / f"{slug}_{counter}.stl"
        counter += 1

    return obj_path, stl_path


def generate_llm_model(prompt: str) -> str:
    """Invoke the active LLM fallback engine to generate custom OBJ file content."""
    from arka.llm.cli import llm_complete

    system_prompt = (
        "You are a 3D modeling expert. The user wants to generate a 3D model in Wavefront OBJ format representing:\n"
        f"'{prompt}'\n\n"
        "Generate a complete, syntactically valid OBJ file content containing vertices ('v x y z') and triangular or quad faces ('f v1 v2 v3 ...'). "
        "Structure the object logically with proper scaling and proportions. Use a standard coordinates system.\n\n"
        "Rules:\n"
        "1. Provide ONLY the raw text content of the OBJ file.\n"
        "2. Do NOT wrap the output in markdown block code ticks (like ``` or ```obj).\n"
        "3. Do NOT include HTML, explanation text, or introductory notes. Start directly with vertices or comment lines.\n"
    )

    obj_content = llm_complete(
        system=system_prompt,
        user=f"Create a 3D model of: {prompt}",
        temperature=0.2,
        task="create_3d_model",
        skill="three_d",
    )

    # Post-process to remove code block artifacts if LLM ignores instruction
    lines = obj_content.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip() + "\n"
