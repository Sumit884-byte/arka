"""Configure in-engine speculative decoding for local runtimes."""
from __future__ import annotations
import argparse
import os

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka speculative")
    p.add_argument("backend", choices=("vllm", "exo", "ollama", "mlx"))
    p.add_argument("--draft-model", default="")
    p.add_argument("--num-draft-tokens", type=int, default=5)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    if a.backend == "ollama":
        print("support\tOllama speculative decoding depends on the installed build; verify runtime docs")
    elif a.backend == "mlx":
        print("support\tMLX speculative decoding requires an MLX runtime exposing draft-model options")
    else:
        print("support\tOpenAI-compatible endpoint; launch configuration is backend-specific")
    if not a.draft_model:
        print("draft_model\t" + (os.environ.get("ARKA_DRAFT_MODEL") or "not_set"))
        return 0
    print(f"draft_model\t{a.draft_model}\nnum_draft_tokens\t{max(1, a.num_draft_tokens)}")
    if a.apply:
        from arka.llm.provider_select import set_env_vars
        path = set_env_vars({"ARKA_DRAFT_MODEL": a.draft_model, "ARKA_DRAFT_TOKENS": str(max(1, a.num_draft_tokens))})
        print(f"configured\t{path}")
    else:
        print("preview\tpass --apply to persist draft settings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
