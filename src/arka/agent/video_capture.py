"""Browser walkthrough video capture via Playwright."""
from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.core.screenshot_paths import screenshot_path

DEFAULT_VIEWPORT = (1440, 900)
DEFAULT_WALKTHROUGH_URL = os.environ.get("ARKA_WALKTHROUGH_URL", "http://127.0.0.1:5173")


def temporary_output() -> str:
    path = tempfile.mkdtemp(prefix="arka-video-capture-")
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def _finalize_video(page: Any, context: Any) -> str | None:
    """Close Playwright page/context and return the finalized video path."""
    video_obj = getattr(page, "video", None)
    try:
        close_page = getattr(page, "close", None)
        if callable(close_page):
            close_page()
    finally:
        context.close()
    if not video_obj:
        return None
    try:
        video_path = video_obj.path()
    except Exception:
        return None
    return str(video_path) if video_path else None


def dashboard_walkthrough_actions(base_url: str) -> list[dict[str, Any]]:
    """Default step list for the Arka web dashboard (Chat → Skills → Status)."""
    base = base_url.rstrip("/")
    return [
        {"type": "goto", "url": f"{base}/"},
        {"type": "wait", "ms": 2000},
        {"type": "screenshot", "name": "01-chat.png"},
        {"type": "click", "text": "Skills"},
        {"type": "wait", "ms": 1500},
        {"type": "screenshot", "name": "02-skills.png"},
        {"type": "click", "text": "Status"},
        {"type": "wait", "ms": 1500},
        {"type": "screenshot", "name": "03-status.png"},
    ]


def load_actions(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).expanduser().read_text())
    if not isinstance(data, list):
        raise ValueError("actions JSON must be a list of step objects")
    return data


def _run_action(page: Any, action: dict[str, Any], output_dir: Path, index: int) -> Path | None:
    kind = str(action.get("type") or action.get("action") or "").lower()
    if kind in {"goto", "navigate"}:
        url = action.get("url") or action.get("target")
        if not url:
            raise ValueError(f"step {index}: navigate action requires url")
        page.goto(str(url), wait_until="load", timeout=30_000)
        return None
    if kind == "click":
        if "selector" in action:
            page.locator(action["selector"]).first.click(timeout=10_000)
        elif "text" in action:
            page.get_by_text(str(action["text"]), exact=action.get("exact", False)).first.click(timeout=10_000)
        else:
            raise ValueError(f"step {index}: click action requires selector or text")
        return None
    if kind == "wait":
        ms = action.get("ms")
        if ms is None:
            seconds = float(action.get("seconds", 1))
            ms = int(seconds * 1000)
        page.wait_for_timeout(max(0, int(ms)))
        return None
    if kind in {"wait_for_text", "assert_text"}:
        text = action.get("text")
        if not text:
            raise ValueError(f"step {index}: wait_for_text requires text")
        timeout = int(action.get("timeout_ms", action.get("timeout", 15_000)))
        locator = page.locator(action["selector"]).first if "selector" in action else page.get_by_text(str(text), exact=action.get("exact", False)).first
        try:
            if "selector" in action:
                locator.get_by_text(str(text), exact=action.get("exact", False)).wait_for(timeout=timeout)
            else:
                locator.wait_for(timeout=timeout)
        except Exception:
            if action.get("optional"):
                return None
            raise
        return None
    if kind == "press":
        key = action.get("key")
        if not key:
            raise ValueError(f"step {index}: press action requires key")
        page.keyboard.press(str(key))
        return None
    if kind in {"type", "fill"}:
        text = action.get("text")
        if text is None:
            text = action.get("value")
        if text is None:
            raise ValueError(f"step {index}: type/fill action requires text")
        if "selector" in action:
            page.locator(action["selector"]).first.fill(str(text))
        elif "placeholder" in action:
            page.get_by_placeholder(str(action["placeholder"])).first.fill(str(text))
        else:
            page.keyboard.type(str(text))
        return None
    if kind == "screenshot":
        name = action.get("name") or f"step-{index:03d}"
        stem = Path(str(name)).stem if str(name).endswith(".png") else str(name)
        path = screenshot_path(stem, output_dir)
        page.screenshot(path=str(path), full_page=bool(action.get("full_page", False)))
        return path
    raise ValueError(f"step {index}: unknown action type {kind!r}")


def capture(
    url: str,
    *,
    output: str | None = None,
    actions: list[dict[str, Any]] | None = None,
    settle_seconds: float | None = None,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
    record_video: bool = True,
    screenshot_steps: bool = True,
) -> dict[str, Any]:
    """Load a URL, run optional walkthrough steps, and capture PNGs and/or MP4."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "video capture requires Playwright: pip install playwright && playwright install chromium"
        ) from exc

    settle = float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "2.5")) if settle_seconds is None else settle_seconds
    if settle < 0 or settle > 60:
        raise ValueError("settle_seconds must be between 0 and 60")

    target = Path(output or temporary_output()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    steps = list(actions or [])
    if not steps:
        steps = [
            {"type": "goto", "url": url},
            {"type": "wait", "seconds": settle},
        ]
        if screenshot_steps:
            steps.append({"type": "screenshot", "name": "capture.png"})

    screenshots: list[Path] = []
    video: str | None = None
    width, height = viewport

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
                record_video_dir=str(target) if record_video else None,
                record_video_size={"width": width, "height": height} if record_video else None,
            )
            page = context.new_page()
            if steps and steps[0].get("type", steps[0].get("action")) not in {"goto", "navigate"}:
                page.goto(url, wait_until="load", timeout=30_000)
                page.wait_for_timeout(int(settle * 1000))

            for index, action in enumerate(steps):
                shot = _run_action(page, action, target, index)
                if shot is not None:
                    screenshots.append(shot)

            if record_video:
                raw_video = _finalize_video(page, context)
                if raw_video:
                    src = Path(raw_video)
                    dest = target / "walkthrough.webm"
                    if src.exists():
                        if dest.exists():
                            dest.unlink()
                        src.rename(dest)
                        video = str(dest)
            else:
                page.close()
                context.close()
        finally:
            browser.close()

    return {
        "url": url,
        "output": str(target),
        "video": video,
        "screenshots": [str(path) for path in screenshots],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka capture video")
    parser.add_argument("url", nargs="?", help="Page URL to open (default with --walkthrough)")
    parser.add_argument("--output", help="Output directory (temporary by default)")
    parser.add_argument("--walkthrough", action="store_true", help="Use the Arka dashboard walkthrough preset")
    parser.add_argument("--actions", help="JSON file with walkthrough steps")
    parser.add_argument("--settle", type=float, help="Seconds to wait after initial load")
    parser.add_argument("--no-video", action="store_true", help="Capture step PNGs only")
    parser.add_argument("--no-screenshots", action="store_true", help="Record MP4 only")
    parser.add_argument("--width", type=int, default=DEFAULT_VIEWPORT[0])
    parser.add_argument("--height", type=int, default=DEFAULT_VIEWPORT[1])
    args = parser.parse_args(argv)

    try:
        url = args.url or (DEFAULT_WALKTHROUGH_URL if args.walkthrough else None)
        if not url:
            parser.error("url is required unless --walkthrough is used")

        if args.actions:
            actions = load_actions(args.actions)
        elif args.walkthrough:
            actions = dashboard_walkthrough_actions(url)
        else:
            actions = None

        result = capture(
            url,
            output=args.output,
            actions=actions,
            settle_seconds=args.settle,
            viewport=(args.width, args.height),
            record_video=not args.no_video,
            screenshot_steps=not args.no_screenshots,
        )
        if result["video"]:
            print(result["video"])
        for path in result["screenshots"]:
            print(path)
        return 0
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"capture video: {exc}")
        return 2


def walkthrough_output_dir(base: str | Path | None = None) -> Path:
    """Return a timestamped output directory under recordings/live-demo-ui/."""
    root = Path(base or Path(__file__).resolve().parents[3] / "recordings" / "live-demo-ui")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = root / f"run-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
