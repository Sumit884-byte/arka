from pathlib import Path

from arka.agent.model_to_image import _blender_script
from arka.routing.symbolic import route_offline_extras


def test_blender_script_has_transparent_render(tmp_path: Path):
    script = _blender_script(tmp_path / "a.obj", tmp_path / "a.png", 512)
    assert "film_transparent=True" in script
    assert "resolution_x=512" in script


def test_model_to_image_route():
    result = route_offline_extras("render model chair.obj as an image")
    assert result == "model_to_image chair.obj --output chair-render.png"
