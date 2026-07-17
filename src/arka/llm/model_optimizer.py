"""Hardware- and preference-aware model recommendations."""
from __future__ import annotations
import argparse
import os
from arka.llm.model_advisor import probe_hardware

def recommend() -> dict[str, str]:
    hw = probe_hardware()
    mode = os.environ.get("ARKA_MODEL_MODE", "auto").lower()
    configured_model = ""
    try:
        from arka.core.default_config import read as read_defaults

        configured_model = str(read_defaults().get("model", "")).strip()
    except (ImportError, OSError, ValueError, TypeError):
        pass
    quant = os.environ.get("ARKA_QUANT", "4bit")
    context = os.environ.get("ARKA_MAX_CONTEXT", "auto")
    if mode == "offline" or mode == "cheap":
        model = os.environ.get("ARKA_PREFERRED_SMALL_MODEL", "llama3.2:3b")
    elif os.environ.get("ARKA_PREFERRED_CODING_MODEL") and mode == "performance":
        model = os.environ["ARKA_PREFERRED_CODING_MODEL"]
    elif hw.ram_total_gb >= 24 or (hw.gpu_vram_gb or 0) >= 16:
        model = os.environ.get("ARKA_PREFERRED_CODING_MODEL", configured_model or "qwen2.5-coder:14b")
    else:
        model = os.environ.get("ARKA_PREFERRED_SMALL_MODEL", configured_model or "llama3.2:3b")
    return {"model": model, "mode": mode, "quant": quant, "context": context, "hardware": hw.gpu_kind}

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka model-optimizer")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("recommend")
    setup = sub.add_parser("setup", help="configure the recommended local backend")
    setup.add_argument("--backend", choices=("ollama", "vllm", "lmstudio"), default="ollama")
    setup.add_argument("--apply", action="store_true")
    switch = sub.add_parser("switch")
    switch.add_argument("model", nargs="?")
    a = p.parse_args(argv)
    result = recommend()
    if a.cmd == "setup":
        result["backend"] = a.backend
        result["next"] = f"{a.backend} pull {result['model']}" if a.backend == "ollama" else f"start {a.backend} with {result['model']}"
        if a.apply:
            from arka.llm.provider_select import set_env_vars
            values = {"AI_PREFERRED_PROVIDER": a.backend, "AI_PREFERRED_MODEL": result["model"]}
            if a.backend == "ollama":
                values["OLLAMA_CHAT_MODEL"] = result["model"]
            elif a.backend == "vllm":
                values["VLLM_MODEL"] = result["model"]
            result["config"] = str(set_env_vars(values))
        for key, value in result.items():
            print(f"{key}\t{value}")
    elif a.cmd == "switch":
        result["model"] = a.model or result["model"]
        print(f"preview\tset AI_PREFERRED_MODEL={result['model']} (apply via provider setup)")
    else:
        for key, value in result.items():
            print(f"{key}\t{value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
