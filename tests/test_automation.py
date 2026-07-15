import pytest

from arka.agent.automation import validate_steps
from arka.routing.symbolic import route_offline_extras


def test_validates_declarative_steps():
    validate_steps([{"action": "click", "selector": "button"}, {"action": "wait", "ms": 10}])


def test_rejects_unknown_action():
    with pytest.raises(ValueError):
        validate_steps([{"action": "run_shell"}])


def test_routes_app_automation():
    result = route_offline_extras("automate this web app at http://localhost:3000 for testing")
    assert result == "automate http://localhost:3000"
