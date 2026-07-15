from pathlib import Path

from arka.agent.repo_graph import build, render
from arka.routing.symbolic import route_offline_extras


def test_build_finds_import_edges_and_priorities(tmp_path: Path):
    (tmp_path / "a.py").write_text("import b\n# TODO: finish\n")
    (tmp_path / "b.py").write_text("VALUE = 1\n")
    graph = build(tmp_path)
    assert {edge["to"] for edge in graph["edges"]} == {"b.py"}
    assert graph["priority"][0]["file"] == "a.py"
    assert "graph TD" in render(graph, "mermaid")


def test_repo_graph_nl_route():
    assert route_offline_extras("show the repository dependency graph and priorities") == "repo_graph"
