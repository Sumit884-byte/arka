#!/usr/bin/env python3
"""Beautiful terminal output for Arka stock intelligence modules."""

from __future__ import annotations

import os
import re
import sys
from typing import Sequence


def use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("STOCK_PLAIN", "").lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("STOCK_TERMINAL", "").lower() in {"1", "true", "yes"}:
        return True
    return sys.stdout.isatty()


def use_terminal_ui() -> bool:
    if os.environ.get("STOCK_PLAIN", "").lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("STOCK_TERMINAL", "").lower() in {"1", "true", "yes"}:
        return True
    return sys.stdout.isatty()


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_RED = "\033[41m"


def _c(text: str, code: str) -> str:
    if not use_color():
        return text
    return f"{code}{text}{C.RESET}"


def banner(title: str, *, subtitle: str = "", icon: str = "📈") -> None:
    width = min(72, max(len(title) + 6, 52))
    line = "═" * width
    print(_c(line, C.CYAN))
    head = f" {icon}  {title} "
    print(_c(head, C.BOLD + C.CYAN))
    if subtitle:
        print(_c(f" {subtitle}", C.DIM))
    print(_c(line, C.CYAN))
    print()


def section(title: str) -> None:
    print(_c(f"\n▸ {title}", C.BOLD + C.YELLOW))
    print(_c("─" * min(68, len(title) + 4), C.DIM))


def note(text: str) -> None:
    print(_c(f"  {text}", C.DIM))


def bullet(text: str, *, indent: int = 2) -> None:
    pad = " " * indent
    print(f"{pad}{_c('•', C.CYAN)} {text}")


def headline_item(index: int, source: str, title: str, *, max_len: int = 88) -> None:
    src = _c(f"[{source}]", C.MAGENTA)
    t = title if len(title) <= max_len else title[: max_len - 1] + "…"
    print(f"  {_c(f'{index:>2}.', C.DIM)} {src} {t}")


def pct(val: float | None, *, signed: bool = True) -> str:
    if val is None:
        return _c("—", C.DIM)
    text = f"{val:+.2f}%" if signed else f"{val:.2f}%"
    if val > 0:
        return _c(text, C.GREEN)
    if val < 0:
        return _c(text, C.RED)
    return _c(text, C.DIM)


def tag(label: str, tone: str = "neutral") -> str:
    tones = {
        "good": C.GREEN,
        "bad": C.RED,
        "warn": C.YELLOW,
        "info": C.CYAN,
        "neutral": C.DIM,
    }
    return _c(f" {label} ", tones.get(tone, C.DIM))


def fear_greed_bar(index: int, label: str) -> None:
    width = 36
    filled = max(0, min(width, int(index / 100 * width)))
    if index < 25:
        color = C.RED
    elif index < 45:
        color = C.YELLOW
    elif index < 55:
        color = C.DIM
    elif index < 75:
        color = C.GREEN
    else:
        color = C.MAGENTA
    bar = "█" * filled + "░" * (width - filled)
    print(
        f"  Fear & Greed  {_c(bar, color)}  "
        f"{_c(str(index), C.BOLD)}/100  {_c(label, color)}"
    )


def stat_row(label: str, value: str) -> None:
    print(f"  {_c(label + ':', C.DIM):<22} {value}")


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, aligns: Sequence[str] | None = None) -> None:
    if not rows:
        print(_c("  (no data)", C.DIM))
        return
    str_rows = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    plain_rows: list[list[str]] = []
    for row in str_rows:
        plain = [re.sub(r"\033\[[0-9;]*m", "", c) for c in row]
        plain_rows.append(plain)
        for i, cell in enumerate(plain):
            widths[i] = max(widths[i], len(cell))

    aligns = aligns or ["l"] * len(headers)

    def fmt_cell(text: str, width: int, align: str) -> str:
        plain = re.sub(r"\033\[[0-9;]*m", "", text)
        pad = width - len(plain)
        if align == "r":
            return " " * pad + text
        if align == "c":
            left = pad // 2
            return " " * left + text + " " * (pad - left)
        return text + " " * pad

    header_line = "  ".join(
        _c(fmt_cell(h, widths[i], "l"), C.BOLD) for i, h in enumerate(headers)
    )
    print(f"  {header_line}")
    print(f"  {_c('  '.join('─' * w for w in widths), C.DIM)}")
    for row in str_rows:
        plain = [re.sub(r"\033\[[0-9;]*m", "", c) for c in row]
        line = "  ".join(fmt_cell(row[i], widths[i], aligns[i]) for i in range(len(headers)))
        print(f"  {line}")


def leader_footer(leader: str, laggard: str, leader_chg: str, laggard_chg: str) -> None:
    print(
        f"\n  {_c('Leader', C.GREEN)} {leader} ({leader_chg})"
        f"  {_c('·', C.DIM)}  {_c('Laggard', C.RED)} {laggard} ({laggard_chg})"
    )


def stock_project_missing(path: str) -> None:
    banner("Stock bridge unavailable", icon="⚠️", subtitle="Optional stock_analysis project not found")
    bullet(f"Expected path: {_c(path, C.CYAN)}")
    bullet("Standalone skills still work: macro, emotion, fundamentals, funding, competition")
    bullet("Set ARKA_STOCK_PROJECT in .env when you clone the project")
    print()
