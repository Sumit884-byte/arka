"""Generate a Three.js scene shell that composes real glTF/GLB assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from arka.media.scene_3d_template import build_spec, render_html
from arka.media.scene_layout import camera_from_orientation, infer_preset, layout_from_plan, simple_layout
from arka.media.scene_assets import localize_asset, resolve_assets


def create(
    title: str,
    assets: list[dict],
    output: str,
    *,
    preset: str = "studio",
    camera: dict | None = None,
    plan: dict | None = None,
    intent: str = "",
) -> dict[str, object]:
    if not assets:
        raise ValueError("at least one real .glb/.gltf asset URL or local path is required")
    root = Path(output).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.html"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {target}")

    # Localize any local model paths into the output directory
    localized: list[dict] = []
    for asset in assets:
        item = dict(asset)
        item["url"] = localize_asset(str(item["url"]), root)
        localized.append(item)

    if plan:
        localized = layout_from_plan(plan, localized)
    else:
        localized = simple_layout(localized)

    text = f"{title} {intent}".strip()
    cam = camera or camera_from_orientation(text)
    spec = build_spec(title=title, assets=localized, preset=preset, camera=cam)
    target.write_text(render_html(spec), encoding="utf-8")
    return {
        "output": str(target),
        "assets": len(localized),
        "renderer": "three.js",
        "preset": preset,
        "models": localized,
    }


def plan_scene(title: str, intent: str = "") -> dict[str, object]:
    """Plan contextual model roles before any assets are selected."""
    text = f"{title} {intent}".lower()
    from arka.core.object_orientation import default_view, object_kind, orientation_note

    view = default_view(text)
    kind = object_kind(text)
    roles = ["primary character"]
    context = "neutral studio"
    if kind == "vehicle" and ("race" in text or "game" in text or "drive" in text):
        context, roles = "racing scene", ["player vehicle", "track/road", "environment markers", "chase camera"]
    elif kind == "vehicle":
        context, roles = "vehicle showcase", ["vehicle", "ground plane", "scale reference"]
    elif kind == "aircraft":
        context, roles = "aircraft showcase", ["aircraft", "runway or sky environment", "scale reference"]
    elif "sleep" in text or "bed" in text:
        context, roles = "bedroom", ["sleeping character", "bed", "bedside lamp", "blanket"]
    elif "type" in text or "code" in text or "work" in text:
        context, roles = "desk workspace", ["seated character", "desk", "keyboard", "monitor", "chair"]
    elif "eat" in text or "dinner" in text:
        context, roles = "dining room", ["seated character", "table", "plate", "chair"]
    elif any(w in text for w in ("gallery", "museum", "exhibit")):
        context, roles = "gallery", ["primary character", "environment markers"]
    elif any(w in text for w in ("space", "cosmos", "starfield")):
        context, roles = "space", ["primary character", "environment"]
    dimensions = {
        "bed": {"width_m": 1.6, "depth_m": 2.0, "height_m": 0.55},
        "desk": {"width_m": 1.4, "depth_m": 0.7, "height_m": 0.75},
        "keyboard": {"width_m": 0.45, "depth_m": 0.15, "height_m": 0.03},
        "monitor": {"width_m": 0.55, "depth_m": 0.05, "height_m": 0.35},
        "chair": {"width_m": 0.55, "depth_m": 0.55, "height_m": 1.1},
        "character": {"width_m": 0.5, "depth_m": 0.35, "height_m": 1.75},
        "lamp": {"width_m": 0.25, "depth_m": 0.25, "height_m": 0.45},
        "table": {"width_m": 1.2, "depth_m": 0.8, "height_m": 0.75},
        "car": {"width_m": 1.8, "depth_m": 4.5, "height_m": 1.4},
        "truck": {"width_m": 2.1, "depth_m": 5.8, "height_m": 1.9},
        "race track lane": {"width_m": 3.5, "depth_m": 100.0, "height_m": 0.02},
    }
    placement = {
        "racing scene": [
            {"object": "player vehicle", "relation": "on", "target": "track/road", "note": "centered in lane with forward direction aligned down the track"},
            {"object": "chase camera", "relation": "behind_above", "target": "player vehicle", "note": "rear three-quarter view, like common racing games"},
            {"object": "environment markers", "relation": "alongside", "target": "track/road", "note": "placed at lane edges for speed and depth cues"},
        ],
        "vehicle showcase": [
            {"object": "vehicle", "relation": "on", "target": "ground plane", "note": "wheels contact ground; do not float or sink"},
            {"object": "camera", "relation": "front_three_quarter", "target": "vehicle", "note": "unless the task is racing/driving, where rear chase view is preferred"},
        ],
        "aircraft showcase": [
            {"object": "aircraft", "relation": "on_or_above", "target": "runway or sky environment", "note": "nose and wings readable in a front three-quarter view"},
        ],
        "desk workspace": [
            {"object": "keyboard", "relation": "on", "target": "desk", "note": "centered near the front edge"},
            {"object": "monitor", "relation": "on", "target": "desk", "note": "centered at the back with screen facing the character"},
            {"object": "chair", "relation": "in_front_of", "target": "desk", "note": "keyboard-facing with clearance for legs"},
            {"object": "character", "relation": "seated_on", "target": "chair", "note": "hands aligned with keyboard height"},
        ],
        "bedroom": [
            {"object": "character", "relation": "on", "target": "bed", "note": "aligned with mattress and under blanket"},
            {"object": "lamp", "relation": "beside", "target": "bed", "note": "on a bedside surface, not floating"},
        ],
        "dining room": [
            {"object": "character", "relation": "seated_on", "target": "chair", "note": "facing the table"},
            {"object": "plate", "relation": "on", "target": "table", "note": "within comfortable reach"},
        ],
    }
    return {
        "title": title,
        "context": context,
        "roles": roles,
        "default_view": view,
        "orientation_note": orientation_note(text),
        "real_world_dimensions_m": dimensions,
        "placement_rules": placement.get(context, []),
        "unit": "meters",
        "asset_policy": "Use verified GLB/GLTF assets; do not substitute primitives for real objects.",
        "approval": "Review this plan and provide model URLs/paths before generation.",
    }


def describe_model(path: str) -> str:
    try:
        from arka.vision.describe import describe_source
        return describe_source(path, "Describe this 3D model preview or screenshot: identity, pose, materials, scale cues, and whether it fits the planned scene.")
    except Exception as exc:
        return f"Model description unavailable: {exc}"


def _build_assets_from_models(models: list[str], plan: dict) -> list[dict]:
    roles = list(plan.get("roles") or [])
    assets: list[dict] = []
    for i, model in enumerate(models):
        role = roles[i] if i < len(roles) else f"asset_{i}"
        assets.append({"url": model, "role": role, "animate": True})
    return assets


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka scene-3d")
    p.add_argument("title")
    p.add_argument("--model", action="append", help="GLB/GLTF URL or local path; repeat for multiple models")
    p.add_argument("--auto", action="store_true", help="Auto-resolve assets from plan roles (curated catalog, optional search/generation)")
    p.add_argument("--no-generate", action="store_true", help="With --auto, never call AI mesh backends")
    p.add_argument("--preset", choices=("gallery", "studio", "outdoor", "racing", "interior", "space", "museum"), help="Visual preset (default: infer from plan)")
    p.add_argument("--out", default="arka-scene")
    p.add_argument("--json", action="store_true")
    p.add_argument("--intent", default="", help="Action/context, e.g. 'typing while sleeping' (used for planning)")
    p.add_argument("--plan", action="store_true", help="Print the contextual model plan before generation")
    p.add_argument("--describe-model", help="Describe a local model preview image with the configured vision/vLLM backend")
    args = p.parse_args(argv)

    if not args.model and not args.auto:
        p.error("provide --model URL/path(s) or use --auto to resolve assets")

    plan = plan_scene(args.title, args.intent)
    if args.plan:
        print(json.dumps(plan, indent=2))
    if args.describe_model:
        print(json.dumps({"model_description": describe_model(args.describe_model)}, indent=2))

    out_path = Path(args.out).expanduser()
    warnings: list[str] = []

    if args.model:
        assets = _build_assets_from_models(args.model, plan)
    else:
        assets, warnings = resolve_assets(
            plan,
            title=args.title,
            intent=args.intent,
            allow_generate=not args.no_generate,
            output_dir=out_path,
        )

    preset = args.preset or infer_preset(plan, f"{args.title} {args.intent}")
    camera = camera_from_orientation(f"{args.title} {args.intent}")

    try:
        result = create(
            args.title,
            assets,
            args.out,
            preset=preset,
            camera=camera,
            plan=plan,
            intent=args.intent,
        )
    except (OSError, ValueError) as exc:
        p.error(str(exc))

    if warnings:
        for w in warnings:
            print(f"Warning: {w}", flush=True)

    print(json.dumps(result, indent=2) if args.json else f"Created Three.js scene: {result['output']} ({result['assets']} model assets, preset={preset})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
