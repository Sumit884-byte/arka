"""Create venv-arka and install chat/web dependencies for daily_brief, web_answer, etc."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from arka.paths import arka_home, bundled_dir, checkout_root, config_dir, package_dir

CHAT_IMPORTS = ("ddgs", "trafilatura", "bs4", "sympy", "geopy", "agno")


def venv_candidates() -> list[Path]:
    """Locations fish and legacy installs may place venv-arka."""
    seen: set[Path] = set()
    out: list[Path] = []

    def add(path: Path) -> None:
        path = path.expanduser().resolve()
        if path in seen:
            return
        seen.add(path)
        out.append(path)

    root = checkout_root()
    if root:
        add(root / "venv-arka")
    home = arka_home()
    add(home / "venv-arka")
    if (home / "src" / "arka").is_dir():
        add(home / "venv-arka")
    add(Path.home() / ".config" / "fish" / "venv-arka")
    add(config_dir() / "venv-arka")
    return out


def venv_dir() -> Path:
    """Preferred venv-arka directory (first candidate path)."""
    cands = venv_candidates()
    for vdir in cands:
        if (vdir / "bin" / "python3").is_file():
            return vdir
    if cands:
        return cands[0]
    return checkout_root() / "venv-arka" if checkout_root() else arka_home() / "venv-arka"


def resolve_venv_python(*, require_agno: bool = True) -> Path | None:
    """First venv python that exists and optionally imports chat deps."""
    for vdir in venv_candidates():
        py = vdir / "bin" / "python3"
        if not py.is_file():
            continue
        if require_agno and verify_chat_imports(py):
            continue
        return py
    return None


def venv_python() -> Path | None:
    py = venv_dir() / "bin" / "python3"
    return py if py.is_file() else None


def chat_requirements_path() -> Path | None:
    for candidate in (
        package_dir() / "requirements" / "chat.txt",
        bundled_dir() / "arka_chat_requirements.txt",
        arka_home() / "src" / "arka" / "requirements" / "chat.txt",
        arka_home() / "arka_chat_requirements.txt",
    ):
        if candidate.is_file():
            return candidate
    root = checkout_root()
    if root:
        p = root / "src" / "arka" / "requirements" / "chat.txt"
        if p.is_file():
            return p
    return None


def _run(cmd: list[str], *, cwd: Path | None = None) -> int:
    print(f"→ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd).returncode


def ensure_venv(*, install_chat: bool = True) -> Path:
    vdir = venv_dir()
    py = vdir / "bin" / "python3"
    if not py.is_file():
        vdir.parent.mkdir(parents=True, exist_ok=True)
        rc = _run([sys.executable, "-m", "venv", str(vdir)])
        if rc != 0:
            raise RuntimeError(f"Failed to create virtualenv at {vdir}")

    if not install_chat:
        return vdir

    pip = vdir / "bin" / "pip"
    root = checkout_root()
    if root and (root / "pyproject.toml").is_file():
        rc = _run([str(pip), "install", "-e", f"{root}[chat]"], cwd=root)
        if rc != 0:
            req = chat_requirements_path()
            if req:
                _run([str(pip), "install", "-r", str(req)])
    else:
        _run([str(pip), "install", "-U", "arka-agent[chat]"])
        req = chat_requirements_path()
        if req:
            _run([str(pip), "install", "-r", str(req)])

    return vdir


def verify_chat_imports(python: Path | None = None) -> list[str]:
    """Return missing module names (empty list = all ok)."""
    py = python or venv_python() or Path(sys.executable)
    missing: list[str] = []
    for mod in CHAT_IMPORTS:
        rc = subprocess.run(
            [str(py), "-c", f"import {mod}"],
            capture_output=True,
        )
        if rc.returncode != 0:
            missing.append(mod)
    return missing
