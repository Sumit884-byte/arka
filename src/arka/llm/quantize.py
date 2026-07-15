"""Safe preview and execution wrapper for local model quantization."""
from __future__ import annotations
import argparse
import shutil
import subprocess
from pathlib import Path

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka quantize")
    p.add_argument("model", type=Path, help="input GGUF or model directory")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--type", default="Q4_K_M", choices=("Q4_K_M", "Q5_K_M", "Q8_0", "F16"))
    p.add_argument("--run", action="store_true", help="execute conversion; otherwise preview only")
    args = p.parse_args(argv)
    tool = shutil.which("llama-quantize") or shutil.which("quantize")
    command = [tool or "llama-quantize", str(args.model), str(args.output), args.type]
    print("command\t" + " ".join(command))
    if not args.run:
        print("preview\tpass --run to execute; install llama.cpp for the quantizer")
        return 0
    if not args.model.exists():
        print(f"model not found: {args.model}")
        return 1
    if not tool:
        print("llama-quantize not found; install llama.cpp first")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
