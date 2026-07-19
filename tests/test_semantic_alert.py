import json

from arka.agent.semantic_alert import main
from arka.routing.symbolic import route_offline_extras


def test_alert_requires_verified_deadline(capsys):
    assert main(["OpenAI Build Week deadline", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_deadline"


def test_alert_route():
    assert route_offline_extras("alert me when OpenAI Build Week deadline arrives").startswith("semantic_alert ")


def test_program_watch_requires_source_and_interval(capsys):
    assert main(["alert me whenever a new OpenAI hackathon or program comes", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_watch_config"
