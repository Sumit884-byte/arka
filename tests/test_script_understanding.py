from arka.agent.script_understanding import remember, understand
from arka.routing.symbolic import route_script_understanding


def test_understand_and_remember(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    script = tmp_path / "tool.py"
    script.write_text("import argparse\ndef main(): pass\n")
    data = understand(str(script))
    assert data["has_cli"] is True
    assert remember(str(script))["functions"] == ["main"]


def test_script_route():
    assert route_script_understanding("remember this script tools/build.py") == "understand_script remember tools/build.py"
