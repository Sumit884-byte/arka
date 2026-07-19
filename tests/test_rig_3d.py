import json

from arka.agent.rig_3d import create
from arka.routing.symbolic import route_offline_extras


def test_rig_scene_contains_skeleton_tools(tmp_path):
    result = create("Robot", "https://example.com/robot.glb", str(tmp_path))
    html = (tmp_path / "index.html").read_text()
    assert "SkeletonHelper" in html
    assert "AnimationMixer" in html
    assert result["model"].endswith("robot.glb")


def test_rig_manifest_and_route():
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/rig_3d/skill.json").read_text())
    assert manifest["name"] == "rig_3d"
    assert route_offline_extras("rig this 3d human model https://example.com/human.glb").startswith("rig_3d ")
