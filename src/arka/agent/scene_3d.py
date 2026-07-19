"""Generate a Three.js scene shell that composes real glTF/GLB assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title><style>html,body{{margin:0;height:100%;overflow:hidden;background:#080b18}}#info{{position:fixed;z-index:2;color:white;padding:16px;font:14px system-ui}}canvas{{display:block}}</style><script type="importmap">{{"imports":{{"three":"https://unpkg.com/three@0.170.0/build/three.module.js"}}}}</script></head><body><div id="info">{title} · drag to orbit · scroll to zoom</div><script type="module">
import * as THREE from 'https://unpkg.com/three@0.170.0/build/three.module.js';import {{OrbitControls}} from 'https://unpkg.com/three@0.170.0/examples/jsm/controls/OrbitControls.js';import {{GLTFLoader}} from 'https://unpkg.com/three@0.170.0/examples/jsm/loaders/GLTFLoader.js';
const scene=new THREE.Scene();scene.background=new THREE.Color(0x080b18);const camera=new THREE.PerspectiveCamera(45,innerWidth/innerHeight,.1,1000);camera.position.set(4,3,7);const renderer=new THREE.WebGLRenderer({{antialias:true}});renderer.setPixelRatio(devicePixelRatio);renderer.setSize(innerWidth,innerHeight);document.body.append(renderer.domElement);const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,1,0);controls.update();scene.add(new THREE.HemisphereLight(0xbad7ff,0x182038,2));const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(4,8,5);scene.add(key);
const loader=new GLTFLoader();const assets={assets};for(const asset of assets)loader.load(asset.url,g=>{{g.scene.position.set(...(asset.position||[0,0,0]));g.scene.scale.setScalar(asset.scale||1);scene.add(g.scene);if(asset.animate&&g.animations.length){{const mixer=new THREE.AnimationMixer(g.scene);mixer.clipAction(g.animations[0]).play();g.mixer=mixer}}}},undefined,e=>console.warn('model load failed',asset.url,e));
const clock=new THREE.Clock();function animate(){{requestAnimationFrame(animate);const dt=clock.getDelta();scene.traverse(o=>o.mixer?.update(dt));renderer.render(scene,camera)}}animate();addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)}});
</script></body></html>"""


def create(title: str, assets: list[dict], output: str) -> dict[str, object]:
    if not assets:
        raise ValueError("at least one real .glb/.gltf asset URL or local path is required")
    root = Path(output).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.html"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {target}")
    target.write_text(HTML.format(title=title or "Arka 3D Scene", assets=json.dumps(assets)), encoding="utf-8")
    return {"output": str(target), "assets": len(assets), "renderer": "three.js", "models": assets}


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka scene-3d")
    p.add_argument("title")
    p.add_argument("--model", action="append", required=True, help="GLB/GLTF URL or local path; repeat for multiple models")
    p.add_argument("--out", default="arka-scene")
    p.add_argument("--json", action="store_true")
    p.add_argument("--intent", default="", help="Action/context, e.g. 'typing while sleeping' (used for planning)")
    p.add_argument("--plan", action="store_true", help="Print the contextual model plan before generation")
    p.add_argument("--describe-model", help="Describe a local model preview image with the configured vision/vLLM backend")
    args = p.parse_args(argv)
    plan = plan_scene(args.title, args.intent)
    if args.plan:
        print(json.dumps(plan, indent=2))
    if args.describe_model:
        print(json.dumps({"model_description": describe_model(args.describe_model)}, indent=2))
    assets = [{"url": model, "position": [i * 2, 0, 0], "scale": 1, "animate": True} for i, model in enumerate(args.model)]
    try:
        result = create(args.title, assets, args.out)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"Created Three.js scene: {result['output']} ({result['assets']} model assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
