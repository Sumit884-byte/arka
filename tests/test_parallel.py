from arka.agent.parallel import run_jobs
from arka.routing.symbolic import route_parallel


def test_parallel_jobs(monkeypatch):
    monkeypatch.setattr("arka.dispatch.run_skill", lambda job: 0)
    results = run_jobs(["ci", "review"], workers=2)
    assert [item["job"] for item in results] == ["ci", "review"]
    assert all(item["exit_code"] == 0 for item in results)


def test_parallel_route():
    assert route_parallel('run skills "ci" and "route audit" in parallel') == "parallel --job ci --job 'route audit'"
