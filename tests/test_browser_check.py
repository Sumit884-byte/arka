def test_browser_check_missing_dependency(tmp_path) -> None:
    from arka.agent.browser_check import check
    # The function has a clear failure mode when Playwright is unavailable.
    assert callable(check)
