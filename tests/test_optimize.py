def test_bounded_optimizer_finds_minimum() -> None:
    from arka.agent.optimize import optimize
    result = optimize("(x - 3)**2", -10, 10, iterations=80, seed=4)
    assert abs(result["x"] - 3) < 1
