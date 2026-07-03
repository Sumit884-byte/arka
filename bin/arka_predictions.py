#!/usr/bin/env python3
"""Legacy entrypoint — prefer the ``arka`` package module."""
from arka._bootstrap import run_legacy_module

if __name__ == "__main__":
    raise SystemExit(run_legacy_module("arka.stock.predictions"))
