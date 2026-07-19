import json

from arka.agent.scene_3d import create, plan_scene
from arka.routing.symbolic import route_offline_extras


def test_scene_uses_real_model_assets(tmp_path):
    result = create("Museum", [{"url": "https://example.com/human.glb"}], str(tmp_path))
    html = (tmp_path / "index.html").read_text()
    assert result["assets"] == 1
    assert "GLTFLoader" in html
    assert "human.glb" in html


def test_scene_manifest_and_route():
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/scene_3d/skill.json").read_text())
    assert manifest["name"] == "scene_3d"
    assert route_offline_extras("create a 3d human scene with https://example.com/human.glb").startswith("scene_3d ")


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
