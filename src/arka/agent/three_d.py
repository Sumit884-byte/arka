#!/usr/bin/env python3
"""Backward-compatible alias for compose_3d."""

from __future__ import annotations

from arka.media.compose_3d import main, nl_to_argv, route_command

__all__ = ["main", "nl_to_argv", "route_command"]


if __name__ == "__main__":
    raise SystemExit(main())
