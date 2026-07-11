#!/usr/bin/env python3
"""Lightweight repo map — project layout and Python symbols for agent context."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from arka.agent.pr_check import git_root
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def git_root() -> Path | None:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        root = Path((proc.stdout or "").strip())
        return root if root.is_dir() else None


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"repo\s+map|map\s+(?:this\s+)?repo|project\s+(?:map|structure|overview|layout)|"
    r"repo\s+(?:structure|overview|layout|summary)|"
    r"what(?:'s|\s+is)\s+in\s+(?:this\s+)?(?:repo|project|codebase)|"
    r"codebase\s+(?:map|overview|structure|layout)|"
    r"show\s+(?:me\s+)?(?:the\s+)?(?:repo|project|codebase)\s+(?:structure|layout|map)"
    r")\b"
)
_SYMBOLS_RE = re.compile(r"(?i)\b(?:symbols?|classes?|functions?|defs?|exports?)\b")
_DEEP_RE = re.compile(r"(?i)\b(?:deep|detailed|full)\b")

IGNORE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        "target",
        ".idea",
        ".vscode",
        "coverage",
        "htmlcov",
        ".cache",
        ".turbo",
        ".next",
        "site-packages",
    }
)

MARKER_FILES = (
    ("pyproject.toml", "Python"),
    ("setup.py", "Python"),
    ("requirements.txt", "Python"),
    ("package.json", "Node.js"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("pom.xml", "Java/Maven"),
    ("build.gradle", "Gradle"),
    ("Makefile", "Make"),
    ("Dockerfile", "Docker"),
)


@dataclass(frozen=True)
class SymbolInfo:
    path: Path
    classes: tuple[str, ...]
    functions: tuple[str, ...]


def _project_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = git_root()
    if root:
        return root
    return Path.cwd().resolve()


def detect_project_types(root: Path) -> list[str]:
    found: list[str] = []
    for name, label in MARKER_FILES:
        if (root / name).is_file() and label not in found:
            found.append(label)
    if (root / "src").is_dir() and "Python" not in found:
        if any(root.glob("src/**/*.py")):
            found.append("Python")
    return found or ["Unknown"]


def _should_skip_dir(name: str) -> bool:
    return name in IGNORE_DIRS or name.startswith(".")


def tree_lines(root: Path, *, depth: int = 2, max_entries: int = 80) -> list[str]:
    lines: list[str] = []
    count = 0

    def walk(path: Path, prefix: str, level: int) -> None:
        nonlocal count
        if count >= max_entries or level > depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        dirs = [e for e in entries if e.is_dir() and not _should_skip_dir(e.name)]
        files = [e for e in entries if e.is_file() and not e.name.startswith(".")]
        for entry in dirs + files:
            if count >= max_entries:
                lines.append(f"{prefix}…")
                return
            kind = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{entry.name}{kind}")
            count += 1
            if entry.is_dir() and level < depth:
                walk(entry, prefix + "  ", level + 1)

    walk(root, "", 0)
    return lines


def _python_files(root: Path, *, limit: int = 40) -> list[Path]:
    candidates: list[Path] = []
    for pattern in ("src/**/*.py", "**/*.py"):
        for path in root.glob(pattern):
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.name == "__init__.py" and path.stat().st_size < 80:
                continue
            candidates.append(path)
    candidates.sort(key=lambda p: (len(p.parts), p.as_posix()))
    return candidates[:limit]


def extract_symbols(path: Path) -> SymbolInfo | None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    classes: list[str] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append(node.name)
    if not classes and not functions:
        return None
    return SymbolInfo(path=path, classes=tuple(classes[:12]), functions=tuple(functions[:12]))


def collect_symbols(root: Path, *, limit: int = 25) -> list[SymbolInfo]:
    out: list[SymbolInfo] = []
    for path in _python_files(root, limit=limit * 2):
        info = extract_symbols(path)
        if info:
            out.append(info)
        if len(out) >= limit:
            break
    return out


def map_text(
    root: Path,
    *,
    depth: int = 2,
    include_symbols: bool = True,
    max_tree: int = 80,
) -> str:
    types = detect_project_types(root)
    lines = [
        f"Repo map: {root.name}",
        f"Path: {root}",
        f"Type: {', '.join(types)}",
        "",
        f"Layout (depth {depth}):",
    ]
    tree = tree_lines(root, depth=depth, max_entries=max_tree)
    if tree:
        lines.extend(tree)
    else:
        lines.append("  (empty)")

    if include_symbols and "Python" in types:
        symbols = collect_symbols(root)
        if symbols:
            lines.append("")
            lines.append("Python symbols (sample):")
            for info in symbols:
                rel = info.path.relative_to(root)
                parts: list[str] = []
                if info.classes:
                    parts.append("class " + ", ".join(info.classes[:6]))
                if info.functions:
                    parts.append("def " + ", ".join(info.functions[:6]))
                lines.append(f"  {rel}: {'; '.join(parts)}")

    lines.append("")
    lines.append("Tip: use repo_map --depth 3 --symbols for more detail.")
    return "\n".join(lines)


def wants_repo_map(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_repo_map(text):
        return ""
    clean = (text or "").strip()
    parts = ["repo_map"]
    if _DEEP_RE.search(clean):
        parts.append("--depth")
        parts.append("3")
    if _SYMBOLS_RE.search(clean) or not re.search(r"(?i)\b(?:no|without|skip)\s+symbols?\b", clean):
        parts.append("--symbols")
    return " ".join(parts)


def cmd_map(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    text = map_text(
        root,
        depth=max(1, int(args.depth)),
        include_symbols=bool(args.symbols),
        max_tree=max(20, int(args.max_entries)),
    )
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Lightweight repo structure map")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to repo_map command")
    p_route.add_argument("text", nargs="+")

    p_map = sub.add_parser("map", help="Show repo layout and symbols")
    p_map.add_argument("path", nargs="?", default=None)
    p_map.add_argument("--depth", type=int, default=2)
    p_map.add_argument("--symbols", action="store_true", default=True)
    p_map.add_argument("--no-symbols", dest="symbols", action="store_false")
    p_map.add_argument("--max-entries", type=int, default=80)
    p_map.set_defaults(func=cmd_map)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if args.cmd == "map":
        return int(args.func(args))
    if args.cmd is None:
        args = parser.parse_args(["map"] + (argv or []))
        if args.cmd == "map":
            return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
