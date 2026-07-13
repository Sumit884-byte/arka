"""Metallurgy heat-treatment sources for Arka flow — bundled index."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_lib() -> Any | None:
    lib_path = Path(__file__).resolve().parent / "lib.py"
    if not lib_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_metallurgy_lib", lib_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def try_metallurgy_flow_from_sources(topic: str) -> tuple[str | None, str]:
    """
    Try bundled heat-treatment flows before LLM.

    Returns (markdown_or_none, source_kind) where source_kind is bundled | none.
    """
    lib = _load_lib()
    if lib is None:
        return None, "none"
    try:
        hit = lib.resolve_bundled_heat_flow(topic)
    except Exception:
        return None, "none"
    if hit:
        return hit[0], hit[1]
    return None, "none"
