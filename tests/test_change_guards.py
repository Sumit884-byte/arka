from arka.agent.change_guards import animation_scope_guard


def test_animation_request_protects_tests():
    guard = animation_scope_guard("add more animations to the dashboard")
    assert "Do not modify tests" in guard


def test_explicit_test_animation_scope():
    assert "explicitly named test" in animation_scope_guard("add an animation test")


def test_unrelated_goal_has_no_guard():
    assert animation_scope_guard("fix the API response") == ""
