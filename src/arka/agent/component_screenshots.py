"""Capture full-page and per-component screenshots from a URL."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import atexit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SELECTORS = (
    "[data-testid]",
    "[data-component]",
    "[data-test-id]",
)
COMMON_SELECTORS = (
    "button:not([type='hidden'])",
    "input:not([type='hidden'])",
    "select",
    "textarea",
    "[role='button']",
    "[role='navigation']",
    "[role='dialog']",
    "[role='tab']",
    "[role='menuitem']",
    "[role='banner']",
    "[role='main']",
)
NAME_ATTRS = ("data-testid", "data-component", "data-test-id", "id", "aria-label", "name")
STORYBOOK_IFRAME = "iframe#storybook-preview-iframe, iframe[title='storybook-preview-iframe']"


def temporary_output() -> str:
    path = tempfile.mkdtemp(prefix="arka-component-shots-")
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "component"


def _normalize_url(url: str) -> str:
    candidate = url.strip()
    path = Path(candidate).expanduser()
    if path.is_file() and path.suffix.lower() in {".html", ".htm"}:
        return path.resolve().as_uri()
    if candidate.startswith("/") and path.is_file():
        return path.resolve().as_uri()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", candidate):
        return f"http://{candidate.lstrip('/')}"
    return candidate


def _boxes_overlap(a: dict[str, float], b: dict[str, float], threshold: float = 0.85) -> bool:
    x_overlap = max(0.0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
    y_overlap = max(0.0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
    overlap_area = x_overlap * y_overlap
    if overlap_area <= 0:
        return False
    smaller = min(a["width"] * a["height"], b["width"] * b["height"])
    if smaller <= 0:
        return False
    return (overlap_area / smaller) >= threshold


def _element_name(item: Any, selector: str, index: int) -> str:
    for attr in NAME_ATTRS:
        try:
            value = item.get_attribute(attr)
        except Exception:
            value = None
        if value and value.strip():
            return slugify(value)
    try:
        text = item.inner_text(timeout=500).strip()
    except Exception:
        text = ""
    if text:
        return slugify(text[:48])
    return slugify(f"{selector}-{index}")


def _unique_filename(base: str, used: set[str]) -> str:
    stem = slugify(base) or "component"
    candidate = f"component-{stem}.png"
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while True:
        candidate = f"component-{stem}-{index}.png"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def discover_components(
    root: Any,
    selectors: list[str] | None = None,
    *,
    include_common: bool = False,
    max_components: int = 100,
) -> list[dict[str, Any]]:
    chosen = list(selectors or [])
    if not selectors:
        chosen = [*DEFAULT_SELECTORS, *COMMON_SELECTORS]
    elif include_common:
        chosen.extend(COMMON_SELECTORS)
    if not chosen:
        chosen = [*DEFAULT_SELECTORS, *COMMON_SELECTORS]

    seen_boxes: list[dict[str, float]] = []
    used_names: set[str] = set()
    components: list[dict[str, Any]] = []

    for selector in chosen:
        locator = root.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
            except Exception:
                continue
            if not box or box.get("width", 0) < 2 or box.get("height", 0) < 2:
                continue
            if any(_boxes_overlap(box, seen) for seen in seen_boxes):
                continue
            name = _element_name(item, selector, index)
            filename = _unique_filename(name, used_names)
            seen_boxes.append(box)
            components.append(
                {
                    "name": name,
                    "file": filename,
                    "selector": selector,
                    "index": index,
                    "box": box,
                }
            )
            if len(components) >= max_components:
                return components
    return components


def _storybook_root(page: Any) -> Any:
    frame = page.frame_locator(STORYBOOK_IFRAME)
    try:
        if frame.locator("body").count() > 0:
            return frame
    except Exception:
        pass
    return page


def capture(
    url: str,
    output: str | None = None,
    *,
    selectors: list[str] | None = None,
    include_common: bool = False,
    max_components: int = 100,
    full_page: bool = True,
    settle_seconds: float | None = None,
    storybook: bool = False,
) -> dict[str, Any]:
    if max_components < 1 or max_components > 500:
        raise ValueError("max_components must be between 1 and 500")
    settle = float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "2.5")) if settle_seconds is None else settle_seconds
    if settle < 0 or settle > 60:
        raise ValueError("settle_seconds must be between 0 and 60")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "component screenshots require Playwright: pip install playwright && playwright install chromium"
        ) from exc

    target = Path(output or temporary_output()).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    normalized = _normalize_url(url)
    use_storybook = storybook or "storybook" in normalized.lower()
    captured: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page.goto(normalized, wait_until="load", timeout=45_000)
            page.wait_for_timeout(int(settle * 1000))

            root = _storybook_root(page) if use_storybook else page
            full_page_path = target / "full-page.png"
            if use_storybook:
                try:
                    root.locator("body").screenshot(path=str(full_page_path))
                except Exception:
                    page.screenshot(path=str(full_page_path), full_page=full_page)
            else:
                page.screenshot(path=str(full_page_path), full_page=full_page)
            discovered = discover_components(
                root,
                selectors,
                include_common=include_common,
                max_components=max_components,
            )

            for component in discovered:
                item = root.locator(component["selector"]).nth(component["index"])
                try:
                    item.scroll_into_view_if_needed(timeout=5_000)
                    page.wait_for_timeout(150)
                    out_path = target / component["file"]
                    item.screenshot(path=str(out_path))
                    captured.append({**component, "path": str(out_path), "status": "ok"})
                except Exception as exc:
                    captured.append({**component, "status": "error", "error": str(exc)})

            manifest = {
                "url": normalized,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "output_dir": str(target),
                "full_page": str(full_page_path),
                "selectors": list(selectors or []),
                "include_common": include_common,
                "storybook": use_storybook,
                "components": captured,
                "total_discovered": len(discovered),
                "total_captured": sum(1 for item in captured if item.get("status") == "ok"),
            }
            manifest_path = target / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return manifest
        finally:
            browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka component-screenshots")
    parser.add_argument("url", nargs="?", help="URL, localhost:port, or local HTML file")
    parser.add_argument("--url", dest="url_flag", help="URL (alternative to positional)")
    parser.add_argument("--output", help="persistent output directory (temporary by default)")
    parser.add_argument(
        "--selector",
        action="append",
        dest="selectors",
        help="CSS selector to capture (repeatable; defaults to data-testid/component attrs and common UI roles)",
    )
    parser.add_argument("--include-common", action="store_true", help="Also capture buttons, inputs, and ARIA roles")
    parser.add_argument("--max-components", type=int, default=100, help="Maximum components to capture (default: 100)")
    parser.add_argument("--viewport-only", action="store_true", help="Capture only the visible viewport for full-page shot")
    parser.add_argument("--settle", type=float, help="Seconds to wait after load (default: ARKA_BROWSER_SETTLE_SECONDS or 2.5)")
    parser.add_argument("--storybook", action="store_true", help="Capture components inside the Storybook preview iframe")
    parser.add_argument("--json", action="store_true", help="Print manifest JSON instead of file paths")
    args = parser.parse_args(argv)

    page_url = args.url_flag or args.url
    if not page_url:
        parser.error("url is required (positional or --url)")

    try:
        manifest = capture(
            page_url,
            args.output,
            selectors=args.selectors,
            include_common=args.include_common,
            max_components=args.max_components,
            full_page=not args.viewport_only,
            settle_seconds=args.settle,
            storybook=args.storybook,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"component-screenshots: {exc}")
        return 2

    if args.json:
        print(json.dumps(manifest, indent=2))
        return 0

    print(manifest["full_page"])
    for item in manifest["components"]:
        if item.get("status") == "ok":
            print(item["path"])
    print(manifest["output_dir"] + "/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
