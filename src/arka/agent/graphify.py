"""Export Arka repository/workspace relationships as graph artifacts."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from arka.agent.repo_graph import build, render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka graphify")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--format", choices=("mermaid", "dot", "json"), default="mermaid")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--render", choices=("svg", "png"))
    args = parser.parse_args(argv)
    graph = build(Path(args.path).expanduser().resolve())
    if args.format == "dot":
        text = "digraph repo {\n" + "\n".join(f'  "{edge["from"]}" -> "{edge["to"]}";' for edge in graph["edges"]) + "\n}"
    else:
        text = render(graph, args.format)
    if not args.output:
        print(text)
        return 0
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    if args.render:
        if not shutil.which("dot"):
            print("Graphviz 'dot' is not installed; graph source was written")
            return 1
        subprocess.run(["dot", f"-T{args.render}", str(output), "-o", str(output.with_suffix(f".{args.render}"))], check=False)
    print(f"created\t{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
