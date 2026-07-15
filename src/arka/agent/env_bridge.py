"""Safely project Arka environment values into another project's .env."""
from __future__ import annotations
import argparse
import os
from pathlib import Path

def _arka_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.endswith(("_API_KEY", "_TOKEN", "_URL", "_BASE", "_MODEL")) and v}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka env-bridge")
    parser.add_argument("project", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow", default="")
    args = parser.parse_args(argv)
    target = args.project.expanduser().resolve() / ".env"
    allowed = {x.strip() for x in args.allow.split(",") if x.strip()}
    values = _arka_env()
    if allowed:
        values = {k: v for k, v in values.items() if k in allowed}
    existing = {}
    if target.is_file():
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value
    additions = {k: v for k, v in values.items() if k not in existing}
    print(f"target\t{target}\nsource\tlocal Arka environment\nkeys\t{len(additions)}")
    for key in sorted(additions):
        print(f"candidate\t{key}\t[redacted]")
    if not args.apply:
        print("preview\tpass --apply to write; values never printed")
        return 0
    if not target.parent.is_dir():
        print(f"project not found: {target.parent}")
        return 1
    with target.open("a", encoding="utf-8") as handle:
        for key, value in additions.items():
            handle.write(f"{key}={value}\n")
    print(f"applied\t{len(additions)}")
    return 0
