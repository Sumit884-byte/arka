"""Inspect and scaffold GitHub Actions workflows."""
from __future__ import annotations
import argparse
import shutil
import subprocess
from pathlib import Path

WORKFLOW = "name: Arka CI\\n\\non:\\n  push:\\n    branches: [main]\\n  pull_request:\\npermissions:\\n  contents: read\\njobs:\\n  ci:\\n    runs-on: ubuntu-latest\\n    steps:\\n      - uses: actions/checkout@v4\\n      - uses: actions/setup-python@v5\\n        with:\\n          python-version: '3.12'\\n      - run: python -m pip install -e '.[dev]'\\n      - run: python -m ruff check src/ tests/\\n      - run: python -m pytest -q\\n"

def inspect(root: str = ".") -> list[Path]:
    return sorted((Path(root).expanduser().resolve() / ".github" / "workflows").glob("*.y*ml"))

def scaffold(root: str = ".", *, force: bool = False) -> Path:
    target = Path(root).expanduser().resolve() / ".github" / "workflows" / "arka-ci.yml"
    if target.exists() and not force:
        raise FileExistsError(f"workflow already exists: {target}; use --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WORKFLOW, encoding="utf-8")
    return target


def status(root: str = ".") -> int:
    """Report the latest GitHub Actions production/CI run via gh, read-only."""
    if not shutil.which("gh"):
        print("GitHub CLI is not installed; install gh and authenticate to inspect remote runs")
        return 2
    proc = subprocess.run(["gh", "run", "list", "--limit", "10", "--json", "name,status,conclusion,headBranch,createdAt"], cwd=Path(root).expanduser(), text=True, capture_output=True, check=False)
    if proc.returncode:
        print(proc.stderr.strip() or "Unable to read GitHub Actions runs")
        return proc.returncode
    print(proc.stdout.strip() or "No workflow runs found")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka github-actions")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("path", nargs="?", default=".")
    p = sub.add_parser("new")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("status")
    p.add_argument("path", nargs="?", default=".")
    args = parser.parse_args(argv)
    if args.action == "inspect":
        print("\\n".join(str(path) for path in inspect(args.path)) or "No GitHub Actions workflows found")
        return 0
    if args.action == "status":
        return status(args.path)
    try:
        print(scaffold(args.path, force=args.force))
    except (OSError, FileExistsError) as exc:
        print(f"github-actions: {exc}")
        return 2
    return 0
