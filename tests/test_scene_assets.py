from arka.media.scene_assets import CURATED_CATALOG, match_catalog, resolve_assets


def test_catalog_has_robot():
    names = {e["name"] for e in CURATED_CATALOG}
    assert "RobotExpressive" in names


def test_match_catalog_bird():
    entry = match_catalog("flamingo in a park", "animal")
    assert entry is not None
    assert entry["name"] == "Flamingo"


def test_resolve_assets_no_generate():
    plan = {"roles": ["primary character"], "context": "gallery"}
    assets, warnings = resolve_assets(
        plan,
        title="Animated robot gallery",
        allow_generate=False,
    )
    assert assets
    assert any("threejs.org" in a["url"] for a in assets)


def test_resolve_user_models():
    plan = {"roles": ["character", "desk"], "context": "desk workspace"}
    assets, warnings = resolve_assets(
        plan,
        user_models=["https://example.com/person.glb"],
    )
    assert len(assets) == 1
    assert assets[0]["url"] == "https://example.com/person.glb"
    assert not warnings
