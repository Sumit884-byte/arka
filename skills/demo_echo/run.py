#!/usr/bin/env python3
"""Demo third-party Arka skill."""

from __future__ import annotations

import sys


def main() -> int:
    text = " ".join(sys.argv[1:]).strip() or "Hello from a third-party Arka skill!"
    print("━━━ Answer ━━━")
    print(text)
    print(f"\nPlugin received {len(sys.argv) - 1} argument(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
