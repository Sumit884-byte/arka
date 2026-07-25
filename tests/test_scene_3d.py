import json

from arka.agent.scene_3d import create, plan_scene
from arka.media.scene_3d_template import build_spec, render_html
from arka.media.scene_layout import camera_from_orientation, infer_preset, layout_from_plan
from arka.media.scene_assets import match_catalog, resolve_assets
from arka.routing.symbolic import route_offline_extras, route_scene_3d


def test_scene_uses_real_model_assets(tmp_path):
    result = create(
        "Museum",
        [{"url": "https://example.com/human.glb", "role": "character"}],
        str(tmp_path),
        preset="museum",
    )
    html = (tmp_path / "index.html").read_text()
    assert result["assets"] == 1
    assert result["preset"] == "museum"
    assert "GLTFLoader" in html
    assert "human.glb" in html
    assert "shadowMap" in html
    assert "ACESFilmicToneMapping" in html
    assert "Loading scene" in html


def test_scene_template_has_ground_and_bloom():
    spec = build_spec(
        title="Gallery",
        assets=[{"url": "https://example.com/a.glb"}],
        preset="gallery",
    )
    html = render_html(spec)
    assert "PlaneGeometry" in html
    assert "UnrealBloomPass" in html
    assert "toneMapping" in html


def test_scene_manifest_and_route():
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/scene_3d/skill.json").read_text())
    assert manifest["name"] == "scene_3d"
    assert "impressive 3d scene" in manifest["triggers"]
    routed = route_offline_extras("create a 3d human scene with https://example.com/human.glb")
    assert routed.startswith("scene_3d ")
    assert "--model" in routed
    assert "human.glb" in routed


def test_route_auto_without_glb():
    routed = route_scene_3d("create an impressive interactive 3d robot gallery scene")
    assert routed is not None
    assert "--auto" in routed
    assert "robot gallery" in routed.lower() or "Robot" in routed
    assert routed.count("--model") == 0


def test_route_title_not_full_command():
    routed = route_scene_3d('create a 3d scene "Animated robot gallery" with cool lighting')
    assert routed is not None
    assert "create a 3d scene" not in routed.split("--", 1)[0]


def test_scene_plan_maps_context_to_model_roles():
    plan = plan_scene("Person typing", "at a desk while working")
    assert plan["context"] == "desk workspace"
    assert "keyboard" in plan["roles"]
    assert "verified GLB/GLTF" in plan["asset_policy"]
    assert plan["real_world_dimensions_m"]["desk"]["height_m"] == 0.75
    assert plan["unit"] == "meters"
    assert any(rule["object"] == "keyboard" and rule["relation"] == "on" for rule in plan["placement_rules"])


def test_scene_plan_uses_racing_game_vehicle_orientation():
    plan = plan_scene("Cybertruck vs Ferrari", "racing game battle")
    assert plan["context"] == "racing scene"
    assert plan["default_view"] == "rear-three-quarter"
    assert "racing-game" in plan["orientation_note"]
    assert any(rule["relation"] == "behind_above" for rule in plan["placement_rules"])


def test_layout_desk_workspace():
    plan = plan_scene("Person typing", "at a desk while working")
    assets = [
        {"url": "https://example.com/desk.glb", "role": "desk"},
        {"url": "https://example.com/keyboard.glb", "role": "keyboard"},
    ]
    laid = layout_from_plan(plan, assets)
    desk = next(a for a in laid if a["role"] == "desk")
    keyboard = next(a for a in laid if a["role"] == "keyboard")
    assert desk["position"][1] > 0
    assert keyboard["position"][1] > desk["position"][1]


def test_camera_racing_chase():
    cam = camera_from_orientation("Cybertruck racing game")
    assert cam["position"][2] < 0


def test_infer_preset_gallery():
    plan = plan_scene("Animated robot gallery", "")
    assert infer_preset(plan, "animated robot gallery") == "gallery"


def test_match_catalog_robot():
    entry = match_catalog("animated robot gallery", "primary character")
    assert entry is not None
    assert entry["name"] == "RobotExpressive"


def test_resolve_assets_curated():
    plan = plan_scene("Robot gallery", "")
    assets, warnings = resolve_assets(plan, title="Robot gallery", allow_generate=False)
    assert len(assets) >= 1
    assert "RobotExpressive" in assets[0]["url"] or assets[0].get("source", "").startswith("curated")
