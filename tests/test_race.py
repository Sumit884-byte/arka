from arka.agent import race
from arka.routing.symbolic import route_offline_extras


def test_race_runs_and_judges(monkeypatch):
    monkeypatch.setattr(race, "contestant", lambda task, spec: {"model": spec, "status": "ok", "answer": spec})
    monkeypatch.setattr(race, "judge", lambda task, answers, judge_spec="": {"winner": 1, "scores": {"1": 9}, "rationale": "clear"})
    result = race.run("solve it", ["a/b", "c/d"])
    assert len(result["contestants"]) == 2
    assert result["judge"]["winner"] == 1


def test_race_nl_route():
    result = route_offline_extras("race several agents on a coding task")
    assert result.startswith("race ")
    assert "--models" in result
