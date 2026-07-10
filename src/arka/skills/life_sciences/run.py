#!/usr/bin/env python3
"""Arka gateway to the Anthropic life-sciences marketplace."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import (  # noqa: E402
    doctor,
    install_plugin,
    print_plugin_info,
    print_plugin_list,
)


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print("Anthropic life-sciences marketplace for Arka")
        print("Usage:")
        print("  arka life_sciences list")
        print("  arka life_sciences info <plugin>")
        print("  arka life_sciences install <plugin>")
        print("  arka life_sciences doctor")
        return 0

    cmd = args[0].lower()
    rest = args[1:]

    if cmd == "list":
        print_plugin_list()
        return 0
    if cmd == "info":
        if not rest:
            print("Usage: arka life_sciences info <plugin>", file=sys.stderr)
            return 1
        return print_plugin_info(rest[0])
    if cmd == "install":
        if not rest:
            print("Usage: arka life_sciences install <plugin>", file=sys.stderr)
            return 1
        return install_plugin(rest[0])
    if cmd == "doctor":
        return doctor()

    # Allow `arka life_sciences install pubmed` style passthrough when user omits subcommand.
    if cmd in {"pubmed", "single-cell-rna-qc", "nextflow-development", "scvi-tools"}:
        return install_plugin(cmd)
    return install_plugin(args[0]) if len(args) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
