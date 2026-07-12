"""Ensure pip wheel bundled shims stay in sync with bin/ entrypoints."""

from __future__ import annotations

from pathlib import Path


def test_bundled_entrypoints_match_bin():
    root = Path(__file__).resolve().parent.parent
    bin_scripts = {p.name for p in (root / "bin").glob("arka_*.py")}
    bundled_scripts = {p.name for p in (root / "src" / "arka" / "bundled").glob("arka_*.py")}
    missing = sorted(bin_scripts - bundled_scripts)
    assert not missing, f"bundled/ missing bin shims: {missing}"
