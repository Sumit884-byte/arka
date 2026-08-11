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
    return test_gaps_for_files(changed(root), root=root)


def _read_probe_text(path: Path, *, limit: int = 12_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _test_file_stems(root: Path) -> set[str]:
    stems: set[str] = set()
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for path in tests_dir.rglob("test_*.py"):
            stems.add(path.stem.removeprefix("test_").lower())
    return stems


def _script_probe_covers(module_path: str, root: Path) -> bool:
    try:
        from arka.agent.script_discovery import discover_verification_scripts
    except ImportError:
        return False
    stem = Path(module_path).stem.lower()
    dotted = module_path.replace("/", ".").removesuffix(".py")
    for probe in discover_verification_scripts(root):
        blob = f"{probe.path.name} {probe.docstring} {_read_probe_text(probe.path)}".lower()
        if stem in blob or dotted in blob or module_path.lower() in blob:
            return True
    return False


def _source_has_test_coverage(module_path: str, root: Path, test_stems: set[str]) -> bool:
    stem = Path(module_path).stem.lower()
    if stem in test_stems:
        return True
    if any(stem in item or item in stem for item in test_stems):
        return True
    for pattern in (f"tests/test_{stem}.py", f"tests/**/test_{stem}.py"):
        if list(root.glob(pattern)):
            return True
    return _script_probe_covers(module_path, root)


def test_gaps_for_files(files: list[str], root: Path | None = None) -> list[str]:
    project = (root or Path.cwd()).expanduser().resolve()
    test_stems = _test_file_stems(project) if project.is_dir() else set()
    gaps: list[str] = []
    for file in files:
        if not (file.startswith("src/") and Path(file).suffix in {".py", ".ts", ".tsx", ".js"}):
            continue
        if not _source_has_test_coverage(file, project, test_stems):
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
