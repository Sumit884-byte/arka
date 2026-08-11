"""Lightweight code search — ripgrep/grep with optional embedding hook point."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _project_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    try:
        from arka.core.code_project import get_active_root

        active = get_active_root()
        if active is not None:
            return active.resolve()
    except ImportError:
        pass
    try:
        from arka.agent.pr_check import git_root

        root = git_root()
        if root is not None:
            return root.resolve()
    except ImportError:
        pass
    return Path.cwd().resolve()


def _run_rg(root: Path, pattern: str, *, glob: str | None, limit: int) -> list[dict[str, Any]]:
    cmd = ["rg", "--json", "--line-number", "--max-count", str(max(1, limit)), pattern, str(root)]
    if glob:
        cmd.insert(1, f"--glob={glob}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except OSError:
        return []
    hits: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "match":
            continue
        data = payload.get("data") or {}
        path = ((data.get("path") or {}).get("text") or "").strip()
        line_no = data.get("line_number")
        text = ((data.get("lines") or {}).get("text") or "").rstrip()
        if path:
            try:
                rel = str(Path(path).resolve().relative_to(root))
            except ValueError:
                rel = path
            hits.append({"file": rel, "line": line_no, "text": text})
        if len(hits) >= limit:
            break
    return hits


def _run_grep(root: Path, pattern: str, *, glob: str | None, limit: int) -> list[dict[str, Any]]:
    cmd = ["grep", "-R", "-n", "-I", "-E", pattern, str(root)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except OSError:
        return []
    hits: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, line_no, text = parts[0], parts[1], parts[2]
        try:
            rel = str(Path(path).resolve().relative_to(root))
        except ValueError:
            rel = path
        hits.append({"file": rel, "line": int(line_no) if line_no.isdigit() else line_no, "text": text.strip()})
        if len(hits) >= limit:
            break
    return hits


def search_payload(
    query: str,
    *,
    root: Path | str | None = None,
    glob: str | None = None,
    limit: int = 40,
    use_embeddings: bool = False,
) -> dict[str, Any]:
    """Search project source with rg/grep. Embeddings reserved for future hook."""
    project = _project_root(root)
    pattern = (query or "").strip()
    if not pattern:
        raise ValueError("query is required")
    if use_embeddings:
        return {
            "path": str(project),
            "query": pattern,
            "engine": "embeddings",
            "notice": "Embedding search hook not configured — falling back to ripgrep.",
            "results": _run_rg(project, pattern, glob=glob, limit=limit)
            or _run_grep(project, pattern, glob=glob, limit=limit),
        }
    results = _run_rg(project, pattern, glob=glob, limit=limit)
    engine = "ripgrep"
    if not results:
        results = _run_grep(project, pattern, glob=glob, limit=limit)
        engine = "grep"
    return {
        "path": str(project),
        "query": pattern,
        "engine": engine,
        "count": len(results),
        "results": results,
    }


def search_text(query: str, *, root: Path | str | None = None, limit: int = 20) -> str:
    payload = search_payload(query, root=root, limit=limit)
    lines = [f"Code search ({payload['engine']}): {payload['query']}", f"Root: {payload['path']}", ""]
    for hit in payload["results"]:
        lines.append(f"{hit['file']}:{hit['line']}: {hit['text']}")
    if not payload["results"]:
        lines.append("(no matches)")
    return "\n".join(lines)
