import json

from arka.agent.parallax_2d import create
from arka.routing.symbolic import route_offline_extras


def test_parallax_scene_creates_depth_layers(tmp_path):
    result = create("Forest", ["background.png", "trees.png", "character.png"], str(tmp_path))
    html = (tmp_path / "index.html").read_text()
    assert result["technique"] == "2.5D parallax"
    assert html.count("data-depth") == 3
    assert "pointermove" in html


def test_parallax_manifest_and_route():
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/parallax_2d/skill.json").read_text())
    assert manifest["name"] == "parallax_2d"
    assert route_offline_extras("create a parallax scene from background.png foreground.png").startswith("parallax_2d ")
