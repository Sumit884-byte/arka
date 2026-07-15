from arka.agent.app_check import check
from arka.routing.symbolic import route_app_check


def test_detect_python_app(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    assert check(str(tmp_path))["commands"][0][:3] == ["python", "-m", "compileall"]


def test_route_app_check():
    assert route_app_check("build and test this app") == "app_check . --run"
