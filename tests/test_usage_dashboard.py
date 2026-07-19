from arka.agent.usage_dashboard import build
from arka.routing.symbolic import route_offline_extras


def test_usage_dashboard_is_local_and_rendered(tmp_path):
    result = build(str(tmp_path / "usage.html"))
    assert result["output"].endswith("usage.html")
    assert "Arka usage dashboard" in (tmp_path / "usage.html").read_text()


def test_usage_dashboard_route():
    assert route_offline_extras("show my Arka usage dashboard") == "usage dashboard"
