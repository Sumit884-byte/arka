#!/usr/bin/env python3
"""Arka 3D model generator skill."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import (
    generate_cone,
    generate_cube,
    generate_cylinder,
    generate_llm_model,
    generate_sphere,
    get_output_paths,
    write_obj,
    write_stl,
)


def parse_obj(
    obj_text: str,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Parse Wavefront OBJ string to extract vertices and faces (triangulated)."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line in obj_text.splitlines():
        line = line.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    vertices.append(
                        (float(parts[1]), float(parts[2]), float(parts[3]))
                    )
                except ValueError:
                    pass
        elif line.startswith("f "):
            parts = line.split()
            if len(parts) >= 4:
                face_vertices = []
                for part in parts[1:]:
                    idx_str = part.split("/")[0]
                    try:
                        face_vertices.append(int(idx_str))
                    except ValueError:
                        pass
                if len(face_vertices) == 3:
                    faces.append(
                        (face_vertices[0], face_vertices[1], face_vertices[2])
                    )
                elif len(face_vertices) == 4:
                    # Quad: split into two triangles
                    faces.append(
                        (face_vertices[0], face_vertices[1], face_vertices[2])
                    )
                    faces.append(
                        (face_vertices[0], face_vertices[2], face_vertices[3])
                    )
                elif len(face_vertices) > 4:
                    # Polygon: fan triangulation
                    for i in range(1, len(face_vertices) - 1):
                        faces.append(
                            (
                                face_vertices[0],
                                face_vertices[i],
                                face_vertices[i + 1],
                            )
                        )
    return vertices, faces


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print("Arka 3D Model Generator — generate OBJ & STL models")
        print("Usage:")
        print("  arka 3d cube [--width W] [--height H] [--depth D] [--name NAME]")
        print("  arka 3d sphere [--radius R] [--segments S] [--rings RG] [--name NAME]")
        print("  arka 3d cylinder [--radius R] [--height H] [--segments S] [--name NAME]")
        print("  arka 3d cone [--radius R] [--height H] [--segments S] [--name NAME]")
        print("  arka 3d <prompt>                   — generate custom model using AI")
        return 0

    cmd = args[0].lower()

    if cmd in ("cube", "box"):
        parser = argparse.ArgumentParser()
        parser.add_argument("--width", type=float, default=1.0)
        parser.add_argument("--height", type=float, default=1.0)
        parser.add_argument("--depth", type=float, default=1.0)
        parser.add_argument("--name", type=str, default="cube")
        parsed, _ = parser.parse_known_args(args[1:])

        vertices, faces = generate_cube(parsed.width, parsed.height, parsed.depth)
        obj_path, stl_path = get_output_paths(parsed.name)

        obj_path.write_text(write_obj(vertices, faces), encoding="utf-8")
        stl_path.write_text(write_stl(vertices, faces, parsed.name), encoding="utf-8")

        print("━━━ Answer ━━━")
        print(f"Successfully generated offline 3D cube model:")
        print(f"  OBJ model: {obj_path}")
        print(f"  STL model: {stl_path}")
        return 0

    if cmd == "sphere":
        parser = argparse.ArgumentParser()
        parser.add_argument("--radius", type=float, default=1.0)
        parser.add_argument("--segments", type=int, default=16)
        parser.add_argument("--rings", type=int, default=16)
        parser.add_argument("--name", type=str, default="sphere")
        parsed, _ = parser.parse_known_args(args[1:])

        vertices, faces = generate_sphere(
            parsed.radius, parsed.segments, parsed.rings
        )
        obj_path, stl_path = get_output_paths(parsed.name)

        obj_path.write_text(write_obj(vertices, faces), encoding="utf-8")
        stl_path.write_text(write_stl(vertices, faces, parsed.name), encoding="utf-8")

        print("━━━ Answer ━━━")
        print(f"Successfully generated offline 3D sphere model:")
        print(f"  OBJ model: {obj_path}")
        print(f"  STL model: {stl_path}")
        return 0

    if cmd == "cylinder":
        parser = argparse.ArgumentParser()
        parser.add_argument("--radius", type=float, default=1.0)
        parser.add_argument("--height", type=float, default=2.0)
        parser.add_argument("--segments", type=int, default=16)
        parser.add_argument("--name", type=str, default="cylinder")
        parsed, _ = parser.parse_known_args(args[1:])

        vertices, faces = generate_cylinder(
            parsed.radius, parsed.height, parsed.segments
        )
        obj_path, stl_path = get_output_paths(parsed.name)

        obj_path.write_text(write_obj(vertices, faces), encoding="utf-8")
        stl_path.write_text(write_stl(vertices, faces, parsed.name), encoding="utf-8")

        print("━━━ Answer ━━━")
        print(f"Successfully generated offline 3D cylinder model:")
        print(f"  OBJ model: {obj_path}")
        print(f"  STL model: {stl_path}")
        return 0

    if cmd == "cone":
        parser = argparse.ArgumentParser()
        parser.add_argument("--radius", type=float, default=1.0)
        parser.add_argument("--height", type=float, default=2.0)
        parser.add_argument("--segments", type=int, default=16)
        parser.add_argument("--name", type=str, default="cone")
        parsed, _ = parser.parse_known_args(args[1:])

        vertices, faces = generate_cone(
            parsed.radius, parsed.height, parsed.segments
        )
        obj_path, stl_path = get_output_paths(parsed.name)

        obj_path.write_text(write_obj(vertices, faces), encoding="utf-8")
        stl_path.write_text(write_stl(vertices, faces, parsed.name), encoding="utf-8")

        print("━━━ Answer ━━━")
        print(f"Successfully generated offline 3D cone model:")
        print(f"  OBJ model: {obj_path}")
        print(f"  STL model: {stl_path}")
        return 0

    # Fallback to LLM AI generation
    prompt = " ".join(args).strip()
    print(f"Invoking AI engine to generate custom 3D model for: '{prompt}'...")

    try:
        obj_content = generate_llm_model(prompt)
    except Exception as e:
        print(f"Error calling LLM AI engine: {e}", file=sys.stderr)
        return 1

    obj_path, stl_path = get_output_paths(prompt)
    obj_path.write_text(obj_content, encoding="utf-8")

    # Try parsing and writing STL too
    try:
        vertices, faces = parse_obj(obj_content)
        if vertices and faces:
            stl_content = write_stl(vertices, faces, prompt)
            stl_path.write_text(stl_content, encoding="utf-8")
            print("━━━ Answer ━━━")
            print(f"Successfully generated 3D models using AI:")
            print(f"  OBJ model: {obj_path}")
            print(f"  STL model: {stl_path}")
        else:
            print("━━━ Answer ━━━")
            print(f"Successfully generated 3D model using AI:")
            print(f"  OBJ model: {obj_path}")
            print("  (Could not generate STL format due to face parsing limitation)")
    except Exception as e:
        print("━━━ Answer ━━━")
        print(f"Successfully generated 3D model using AI:")
        print(f"  OBJ model: {obj_path}")
        print(f"  (Failed to output STL: {e})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
