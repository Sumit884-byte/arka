from arka.agent.surgical_edit import edit, find
from arka.routing.symbolic import route_surgical_edit


def test_surgical_edit_requires_unique_match(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("alpha\nalpha\n")
    assert len(find(str(path), "alpha")) == 2
    assert edit(str(path), "alpha", "beta", yes=True) == 2
    assert edit(str(path), "alpha", "beta", all_matches=True, yes=True) == 0
    assert path.read_text() == "beta\nbeta\n"


def test_surgical_route():
    assert route_surgical_edit("surgical edit in app.py: replace 'old' with 'new'") == "surgical_edit edit app.py old new"
