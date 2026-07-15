from arka.agent.hackathon import plan
from arka.routing.symbolic import route_offline_extras


def test_hackathon_plan_is_bounded():
    result = plan("climate AI", hours=24)
    assert result["schedule_hours"] == 24
    assert result["milestones"]
    assert "do not submit" in " ".join(result["guardrails"])


def test_hackathon_nl_routes():
    assert route_offline_extras("find hackathons about robotics") == "hackathon find about robotics"
    assert route_offline_extras("participate in a fintech hackathon") == "hackathon plan fintech"
