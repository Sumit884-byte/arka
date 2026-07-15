from arka.agent.pr_check import route_command


def test_routes_github_issue_fix_request_to_coding_agent():
    route = route_command("fix GitHub issues in my code")
    assert route.startswith("agent_code ")
    assert "focused tests" in route
