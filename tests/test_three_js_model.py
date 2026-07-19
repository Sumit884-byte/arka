from arka.agent.three_js_model import GUIDANCE
from arka.routing.symbolic import route_offline_extras


def test_three_js_route_recommends_existing_model_assets():
    hit = route_offline_extras("build a Three.js 3d scene with a robot model")
    assert hit and hit.startswith("three_js_model guide")


def test_three_js_guidance_is_license_and_reuse_aware(capsys):
    from arka.agent.three_js_model import main

    assert main(["guide", "robot"]) == 0
    output = capsys.readouterr().out
    assert "license" in output.lower()
    assert "GLTF/GLB" in GUIDANCE
    assert "boxes" in GUIDANCE
    assert "three_js_model search" in output


def test_satellite_scene_routes_to_realistic_three_js_guidance():
    from arka.routing.symbolic import route_offline_extras

    hit = route_offline_extras("add realistic satellite 3d models to the solar system scene")
    assert hit and hit.startswith("three_js_model guide")


def test_symbolic_reality_check_requires_real_asset_for_known_entity():
    from arka.agent.three_js_model import model_selection_instruction, symbolic_real_world_entity

    assert symbolic_real_world_entity("add a satellite") is True
    assert symbolic_real_world_entity("make an imaginary crystal") is False
    assert symbolic_real_world_entity("make a nebula artifact") is None
    instruction = model_selection_instruction("add a satellite")
    assert "trusted catalog" in instruction
    assert "geometric placeholders" in instruction


def test_real_entity_dimensions_require_cited_web_source():
    from arka.agent.three_js_model import dimension_research_instruction

    instruction = dimension_research_instruction("build a realistic satellite")
    assert "authoritative real-world dimensions" in instruction
    assert "source URL" in instruction
    assert "uncertainty" in instruction


def test_three_js_asset_query_extracts_real_object():
    from arka.agent.three_js_model import asset_query

    assert asset_query("add realistic satellite 3d models to this scene") == "satellite"
    assert asset_query("find GLB model for a desk workspace") == "desk"


def test_three_js_candidate_normalization_and_ranking():
    from arka.agent.three_js_model import parse_model_candidates

    candidates = parse_model_candidates({
        "downloadable_models": [
            {"uid": "box", "name": "Preview only", "formats": {}, "viewerUrl": "https://example.com/box"},
            {
                "uid": "sat",
                "name": "Real Satellite",
                "formats": {"glb": 1200, "gltf": 2000},
                "viewerUrl": "https://sketchfab.com/3d-models/sat",
                "user": "NASA",
                "license": "CC-BY",
            },
        ]
    })
    assert candidates[0].name == "Real Satellite"
    assert candidates[0].has_threejs_format is True
    assert candidates[0].downloadable is True
    assert candidates[0].attribution == "NASA"


def test_three_js_search_no_provider_does_not_invent_urls(capsys):
    from arka.agent.three_js_model import main

    assert main(["search", "satellite", "--no-mcp"]) == 0
    output = capsys.readouterr().out
    assert "candidates\t0" in output
    assert "Do not invent model URLs" in output
    assert "arka mcp preset threejs --apply" in output


def test_three_js_search_uses_configured_mcp(monkeypatch):
    from arka.agent import three_js_model

    monkeypatch.setattr("arka.integrations.mcp_manager.list_server_names", lambda: ["threejs"])
    monkeypatch.setattr(
        "arka.integrations.mcp_manager.call_tool",
        lambda server, tool, args: '{"downloadable_models":[{"uid":"sat","name":"Satellite","formats":{"glb":1}}]}',
    )
    candidates, source = three_js_model.search_models("find satellite model")
    assert source == "threejs-mcp"
    assert candidates[0].uid == "sat"


def test_three_js_route_can_search_assets():
    from arka.routing.symbolic import route_offline_extras

    hit = route_offline_extras("find a realistic satellite glb model for three.js")
    assert hit and hit.startswith("three_js_model search")
