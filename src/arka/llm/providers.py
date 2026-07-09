#!/usr/bin/env python3
"""LLM provider registry — env keys, defaults, and OpenAI-compatible endpoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ProviderKind = Literal["native", "openai_compatible", "local_openai"]


@dataclass(frozen=True)
class ProviderSpec:
    slug: str
    display_name: str
    env_keys: tuple[str, ...]
    default_model: str
    kind: ProviderKind
    base_url_env: str = ""
    default_base_url: str = ""
    models_env: str = ""
    default_models: tuple[str, ...] = ()
    api_key_env: str = ""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def provider_specs() -> tuple[ProviderSpec, ...]:
    return PROVIDERS


def get_provider(slug: str) -> ProviderSpec | None:
    key = (slug or "").strip().lower()
    for spec in PROVIDERS:
        if spec.slug == key:
            return spec
    return None


def provider_base_url(spec: ProviderSpec) -> str:
    if spec.base_url_env:
        url = _env(spec.base_url_env)
        if not url and spec.slug == "vllm-cloud":
            url = _env("VLLM_CLOUD_API_URL")
        if not url and spec.slug == "vllm":
            host = _env("VLLM_HOST", "127.0.0.1:8000")
            url = f"http://{host}" if not host.startswith("http") else host
        if url:
            base = url.rstrip("/")
            if spec.slug == "vllm" and not base.endswith("/v1"):
                base = f"{base}/v1"
            return base
    return (spec.default_base_url or "").rstrip("/")


def vllm_cloud_configured() -> bool:
    """True when a remote vLLM OpenAI-compatible endpoint is configured."""
    spec = get_provider("vllm-cloud")
    return bool(spec and provider_base_url(spec))


def provider_api_key(spec: ProviderSpec) -> str:
    if spec.api_key_env:
        val = _env(spec.api_key_env)
        if val:
            return val
    for name in spec.env_keys:
        val = _env(name)
        if val:
            return val
    return ""


def provider_model_ids(spec: ProviderSpec) -> list[str]:
    if spec.models_env:
        raw = _env(spec.models_env)
        if raw:
            out: list[str] = []
            for part in raw.replace(";", ",").split(","):
                mid = part.strip()
                if mid and mid not in out:
                    out.append(mid)
            if out:
                return out
    if spec.default_models:
        return list(spec.default_models)
    if spec.default_model:
        return [spec.default_model]
    return []


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        slug="anthropic",
        display_name="Anthropic (Claude)",
        env_keys=("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS"),
        default_model="claude-sonnet-4-20250514",
        kind="native",
        models_env="ANTHROPIC_MODELS",
        default_models=("claude-sonnet-4-20250514", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"),
    ),
    ProviderSpec(
        slug="openai",
        display_name="OpenAI (GPT)",
        env_keys=("OPENAI_API_KEY", "OPENAI_API_KEYS"),
        default_model="gpt-4o-mini",
        kind="native",
        models_env="OPENAI_MODELS",
        default_models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
    ),
    ProviderSpec(
        slug="gemini",
        display_name="Google AI (Gemini)",
        env_keys=("GEMINI_API_KEY", "GEMINI_API_KEYS", "GOOGLE_API_KEY"),
        default_model="gemini-2.0-flash",
        kind="native",
        models_env="GEMINI_MODELS",
        default_models=("gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"),
    ),
    ProviderSpec(
        slug="groq",
        display_name="Groq",
        env_keys=("GROQ_API_KEY", "GROQ_API_KEYS"),
        default_model="llama-3.3-70b-versatile",
        kind="native",
        models_env="GROQ_MODELS",
        default_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
    ),
    ProviderSpec(
        slug="xai",
        display_name="xAI (Grok)",
        env_keys=("XAI_API_KEY", "XAI_API_KEYS"),
        api_key_env="XAI_API_KEY",
        default_model="grok-2-latest",
        kind="openai_compatible",
        base_url_env="XAI_API_BASE",
        default_base_url="https://api.x.ai/v1",
        models_env="XAI_MODELS",
        default_models=("grok-2-latest", "grok-beta"),
    ),
    ProviderSpec(
        slug="deepseek",
        display_name="DeepSeek",
        env_keys=("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEYS"),
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        kind="openai_compatible",
        base_url_env="DEEPSEEK_API_BASE",
        default_base_url="https://api.deepseek.com/v1",
        models_env="DEEPSEEK_MODELS",
        default_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderSpec(
        slug="moonshot",
        display_name="Moonshot AI (Kimi)",
        env_keys=("MOONSHOT_API_KEY", "MOONSHOT_API_KEYS", "KIMI_API_KEY"),
        api_key_env="MOONSHOT_API_KEY",
        default_model="moonshot-v1-8k",
        kind="openai_compatible",
        base_url_env="MOONSHOT_API_BASE",
        default_base_url="https://api.moonshot.ai/v1",
        models_env="MOONSHOT_MODELS",
        default_models=("moonshot-v1-8k", "moonshot-v1-32k", "kimi-k2-turbo-preview"),
    ),
    ProviderSpec(
        slug="zai",
        display_name="Z.AI (GLM)",
        env_keys=("ZAI_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY"),
        api_key_env="ZAI_API_KEY",
        default_model="glm-4-flash",
        kind="openai_compatible",
        base_url_env="ZAI_API_BASE",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        models_env="ZAI_MODELS",
        default_models=("glm-4-flash", "glm-4-plus"),
    ),
    ProviderSpec(
        slug="minimax",
        display_name="MiniMax",
        env_keys=("MINIMAX_API_KEY", "MINIMAX_API_KEYS"),
        api_key_env="MINIMAX_API_KEY",
        default_model="MiniMax-Text-01",
        kind="openai_compatible",
        base_url_env="MINIMAX_API_BASE",
        default_base_url="https://api.minimax.io/v1",
        models_env="MINIMAX_MODELS",
        default_models=("MiniMax-Text-01", "abab6.5s-chat"),
    ),
    ProviderSpec(
        slug="venice",
        display_name="Venice.ai",
        env_keys=("VENICE_API_KEY", "VENICE_API_KEYS"),
        api_key_env="VENICE_API_KEY",
        default_model="venice-uncensored",
        kind="openai_compatible",
        base_url_env="VENICE_API_BASE",
        default_base_url="https://api.venice.ai/api/v1",
        models_env="VENICE_MODELS",
        default_models=("venice-uncensored", "llama-3.3-70b"),
    ),
    ProviderSpec(
        slug="bedrock",
        display_name="Amazon Bedrock",
        env_keys=("AWS_ACCESS_KEY_ID", "AWS_BEDROCK_API_KEY", "BEDROCK_API_KEY"),
        api_key_env="BEDROCK_API_KEY",
        default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        kind="openai_compatible",
        base_url_env="BEDROCK_API_BASE",
        default_base_url="",
        models_env="BEDROCK_MODELS",
        default_models=("anthropic.claude-3-5-sonnet-20241022-v2:0", "amazon.nova-lite-v1:0"),
    ),
    ProviderSpec(
        slug="azure",
        display_name="Azure Foundry",
        env_keys=("AZURE_OPENAI_API_KEY", "AZURE_API_KEY"),
        api_key_env="AZURE_OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        kind="openai_compatible",
        base_url_env="AZURE_OPENAI_ENDPOINT",
        default_base_url="",
        models_env="AZURE_OPENAI_MODELS",
        default_models=("gpt-4o-mini", "gpt-4o"),
    ),
    ProviderSpec(
        slug="openrouter",
        display_name="OpenRouter",
        env_keys=("OPENROUTER_API_KEY", "OPENROUTER_API_KEYS"),
        api_key_env="OPENROUTER_API_KEY",
        default_model="anthropic/claude-3.5-sonnet",
        kind="openai_compatible",
        base_url_env="OPENROUTER_API_BASE",
        default_base_url="https://openrouter.ai/api/v1",
        models_env="OPENROUTER_MODELS",
        default_models=("anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash-001", "openai/gpt-4o-mini"),
    ),
    ProviderSpec(
        slug="litellm",
        display_name="LiteLLM",
        env_keys=("LITELLM_API_KEY", "LITELLM_MASTER_KEY"),
        api_key_env="LITELLM_API_KEY",
        default_model="gpt-4o-mini",
        kind="local_openai",
        base_url_env="LITELLM_API_BASE",
        default_base_url="http://127.0.0.1:4000/v1",
        models_env="LITELLM_MODELS",
        default_models=("gpt-4o-mini", "claude-3-5-sonnet-latest"),
    ),
    ProviderSpec(
        slug="ollama",
        display_name="Ollama (local models)",
        env_keys=("OLLAMA_API_KEY", "OLLAMA_API_KEYS"),
        default_model="llama3.2:1b",
        kind="native",
        models_env="OLLAMA_MODELS",
        default_models=("minimax-m2.5:cloud", "qwen3:8b", "llama3.2:1b"),
    ),
    ProviderSpec(
        slug="lmstudio",
        display_name="LM Studio (local models)",
        env_keys=("LMSTUDIO_API_KEY",),
        api_key_env="LMSTUDIO_API_KEY",
        default_model="local-model",
        kind="local_openai",
        base_url_env="LMSTUDIO_API_BASE",
        default_base_url="http://127.0.0.1:1234/v1",
        models_env="LMSTUDIO_MODELS",
        default_models=("local-model",),
    ),
    ProviderSpec(
        slug="vllm",
        display_name="vLLM (local OpenAI-compatible)",
        env_keys=("VLLM_API_KEY", "VLLM_API_KEYS"),
        api_key_env="VLLM_API_KEY",
        default_model="default",
        kind="local_openai",
        base_url_env="VLLM_API_URL",
        default_base_url="http://127.0.0.1:8000/v1",
        models_env="VLLM_MODELS",
        default_models=(),
    ),
    ProviderSpec(
        slug="vllm-cloud",
        display_name="vLLM Cloud (remote OpenAI-compatible)",
        env_keys=("VLLM_CLOUD_API_KEY", "VLLM_CLOUD_API_KEYS"),
        api_key_env="VLLM_CLOUD_API_KEY",
        default_model="default",
        kind="openai_compatible",
        base_url_env="VLLM_CLOUD_URL",
        default_base_url="",
        models_env="VLLM_CLOUD_MODELS",
        default_models=(),
    ),
)

OPENAI_COMPAT_SLUGS = frozenset(
    spec.slug for spec in PROVIDERS if spec.kind in {"openai_compatible", "local_openai"}
)
