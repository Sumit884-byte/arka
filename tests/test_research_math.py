def test_safe_math_and_script(tmp_path) -> None:
    from arka.agent.research_math import evaluate, main
    assert evaluate("sqrt(16) + 2**3") == 12.0
    assert main(["2 + 2", "--output", str(tmp_path / "calc.py")]) == 0

def test_blocks_code() -> None:
    from arka.agent.research_math import evaluate
    try:
        evaluate("__import__('os').system('id')")
    except ValueError:
        return
    raise AssertionError("unsafe expression was accepted")
