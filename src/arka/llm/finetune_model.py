"""Plan, validate, and scaffold local LLM fine-tuning jobs (LoRA/QLoRA/full)."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.llm.model_advisor import probe_hardware
from arka.llm.train_plan import plan as base_plan
from arka.llm.train_plan import validate_dataset as base_validate_dataset

FINETUNE_SUBCOMMANDS = frozenset({"plan", "validate", "generate", "status", "parse", "check"})
FINETUNE_CLI_HEADS = frozenset(
    {
        "finetune_model",
        "finetune-model",
        "model_finetune",
        "model-finetune",
    }
)
METHODS = ("auto", "lora", "qlora", "full")
BACKENDS = ("auto", "mlx", "unsloth", "axolotl", "huggingface", "trl")

_NL_METHOD = re.compile(r"(?i)\b(qlora|q[- ]?lora|lora|full[- ]?fine[- ]?tune|full)\b")
_NL_BACKEND = re.compile(r"(?i)\b(mlx|unsloth|axolotl|huggingface|hf|trl)\b")
_NL_DATASET = re.compile(
    r"(?i)(?:on|from|using|with|dataset)\s+([^\s,]+\.(?:jsonl?|csv|txt|md)|[^\s,]+/[^\s,]*|\.[^\s]+/[^\s]+)"
)
_NL_BASE_EXPLICIT = re.compile(r"(?i)\bbase[- ]?model\s+([A-Za-z0-9._/-]+)")
_NL_HF_ID = re.compile(r"\b([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)\b")
_NL_OUTPUT = re.compile(r"(?i)(?:output|out(?:put)?[- ]?dir|to)\s+([^\s,]+)")


def _normalize_argv(argv: list[str]) -> list[str]:
    args = list(argv)
    while args and args[0] == "--":
        args.pop(0)
    if args and args[0] in FINETUNE_CLI_HEADS:
        args = args[1:]
    if args and args[0] == "finetune":
        args = args[1:]
    return args


def _pick_backend(hw_platform: str, backend: str) -> str:
    if backend != "auto":
        return backend
    if hw_platform == "darwin":
        return "mlx"
    if hw_platform.startswith("linux"):
        return "unsloth"
    return "huggingface"


def _pick_runner(backend: str) -> str:
    return {
        "mlx": "mlx-lm",
        "unsloth": "unsloth",
        "axolotl": "axolotl",
        "huggingface": "transformers + trl",
        "trl": "transformers + trl",
    }.get(backend, "transformers + trl")


def parse_nl(text: str) -> dict[str, Any]:
    """Extract fine-tune parameters from natural language."""
    t = text.strip()
    out: dict[str, Any] = {"task": t, "method": "auto", "backend": "auto"}
    if m := _NL_METHOD.search(t):
        token = m.group(1).lower().replace("-", "").replace(" ", "")
        if token.startswith("q"):
            out["method"] = "qlora"
        elif token == "full" or "fullfinetune" in token:
            out["method"] = "full"
        else:
            out["method"] = "lora"
    if m := _NL_BACKEND.search(t):
        token = m.group(1).lower()
        out["backend"] = "huggingface" if token in {"hf", "huggingface"} else token
    if m := _NL_DATASET.search(t):
        out["dataset"] = m.group(1).strip("'\"")
    if m := _NL_BASE_EXPLICIT.search(t):
        out["base_model"] = m.group(1).strip("'\"")
    elif m := _NL_HF_ID.search(t):
        out["base_model"] = m.group(1).strip("'\"")
    if m := _NL_OUTPUT.search(t):
        out["output_dir"] = m.group(1).strip("'\"")
    return out


def nl_to_argv(text: str) -> list[str]:
    """Map NL to explicit finetune_model argv."""
    t = text.strip()
    if not t:
        return []
    explicit = re.match(
        r"(?i)^(?:arka\s+)?(?:model\s+)?(?:finetune(?:[-_ ]model)?|finetune_model|model_finetune)\s+"
        r"(?P<sub>plan|validate|generate|status|parse|check)\b(?P<rest>.*)$",
        t,
    )
    if explicit:
        sub = explicit.group("sub").lower()
        rest = explicit.group("rest").strip()
        return [sub, *shlex.split(rest)] if rest else [sub]
    if re.search(r"(?i)\b(?:finetune|fine[- ]?tune|lora|qlora)\b.*\b(?:model|llm|dataset)\b", t):
        return ["plan", t]
    if re.search(r"(?i)\b(?:train|lora)\s+(?:a\s+)?model\b", t):
        return ["plan", t]
    if re.search(r"(?i)\bvalidate\s+(?:fine[- ]?tune\s+)?dataset\b", t):
        ds = _NL_DATASET.search(t)
        return ["validate", ds.group(1)] if ds else []
    return []


def _is_finetune_request(text: str) -> bool:
    return bool(nl_to_argv(text))


def plan_job(
    task: str,
    *,
    method: str = "auto",
    backend: str = "auto",
    base_model: str | None = None,
    dataset: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    parsed = parse_nl(task) if not base_model and not dataset else {}
    task_text = parsed.get("task", task)
    method = method if method != "auto" else parsed.get("method", "auto")
    backend = backend if backend != "auto" else parsed.get("backend", "auto")
    base_model = base_model or parsed.get("base_model")
    dataset = dataset or parsed.get("dataset")
    output_dir = output_dir or parsed.get("output_dir") or "./finetune-out"

    core = base_plan(task_text, method, backend)
    hw = probe_hardware(include_ollama=False)
    selected_backend = _pick_backend(hw.platform, core["backend"] if core["backend"] != "auto" else backend)
    payload: dict[str, Any] = {
        **core,
        "backend": selected_backend,
        "runner": _pick_runner(selected_backend),
        "base_model": base_model or "meta-llama/Llama-3.2-3B-Instruct",
        "dataset": dataset,
        "output_dir": output_dir,
        "hardware": asdict(hw),
        "artifacts": {
            "config": str(Path(output_dir) / "finetune_config.yaml"),
            "script": str(Path(output_dir) / "run_finetune.sh"),
            "readme": str(Path(output_dir) / "README.finetune.md"),
        },
        "dry_run_default": True,
        "next_steps": [
            "validate dataset with finetune_model validate",
            "generate config with finetune_model generate (dry-run)",
            "re-run generate with --apply after review",
        ],
    }
    if dataset:
        payload["dataset_validation"] = validate_dataset(Path(dataset).expanduser())
    return payload


def validate_dataset(path: Path) -> dict[str, Any]:
    base = base_validate_dataset(path)
    files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
    jsonl_files = [p for p in files if p.suffix.lower() in {".jsonl", ".json"}]
    chat_ok = 0
    row_count = 0
    sample_issues: list[str] = []
    for fp in jsonl_files[:5]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                row_count += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    sample_issues.append(f"{fp.name}:{line_no} invalid JSON")
                    continue
                if isinstance(row, dict) and (
                    ("messages" in row and isinstance(row["messages"], list))
                    or ("prompt" in row and "completion" in row)
                    or ("instruction" in row and "output" in row)
                    or ("text" in row)
                ):
                    chat_ok += 1
                else:
                    sample_issues.append(f"{fp.name}:{line_no} missing chat fields")
        except OSError as exc:
            sample_issues.append(f"{fp.name}: {exc}")
    base.update(
        {
            "jsonl_files": len(jsonl_files),
            "rows_sampled": row_count,
            "chat_format_rows": chat_ok,
            "chat_format_ok": chat_ok > 0 and not sample_issues,
            "issues": sample_issues[:10],
        }
    )
    return base


def _config_yaml(
    *,
    base_model: str,
    dataset: str,
    method: str,
    backend: str,
    output_dir: str,
) -> str:
    lora = method in {"lora", "qlora"}
    quant = method == "qlora"
    return (
        f"# Generated by arka finetune_model — review before training\n"
        f"base_model: {base_model}\n"
        f"dataset: {dataset}\n"
        f"output_dir: {output_dir}\n"
        f"method: {method}\n"
        f"backend: {backend}\n"
        f"lora:\n"
        f"  enabled: {str(lora).lower()}\n"
        f"  r: 16\n"
        f"  alpha: 32\n"
        f"  dropout: 0.05\n"
        f"quantization:\n"
        f"  load_in_4bit: {str(quant).lower()}\n"
        f"training:\n"
        f"  epochs: 3\n"
        f"  batch_size: 2\n"
        f"  gradient_accumulation_steps: 4\n"
        f"  learning_rate: 2.0e-4\n"
        f"  max_seq_length: 2048\n"
        f"  eval_split: 0.1\n"
        f"guardrails:\n"
        f"  - hold_out_test_set\n"
        f"  - record_dataset_provenance\n"
        f"  - benchmark_base_model_first\n"
    )


def _run_script(*, backend: str, config_path: str, method: str) -> str:
    runner = _pick_runner(backend)
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"# Generated by arka finetune_model ({method} via {runner})\n"
        f"CONFIG={shlex.quote(config_path)}\n"
        "echo \"Review $CONFIG and hardware before running.\"\n"
        f"echo \"Suggested runner: {runner}\"\n"
        "echo \"Dry-run only — uncomment the runner line after installing deps.\"\n"
        f"# python -m arka.llm.finetune_model launch --config \"$CONFIG\"\n"
    )


def generate_artifacts(
    *,
    base_model: str,
    dataset: str,
    method: str = "auto",
    backend: str = "auto",
    output_dir: str = "./finetune-out",
    apply: bool = False,
) -> dict[str, Any]:
    job = plan_job(
        f"fine-tune {base_model} on {dataset}",
        method=method,
        backend=backend,
        base_model=base_model,
        dataset=dataset,
        output_dir=output_dir,
    )
    out = Path(output_dir).expanduser()
    config_path = out / "finetune_config.yaml"
    script_path = out / "run_finetune.sh"
    readme_path = out / "README.finetune.md"
    config_text = _config_yaml(
        base_model=job["base_model"],
        dataset=dataset,
        method=job["method"],
        backend=job["backend"],
        output_dir=str(out),
    )
    script_text = _run_script(backend=job["backend"], config_path=str(config_path), method=job["method"])
    readme_text = (
        f"# Fine-tune job scaffold\n\n"
        f"- Base model: `{job['base_model']}`\n"
        f"- Dataset: `{dataset}`\n"
        f"- Method: `{job['method']}`\n"
        f"- Backend: `{job['backend']}` ({job['runner']})\n\n"
        f"Generated at {datetime.now(timezone.utc).isoformat()}.\n"
        f"Review config, install runner deps, then execute `run_finetune.sh`.\n"
    )
    result: dict[str, Any] = {
        "dry_run": not apply,
        "output_dir": str(out),
        "method": job["method"],
        "backend": job["backend"],
        "runner": job["runner"],
        "files": {
            "config": {"path": str(config_path), "content": config_text},
            "script": {"path": str(script_path), "content": script_text},
            "readme": {"path": str(readme_path), "content": readme_text},
        },
    }
    if apply:
        out.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_text, encoding="utf-8")
        script_path.write_text(script_text, encoding="utf-8")
        readme_path.write_text(readme_text, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | 0o111)
        result["written"] = [str(config_path), str(script_path), str(readme_path)]
    return result


def job_status(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser()
    if not root.exists():
        return {"path": str(root), "exists": False, "status": "missing"}
    config = root / "finetune_config.yaml"
    script = root / "run_finetune.sh"
    checkpoints = list(root.glob("**/checkpoint-*")) + list(root.glob("**/*.safetensors"))
    logs = list(root.glob("**/*.log")) + list(root.glob("**/trainer_state.json"))
    state = "scaffolded" if config.is_file() else "empty"
    if checkpoints:
        state = "checkpoints_found"
    elif logs:
        state = "logs_found"
    return {
        "path": str(root),
        "exists": True,
        "status": state,
        "config": config.is_file(),
        "script": script.is_file(),
        "checkpoints": len(checkpoints),
        "logs": len(logs),
    }


def main(argv: list[str] | None = None) -> int:
    args = _normalize_argv(list(argv or []))
    parser = argparse.ArgumentParser(prog="arka finetune_model")
    sub = parser.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="Plan a fine-tune job from NL or flags")
    p_plan.add_argument("task", nargs="*", help="Natural language task description")
    p_plan.add_argument("--method", choices=METHODS, default="auto")
    p_plan.add_argument("--backend", choices=BACKENDS, default="auto")
    p_plan.add_argument("--base-model", dest="base_model", default=None)
    p_plan.add_argument("--dataset", default=None)
    p_plan.add_argument("--output-dir", dest="output_dir", default=None)

    p_val = sub.add_parser("validate", help="Validate dataset path or JSONL chat format")
    p_val.add_argument("path", type=Path)

    p_gen = sub.add_parser("generate", help="Generate training config and script (dry-run default)")
    p_gen.add_argument("--base-model", dest="base_model", required=True)
    p_gen.add_argument("--dataset", required=True)
    p_gen.add_argument("--method", choices=METHODS, default="auto")
    p_gen.add_argument("--backend", choices=BACKENDS, default="auto")
    p_gen.add_argument("--output-dir", dest="output_dir", default="./finetune-out")
    p_gen.add_argument("--apply", action="store_true", help="Write files to disk")

    p_status = sub.add_parser("status", help="Inspect a fine-tune output directory")
    p_status.add_argument("output_dir", type=Path)

    p_parse = sub.add_parser("parse", help="Parse NL into argv")
    p_parse.add_argument("text", nargs="+")

    sub.add_parser("check", help="Show capability summary")

    ns = parser.parse_args(args)
    if ns.cmd == "plan":
        task = " ".join(ns.task) if ns.task else "fine-tune a model"
        result = plan_job(
            task,
            method=ns.method,
            backend=ns.backend,
            base_model=ns.base_model,
            dataset=ns.dataset,
            output_dir=ns.output_dir,
        )
    elif ns.cmd == "validate":
        result = validate_dataset(ns.path.expanduser())
    elif ns.cmd == "generate":
        result = generate_artifacts(
            base_model=ns.base_model,
            dataset=ns.dataset,
            method=ns.method,
            backend=ns.backend,
            output_dir=ns.output_dir,
            apply=ns.apply,
        )
    elif ns.cmd == "status":
        result = job_status(ns.output_dir)
    elif ns.cmd == "parse":
        result = {"argv": nl_to_argv(" ".join(ns.text))}
    elif ns.cmd == "check":
        hw = probe_hardware(include_ollama=False)
        result = {
            "ok": True,
            "methods": list(METHODS),
            "backends": list(BACKENDS),
            "hardware": asdict(hw),
            "cli": "arka finetune_model plan|validate|generate|status|parse",
            "mcp": "arka_finetune_model",
        }
    else:
        parser.print_help()
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
