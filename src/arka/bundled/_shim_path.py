"""Ensure ``import arka`` works when running flat scripts from bin/ or bundled/."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure() -> None:
    try:
        import arka  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "src", here.parent.parent, here.parent.parent / "src"):
        if (candidate / "arka" / "__init__.py").is_file():
            root = str(candidate)
            if root not in sys.path:
                sys.path.insert(0, root)
            return
