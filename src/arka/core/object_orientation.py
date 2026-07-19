"""Semantic object orientation defaults for 3D scenes and renders."""

from __future__ import annotations

import re


def object_kind(text: str) -> str:
    """Return a coarse real-world object kind from natural language."""
    clean = (text or "").lower()
    if re.search(r"\b(?:car|racecar|racing\s+car|truck|cyber\s*truck|ferrari|vehicle|automobile)\b", clean):
        return "vehicle"
    if re.search(r"\b(?:airplane|aeroplane|aircraft|jet|fighter|helicopter|drone)\b", clean):
        return "aircraft"
    if re.search(r"\b(?:human|person|man|woman|boy|girl|character|robot|avatar)\b", clean):
        return "character"
    if re.search(r"\b(?:phone|laptop|monitor|screen|tv|dashboard)\b", clean):
        return "screen_device"
    return "generic"


def task_context(text: str) -> str:
    """Return the likely use context for an object."""
    clean = (text or "").lower()
    if re.search(r"\b(?:race|racing|drive|driving|chase|runner|game|cockpit|third[- ]person)\b", clean):
        return "racing_game"
    if re.search(r"\b(?:catalog|product|hero|marketing|thumbnail|showcase)\b", clean):
        return "product_showcase"
    if re.search(r"\b(?:diagram|assembly|blueprint|layout|roof|top)\b", clean):
        return "technical_overview"
    return "general"


def default_view(text: str) -> str:
    """Choose the most useful default camera view for a task/object pair."""
    kind = object_kind(text)
    context = task_context(text)
    clean = (text or "").lower()
    if re.search(r"\b(?:back|rear|behind)\b", clean):
        return "rear"
    if re.search(r"\b(?:front|face|head[- ]on)\b", clean):
        return "front"
    if re.search(r"\b(?:side|profile|silhouette)\b", clean):
        return "side"
    if context == "technical_overview":
        return "top"
    if kind == "vehicle" and context == "racing_game":
        return "rear-three-quarter"
    if kind == "aircraft" and context in {"racing_game", "product_showcase"}:
        return "front-three-quarter"
    if kind == "character":
        return "front-three-quarter"
    return "three-quarter"


def orientation_note(text: str) -> str:
    """Human-readable orientation guidance for planning output."""
    view = default_view(text)
    if view == "rear-three-quarter":
        return "Use a rear three-quarter camera behind the vehicle, matching common third-person racing-game views."
    if view == "rear":
        return "Show the object's back/rear because the user explicitly requested a rear or behind view."
    if view == "top":
        return "Use a top/overhead view for layouts, roof details, or technical assembly tasks."
    if view == "side":
        return "Use a side/profile view when silhouette or lateral shape matters."
    if view == "front-three-quarter":
        return "Use a front three-quarter view so the object identity and depth are both readable."
    return "Use a balanced three-quarter view by default."
