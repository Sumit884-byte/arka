from arka.llm import hybrid


def test_route_partitions_and_policy(monkeypatch):
    monkeypatch.setattr(hybrid, "ordered_model_candidates", lambda **_: [("ollama", "qwen"), ("openrouter", "x")])
    monkeypatch.setattr(hybrid, "provider_available", lambda provider: True)
    result = hybrid.route("hosted-first")
    assert result.hosted == (("openrouter", "x"),)
    assert result.candidates[0] == ("openrouter", "x")


def test_local_only_has_no_hosted(monkeypatch):
    monkeypatch.setattr(hybrid, "ordered_model_candidates", lambda **_: [("ollama", "qwen"), ("openrouter", "x")])
    monkeypatch.setattr(hybrid, "provider_available", lambda provider: True)
    result = hybrid.route("local-only")
    assert result.candidates == (("ollama", "qwen"),)


def test_status_cli(monkeypatch, capsys):
    monkeypatch.setattr(hybrid, "ordered_model_candidates", lambda **_: [])
    assert hybrid.main(["status"]) == 0
    assert "local: none" in capsys.readouterr().out


def test_parallel_uses_one_local_and_one_hosted(monkeypatch):
    monkeypatch.setattr(hybrid, "ordered_model_candidates", lambda **_: [("ollama", "qwen"), ("openrouter", "x")])
    monkeypatch.setattr(hybrid, "provider_available", lambda provider: True)
    calls = []
    monkeypatch.setattr(hybrid, "llm_complete", lambda *args, **kwargs: calls.append(kwargs["chain"]) or "answer")
    result = hybrid.complete("system", "question", policy="parallel")
    assert len(calls) == 2
    assert "ollama/qwen" in result
    assert "openrouter/x" in result
