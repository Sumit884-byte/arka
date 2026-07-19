import json
from pathlib import Path

from arka.agent.data_collect import clean_text, collect_catalog, duration_seconds
from arka.routing.symbolic import route_offline_extras
from arka.agent.game_studio import create


def test_duration_and_cleaning():
    assert duration_seconds("5m") == 300
    assert clean_text("<script>x</script> Hello   world") == "Hello world"


def test_collection_route():
    assert route_offline_extras("auto collect data about renewable energy for 2 minutes") == "data collect about renewable energy for 2 minutes"


def test_catalog_route_for_complete_category_request():
    assert route_offline_extras("collect all data about Indian aeroplanes") == "data catalog about Indian aeroplanes"


def test_catalog_paginates_deduplicates_and_reports_honest_coverage(monkeypatch, tmp_path):
    calls = []

    def fake_collect(topic, **kwargs):
        calls.append(topic)
        page = len(calls)
        return {"data": [
            {"topic": topic, "title": f"item {page}", "url": "https://example.test/shared", "text": "x", "source": "web"},
            {"topic": topic, "title": f"item {page}b", "url": f"https://example.test/{page}", "text": "x", "source": "web"},
        ]}

    monkeypatch.setattr("arka.agent.data_collect.collect", fake_collect)
    output = tmp_path / "catalog.json"
    result = collect_catalog("Indian aeroplanes", duration="1s", limit=3, output=str(output), fmt="json")

    assert result["reported_total"] is None
    assert result["coverage"].startswith("partial")
    assert result["rows"] == 3
    assert result["pages"] == 2
    assert output.exists()
    assert json.loads(output.read_text())["rows"] == 3


def test_game_studio_creates_safe_starter(tmp_path):
    result = create("Solar Drift", str(tmp_path / "game"))
    assert result["template"] == "neon-arena"
    assert (tmp_path / "game" / "index.html").read_text().find("Solar Drift") >= 0
    assert (tmp_path / "game" / "game.js").exists()


def test_game_studio_route():
    assert route_offline_extras("create an awesome browser game") == "game create an awesome browser game"
    assert route_offline_extras("check my game at http://localhost:5173") == "game check http://localhost:5173"
    assert route_offline_extras("record gameplay video at http://localhost:5173") == "game check http://localhost:5173 --record"
    assert route_offline_extras("check my game at http://localhost:5173 and verify visuals before saying done") == "game check http://localhost:5173 --verify"


def test_game_control_skill_manifest():
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/game_control/skill.json").read_text())
    assert manifest["name"] == "game_control"
    assert "record gameplay" in manifest["triggers"]


def test_visual_issue_routes_to_local_pixel_review_not_web_search():
    route = route_offline_extras("analyze visual issues in recordings/frame-001.png")
    assert route == "frontend_loop review recordings/frame-001.png"
