from unittest.mock import patch

def test_bounded_iterations() -> None:
    from arka.agent.iterate import run_iterations
    with patch("arka.agent.iterate._run", return_value=0) as run:
        assert run_iterations("repo_health", 3) == 0
        assert run.call_count == 3

def test_interval_loop_count() -> None:
    from arka.agent.iterate import run_loop
    with patch("arka.agent.iterate._run", return_value=0) as run, patch("arka.agent.iterate.time.sleep"):
        assert run_loop("repo_health", 1, 2) == 0
        assert run.call_count == 2
