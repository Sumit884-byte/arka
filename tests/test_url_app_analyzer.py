from arka.agent.url_app_analyzer import render
from arka.routing.symbolic import route_url_app


def test_render_interactive_review(tmp_path):
    out = render({"url": "https://example.com", "title": "Demo", "status": 200, "signals": ["heading"]}, str(tmp_path / "review.html"))
    assert "Prioritized improvement prompts" in out.read_text()


def test_url_app_route():
    assert route_url_app("analyze the app design at https://example.com") == "url_app https://example.com"
