from arka.agent.spline_guide import guide
from arka.routing.symbolic import route_spline


def test_spline_topics(monkeypatch):
    from arka.agent import spline_guide

    monkeypatch.setattr(spline_guide, "spline_mcp_available", lambda: False)
    assert "react-spline" in guide("react")
    assert "lazy-load" in guide("performance")
    assert "arka mcp preset spline --apply" in guide("web")


def test_spline_route():
    assert route_spline("how do I embed a Spline 3D model in React") == "spline react"


def test_spline_uses_mcp_when_configured(monkeypatch):
    from arka.agent import spline_guide

    monkeypatch.setattr(spline_guide, "spline_mcp_available", lambda: True)
    monkeypatch.setattr(spline_guide, "query_spline_mcp", lambda topic: "mcp answer")

    assert guide("react").startswith("Spline MCP preferred")
    assert "mcp answer" in guide("react")
