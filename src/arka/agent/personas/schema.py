"""Persona config schema validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DEFAULT_DISCLAIMER = "Simulated persona for fun — not the real person."

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def slugify(name: str) -> str:
    """Turn a display or NL name into a persona slug."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise ValueError("Invalid persona name")
    if not _NAME_RE.match(s):
        s = re.sub(r"[^a-z0-9_-]", "", s)
        if not s or not _NAME_RE.match(s):
            raise ValueError(f"Invalid persona slug: {name!r}")
    return s


@dataclass
class Persona:
    name: str
    display_name: str = ""
    description: str = ""
    system_prompt: str = ""
    disclaimer: str = DEFAULT_DISCLAIMER
    voice: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "disclaimer": self.disclaimer or DEFAULT_DISCLAIMER,
        }
        if self.voice:
            data["voice"] = self.voice
        return data

    @property
    def formatted_disclaimer(self) -> str:
        text = (self.disclaimer or DEFAULT_DISCLAIMER).strip()
        if not text.endswith("\n"):
            text += "\n"
        return f"Note: {text}\n"


def parse_persona(data: dict[str, Any], *, source: str = "") -> Persona:
    if not isinstance(data, dict):
        raise ValueError("Persona root must be an object")
    raw_name = str(data.get("name", "")).strip()
    if not raw_name:
        raise ValueError("Persona missing required field: name")
    name = slugify(raw_name)
    system_prompt = str(data.get("system_prompt", "")).strip()
    if not system_prompt:
        raise ValueError(f"Persona {name!r} missing required field: system_prompt")
    display_name = str(data.get("display_name", name)).strip() or name
    description = str(data.get("description", "")).strip()
    disclaimer = str(data.get("disclaimer", DEFAULT_DISCLAIMER)).strip() or DEFAULT_DISCLAIMER
    voice = str(data.get("voice", "")).strip()
    return Persona(
        name=name,
        display_name=display_name,
        description=description,
        system_prompt=system_prompt,
        disclaimer=disclaimer,
        voice=voice,
        source=source,
    )
