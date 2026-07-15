from arka.agent.super_replica import analyze
from arka.routing.symbolic import route_super_replica


def test_startup_advice_and_questions(tmp_path):
    result = analyze(str(tmp_path), "startup")
    assert "defer complex scalability" in result["advice"]
    assert result["questions"]


def test_detect_stack(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert "Node/JavaScript" in analyze(str(tmp_path))["stack"]


def test_route_super_replica():
    assert route_super_replica("use super replica on this repository") == "super_replica ."
