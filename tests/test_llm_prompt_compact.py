def test_llm_complete_compacts_before_backend(monkeypatch):
    from arka.llm import cli

    seen = {}

    def fake_fallback(system, user, temperature, *, task=None, skill=None):
        seen["system"] = system
        seen["user"] = user
        seen["task"] = task
        return "ok"

    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "1")
    monkeypatch.setenv("ARKA_PROMPT_COMPACT_MIN_CHARS", "400")
    monkeypatch.setattr(cli, "_fallback_complete", fake_fallback)
    monkeypatch.setattr("arka.core.security.apply_llm_security", lambda system, user, task=None: ("", system, user))

    prompt = "Please help. " * 60 + "You must update docs. Add tests. Verify with pytest."

    assert cli.llm_complete("system", prompt, task="chat") == "ok"
    assert seen["user"].startswith("Task IR:")
    assert "update docs" in seen["user"]
    assert len(seen["user"]) < len(prompt)


def test_llm_complete_security_sees_original_before_compaction(monkeypatch):
    from arka.llm import cli

    calls = {}

    def fake_security(system, user, task=None):
        calls["security_user"] = user
        return "", system, user

    def fake_fallback(system, user, temperature, *, task=None, skill=None):
        calls["backend_user"] = user
        return "ok"

    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "1")
    monkeypatch.setenv("ARKA_PROMPT_COMPACT_MIN_CHARS", "400")
    monkeypatch.setattr("arka.core.security.apply_llm_security", fake_security)
    monkeypatch.setattr(cli, "_fallback_complete", fake_fallback)
    prompt = "Context only. " * 60 + "Need to preserve this exact requirement. Verify output."

    cli.llm_complete("system", prompt, task="chat")

    assert calls["security_user"] == prompt
    assert calls["backend_user"] != prompt
    assert calls["backend_user"].startswith("Task IR:")


def test_llm_complete_no_compact_opt_out(monkeypatch):
    from arka.llm import cli

    seen = {}
    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "1")
    monkeypatch.setenv("ARKA_PROMPT_COMPACT_MIN_CHARS", "400")
    monkeypatch.setattr("arka.core.security.apply_llm_security", lambda system, user, task=None: ("", system, user))
    monkeypatch.setattr(
        cli,
        "_fallback_complete",
        lambda system, user, temperature, *, task=None, skill=None: seen.setdefault("user", user) or "ok",
    )
    prompt = "Need to update docs. " * 40

    cli.llm_complete("system", prompt, task="chat", compact=False)

    assert seen["user"] == prompt


def test_fallback_llm_complete_compacts_direct_call(monkeypatch):
    from arka.llm import fallback

    seen = {}

    class FakeEngine:
        def complete(self, system, user, temperature=0.2):
            seen["user"] = user

            class Result:
                text = "ok"

            return Result()

    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "1")
    monkeypatch.setenv("ARKA_PROMPT_COMPACT_MIN_CHARS", "400")
    monkeypatch.setattr(fallback, "LlmFallbackEngine", lambda **kwargs: FakeEngine())
    prompt = "Context only. " * 60 + "Must preserve direct fallback callers. Add tests."

    assert fallback.llm_complete("system", prompt, task="chat") == "ok"
    assert seen["user"].startswith("Task IR:")
    assert "direct fallback callers" in seen["user"]


def test_fallback_stream_complete_compacts_direct_call(monkeypatch):
    from arka.llm import fallback

    seen = {}

    class FakeEngine:
        def stream_complete(self, system, user, temperature=0.2):
            seen["user"] = user
            yield "ok"

    monkeypatch.setenv("ARKA_PROMPT_COMPACT", "1")
    monkeypatch.setenv("ARKA_PROMPT_COMPACT_MIN_CHARS", "400")
    monkeypatch.setattr(fallback, "LlmFallbackEngine", lambda **kwargs: FakeEngine())
    prompt = "Context only. " * 60 + "Must preserve direct stream callers. Add tests."

    assert list(fallback.llm_stream_complete("system", prompt, task="chat")) == ["ok"]
    assert seen["user"].startswith("Task IR:")
    assert "direct stream callers" in seen["user"]
