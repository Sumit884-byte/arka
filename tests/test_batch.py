import json
from datetime import datetime

from arka.agent import batch
from arka.routing.symbolic import route_offline_extras


def test_parse_due_at_relative_minutes():
    base = datetime(2026, 7, 19, 10, 0, 0)
    assert batch.parse_due_at("in 15 minutes", base=base) == "2026-07-19T10:15:00"


def test_batch_add_list_and_print_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(batch, "BATCH_FILE", tmp_path / "prompt-batches.json")
    assert batch.main(["start", "--until", "in 1 hour"]) == 0
    assert batch.main(["add", "fix", "routing"]) == 0
    capsys.readouterr()
    assert batch.main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows["default"]["items"][0]["prompt"] == "fix routing"
    assert batch.main(["run", "--print"]) == 0
    out = capsys.readouterr().out
    assert "Implement this Arka prompt batch" in out
    assert "fix routing" in out


def test_batch_run_dispatches_agent_code_and_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "BATCH_FILE", tmp_path / "prompt-batches.json")
    calls = []
    monkeypatch.setattr("arka.dispatch.run_skill", lambda line: calls.append(line) or 0)
    assert batch.main(["add", "add", "tests", "--until", "now"]) == 0
    assert batch.main(["run"]) == 0
    assert calls
    assert calls[0].startswith("agent_code ")
    assert "add tests" in calls[0]
    assert batch._load() == {}


def test_batch_route():
    assert route_offline_extras("collect all prompts until 6pm") == "batch start --until 6pm"
    assert route_offline_extras("batch add fix routing").startswith("batch add ")
    assert route_offline_extras("run batch") == "batch run"
