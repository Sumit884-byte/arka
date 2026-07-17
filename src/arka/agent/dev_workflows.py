"""Small, deterministic developer workflow analyzers."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def changed(root: Path) -> list[str]:
    proc = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def impact(root: Path) -> list[str]:
    files = changed(root)
    services = []
    for file in files:
        parts = Path(file).parts
        if parts and parts[0] in {"services", "apps", "packages"} and len(parts) > 1:
            services.append("/".join(parts[:2]))
    return sorted(set(services)) or ["repository-wide"]


def test_gaps(root: Path) -> list[str]:
    files = changed(root)
    tests = {Path(path).stem.replace("test_", "") for path in files if "/tests/" in f"/{path}" or path.startswith("tests/")}
    gaps = []
    for file in files:
        if file.startswith("src/") and Path(file).suffix in {".py", ".ts", ".tsx", ".js"}:
            stem = Path(file).stem.lower()
            if stem not in tests and not any(stem in item for item in tests):
                gaps.append(file)
    return gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka dev-workflow")
    parser.add_argument("command", choices=("impact", "test-gaps", "docs-sync"))
    parser.add_argument("path", nargs="?", default=".")
    args = parser.parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    files = changed(root)
    if args.command == "impact":
        print("changed\t" + str(len(files)))
        for item in impact(root):
            print(f"affected\t{item}")
    elif args.command == "test-gaps":
        gaps = test_gaps(root)
        print(f"potential_gaps\t{len(gaps)}")
        for item in gaps:
            print(f"candidate\t{item}")
    else:
        docs = [path for path in files if path.endswith((".py", ".ts", ".tsx", ".js"))]
        print(f"code_changes\t{len(docs)}\ndocs_review\t{'recommended' if docs else 'not_needed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
