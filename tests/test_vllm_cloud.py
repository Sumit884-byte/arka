import pytest


def test_vllm_cloud_configured_requires_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VLLM_CLOUD_URL", raising=False)
    monkeypatch.delenv("VLLM_CLOUD_API_URL", raising=False)

    from importlib import reload

    import arka.llm.providers as providers

    reload(providers)

    assert providers.vllm_cloud_configured() is False


def test_vllm_cloud_base_url_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VLLM_CLOUD_URL", "https://runpod.example/v1")

    from importlib import reload

    import arka.llm.providers as providers

    reload(providers)

    spec = providers.get_provider("vllm-cloud")
    assert spec is not None
    assert providers.provider_base_url(spec) == "https://runpod.example/v1"
    assert providers.vllm_cloud_configured() is True


def test_vllm_cloud_api_url_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VLLM_CLOUD_URL", raising=False)
    monkeypatch.setenv("VLLM_CLOUD_API_URL", "https://baseten.example/v1")

    from importlib import reload

    import arka.llm.providers as providers

    reload(providers)

    spec = providers.get_provider("vllm-cloud")
    assert spec is not None
    assert providers.provider_base_url(spec) == "https://baseten.example/v1"


def test_build_default_chain_includes_vllm_cloud(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_FALLBACK", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_CHAIN", raising=False)
    monkeypatch.setenv("VLLM_CLOUD_URL", "https://cloud.example/v1")
    monkeypatch.setenv("VLLM_CLOUD_MODEL", "demo-model")

    from importlib import reload

    import arka.llm.fallback as fb

    reload(fb)

    chain = fb.build_default_chain(task="default")
    assert ("vllm-cloud", "demo-model") in chain


def test_parse_chain_vllm_cloud_slug():
    from arka.llm.fallback import parse_chain

    assert parse_chain("vllm-cloud:demo-model") == [("vllm-cloud", "demo-model")]


def test_inference_backend_mapping():
    from arka.llm.fallback import _inference_backend

    assert _inference_backend("vllm-cloud") == "vllm-cloud"
    assert _inference_backend("vllm") == "vllm"


def test_llm_provider_http_url_vllm_cloud(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VLLM_CLOUD_URL", "https://cloud.example/v1")

    from arka.telemetry.tracing import llm_http_span_attributes, llm_provider_http_url

    url = llm_provider_http_url("vllm-cloud")
    assert url == "https://cloud.example/v1/chat/completions"
    attrs = llm_http_span_attributes("vllm-cloud")
    assert attrs["http.method"] == "POST"
    assert attrs["http.url"] == url


def test_record_llm_attempt_tags_vllm_cloud_backend():
    from arka.telemetry.metrics import record_llm_attempt

    record_llm_attempt(provider="vllm-cloud", model="demo", success=True)


def test_record_inference_op_noop_without_otel():
    from arka.telemetry.metrics import record_inference_op

    record_inference_op(backend="vllm-cloud", operation="check", success=False)


def test_vllm_cloud_models_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VLLM_CLOUD_URL", "https://cloud.example")

    from arka.llm.servers import _vllm_cloud_api_base, _vllm_cloud_models_url

    assert _vllm_cloud_api_base() == "https://cloud.example/v1"
    assert _vllm_cloud_models_url() == "https://cloud.example/v1/models"
