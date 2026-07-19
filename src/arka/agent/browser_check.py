"""Bounded Playwright smoke check for validating a web change."""
from __future__ import annotations
import argparse
import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

def check(url: str, output: str | None = None, settle_seconds: float | None = None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install browser checks with: pip install playwright && playwright install chromium") from exc
    errors: list[str] = []
    temporary = output is None
    if temporary:
        directory = tempfile.mkdtemp(prefix="arka-browser-check-")
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
        output = str(Path(directory) / "browser-check.png")
    settle = float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "2.5")) if settle_seconds is None else settle_seconds
    if settle < 0 or settle > 60:
        raise ValueError("settle_seconds must be between 0 and 60")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(int(settle * 1000))
        page.screenshot(path=output, full_page=True)
        result = {"url": url, "status": response.status if response else None, "title": page.title(), "console_errors": errors, "screenshot": str(Path(output).resolve())}
        browser.close()
    return result

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check a web page and capture its rendered state")
    p.add_argument("url")
    p.add_argument("--output", help="persistent screenshot path (temporary by default)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--settle", type=float, help="Seconds to wait after load (default: ARKA_BROWSER_SETTLE_SECONDS or 2.5)")
    args = p.parse_args(argv)
    try:
        result = check(args.url, args.output, settle_seconds=args.settle)
    except RuntimeError as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"HTTP: {result['status']}\nTitle: {result['title']}\nConsole errors: {len(result['console_errors'])}\nScreenshot: {result['screenshot']}")
    return 0 if result["status"] and result["status"] < 400 and not result["console_errors"] else 1
