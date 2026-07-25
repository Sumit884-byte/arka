"""Layout and camera helpers for 3D scene composition."""

from __future__ import annotations

from typing import Any

from arka.core.object_orientation import default_view

CONTEXT_PRESETS: dict[str, str] = {
    "racing scene": "racing",
    "vehicle showcase": "studio",
    "aircraft showcase": "outdoor",
    "desk workspace": "interior",
    "bedroom": "interior",
    "dining room": "interior",
    "neutral studio": "studio",
    "gallery": "gallery",
    "space": "space",
}

VIEW_CAMERAS: dict[str, dict[str, list[float] | float]] = {
    "rear-three-quarter": {"position": [0, 2.2, -6], "target": [0, 1, 0], "fov": 50},
    "rear": {"position": [0, 1.8, -5], "target": [0, 1, 0], "fov": 45},
    "front-three-quarter": {"position": [4, 2.5, 5], "target": [0, 1, 0], "fov": 45},
    "front": {"position": [0, 1.8, 6], "target": [0, 1, 0], "fov": 45},
    "side": {"position": [6, 1.8, 0], "target": [0, 1, 0], "fov": 45},
    "top": {"position": [0, 10, 0.01], "target": [0, 0, 0], "fov": 40},
    "three-quarter": {"position": [4, 3, 7], "target": [0, 1, 0], "fov": 45},
}


def infer_preset(plan: dict[str, Any], text: str = "") -> str:
    """Pick a visual preset from plan context or NL keywords."""
    context = str(plan.get("context") or "")
    if context in CONTEXT_PRESETS:
        return CONTEXT_PRESETS[context]
    lower = text.lower()
    if any(w in lower for w in ("gallery", "museum", "exhibit")):
        return "gallery" if "gallery" in lower else "museum"
    if any(w in lower for w in ("space", "cosmos", "starfield", "planet")):
        return "space"
    if any(w in lower for w in ("race", "racing", "track")):
        return "racing"
    if any(w in lower for w in ("outdoor", "park", "garden", "forest")):
        return "outdoor"
    if any(w in lower for w in ("room", "desk", "bedroom", "interior", "office")):
        return "interior"
    return "studio"


def _dim(plan: dict[str, Any], key: str) -> dict[str, float]:
    dims = plan.get("real_world_dimensions_m") or {}
    entry = dims.get(key) or {}
    return {
        "width": float(entry.get("width_m", 1.0)),
        "depth": float(entry.get("depth_m", 1.0)),
        "height": float(entry.get("height_m", 1.0)),
    }


def _normalize_role(role: str) -> str:
    return role.lower().strip()


def layout_from_plan(
    plan: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply placement rules and dimensions to positioned assets."""
    if not assets:
        return []
    context = str(plan.get("context") or "")
    rules = plan.get("placement_rules") or []
    positioned: dict[str, dict[str, Any]] = {}
    result: list[dict[str, Any]] = []

    for asset in assets:
        role = _normalize_role(str(asset.get("role") or ""))
        positioned[role] = dict(asset)

    if context == "desk workspace" and len(assets) >= 2:
        desk = _dim(plan, "desk")
        desk_y = desk["height"] / 2
        positioned.setdefault("desk", {})
        positioned["desk"].update({"position": [0, desk_y, 0], "scale": 1})
        positioned.setdefault("keyboard", {})
        positioned["keyboard"].update({
            "position": [0, desk["height"] + _dim(plan, "keyboard")["height"] / 2, desk["depth"] * 0.15],
            "scale": 0.5,
        })
        positioned.setdefault("monitor", {})
        positioned["monitor"].update({
            "position": [0, desk["height"] + _dim(plan, "monitor")["height"] / 2, -desk["depth"] * 0.25],
            "scale": 0.6,
        })
        positioned.setdefault("chair", {})
        positioned["chair"].update({"position": [0, _dim(plan, "chair")["height"] / 2, desk["depth"] * 0.55], "scale": 0.7})
        char = _dim(plan, "character")
        positioned.setdefault("seated character", positioned.get("character", {}))
        positioned.setdefault("character", {})
        seated = positioned.get("seated character") or positioned["character"]
        seated.update({
            "position": [0, _dim(plan, "chair")["height"] + char["height"] * 0.45, desk["depth"] * 0.55],
            "scale": 1,
        })
    elif context == "racing scene":
        positioned.setdefault("player vehicle", {})
        positioned["player vehicle"].update({"position": [0, 0.7, 0], "scale": 1, "rotation": [0, 0, 0]})
    elif context == "vehicle showcase":
        positioned.setdefault("vehicle", {})
        positioned["vehicle"].update({"position": [0, 0.7, 0], "scale": 1})
    elif context == "bedroom":
        bed = _dim(plan, "bed")
        positioned.setdefault("bed", {})
        positioned["bed"].update({"position": [0, bed["height"] / 2, 0], "scale": 1})
        positioned.setdefault("sleeping character", positioned.get("character", {}))
        positioned.setdefault("character", {})
        char_asset = positioned.get("sleeping character") or positioned["character"]
        char_asset.update({"position": [0, bed["height"] + 0.3, 0], "scale": 1})
    elif context == "dining room":
        table = _dim(plan, "table")
        positioned.setdefault("table", {})
        positioned["table"].update({"position": [0, table["height"] / 2, 0], "scale": 1})
        positioned.setdefault("chair", {})
        positioned["chair"].update({"position": [0, _dim(plan, "chair")["height"] / 2, table["depth"] * 0.6], "scale": 0.8})

    # Apply generic rules for anything not placed yet
    for rule in rules:
        obj = _normalize_role(str(rule.get("object") or ""))
        if obj in positioned and positioned[obj].get("position"):
            continue
        if obj in positioned:
            positioned[obj].setdefault("position", [0, 0, 0])

    # Merge back into asset list preserving order
    used_roles: set[str] = set()
    for asset in assets:
        role = _normalize_role(str(asset.get("role") or ""))
        merged = dict(asset)
        if role in positioned:
            merged.update({k: v for k, v in positioned[role].items() if v is not None})
            used_roles.add(role)
        elif not merged.get("position"):
            idx = len(result)
            merged["position"] = [idx * 2.5, 0, 0]
        merged.setdefault("scale", 1)
        merged.setdefault("animate", True)
        result.append(merged)

    # Any extra positioned roles not in original list
    for role, data in positioned.items():
        if role not in used_roles and data.get("url"):
            data.setdefault("position", [len(result) * 2.5, 0, 0])
            data.setdefault("scale", 1)
            data.setdefault("animate", True)
            data.setdefault("role", role)
            result.append(data)

    return result or assets


def camera_from_orientation(text: str, bounds: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map semantic view defaults to camera position and target."""
    view = default_view(text)
    cam = dict(VIEW_CAMERAS.get(view, VIEW_CAMERAS["three-quarter"]))
    if bounds and bounds.get("center") and bounds.get("size"):
        center = bounds["center"]
        size = max(bounds["size"], 1.0)
        dist = size * 2.5
        cam["target"] = list(center)
        if view == "rear-three-quarter":
            cam["position"] = [center[0], center[1] + size * 0.5, center[2] - dist]
        elif view == "front-three-quarter":
            cam["position"] = [center[0] + dist * 0.6, center[1] + size * 0.4, center[2] + dist * 0.6]
        else:
            cam["position"] = [center[0] + dist * 0.55, center[1] + size * 0.5, center[2] + dist * 0.85]
    return cam


def simple_layout(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback linear spacing when no plan roles match."""
    out: list[dict[str, Any]] = []
    for i, asset in enumerate(assets):
        merged = dict(asset)
        merged.setdefault("position", [i * 2.5, 0, 0])
        merged.setdefault("scale", 1)
        merged.setdefault("animate", True)
        out.append(merged)
    return out
