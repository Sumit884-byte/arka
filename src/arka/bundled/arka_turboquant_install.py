#!/usr/bin/env python3
"""Install Firmamento TurboQuant for Arka RAG (NOT PyPI turboquant + PyTorch)."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = Path.home() / "Projects/TurboQuant"
REPO_URL = "https://github.com/Firmamento-Technologies/TurboQuant.git"
VENV_PIP = Path.home() / ".config/fish/venv-arka/bin/pip"
VENV_PY = Path.home() / ".config/fish/venv-arka/bin/python3"

PYPI_WRONG_MSG = (
    "PyPI package 'turboquant' is a different project (KV-cache compression) that "
    "pulls PyTorch/CUDA (~2GB+). Arka needs Firmamento TurboQuant (vector search) "
    "from the local git repo — only numpy + scipy."
)


def repo_dir() -> Path:
    raw = (os.environ.get("ARKA_TURBOQUANT_DIR") or str(DEFAULT_REPO)).strip()
    return Path(raw).expanduser()


def _distribution_meta() -> importlib.metadata.Distribution | None:
    try:
        return importlib.metadata.distribution("turboquant")
    except importlib.metadata.PackageNotFoundError:
        return None


def _requires_torch(dist: importlib.metadata.Distribution) -> bool:
    for req in dist.requires or []:
        name = req.split(";")[0].strip().lower()
        if name.startswith("torch") or name.startswith("transformers"):
            return True
    return False


def _has_vector_index() -> bool:
    try:
        from turboquant import TurboQuantIndex  # noqa: PLC0415

        TurboQuantIndex(dimension=8, num_bits=2)
        return True
    except Exception:
        return False


def check_install() -> tuple[bool, str]:
    dist = _distribution_meta()
    if dist is None:
        return False, "turboquant not installed"
    if _requires_torch(dist):
        return False, f"wrong package installed ({dist.version}): {PYPI_WRONG_MSG}"
    if not _has_vector_index():
        return False, "turboquant installed but TurboQuantIndex unavailable (broken or wrong package)"
    loc = ""
    try:
        loc = str(dist.locate_file("turboquant"))
    except Exception:
        pass
    return True, f"ok ({dist.version}){f' @ {loc}' if loc else ''}"


def _pip() -> Path:
    if VENV_PIP.is_file():
        return VENV_PIP
    return Path(shutil.which("pip3") or shutil.which("pip") or "pip")


def _ensure_repo(path: Path) -> None:
    if (path / "pyproject.toml").is_file() and (path / "turboquant" / "index.py").is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and any(path.iterdir()):
        raise SystemExit(
            f"{path} exists but is not a TurboQuant checkout.\n"
            f"Remove it or set ARKA_TURBOQUANT_DIR, then rerun: arka rag setup"
        )
    print(f"Cloning TurboQuant → {path}", file=sys.stderr)
    subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(path)],
        check=True,
    )


def _uninstall_wrong_package(pip: Path) -> None:
    dist = _distribution_meta()
    if dist is None:
        return
    if _requires_torch(dist) or not _has_vector_index():
        print(f"Removing incompatible turboquant ({dist.version})…", file=sys.stderr)
        subprocess.run([str(pip), "uninstall", "-y", "turboquant"], check=False)


def cmd_install() -> int:
    pip = _pip()
    repo = repo_dir()
    _ensure_repo(repo)
    _uninstall_wrong_package(pip)

    print(f"Installing editable TurboQuant from {repo} (numpy + scipy only)…", file=sys.stderr)
    subprocess.run(
        [str(pip), "install", "-e", str(repo), "--no-deps"],
        check=True,
    )
    subprocess.run(
        [str(pip), "install", "numpy>=1.24", "scipy>=1.10"],
        check=True,
    )

    ok, msg = check_install()
    if ok:
        print(f"✓ TurboQuant ready: {msg}")
        print("Do NOT run: pip install turboquant  (PyPI = wrong package + PyTorch)", file=sys.stderr)
        return 0
    print(f"Install finished but check failed: {msg}", file=sys.stderr)
    return 1


def cmd_check() -> int:
    ok, msg = check_install()
    if ok:
        print(msg)
        return 0
    print(msg, file=sys.stderr)
    print("\nFix: arka rag setup", file=sys.stderr)
    print("Never: pip install turboquant  (PyPI pulls torch/CUDA)", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install Firmamento TurboQuant for Arka (avoids PyPI name collision)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="Clone repo if needed and pip install -e (lightweight)")
    sub.add_parser("check", help="Verify correct turboquant is installed")
    args = parser.parse_args()
    if args.cmd == "install":
        return cmd_install()
    if args.cmd == "check":
        return cmd_check()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
