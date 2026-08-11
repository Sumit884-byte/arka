from unittest.mock import patch

from arka.llm.arbitrage import (
    CostCandidate,
    apply_swap,
    estimate_cost,
    evaluate_swap,
    rank_available_candidates,
    run_once,
    status_payload,
)


def test_estimate_cost_openrouter_free():
    assert estimate_cost("openrouter", "meta-llama/llama-3.3-70b-instruct:free") == 0.0


def test_estimate_cost_ollama_zero():
    assert estimate_cost("ollama", "llama3.2") == 0.0


def test_estimate_cost_gemini_heuristic():
    cheap = estimate_cost("gemini", "gemini-2.0-flash-lite")
    costly = estimate_cost("gemini", "gemini-ultra-enterprise")
    assert cheap < costly


def test_rank_available_candidates_sorts_by_cost(monkeypatch):
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "openai")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "gpt-4o")

    with patch("arka.llm.arbitrage.provider_available", side_effect=lambda slug: slug == "ollama"), patch(
        "arka.llm.arbitrage.ollama_model_ids", return_value=["llama3.2"]
    ), patch("arka.llm.arbitrage.fetch_openrouter_models_live", return_value=[]), patch(
        "arka.llm.providers.provider_specs", return_value=[]
    ):
        rows = rank_available_candidates(limit=5)
    assert rows
    assert rows[0].provider == "ollama"
    assert rows[0].cost == 0.0


def test_evaluate_swap_to_cheaper_local(monkeypatch):
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "openai")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "gpt-4o")

    candidates = [
        CostCandidate("ollama", "llama3.2", 0.0, "local"),
        CostCandidate("openai", "gpt-4o", 2.0, "preferred"),
    ]
    with patch("arka.llm.arbitrage.get_preferred", return_value=("openai", "gpt-4o")), patch(
        "arka.llm.arbitrage.rank_available_candidates", return_value=candidates
    ), patch("arka.llm.arbitrage.estimate_cost", side_effect=lambda p, m: 2.0 if p == "openai" else 0.0):
        decision = evaluate_swap(min_savings_ratio=0.1)

    assert decision is not None
    assert decision["to"]["provider"] == "ollama"
    assert decision["savings_ratio"] >= 0.1


def test_apply_swap_dry_run():
    decision = {
        "from": {"provider": "openai", "model": "gpt-4o"},
        "to": {"provider": "ollama", "model": "llama3.2"},
        "savings_ratio": 1.0,
    }
    result = apply_swap(decision, dry_run=True)
    assert result["dry_run"] is True
    assert result["to"]["provider"] == "ollama"


def test_run_once_no_swap_when_already_cheap(monkeypatch):
    monkeypatch.setenv("AI_PREFERRED_PROVIDER", "ollama")
    monkeypatch.setenv("AI_PREFERRED_MODEL", "llama3.2")

    with patch("arka.llm.arbitrage.evaluate_swap", return_value=None), patch(
        "arka.llm.arbitrage.get_preferred", return_value=("ollama", "llama3.2")
    ), patch("arka.llm.arbitrage.rank_available_candidates", return_value=[]):
        payload = run_once(dry_run=False)

    assert payload["swapped"] is False
    assert payload["preferred"]["provider"] == "ollama"


def test_status_payload_shape(monkeypatch):
    monkeypatch.delenv("ARKA_ARBITRAGE_ENABLED", raising=False)
    with patch("arka.llm.arbitrage.get_preferred", return_value=("gemini", "gemini-2.0-flash")), patch(
        "arka.llm.arbitrage.rank_available_candidates", return_value=[]
    ):
        payload = status_payload()
    assert "preferred" in payload
    assert "env" in payload
