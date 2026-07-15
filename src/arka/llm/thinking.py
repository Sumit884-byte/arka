"""Portable thinking-depth controls for models without native reasoning knobs."""
from __future__ import annotations
import os
from pathlib import Path

LEVELS = {"off": "Answer directly and concisely.", "low": "Think through the key steps briefly before answering.", "medium": "Reason carefully through the problem, checking assumptions before answering.", "high": "Use thorough internal analysis, verify edge cases, then provide a clear answer."}

def path() -> Path:
    from arka.paths import config_dir
    return config_dir() / "thinking_level"

def get() -> str:
    raw = os.environ.get("ARKA_THINKING_LEVEL", "").strip().lower()
    if not raw and path().is_file():
        raw = path().read_text(encoding="utf-8").strip().lower()
    return raw if raw in LEVELS else "medium"

def set_level(level: str) -> str:
    level = level.strip().lower()
    if level not in LEVELS:
        raise ValueError(f"level must be one of: {', '.join(LEVELS)}")
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(level + "\n", encoding="utf-8")
    return level

def instruction() -> str:
    return LEVELS[get()]
