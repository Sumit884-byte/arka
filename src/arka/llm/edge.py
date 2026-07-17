"""Edge-device inference profile for constrained, offline-friendly machines."""
from __future__ import annotations

import argparse
import os

from arka.llm.model_advisor import probe_hardware


def profile() -> dict[str, object]:
    hw = probe_hardware(include_ollama=False)
    ram = hw.ram_available_gb or hw.ram_total_gb
    model = os.environ.get("ARKA_EDGE_MODEL", "llama3.2:1b" if ram < 8 else "llama3.2:3b")
    return {"enabled": os.environ.get("ARKA_EDGE_MODE", "0") not in {"0", "false", "off"}, "platform": hw.platform, "ram_gb": ram, "battery": hw.on_battery, "model": model, "quantization": os.environ.get("ARKA_QUANT", "4bit"), "policy": "local-only"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka edge")
    parser.add_argument("command", choices=("status", "recommend"), nargs="?", default="status")
    args = parser.parse_args(argv)
    for key, value in profile().items():
        print(f"{key}\t{value}")
    if args.command == "recommend":
        print("next\tARKA_EDGE_MODE=1 ARKA_MODEL_POLICY=local-only arka hybrid status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
