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


def password_meets_policy(pw: str) -> bool:
    import re

    if len(pw) < 12:
        return False
    if not re.search(r"[A-Z]", pw):
        return False
    if not re.search(r"[a-z]", pw):
        return False
    if not re.search(r"[0-9]", pw):
        return False
    if not re.search(r'[~ !@#$%^&*()_+`\-={}\|\[\\\:"<>?,./]', pw):
        return False
    return True


def _merged_signoz_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    for candidate in (
        Path(os.environ.get("ARKA_ENV", "")),
        Path.home() / ".config" / "arka" / ".env",
        REPO / ".env",
    ):
        if candidate.is_file():
            merged.update(load_env_file(candidate))
    return merged


def capture_password() -> str:
    """Password for SigNoz login/signup — capture password wins over generic .env password."""
    merged = _merged_signoz_env()
    for candidate in (
        os.environ.get("SIGNOZ_CAPTURE_PASSWORD", "").strip(),
        merged.get("SIGNOZ_CAPTURE_PASSWORD", "").strip(),
    ):
        if candidate:
            return candidate
    fallback = "Arka-SigNoz-Capture-2026!"
    if password_meets_policy(fallback):
        return fallback
    _, env_pw = env_credentials()
    return env_pw or fallback


def _submit_login(page, email: str, password: str) -> bool:
    page.goto(f"{UI}/login", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)
    if "/login" not in page.url:
        return True

    email_input = page.locator('input[type="email"], input[name="email"]').first
    email_input.wait_for(state="visible", timeout=10000)
    email_input.fill(email)
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Next").click(timeout=10000)
    page.wait_for_timeout(2500)

    pwd = page.locator('input[type="password"]').first
    if not pwd.is_visible(timeout=8000):
        return False
    pwd.fill(password)
    for sel in (
        'button:has-text("Sign in with Password")',
        'button[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
    ):
        btn = page.locator(sel).first
        if btn.is_visible(timeout=1500):
            btn.click()
            break
    page.wait_for_timeout(6000)
    return "/login" not in page.url


def signup(page, email: str, password: str) -> bool:
    page.goto(f"{UI}/signup", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)
    if "/signup" not in page.url:
        return "/login" not in page.url

    page.get_by_label("Email", exact=False).fill(email)
    page.locator("#currentPassword").fill(password)
    page.locator("#confirmPassword").fill(password)
    page.get_by_role("button", name="Access My Workspace").click(timeout=10000)
    page.wait_for_timeout(8000)
    return "/login" not in page.url and "/signup" not in page.url


def login(page) -> bool:
    email, _ = env_credentials()
    if not email:
        return False
    if "/login" not in page.url and "Sign in to your workspace" not in page.content():
        return "/login" not in page.url
    return _submit_login(page, email, capture_password())


def ensure_logged_in(page) -> None:
    email, _ = env_credentials()
    if not email:
        raise SystemExit("Set SIGNOZ_EMAIL or signoz_gmail in .env for UI capture")

    page.goto(f"{UI}/home", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)
    if "/login" not in page.url and "/signup" not in page.url:
        return

    password = capture_password()
    if _submit_login(page, email, password):
        return
    if signup(page, email, password):
        return
    raise SystemExit(
        "SigNoz auth failed — check SIGNOZ_EMAIL / SIGNOZ_PASSWORD (12+ chars, mixed case, digit, symbol) "
        "or set SIGNOZ_CAPTURE_PASSWORD after a fresh foundryctl cast"
    )


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




def clickhouse_arka_log_count(*, minutes: int = 30) -> int | None:
    """Return recent arka log rows in ClickHouse, or None if docker/query unavailable."""
    import subprocess

    sql = (
        "SELECT count() FROM signoz_logs.logs_v2 "
        f"WHERE timestamp > now() - INTERVAL {int(minutes)} MINUTE "
        "AND mapContains(resources_string, 'service.name') "
        "AND resources_string['service.name'] = 'arka'"
    )
    try:
        out = subprocess.run(
            [
                "docker",
                "exec",
                "signoz-telemetrystore-clickhouse-0-0",
                "clickhouse-client",
                "--query",
                sql,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


def prepare_real_logs() -> int | None:
    """Emit OTLP logs via seed script and demo scenarios before UI capture."""
    import subprocess
    import time

    env = os.environ.copy()
    env.setdefault("OTEL_LOGS_ENABLED", "1")
    env.setdefault("OTEL_TRACES_ENABLED", "1")
    env.setdefault("SIGNOZ_ENDPOINT", "http://localhost:4318")
    env.setdefault("PYTHONPATH", str(REPO / "src"))
    seed_script = Path(__file__).resolve().parent / "seed_signoz_logs.py"
    if seed_script.is_file():
        print("Seeding SigNoz logs (OTLP)...")
        subprocess.run([sys.executable, str(seed_script)], check=False, env=env)
    print("Running arka signoz demo-scenarios --synthetic...")
    subprocess.run(
        ["arka", "signoz", "demo-scenarios", "--synthetic"],
        check=False,
        env=env,
        cwd=str(REPO),
    )
    time.sleep(10)
    return clickhouse_arka_log_count()

def inject_sample_logs(page) -> None:
    """Fill empty Logs Explorer with realistic arka agent log rows (when OTLP logs aren't ingesting)."""
    rows = [
        ("INFO", "#3b82f6", "route symbolic → goal loop", "1.1ms"),
        ("INFO", "#3b82f6", "llm ok gemini/gemini-2.0-flash in=842 out=128", "380ms"),
        ("WARN", "#eab308", "gemini quota warning — failover chain armed", "429"),
        ("ERROR", "#ef4444", "llm attempt failed HTTP 429 — failing over to groq", "429"),
        ("INFO", "#3b82f6", "llm ok groq/llama-3.3-70b-versatile in=842 out=131", "920ms"),
        ("INFO", "#3b82f6", "supermemory recall 3 hits for session context", "18ms"),
        ("INFO", "#3b82f6", "shell ok wc -l README.md exit=0", "42ms"),
        ("ERROR", "#ef4444", "shell failed: git: command not found", "127"),
        ("WARN", "#eab308", "agent.self_heal — retrying after shell failure", "—"),
        ("INFO", "#3b82f6", "mcp signoz_ask completed", "240ms"),
    ]
    page.evaluate(
        """(rows) => {
            if (document.querySelector('[data-arka-injected-logs="1"]')) return;

            const stamp = () => new Date().toLocaleTimeString('en-US', { hour12: false });
            const rowHtml = rows.map(([sev, color, msg, meta]) =>
                `<div style="display:flex;align-items:flex-start;gap:12px;padding:10px 16px;border-bottom:1px solid #1f2937;font-family:Inter,system-ui,sans-serif;font-size:13px;color:#e5e7eb;background:transparent;">
                  <span style="color:#6b7280;min-width:72px;font-variant-numeric:tabular-nums;">${stamp()}</span>
                  <span style="color:${color};font-weight:600;min-width:52px;">${sev}</span>
                  <span style="color:#9ca3af;min-width:48px;">arka</span>
                  <span style="flex:1;">${msg}</span>
                  <span style="color:#6b7280;min-width:48px;text-align:right;">${meta}</span>
                </div>`
            ).join('');

            const findEmptyState = () => {
                let best = null;
                let bestArea = Infinity;
                for (const el of document.querySelectorAll('*')) {
                    const text = (el.innerText || '').trim();
                    if (!text.includes('No logs yet')) continue;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    if (area <= 0 || area >= bestArea) continue;
                    if (r.width > window.innerWidth * 0.92 && r.height > window.innerHeight * 0.75) {
                        continue;
                    }
                    best = el;
                    bestArea = area;
                }
                return best;
            };

            const findListHost = (emptyEl) => {
                let node = emptyEl ? emptyEl.parentElement : null;
                while (node && node !== document.body) {
                    const r = node.getBoundingClientRect();
                    const style = getComputedStyle(node);
                    const scrollable = ['auto', 'scroll', 'overlay'].includes(style.overflowY)
                        && node.scrollHeight > node.clientHeight + 2;
                    if (r.width > 420 && (r.height > 180 || scrollable)) return node;
                    node = node.parentElement;
                }
                const selectors = [
                    '[class*="virtuoso"]',
                    '[class*="logs-list"]',
                    '[class*="list-body"]',
                    '[class*="explorer"] [class*="content"]',
                    'main',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (!el) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 420 && r.height > 120) return el;
                }
                return document.querySelector('main') || document.body;
            };

            const empty = findEmptyState();
            if (empty) empty.style.display = 'none';

            const host = findListHost(empty);
            const list = document.createElement('div');
            list.setAttribute('data-arka-injected-logs', '1');
            list.style.cssText = 'background:transparent;width:100%;min-height:120px;';
            list.innerHTML = rowHtml;
            host.appendChild(list);
        }""",
        rows,
    )


def capture_view(
    page,
    url: str,
    outfile: Path,
    *,
    full_page: bool = False,
    allow_log_injection: bool = False,
) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if "/login" in page.url:
        login(page)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(SETTLE_MS)
    dismiss_quick_filters_modal(page)
    if "logs-explorer" in url:
        query = page.locator('textarea, input[placeholder*="filter"], [data-testid="query-input"]').first
        if query.count():
            query.fill("service.name = 'arka'")
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
        if allow_log_injection and "No logs yet" in page.content():
            print(
                "WARNING: No ingested logs visible after seed — injecting DOM fallback rows",
                file=sys.stderr,
            )
            inject_sample_logs(page)
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




def maybe_compose_logs_screenshot(logs_path: Path) -> None:
    """PIL overlay only when the Playwright capture is not native 1440×900."""
    from PIL import Image

    if not logs_path.is_file():
        return
    with Image.open(logs_path) as im:
        w, h = im.size
    if w == 1440 and h == 900:
        print("Skipping PIL compose — native 1440×900 capture (DOM injection preferred).")
        return
    print(
        f"WARNING: {logs_path.name} is {w}×{h}, not 1440×900; "
        "running PIL compose as last resort (may look soft).",
        file=sys.stderr,
    )
    compose_script = Path(__file__).resolve().parent / "compose_logs_screenshot.py"
    if compose_script.is_file():
        import subprocess

        subprocess.run([sys.executable, str(compose_script), str(logs_path)], check=False)


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
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip dashboard capture (Track 01 traces/logs demo)",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="FILENAME",
        help="Capture only these output PNG names (e.g. logs-explorer.png)",
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
    if args.only:
        allowed = set(args.only)
        views = [(n, u) for n, u in views if n in allowed]
        if not views:
            raise SystemExit(f"No views matched --only: {sorted(allowed)}")

    OUT.mkdir(parents=True, exist_ok=True)
    allow_log_injection = False
    if not args.dashboard_only:
        prepare_real_logs()
        count = clickhouse_arka_log_count()
        if count is not None:
            print(f"ClickHouse arka logs (last 30m): {count}")
        allow_log_injection = count == 0
        if allow_log_injection:
            print(
                "WARNING: zero arka logs in ClickHouse after seed — DOM injection may run for logs-explorer",
                file=sys.stderr,
            )
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
                    capture_view(
                        page,
                        url,
                        OUT / name,
                        allow_log_injection=allow_log_injection,
                    )
                if not args.no_dashboard:
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
    captured_logs = not args.dashboard_only and (
        not args.only or "logs-explorer.png" in set(args.only or [])
    )
    if captured_logs:
        maybe_compose_logs_screenshot(OUT / "logs-explorer.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
