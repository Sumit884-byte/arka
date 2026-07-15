from arka.agent import multi_llm
from arka.routing.symbolic import route_multi_llm


def test_multi_llm_labels_and_continues(monkeypatch):
    monkeypatch.setattr("arka.llm.cli.llm_complete", lambda *a, **k: "answer")
    rows = multi_llm.run("hello", ["one/model-a", "two/model-b"])
    assert [row["model"] for row in rows] == ["one/model-a", "two/model-b"]
    assert all(row["status"] == "ok" for row in rows)


def test_multi_llm_route():
    assert route_multi_llm("give me several model alternatives for a landing page")
