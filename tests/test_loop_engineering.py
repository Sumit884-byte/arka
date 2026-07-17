from arka.agent.loop_engineering import MAX_ITERATIONS, STAGES, build_plan


def test_build_plan_is_bounded_and_has_verification() -> None:
    plan = build_plan("improve the checkout frontend", 3)
    assert plan.iterations == 3
    assert plan.stages == STAGES
    assert "frontend_loop" in plan.skills
    assert "ci" in plan.skills
    assert "review" in plan.skills


def test_plan_rejects_unbounded_iterations() -> None:
    try:
        build_plan("fix tests", MAX_ITERATIONS + 1)
    except ValueError as exc:
        assert "between 1 and" in str(exc)
    else:
        raise AssertionError("expected iteration bound")


def test_symbolic_route() -> None:
    from arka.routing.symbolic import route_loop_engineering

    assert route_loop_engineering("engineering loop fix tests for 2 iterations") == (
        "loop-engineering --iterations 2 fix tests"
    )

