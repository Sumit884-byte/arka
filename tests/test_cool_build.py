from arka.agent.cool_build import plan
from arka.routing.symbolic import route_cool_build


def test_cool_plan_requires_approval():
    assert "deploy only after explicit approval" in plan("a visual notes app")["steps"]


def test_cool_route():
    assert route_cool_build("build something cool for local developers") == "build_something_cool 'something cool for local developers'"
    assert route_cool_build("build some cool features for the dashboard") == "build_something_cool 'some cool features for the dashboard'"
