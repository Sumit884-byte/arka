from arka.agent.hallmark import build_request
from arka.routing.symbolic import route_hallmark


def test_hallmark_request_contains_source_and_license() -> None:
    request = build_request("audit", "landing page")
    assert request["license"] == "MIT"
    assert "hallmark" in request["prompt"].lower()


def test_hallmark_routes_natural_language() -> None:
    assert route_hallmark("use hallmark to redesign this dashboard") == "hallmark redesign use to this dashboard"
