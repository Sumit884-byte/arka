from arka.agent.spline_guide import guide
from arka.routing.symbolic import route_spline


def test_spline_topics():
    assert "react-spline" in guide("react")
    assert "lazy-load" in guide("performance")


def test_spline_route():
    assert route_spline("how do I embed a Spline 3D model in React") == "spline react"
