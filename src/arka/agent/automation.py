"""Cross-platform app automation runner.

Web apps use Playwright on every OS. Steps are deliberately declarative so an
agent can generate and review a test plan before executing it.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

SUPPORTED = {"goto", "click", "fill", "press", "type", "hotkey", "wait", "assert_text", "screenshot"}


def validate_steps(steps: list[dict[str, Any]]) -> None:
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get("action") not in SUPPORTED:
            raise ValueError(f"step {index}: action must be one of {', '.join(sorted(SUPPORTED))}")
        action = step["action"]
        if action in {"click", "fill", "press", "assert_text"} and not step.get("selector") and not step.get("x"):
            raise ValueError(f"step {index}: {action} requires selector")
        if action == "goto" and not step.get("url"):
            raise ValueError(f"step {index}: goto requires url")


def run_web(url: str, steps: list[dict[str, Any]], *, headless: bool = True, output: str | None = None) -> dict[str, Any]:
    validate_steps(steps)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install cross-platform web automation: pip install playwright && playwright install chromium") from exc
    screenshots: list[str] = []
    events: list[dict[str, Any]] = []
    target = Path(output).expanduser() if output else Path(tempfile.mkdtemp(prefix="arka-automation-"))
    target.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        for index, step in enumerate(steps, 1):
            action = step["action"]
            if action == "goto":
                page.goto(step["url"], wait_until="domcontentloaded", timeout=30_000)
            elif action == "click":
                page.locator(step["selector"]).click(timeout=15_000)
            elif action == "fill":
                page.locator(step["selector"]).fill(str(step.get("value", "")))
            elif action == "press":
                page.locator(step["selector"]).press(str(step.get("key", "Enter")))
            elif action == "wait":
                page.wait_for_timeout(min(30_000, max(0, int(step.get("ms", 500)))))
            elif action == "assert_text":
                page.locator(step["selector"]).get_by_text(str(step.get("text", "")), exact=False).wait_for(timeout=15_000)
            elif action == "screenshot":
                path = target / str(step.get("name", f"step-{index}.png"))
                page.screenshot(path=str(path), full_page=True)
                screenshots.append(str(path))
            events.append({"step": index, "action": action, "status": "passed"})
        browser.close()
    return {"url": url, "status": "passed", "steps": events, "screenshots": screenshots, "artifacts": str(target)}


def run_desktop(steps: list[dict[str, Any]], *, output: str | None = None) -> dict[str, Any]:
    """Run coordinate/key automation through PyAutoGUI on macOS/Linux/Windows."""
    validate_steps(steps)
    unsupported = {step["action"] for step in steps} - {"click", "type", "hotkey", "press", "wait", "screenshot"}
    if unsupported:
        raise ValueError(f"desktop backend does not support: {', '.join(sorted(unsupported))}")
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError("Install desktop automation: pip install pyautogui") from exc
    target = Path(output).expanduser() if output else Path(tempfile.mkdtemp(prefix="arka-automation-"))
    target.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, Any]] = []
    screenshots: list[str] = []
    for index, step in enumerate(steps, 1):
        action = step["action"]
        if action == "click":
            if step.get("x") is None or step.get("y") is None:
                raise ValueError(f"step {index}: desktop click requires x and y")
            pyautogui.click(int(step["x"]), int(step["y"]))
        elif action == "type":
            pyautogui.write(str(step.get("text", "")), interval=float(step.get("interval", 0.01)))
        elif action == "hotkey":
            pyautogui.hotkey(*(str(key) for key in step.get("keys", [])))
        elif action == "press":
            pyautogui.press(str(step.get("key", "enter")))
        elif action == "wait":
            import time
            time.sleep(min(30, max(0, float(step.get("seconds", step.get("ms", 500) / 1000)))))
        elif action == "screenshot":
            path = target / str(step.get("name", f"step-{index}.png"))
            pyautogui.screenshot(str(path))
            screenshots.append(str(path))
        events.append({"step": index, "action": action, "status": "passed"})
    return {"status": "passed", "steps": events, "screenshots": screenshots, "artifacts": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka automate", description="Run declarative cross-platform web app tests")
    parser.add_argument("url")
    parser.add_argument("--steps", required=True, help="JSON array or path to a JSON file")
    parser.add_argument("--backend", choices=("web", "desktop"), default="web")
    parser.add_argument("--output", help="persistent artifact directory; temporary by default")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.steps).read_text(encoding="utf-8") if Path(args.steps).is_file() else args.steps
        steps = json.loads(raw)
        result = run_desktop(steps, output=args.output) if args.backend == "desktop" else run_web(args.url, steps, headless=not args.headed, output=args.output)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"automation: {result['status']} ({len(result['steps'])} steps)")
    return 0
