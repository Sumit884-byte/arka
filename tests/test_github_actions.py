from arka.agent.github_actions import inspect, scaffold
from arka.routing.symbolic import route_github_actions


def test_scaffold_and_no_overwrite(tmp_path):
    path = scaffold(str(tmp_path))
    assert path.name == "arka-ci.yml"
    assert inspect(str(tmp_path)) == [path]


def test_route_github_actions():
    assert route_github_actions("setup GitHub Actions in this repo") == "github_actions new ."
    assert route_github_actions("did the production GitHub Actions build fail?") == "github_actions status ."
