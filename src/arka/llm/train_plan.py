"""Plan and validate local model training without launching expensive jobs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from arka.llm.model_advisor import probe_hardware


def plan(task: str, method: str, backend: str) -> dict:
    hw = probe_hardware(include_ollama=False)
    selected = method
    if method == "auto":
        selected = "qlora" if hw.ram_total_gb < 64 and (hw.gpu_vram_gb or 0) < 24 else "lora"
    return {
        "task": task,
        "method": selected,
        "backend": backend,
        "hardware": {"platform": hw.platform, "ram_gb": hw.ram_total_gb, "gpu": hw.gpu_name, "vram_gb": hw.gpu_vram_gb},
        "steps": ["validate and deduplicate real data", "split train/validation/test", f"run {selected} in a sandbox", "benchmark against the base model", "quantize and export only after held-out evaluation"],
        "guardrails": ["prefer RAG or prompting when sufficient", "never evaluate on training data only", "record dataset provenance and license"],
    }


def validate_dataset(path: Path) -> dict:
    files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
    return {"path": str(path), "files": len(files), "supported": all(p.suffix.lower() in {".jsonl", ".json", ".csv", ".txt", ".md"} for p in files), "recommendation": "create train/validation/test splits and check provenance before training"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka model train-plan")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("task", nargs="+")
    p_plan.add_argument("--method", choices=("auto", "lora", "qlora", "full"), default="auto")
    p_plan.add_argument("--backend", default="auto")
    p_data = sub.add_parser("validate-data")
    p_data.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    result = plan(" ".join(args.task), args.method, args.backend) if args.cmd == "plan" else validate_dataset(args.path.expanduser())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
