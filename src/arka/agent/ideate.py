"""Open-source trend ideation prompts and research workflow."""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka ideate")
    parser.add_argument("topic", nargs="+", help="Area to explore")
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args(argv)
    topic = " ".join(args.topic)
    print(f"Open-source ideation brief: {topic}")
    print("1. Search current GitHub, package registries, changelogs, and discussions for momentum.")
    print("2. Compare adoption signals, licenses, maintenance, open issues, and integration friction.")
    print("3. Identify one underserved user problem and propose a concrete improvement.")
    print("4. Validate the idea with a small prototype and benchmark before building broadly.")
    print("Use `arka web` or `arka mcp` research tools for live sources; do not treat popularity alone as product validation.")
    return 0
