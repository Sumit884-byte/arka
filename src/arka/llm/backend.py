"""Detect and plan advanced local inference backends."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess


def capabilities(backend: str) -> dict:
    b = backend.lower()
    return {"backend": b, "installed": bool(shutil.which(b) or os.environ.get(f"{b.upper()}_API_BASE")), "flash_attention": b in {"vllm", "mlx"}, "tensor_split": b in {"vllm", "exo"}, "row_split": b == "exo", "co_engine_ds4": b in {"exo", "vllm"}, "evidence": "runtime capability map; verify backend version"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka backend")
    sub = parser.add_subparsers(dest="cmd", required=True)
    caps = sub.add_parser("capabilities")
    caps.add_argument("backend", nargs="?", default="vllm", choices=("vllm", "exo", "mlx", "ollama"))
    caps.add_argument("--json", action="store_true")
    profile = sub.add_parser("profile")
    profile.add_argument("backend", choices=("vllm", "exo", "mlx"))
    profile.add_argument("--model", required=True)
    profile.add_argument("--gpus", type=int, default=1)
    profile.add_argument("--flash-attention", action="store_true")
    profile.add_argument("--row-split", action="store_true")
    profile.add_argument("--co-engine", default="")
    profile.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "capabilities":
        data = capabilities(args.backend)
        print(json.dumps(data, indent=2) if args.json else "\n".join(f"{k}\t{v}" for k, v in data.items()))
        return 0
    cap = capabilities(args.backend)
    if args.flash_attention and not cap["flash_attention"]:
        parser.error(f"{args.backend} does not advertise FlashAttention")
    if args.row_split and not cap["row_split"]:
        parser.error(f"{args.backend} does not advertise row-level splitting")
    command = [args.backend, "serve", args.model]
    if args.gpus > 1 and cap["tensor_split"]:
        command += ["--tensor-parallel-size", str(args.gpus)]
    if args.flash_attention:
        command += ["--enable-flash-attn"]
    if args.row_split:
        command += ["--tensor-split-mode", "row"]
    if args.co_engine:
        command += ["--co-engine", args.co_engine]
    print("command\t" + " ".join(command))
    if not args.run:
        print("preview\tpass --run to launch the experimental profile")
        return 0
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
