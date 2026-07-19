"""Capture a URL at PC, tablet, and mobile viewports."""
from __future__ import annotations

import argparse
import atexit
import os
import shutil
import tempfile
from pathlib import Path

VIEWPORTS = {"pc": (1440, 900), "tablet": (834, 1112), "mobile": (390, 844)}
LAYOUT_ONLY_INVARIANT = "Change layout styling only; preserve the existing button order and interaction order exactly."


def temporary_output() -> str:
    path = tempfile.mkdtemp(prefix="arka-screenshots-")
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def review(output: str = "screenshots") -> list[str]:
    """Return review prompts for a responsive screenshot set."""
    base = Path(output).expanduser()
    present = [mode for mode in VIEWPORTS if (base / f"website-{mode}.png").is_file()]
    if not present:
        raise ValueError(f"no website screenshots found in {base}; capture them first")
    prompts = [LAYOUT_ONLY_INVARIANT] + [
        "Compare PC, tablet, and mobile layouts: identify breakpoint changes that feel abrupt, clipped, or misaligned, then propose fixes scoped only to the affected viewport.",
        "Review visual hierarchy and primary actions per viewport; suggest changes only where the current mode looks weak, preserving modes that already look good.",
        "Check spacing, typography scale, line wrapping, and content density at each viewport; propose a mode-specific adjustment rather than changing the shared layout globally.",
        "Inspect buttons, chips, and links for duplicate or ambiguous labels, sufficient touch targets, and clear hover/focus states; scope copy or style changes to the affected mode.",
        "Check for horizontal overflow, cropped media, overlapping elements, and unreadable contrast; report the failing viewport and never alter a good viewport to fix another.",
    ]
    if len(present) < 3:
        prompts.insert(0, f"Only {', '.join(present)} screenshots are present; capture the missing responsive viewports before finalizing design changes.")
    return prompts


def capture(url: str, output: str | None = None, modes: list[str] | None = None, full_page: bool = True, settle_seconds: float | None = None) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("website screenshots require Playwright: pip install playwright && playwright install chromium") from exc
    selected = modes or list(VIEWPORTS)
    settle = float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "2.5")) if settle_seconds is None else settle_seconds
    if settle < 0 or settle > 60:
        raise ValueError("settle_seconds must be between 0 and 60")
    unknown = sorted(set(selected) - set(VIEWPORTS))
    if unknown:
        raise ValueError(f"unknown viewport(s): {', '.join(unknown)}")
    target = Path(output or temporary_output()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for mode in selected:
                width, height = VIEWPORTS[mode]
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.goto(url, wait_until="load", timeout=30_000)
                page.wait_for_timeout(int(settle * 1000))
                path = target / f"website-{mode}.png"
                page.screenshot(path=str(path), full_page=full_page)
                results.append(path)
                page.close()
        finally:
            browser.close()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka web-screenshot")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--viewport", choices=[*VIEWPORTS, "all"], default="all")
    parser.add_argument("--output", help="persistent output directory (temporary by default)")
    parser.add_argument("--viewport-only", action="store_true", help="Capture only the visible viewport")
    parser.add_argument("--settle", type=float, help="Seconds to wait after load (default: ARKA_BROWSER_SETTLE_SECONDS or 2.5)")
    parser.add_argument("--review", action="store_true", help="Review existing screenshots and print design-change prompts")
    args = parser.parse_args(argv)
    try:
        if args.review:
            if not args.output:
                parser.error("--output is required with --review")
            for index, prompt in enumerate(review(args.output), 1):
                print(f"{index}. {prompt}")
            return 0
        if not args.url:
            parser.error("url is required unless --review is used")
        modes = list(VIEWPORTS) if args.viewport == "all" else [args.viewport]
        for path in capture(args.url, args.output, modes, full_page=not args.viewport_only, settle_seconds=args.settle):
            print(path)
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"web-screenshot: {exc}")
        return 2
