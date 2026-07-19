"""Discover models that are free to use or have no per-token cost."""
from __future__ import annotations

import argparse
import json
import re

from arka.llm.fallback import fetch_ollama_models_live, ollama_model_ids, openrouter_model_ids, openrouter_model_meta


def normalize_model_name(value: str) -> str:
    """Canonicalize common natural-language model names without guessing unknown IDs."""
    raw = " ".join((value or "").strip().lower().split())
    aliases = {"chat gpt": "gpt", "chatgpt": "gpt", "gpt 4o": "gpt-4o", "gpt 4.1": "gpt-4.1"}
    if raw in aliases:
        return aliases[raw]
    raw = re.sub(r"\bgpt\s+([0-9]+(?:\.[0-9]+)?)\s+luna\b", r"gpt-\1-luna", raw)
    raw = re.sub(r"\bgpt\s+([0-9]+(?:\.[0-9]+)?)\b", r"gpt-\1", raw)
    raw = re.sub(r"[^a-z0-9._:/-]+", "-", raw).strip("-")
    return raw


def discover(*, live: bool = True, limit: int = 50, provider: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    # Local runtimes have no provider token cost; availability is labeled separately.
    provider_filter = provider.lower().replace("chatgpt", "openai").replace("gpt", "openai")
    local = fetch_ollama_models_live() if live else ollama_model_ids(include_live=False)
    if not provider_filter or provider_filter == "ollama":
        for model in local:
            rows.append({"provider": "ollama", "model": model, "cost": "local-zero-cost", "confidence": "runtime/catalog"})
    for model in (openrouter_model_ids(include_live=live) if live else openrouter_model_ids(include_live=False)) if not provider_filter or provider_filter == "openrouter" else []:
        meta = openrouter_model_meta(model) or {}
        if ":free" in model or float(meta.get("completion_price", 1.0) or 1.0) == 0:
            rows.append({"provider": "openrouter", "model": model, "cost": "free", "confidence": "live-pricing" if meta else "model-id"})
    for provider_name, models in (("gemini", ["gemini-2.0-flash-lite"]), ("groq", ["llama-3.1-8b-instant"])):
        if provider_filter and provider_filter != provider_name:
            continue
        for model in models:
            rows.append({"provider": provider_name, "model": model, "cost": "free-tier-eligible", "confidence": "provider-plan-dependent"})
    if not provider_filter or provider_filter == "openai":
        rows.append({"provider": "openai/chatgpt", "model": "eligible models vary by ChatGPT plan", "cost": "plan-dependent", "confidence": "account-required"})
    unique: dict[tuple[str, str], dict[str, str]] = {(row["provider"], row["model"]): row for row in rows}
    return list(unique.values())[: max(1, limit)]


def select_requested(model: str, provider: str = "openai") -> dict[str, str | bool]:
    """Select only a model confirmed by the provider catalog/configuration."""
    from arka.llm.provider_select import detect_provider_models, set_env_vars

    model = normalize_model_name(model)
    provider = provider.lower().replace("chatgpt", "openai")
    models, source = detect_provider_models(provider, include_live=True)
    if model not in models:
        return {"selected": False, "provider": provider, "model": model, "reason": "model is not present in the provider catalog; plan-only ChatGPT access cannot be verified by the API"}
    set_env_vars({"AI_PREFERRED_PROVIDER": provider, "AI_PREFERRED_MODEL": model})
    return {"selected": True, "provider": provider, "model": model, "source": source}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka free-models")
    parser.add_argument("--offline", action="store_true", help="use catalogs without live provider queries")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--provider", default="", help="Filter provider, e.g. chatgpt, openai, ollama, openrouter")
    parser.add_argument("--model", default="", help="Check one exact model id")
    parser.add_argument("--select", action="store_true", help="Select the model only after catalog verification")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.model:
        result = select_requested(args.model, args.provider or "openai") if args.select else next((row for row in discover(live=not args.offline, limit=args.limit, provider=args.provider) if row["model"] == args.model), {"selected": False, "model": args.model, "reason": "not confirmed as free"})
        print(json.dumps(result, indent=2) if args.json else str(result))
        return 0 if result.get("selected") or not args.select else 1
    rows = discover(live=not args.offline, limit=args.limit, provider=args.provider)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print("provider\tmodel\tcost\tconfidence")
        for row in rows:
            print("\t".join(row.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
