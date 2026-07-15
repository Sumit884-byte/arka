from arka.llm import model_host_setup
from arka.routing.symbolic import route_offline_extras


def test_setup_writes_local_model_config(monkeypatch, tmp_path):
    monkeypatch.setattr(model_host_setup, "OPTIONS", model_host_setup.OPTIONS)
    monkeypatch.setattr("arka.llm.provider_select.set_env_vars", lambda values: tmp_path / ".env")
    result = model_host_setup.setup("ollama", model="qwen3:8b")
    assert result["host"] == "ollama"


def test_model_setup_nl_routes():
    assert route_offline_extras("set up Ollama for local AI models") == "model setup ollama"
    assert route_offline_extras("configure vLLM hosting") == "model setup vllm"
