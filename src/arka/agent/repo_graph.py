"""Build a lightweight dependency graph and feature-priority report."""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

from arka.agent.repo_map import IGNORE_DIRS, _project_root


def build(root: Path, *, limit: int = 120) -> dict:
    files = [p for p in root.rglob("*.py") if not any(part in IGNORE_DIRS for part in p.parts)][:limit]
    nodes: dict[str, dict] = {}
    edges: list[dict[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        nodes.setdefault(rel, {"id": rel, "kind": "file"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                target = _resolve_import(root, name)
                if target and target != path:
                    target_rel = target.relative_to(root).as_posix()
                    nodes.setdefault(target_rel, {"id": target_rel, "kind": "file"})
                    edges.append({"from": rel, "to": target_rel, "type": "imports"})
    counts: dict[str, int] = {key: 0 for key in nodes}
    for edge in edges:
        counts[edge["to"]] = counts.get(edge["to"], 0) + 1
    features = []
    for rel, node in nodes.items():
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        markers = len(re.findall(r"(?i)\b(?:TODO|FIXME|HACK|XXX)\b", text))
        score = counts.get(rel, 0) * 2 + markers * 3
        features.append({"file": rel, "priority": "high" if score >= 8 else "medium" if score >= 3 else "low", "score": score, "dependents": counts.get(rel, 0), "markers": markers})
    features.sort(key=lambda row: (-row["score"], row["file"]))
    return {"root": str(root), "nodes": list(nodes.values()), "edges": edges, "priority": features}


def _resolve_import(root: Path, name: str) -> Path | None:
    parts = name.split(".")
    for base in (root / "src", root):
        candidate = base.joinpath(*parts).with_suffix(".py")
        if candidate.is_file():
            return candidate
        init = base.joinpath(*parts, "__init__.py")
        if init.is_file():
            return init
    return None


def render(graph: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(graph, indent=2)
    if fmt == "mermaid":
        lines = ["graph TD"]
        for edge in graph["edges"]:
            left = edge["from"].replace("/", "_").replace(".", "_")
            right = edge["to"].replace("/", "_").replace(".", "_")
            lines.append(f'  {left}["{edge["from"]}"] --> {right}["{edge["to"]}"]')
        return "\n".join(lines)
    lines = [f"Repository graph: {graph['root']}", "", "Feature priority (dependency centrality + TODO markers):"]
    lines.extend(f"- {row['priority'].upper()}: {row['file']} (score {row['score']}, dependents {row['dependents']})" for row in graph["priority"][:30])
    lines.append("\nDependencies: " + str(len(graph["edges"])))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka repo_graph")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--format", choices=("text", "json", "mermaid"), default="text")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    graph = build(_project_root(args.path))
    text = render(graph, args.format)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0
