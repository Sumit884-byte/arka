#!/usr/bin/env python3
"""Legacy entrypoint — prefer the ``arka`` package module."""
import sys
from pathlib import Path

_shim_dir = Path(__file__).resolve().parent
if str(_shim_dir) not in sys.path:
    sys.path.insert(0, str(_shim_dir))
import _shim_path

_shim_path.ensure()
from arka._bootstrap import run_legacy_module

if __name__ == "__main__":
    raise SystemExit(run_legacy_module("arka.core.memory_detect"))
