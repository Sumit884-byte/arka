from arka.media.scene_layout import camera_from_orientation, infer_preset, layout_from_plan, simple_layout


def test_simple_layout_spacing():
    assets = [{"url": "a.glb"}, {"url": "b.glb"}]
    laid = simple_layout(assets)
    assert laid[0]["position"] == [0, 0, 0]
    assert laid[1]["position"][0] == 2.5


def test_camera_front_three_quarter():
    cam = camera_from_orientation("product showcase for a satellite")
    assert cam["position"][0] > 0
    assert cam["position"][2] > 0


def test_infer_preset_racing():
    plan = {"context": "racing scene"}
    assert infer_preset(plan) == "racing"


def test_layout_racing_vehicle():
    plan = {
        "context": "racing scene",
        "roles": ["player vehicle"],
        "placement_rules": [],
        "real_world_dimensions_m": {},
    }
    assets = [{"url": "https://example.com/car.glb", "role": "player vehicle"}]
    laid = layout_from_plan(plan, assets)
    assert laid[0]["position"][1] == 0.7
