from arka.llm import free_models
from arka.routing.symbolic import route_offline_extras


def test_discover_labels_cost_confidence(monkeypatch):
    monkeypatch.setattr(free_models, "openrouter_model_ids", lambda **_: ["demo:free"])
    monkeypatch.setattr(free_models, "openrouter_model_meta", lambda model: {"completion_price": 0.0})
    monkeypatch.setattr(free_models, "fetch_ollama_models_live", lambda: ["qwen3:8b"])
    assert {row["model"] for row in free_models.discover()} >= {"demo:free", "qwen3:8b"}
    assert all(row["confidence"] for row in free_models.discover())


def test_free_models_route():
    assert route_offline_extras("find free models across providers") == "free_models"
    assert route_offline_extras("which ChatGPT models can I access for free") == "free_models --provider openai"
    assert route_offline_extras("which Codex models can I access for free") == "free_models --provider openai"


def test_free_models_route_is_not_a_generic_free_keyword_trap():
    assert route_offline_extras("plugin doctor") != "free_models"
    assert route_offline_extras("free tier setup") != "free_models"
    assert route_offline_extras("free plugin doctor") != "free_models"


def test_openai_access_is_plan_labeled(monkeypatch):
    rows = free_models.discover(live=False, provider="chatgpt")
    assert rows[0]["provider"] == "openai/chatgpt"
    assert rows[0]["cost"] == "plan-dependent"


def test_exact_model_query_routes_to_verified_selection():
    result = route_offline_extras("can I access gpt 5.6 luna for free")
    assert result == "free_models --provider openai --model gpt-5.6-luna --select"


def test_symbolic_model_normalization_preserves_unknown_ids():
    assert free_models.normalize_model_name("ChatGPT") == "gpt"
    assert free_models.normalize_model_name("gpt 5.6 luna") == "gpt-5.6-luna"
    assert free_models.normalize_model_name("vendor/custom model") == "vendor/custom-model"
