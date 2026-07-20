from arka.llm.prompt_compact import compact_user_prompt


def test_verbose_prompt_becomes_compact_task_ir(monkeypatch):
    monkeypatch.delenv("ARKA_PROMPT_COMPACT", raising=False)
    prompt = (
        "I want you to please help with this repo. " * 20
        + "You must fix routing for background processes. "
        + "You must fix routing for background processes. "
        + "Add tests and docs. Verify with pytest. "
        + "Do not invent URLs or files."
    )

    result = compact_user_prompt(prompt, force=True, task="chat")

    assert result.changed
    assert result.compact.startswith("Task IR:")
    assert len(result.compact) < len(prompt)
    assert result.compact.count("fix routing for background processes") == 1
    assert "Do not invent URLs or files" in result.compact


def test_compaction_preserves_protected_literals(monkeypatch):
    monkeypatch.delenv("ARKA_PROMPT_COMPACT", raising=False)
    prompt = (
        "Please carefully review this implementation and update it. " * 20
        + "Use https://example.com/api exactly. "
        + "Run command:\npython -m pytest tests/test_api.py\n"
        + "Keep JSON {\"mode\":\"safe\"} unchanged. "
        + "Verify tests after editing."
    )

    result = compact_user_prompt(prompt, force=True, task="chat")

    assert result.changed
    assert "https://example.com/api" in result.compact
    assert "python -m pytest tests/test_api.py" in result.compact
    assert "{\"mode\":\"safe\"}" in result.compact


def test_compaction_can_be_disabled_and_skips_route(monkeypatch):
    prompt = "Add tests and docs. " * 100
    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "0")
    assert compact_user_prompt(prompt, task="chat").compact == prompt
    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "1")
    assert compact_user_prompt(prompt, task="route").compact == prompt


def test_compaction_is_idempotent():
    prompt = "Fix routing and add tests. " * 80
    once = compact_user_prompt(prompt, force=True, task="chat").compact
    twice = compact_user_prompt(once, force=True, task="chat").compact
    assert twice == once
