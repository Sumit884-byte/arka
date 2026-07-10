#!/usr/bin/env python3
"""Read/write per-skill and per-profile LLM model choices."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from arka.llm.fallback import _parse_skill_model_value, parse_chain
from arka.llm.skill_profiles import (
    SKILL_TASK_MAP,
    TASK_PROFILES,
    default_model_for_profile,
    default_model_for_skill,
    known_skill_names,
    known_task_profiles,
    normalize_skill_name,
    skill_task_profile,
    task_profile_info,
)


def default_skill_models_path() -> Path:
    try:
        from platformdirs import user_config_dir

        base = Path(user_config_dir("arka", "arka"))
    except ImportError:
        base = Path.home() / ".config" / "arka"
    return base / "llm-skill-models.json"


def skill_models_path() -> Path:
    raw = (os.environ.get("LLM_SKILL_MODELS") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return default_skill_models_path()


def _format_model(entries: list[tuple[str, str]]) -> str:
    if not entries:
        return ""
    parts: list[str] = []
    for provider, model_id in entries:
        parts.append(f"{provider}/{model_id}" if provider else model_id)
    return ",".join(parts)


def load_skill_models_file() -> dict[str, Any]:
    path = skill_models_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_skill_models_file(data: dict[str, Any]) -> Path:
    path = skill_models_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def configured_model_for_key(key: str) -> str:
    data = load_skill_models_file()
    profiles = data.get("_profiles") if isinstance(data.get("_profiles"), dict) else {}
    if key in data:
        return _format_model(_parse_skill_model_value(data[key]))
    if key in profiles:
        return _format_model(_parse_skill_model_value(profiles[key]))
    return ""


def effective_model_for_skill(skill: str) -> str:
    key = normalize_skill_name(skill)
    if not key:
        return ""
    explicit = configured_model_for_key(key)
    if explicit:
        return explicit
    profile = skill_task_profile(key)
    profile_model = configured_model_for_key(profile)
    if profile_model:
        return profile_model
    return default_model_for_skill(key)


def set_skill_model(target: str, model: str) -> Path:
    """Set model for a skill name or task profile (route, chat, …)."""
    key = normalize_skill_name(target)
    if not key:
        raise ValueError("target required")
    entries = parse_chain(model)
    if not entries:
        raise ValueError(f"invalid model: {model}")

    data = load_skill_models_file()
    if key in known_task_profiles():
        profiles = data.get("_profiles")
        if not isinstance(profiles, dict):
            profiles = {}
        profiles[key] = _format_model(entries)
        data["_profiles"] = profiles
    else:
        data[key] = _format_model(entries)
    return save_skill_models_file(data)


def clear_skill_model(target: str) -> Path:
    key = normalize_skill_name(target)
    data = load_skill_models_file()
    changed = False
    if key in data:
        del data[key]
        changed = True
    profiles = data.get("_profiles")
    if isinstance(profiles, dict) and key in profiles:
        del profiles[key]
        data["_profiles"] = profiles
        changed = True
    if not changed:
        return skill_models_path()
    return save_skill_models_file(data)


def list_skill_model_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for profile in known_task_profiles():
        info = task_profile_info(profile)
        rows.append(
            {
                "kind": "profile",
                "name": profile,
                "profile": profile,
                "configured": configured_model_for_key(profile),
                "suggested": info.get("default_model", default_model_for_profile(profile)),
                "description": info.get("description", ""),
            }
        )
    for skill in known_skill_names():
        profile = skill_task_profile(skill)
        rows.append(
            {
                "kind": "skill",
                "name": skill,
                "profile": profile,
                "configured": configured_model_for_key(skill),
                "suggested": default_model_for_skill(skill),
                "description": task_profile_info(profile).get("description", ""),
            }
        )
    return rows
