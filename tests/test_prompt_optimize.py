from arka.agent.prompt_optimize import optimize_user_prompt


def test_vague_prompt_gets_structured_guards(monkeypatch):
    monkeypatch.delenv("ARKA_PROMPT_OPTIMIZE", raising=False)
    result = optimize_user_prompt("build a dashboard")
    assert result.changed
    assert "intent" in result.optimized
    assert "Return the result first" in result.optimized


def test_protected_inputs_are_unchanged():
    for value in ["https://example.com/a", "curl https://example.com", '{"name":"arka"}', "```python\nprint(1)\n```"]:
        result = optimize_user_prompt(value)
        assert result.optimized == value


def test_opt_out_and_idempotence(monkeypatch):
    monkeypatch.setenv("ARKA_PROMPT_OPTIMIZE", "0")
    assert optimize_user_prompt("build an app").optimized == "build an app"
    monkeypatch.setenv("ARKA_PROMPT_OPTIMIZE", "1")
    once = optimize_user_prompt("build an app").optimized
    assert optimize_user_prompt(once).optimized == once
