"""Load, save, and seed persona configs."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from arka.agent.personas.schema import Persona, parse_persona


def _env_personas_dir() -> Path | None:
    for key in ("ARKA_PERSONAS_DIR", "PERSONAS_DIR"):
        if raw := os.environ.get(key, "").strip():
            return Path(raw).expanduser().resolve()
    return None


def personas_dir() -> Path:
    if override := _env_personas_dir():
        return override
    from arka.paths import config_dir

    return config_dir() / "personas"


def templates_dir() -> Path:
    from arka.paths import package_dir

    return package_dir() / "agent" / "personas" / "templates"


def _load_text(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Persona root must be an object: {path}")
    return data


def _dump_text(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml

            text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        except ImportError:
            path = path.with_suffix(".json")
            text = json.dumps(data, indent=2) + "\n"
    else:
        text = json.dumps(data, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def _config_path(directory: Path, name: str) -> Path | None:
    stem = name.strip()
    if not stem:
        return None
    for ext in (".yaml", ".yml", ".json"):
        candidate = directory / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def list_personas(*, include_templates: bool = False) -> list[str]:
    ensure_layout()
    names: set[str] = set()
    directory = personas_dir()
    if directory.is_dir():
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json"}:
                names.add(path.stem)
    if include_templates:
        src = templates_dir()
        if src.is_dir():
            for path in src.iterdir():
                if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json"}:
                    names.add(path.stem)
    return sorted(names)


def persona_exists(name: str) -> bool:
    ensure_layout()
    return _config_path(personas_dir(), name) is not None


def load_persona(name: str) -> Persona:
    ensure_layout()
    path = _config_path(personas_dir(), name)
    if not path:
        raise FileNotFoundError(f"Persona not found: {name}")
    return parse_persona(_load_text(path), source=str(path))


def save_persona(persona: Persona, *, fmt: str = "yaml") -> Path:
    directory = personas_dir()
    directory.mkdir(parents=True, exist_ok=True)
    ext = ".json" if fmt == "json" else ".yaml"
    path = directory / f"{persona.name}{ext}"
    _dump_text(persona.to_dict(), path)
    return path


def load_template(name: str) -> Persona:
    path = _config_path(templates_dir(), name)
    if not path:
        raise FileNotFoundError(f"Persona template not found: {name}")
    return parse_persona(_load_text(path), source=str(path))


def seed_persona(name: str) -> Path | None:
    """Copy bundled template into user personas dir if missing."""
    ensure_layout()
    dest = _config_path(personas_dir(), name)
    if dest:
        return dest
    src = _config_path(templates_dir(), name)
    if not src:
        return None
    directory = personas_dir()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / src.name
    shutil.copy2(src, dest)
    return dest


def ensure_layout() -> Path:
    directory = personas_dir()
    directory.mkdir(parents=True, exist_ok=True)
    src = templates_dir()
    if src.is_dir():
        for path in src.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            dest = directory / path.name
            if not dest.is_file():
                shutil.copy2(path, dest)
    return directory


_BUNDLED_ELON_STALE_MARK = "keep responses helpful and good-natured"


def _maybe_refresh_bundled_elon(persona: Persona) -> Persona:
    """Upgrade seeded elon persona when it still uses the old neutral prompt."""
    if persona.name != "elon":
        return persona
    if _BUNDLED_ELON_STALE_MARK not in persona.system_prompt:
        return persona
    try:
        template = load_template("elon")
    except FileNotFoundError:
        return persona
    if _BUNDLED_ELON_STALE_MARK in template.system_prompt:
        return persona
    save_persona(template)
    return template


def resolve_persona(name: str) -> Persona:
    """Load persona, seeding bundled template on first use."""
    ensure_layout()
    seeded = seed_persona(name)
    if seeded:
        persona = load_persona(name)
    else:
        persona = load_persona(name)
    return _maybe_refresh_bundled_elon(persona)



def list_payload(*, include_templates: bool = False) -> dict[str, object]:
    """Structured persona inventory for MCP / automation clients."""
    names = list_personas(include_templates=include_templates)
    rows: list[dict[str, object]] = []
    for name in names:
        try:
            persona = load_persona(name)
            rows.append(
                {
                    "name": persona.name,
                    "display_name": persona.display_name or persona.name,
                    "description": persona.description,
                    "voice": persona.voice or "",
                    "source": persona.source or "",
                }
            )
        except (ValueError, FileNotFoundError) as exc:
            rows.append(
                {
                    "name": name,
                    "display_name": name,
                    "description": "",
                    "voice": "",
                    "source": "",
                    "error": str(exc),
                }
            )
    return {
        "personas_dir": str(personas_dir()),
        "count": len(rows),
        "personas": rows,
    }


def show_payload(name: str) -> dict[str, object]:
    """Structured persona details for MCP clients."""
    slug = (name or "").strip()
    if not slug:
        raise ValueError("name is required")
    persona = resolve_persona(slug)
    return {
        "name": persona.name,
        "display_name": persona.display_name or persona.name,
        "description": persona.description,
        "disclaimer": persona.disclaimer,
        "voice": persona.voice or "",
        "source": persona.source or "",
        "system_prompt": persona.system_prompt,
        "system_prompt_chars": len(persona.system_prompt or ""),
    }


def format_persona_list() -> str:
    names = list_personas()
    if not names:
        return "personas\t(none — run: arka persona create my-coach)"
    lines = ["personas"]
    for name in names:
        try:
            persona = load_persona(name)
            desc = persona.description or persona.display_name
            lines.append(f"{name}\t{desc}")
        except (ValueError, FileNotFoundError) as exc:
            lines.append(f"{name}\tinvalid\t{exc}")
    return "\n".join(lines)


def format_persona_show(name: str) -> str:
    persona = resolve_persona(name)
    lines = [
        f"name\t{persona.name}",
        f"display_name\t{persona.display_name}",
        f"description\t{persona.description}",
        f"disclaimer\t{persona.disclaimer}",
        f"source\t{persona.source}",
    ]
    if persona.voice:
        lines.append(f"voice\t{persona.voice}")
    lines.append("system_prompt\t" + persona.system_prompt.replace("\n", "\\n"))
    return "\n".join(lines)
