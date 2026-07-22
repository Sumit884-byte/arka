#!/usr/bin/env python3
"""Capture SigNoz UI screenshots for traces, logs, services, and dashboards."""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
UI = os.environ.get("SIGNOZ_UI_URL", "http://localhost:8080").rstrip("/")
SETTLE_MS = int(float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "4")) * 1000)
QUICK_FILTERS_ANNOUNCEMENT_KEY = "QUICK_FILTERS_SETTINGS_ANNOUNCEMENT"
SCROLL_TARGET_ATTR = "data-arka-scroll-target"
DEFAULT_DASHBOARD_TITLE = "Arka Agent Observability"
DEFAULT_DASHBOARD_JSON = (
    REPO / "signoz" / "dashboards" / "arka-agent-observability.json"
)


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def env_credentials() -> tuple[str, str]:
    merged = {}
    for candidate in (
        Path(os.environ.get("ARKA_ENV", "")),
        Path.home() / ".config" / "arka" / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ):
        if candidate.is_file():
            merged.update(load_env_file(candidate))
    email = (
        os.environ.get("SIGNOZ_EMAIL", "")
        or os.environ.get("signoz_gmail", "")
        or merged.get("SIGNOZ_EMAIL", "")
        or merged.get("signoz_gmail", "")
    ).strip()
    password = (
        os.environ.get("SIGNOZ_PASSWORD", "")
        or os.environ.get("signoz_password", "")
        or merged.get("SIGNOZ_PASSWORD", "")
        or merged.get("signoz_password", "")
    ).strip()
    return email, password


def login(page) -> bool:
    email, password = env_credentials()
    if not email or not password:
        return False
    if "/login" not in page.url and "Sign in to your workspace" not in page.content():
        return "/login" not in page.url

    page.wait_for_timeout(2000)
    page.locator('input[type="email"], input[name="email"]').first.fill(email)
    page.locator('button:has-text("Next")').first.click()
    page.wait_for_timeout(3000)

    pwd = page.locator('input[type="password"]').first
    if not pwd.is_visible(timeout=5000):
        return False
    pwd.fill(password)
    for sel in ('button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Log in")'):
        btn = page.locator(sel).first
        if btn.is_visible(timeout=1500):
            btn.click()
            break
    page.wait_for_timeout(6000)
    return "/login" not in page.url


def ensure_logged_in(page) -> None:
    page.goto(f"{UI}/login", wait_until="domcontentloaded", timeout=45000)
    if not login(page):
        login(page)


def dismiss_quick_filters_modal(page) -> None:
    """Hide SigNoz 'Edit your quick filters' onboarding popup before screenshots."""
    page.evaluate(
        f"() => localStorage.setItem({QUICK_FILTERS_ANNOUNCEMENT_KEY!r}, 'false')"
    )
    modal = page.locator('text=Edit your quick filters')
    if modal.count() and modal.first.is_visible(timeout=500):
        for sel in (
            'button:has-text("Okay")',
            '[aria-label="Close"]',
            'button[aria-label="close"]',
        ):
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click()
                page.wait_for_timeout(500)
                break


def capture_view(page, url: str, outfile: Path, *, full_page: bool = False) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if "/login" in page.url:
        login(page)
    page.wait_for_timeout(SETTLE_MS)
    dismiss_quick_filters_modal(page)
    page.wait_for_timeout(500)
    page.screenshot(path=str(outfile), full_page=full_page)
    print(outfile)


def ensure_dashboard(
    page,
    *,
    title: str = DEFAULT_DASHBOARD_TITLE,
    template_json: Path = DEFAULT_DASHBOARD_JSON,
    replace: bool = False,
) -> str:
    """Open an existing dashboard by title or import the bundled JSON template."""
    page.goto(f"{UI}/dashboard", wait_until="domcontentloaded", timeout=45000)
    if "/login" in page.url:
        login(page)
        page.goto(f"{UI}/dashboard", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)

    link = page.locator(f'text="{title}"').first
    if not replace and link.is_visible(timeout=1500):
        link.click()
        page.wait_for_timeout(SETTLE_MS)
        return page.url

    if not template_json.is_file():
        raise FileNotFoundError(f"Dashboard template not found: {template_json}")

    page.locator('button:has-text("New dashboard")').first.click()
    page.wait_for_timeout(1500)
    page.locator("text=Import").first.click()
    page.wait_for_timeout(1500)
    page.locator('input[type="file"]').set_input_files(str(template_json.resolve()))
    page.wait_for_timeout(2000)
    page.locator('button:has-text("Import and Next")').first.click()
    page.wait_for_timeout(SETTLE_MS)
    if "/dashboard/" not in page.url:
        raise RuntimeError(f"Dashboard import failed; still on {page.url}")
    return page.url


def _mark_scroll_container(page) -> dict | None:
    return page.evaluate(
        f"""() => {{
        const isScrollable = (el) => {{
            const style = getComputedStyle(el);
            const oy = style.overflowY;
            return (oy === 'auto' || oy === 'scroll' || oy === 'overlay')
                && el.scrollHeight > el.clientHeight + 2;
        }};
        const main = [...document.querySelectorAll('*')].filter(isScrollable)
            .sort((a, b) => (b.scrollHeight * b.clientWidth) - (a.scrollHeight * a.clientWidth))[0];
        if (!main) return null;
        main.setAttribute({SCROLL_TARGET_ATTR!r}, '1');
        const rect = main.getBoundingClientRect();
        return {{
            scrollHeight: main.scrollHeight,
            clientHeight: main.clientHeight,
            clipX: Math.round(rect.x),
            clipY: Math.round(rect.y),
            clipWidth: Math.round(rect.width),
        }};
    }}"""
    )


def _scroll_container_metrics(page) -> dict:
    return page.evaluate(
        f"""() => {{
        const el = document.querySelector('[{SCROLL_TARGET_ATTR}]');
        const rect = el.getBoundingClientRect();
        return {{
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            clipX: Math.round(rect.x),
            clipY: Math.round(rect.y),
            clipWidth: Math.round(rect.width),
        }};
    }}"""
    )


def _stabilize_scroll_height(page, *, settle_ms: int) -> dict:
    for _ in range(30):
        prev = page.evaluate(
            f"""() => {{
            const el = document.querySelector('[{SCROLL_TARGET_ATTR}]');
            el.scrollTop = el.scrollHeight;
            return el.scrollHeight;
        }}"""
        )
        page.wait_for_timeout(settle_ms)
        cur = page.evaluate(
            f"() => document.querySelector('[{SCROLL_TARGET_ATTR}]').scrollHeight"
        )
        if cur == prev:
            break
    return _scroll_container_metrics(page)


def capture_long_screenshot(page, outfile: Path, *, settle_ms: int = 400) -> None:
    """Capture a nested scroll container by scrolling and stitching clipped slices."""
    from PIL import Image

    info = _mark_scroll_container(page)
    if not info:
        page.screenshot(path=str(outfile), full_page=True)
        print(outfile)
        return

    info = _stabilize_scroll_height(page, settle_ms=settle_ms)
    scroll_height = info["scrollHeight"]
    step = info["clientHeight"]
    max_scroll = max(0, scroll_height - step)

    if scroll_height <= step + 5:
        page.screenshot(path=str(outfile), full_page=True)
        print(outfile)
        return

    page.evaluate(
        f"() => {{ document.querySelector('[{SCROLL_TARGET_ATTR}]').scrollTop = 0; }}"
    )
    page.wait_for_timeout(settle_ms)
    top_shot = Image.open(io.BytesIO(page.screenshot(type="png")))

    bottom_shot = top_shot
    if max_scroll > 0:
        page.evaluate(
            f"(scrollTop) => {{ document.querySelector('[{SCROLL_TARGET_ATTR}]').scrollTop = scrollTop; }}",
            max_scroll,
        )
        page.wait_for_timeout(settle_ms)
        bottom_shot = Image.open(io.BytesIO(page.screenshot(type="png")))

    canvas = Image.new("RGB", (top_shot.width, scroll_height))
    canvas.paste(top_shot.crop((0, 0, top_shot.width, step)), (0, 0))

    if scroll_height > step:
        tail_h = scroll_height - step
        src_top = step - max_scroll
        canvas.paste(
            bottom_shot.crop((0, src_top, bottom_shot.width, src_top + tail_h)),
            (0, step),
        )

    canvas.save(outfile)
    print(outfile)


def capture_dashboard(
    page,
    outfile: Path,
    *,
    title: str = DEFAULT_DASHBOARD_TITLE,
    template_json: Path = DEFAULT_DASHBOARD_JSON,
    long_screenshot: bool = True,
    replace: bool = False,
) -> str:
    url = ensure_dashboard(
        page,
        title=title,
        template_json=template_json,
        replace=replace,
    )
    dismiss_quick_filters_modal(page)
    page.wait_for_timeout(500)
    if long_screenshot:
        capture_long_screenshot(page, outfile)
    else:
        page.screenshot(path=str(outfile), full_page=False)
        print(outfile)
    return url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dashboard-only",
        action="store_true",
        help="Capture only the Arka Agent Observability dashboard",
    )
    parser.add_argument(
        "--dashboard-title",
        default=DEFAULT_DASHBOARD_TITLE,
        help="Dashboard title to open or import",
    )
    parser.add_argument(
        "--dashboard-json",
        type=Path,
        default=DEFAULT_DASHBOARD_JSON,
        help="Bundled dashboard JSON used when the title is missing in SigNoz",
    )
    parser.add_argument(
        "--dashboard-out",
        type=Path,
        default=OUT / "dashboard-observability-long.png",
        help="Output screenshot path for the dashboard capture",
    )
    parser.add_argument(
        "--viewport-dashboard",
        action="store_true",
        help="Capture only the visible dashboard viewport (no scroll stitch)",
    )
    parser.add_argument(
        "--replace-dashboard",
        action="store_true",
        help="Import bundled dashboard JSON even when a dashboard with the same title exists",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 1

    args = parse_args(argv)
    views = [
        ("home-dashboard.png", f"{UI}/home"),
        ("traces-arka-service.png", f"{UI}/services/arka/traces?relativeTime=30m"),
        ("traces-explorer.png", f"{UI}/traces-explorer?selectedTracesFields=serviceName&selectedTracesFields=name&selectedTracesFields=durationNano&selectedTracesFields=httpMethod&selectedTracesFields=responseStatusCode&selectedTracesFields=traceID&filterServiceName=arka"),
        ("logs-explorer.png", f"{UI}/logs/logs-explorer?filterServiceName=arka"),
        ("services-metrics.png", f"{UI}/services"),
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(
            f"localStorage.setItem({QUICK_FILTERS_ANNOUNCEMENT_KEY!r}, 'false');"
        )
        page = context.new_page()
        try:
            ensure_logged_in(page)
            if args.dashboard_only:
                url = capture_dashboard(
                    page,
                    args.dashboard_out,
                    title=args.dashboard_title,
                    template_json=args.dashboard_json,
                    long_screenshot=not args.viewport_dashboard,
                    replace=args.replace_dashboard,
                )
                print(f"url\t{url}")
            else:
                for name, url in views:
                    capture_view(page, url, OUT / name)
                url = capture_dashboard(
                    page,
                    args.dashboard_out,
                    title=args.dashboard_title,
                    template_json=args.dashboard_json,
                    long_screenshot=not args.viewport_dashboard,
                    replace=args.replace_dashboard,
                )
                print(f"url\t{url}")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
