from pathlib import Path

from arka.agent.model_to_image import _blender_script
from arka.routing.symbolic import route_offline_extras


def test_blender_script_has_transparent_render(tmp_path: Path):
    script = _blender_script(tmp_path / "a.obj", tmp_path / "a.png", 512)
    assert "film_transparent=True" in script
    assert "resolution_x=512" in script
    assert "camera.location" in script


def test_angle_selection_has_deterministic_fallback(monkeypatch):
    from arka.agent.model_to_image import choose_angle

    monkeypatch.delenv("VLLM_API_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    assert choose_angle("show the roof and top assembly") == "top"
    assert choose_angle("show side profile") == "side"
    assert choose_angle("render a racing car for a third person driving game") == "rear-three-quarter"


def test_vllm_angle_selection(monkeypatch):
    from arka.agent import model_to_image

    monkeypatch.setenv("VLLM_API_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setattr(
        "arka.llm.fallback.llm_complete",
        lambda *args, **kwargs: '{"angle":"top"}',
    )
    assert model_to_image.choose_angle("show the internal assembly") == "top"


def test_model_to_image_route():
    result = route_offline_extras("render model chair.obj as an image")
    assert result == "model_to_image chair.obj --output chair-render.png"
