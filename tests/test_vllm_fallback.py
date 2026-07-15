def test_vllm_fallback_can_be_enabled(monkeypatch) -> None:
    import arka.llm.fallback as fallback
    monkeypatch.setenv("VLLM_FALLBACK", "1")
    monkeypatch.setattr(fallback, "vllm_explicitly_configured", lambda: False)
    monkeypatch.setattr(fallback, "is_reachable", lambda provider: False)
    monkeypatch.setattr(fallback, "_explicit_fallback_chain", lambda task: None)
    monkeypatch.setattr(fallback, "_has_openrouter", lambda: False)
    monkeypatch.setattr(fallback, "_has_primary_cloud_keys", lambda: False)
    chain = fallback.build_default_chain()
    assert ("vllm", "default") in chain
