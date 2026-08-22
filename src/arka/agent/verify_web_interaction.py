"""Verify live website interactions against local code context."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import atexit
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from arka.core.screenshot_paths import screenshot_path

VISION_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)

SELECTOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"""data-testid\s*=\s*["'{]([^"'{}]+)["'}]""", re.I), "testid"),
    (re.compile(r"""data-test-id\s*=\s*["'{]([^"'{}]+)["'}]""", re.I), "testid"),
    (re.compile(r"""data-component\s*=\s*["'{]([^"'{}]+)["'}]""", re.I), "testid"),
    (re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.I), "id"),
    (re.compile(r"""\bname\s*=\s*["']([^"']+)["']""", re.I), "name"),
    (re.compile(r"""aria-label\s*=\s*["']([^"']+)["']""", re.I), "aria"),
    (re.compile(r"""getByTestId\s*\(\s*["']([^"']+)["']\s*\)"""), "testid"),
    (re.compile(r"""getByRole\s*\(\s*["']([^"']+)["']"""), "role"),
    (re.compile(r"""getByText\s*\(\s*["']([^"']+)["']\s*\)"""), "text"),
    (re.compile(r"""locator\s*\(\s*(\[[^\]]+\]|["'][^"']+["'])\s*\)"""), "locator"),
    (re.compile(r"""page\.(?:click|fill|locator)\s*\(\s*(\[[^\]]+\]|["'][^"']+["'])"""), "locator"),
    (re.compile(r"""cy\.get\s*\(\s*(\[[^\]]+\]|["'][^"']+["'])\s*\)"""), "locator"),
)

TEXT_PATTERNS = (
    re.compile(r"""<button[^>]*>([^<]{1,80})</button>""", re.I),
    re.compile(r"""getByText\s*\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""expect\s*\([^)]*\)\.toHaveText\s*\(\s*["']([^"']+)["']"""),
    re.compile(r"""assert_text\s*:\s*["']([^"']+)["']"""),
)

HREF_PATTERN = re.compile(r"""href\s*=\s*["']([^"'#][^"']*)["']""", re.I)
ROUTE_PATTERNS = (
    re.compile(r"""path\s*:\s*["']([^"']+)["']"""),
    re.compile(r"""route\s*\(\s*["']([^"']+)["']"""),
    re.compile(r"""@app\.(?:get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']"""),
)

_QUOTED_SELECTOR = r"""(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|\[[^\]]+\])"""

PLAYWRIGHT_STEP_PATTERNS = (
    (re.compile(r"""page\.goto\s*\(\s*['"]([^'"]+)['"]"""), "goto", "url"),
    (re.compile(rf"""page\.click\s*\(\s*({_QUOTED_SELECTOR})"""), "click", "selector"),
    (re.compile(rf"""page\.fill\s*\(\s*({_QUOTED_SELECTOR})\s*,\s*['"]([^'"]*)['"]"""), "fill", ("selector", "value")),
    (re.compile(rf"""page\.locator\s*\(\s*({_QUOTED_SELECTOR})\s*\)\.click"""), "click", "selector"),
    (re.compile(r"""getByRole\s*\(\s*['"]([^'"]+)['"]\s*,\s*\{[^}]*name\s*:\s*['"]([^'"]+)['"]"""), "click_role", ("role", "name")),
    (re.compile(r"""getByText\s*\(\s*['"]([^'"]+)['"]\s*\)\.click"""), "click_text", "text"),
    (re.compile(rf"""expect\s*\(\s*page\.locator\s*\(\s*({_QUOTED_SELECTOR})\s*\)\s*\)\.toBeVisible"""), "assert_visible", "selector"),
    (re.compile(r"""expect\s*\(\s*page\.getByText\s*\(\s*['"]([^'"]+)['"]\s*\)\s*\)\.toBeVisible"""), "assert_text_visible", "text"),
)

CYPRESS_STEP_PATTERNS = (
    (re.compile(r"""cy\.visit\s*\(\s*['"]([^'"]+)['"]"""), "goto", "url"),
    (re.compile(rf"""cy\.get\s*\(\s*({_QUOTED_SELECTOR})\s*\)\.click"""), "click", "selector"),
    (re.compile(rf"""cy\.get\s*\(\s*({_QUOTED_SELECTOR})\s*\)\.type\s*\(\s*['"]([^'"]*)['"]"""), "fill", ("selector", "value")),
    (re.compile(r"""cy\.contains\s*\(\s*['"]([^'"]+)['"]\s*\)\.click"""), "click_text", "text"),
)


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


def _selector_from_testid(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith(("[", ".", "#")):
        return cleaned
    return f'[data-testid="{cleaned}"]'


def _normalize_selector(raw: str) -> str:
    cleaned = raw.strip().strip("'\"")
    if cleaned.startswith(("[", ".", "#", "text=")):
        return cleaned
    return f'[data-testid="{cleaned}"]'


def _selector_from_match(kind: str, raw: str) -> str | None:
    value = raw.strip().strip("'\"")
    if not value:
        return None
    if kind == "testid":
        return _selector_from_testid(value)
    if kind == "id":
        return f"#{value}"
    if kind == "name":
        return f'[name="{value}"]'
    if kind == "aria":
        return f'[aria-label="{value}"]'
    if kind == "role":
        return f'role={value}'
    if kind == "locator":
        return _normalize_selector(value)
    return None


def parse_code_context(path: str | Path) -> dict[str, Any]:
    """Extract selectors, text, routes, and hrefs from a source file."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"context file not found: {file_path}")
    text = file_path.read_text(encoding="utf-8", errors="replace")

    selectors: list[str] = []
    texts: list[str] = []
    routes: list[str] = []
    hrefs: list[str] = []

    for pattern, kind in SELECTOR_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).strip()
            selector = _selector_from_match(kind, raw)
            if kind == "text":
                if raw and raw not in texts:
                    texts.append(raw)
                continue
            if selector and selector not in selectors:
                selectors.append(selector)

    for pattern in TEXT_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            if value and value not in texts:
                texts.append(value)

    for pattern in ROUTE_PATTERNS:
        for match in pattern.finditer(text):
            route = match.group(1).strip()
            if route and route not in routes:
                routes.append(route)

    for match in HREF_PATTERN.finditer(text):
        href = match.group(1).strip()
        if href and href not in hrefs:
            hrefs.append(href)

    return {
        "source": str(file_path),
        "selectors": selectors,
        "texts": texts,
        "routes": routes,
        "hrefs": hrefs,
    }


def parse_spec(path: str | Path) -> list[dict[str, Any]]:
    """Extract interaction steps from Playwright/Cypress-style test files."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"spec file not found: {file_path}")
    text = file_path.read_text(encoding="utf-8", errors="replace")
    steps: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pattern, action, field in (*PLAYWRIGHT_STEP_PATTERNS, *CYPRESS_STEP_PATTERNS):
        for match in pattern.finditer(text):
            if isinstance(field, tuple):
                payload = {
                    key: _normalize_selector(match.group(index + 1).strip())
                    if key == "selector"
                    else match.group(index + 1).strip()
                    for index, key in enumerate(field)
                }
            elif field == "raw":
                payload = {"raw": match.group(0).strip()}
            elif field == "selector":
                payload = {field: _normalize_selector(match.group(1).strip())}
            else:
                payload = {field: match.group(1).strip()}
            key = json.dumps({"action": action, **payload}, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            steps.append({"action": action, **payload})

    return steps


def find_repo_context(repo: str | Path, url: str) -> list[str]:
    """Find likely component/test files near a repo path."""
    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"repo path is not a directory: {root}")

    candidates: list[Path] = []
    suffixes = {".tsx", ".jsx", ".ts", ".js", ".html", ".htm", ".vue", ".svelte"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if any(part in {"node_modules", ".git", "dist", "build", ".next", "coverage"} for part in path.parts):
            continue
        candidates.append(path)
        if len(candidates) >= 200:
            break

    scored: list[tuple[int, Path]] = []
    host = re.sub(r"^https?://", "", url.lower()).split("/")[0]
    for path in candidates:
        score = 0
        name = path.name.lower()
        if any(token in name for token in ("page", "component", "view", "screen", "layout")):
            score += 2
        if path.suffix.lower() in {".tsx", ".jsx"}:
            score += 1
        try:
            body = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if host and host in body:
            score += 3
        if "data-testid" in body:
            score += 2
        if score:
            scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return [str(path) for _, path in scored[:5]]


def build_interaction_plan(
    url: str,
    *,
    context: dict[str, Any] | None = None,
    spec_steps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Turn parsed code/spec hints into declarative verification steps."""
    steps: list[dict[str, Any]] = [{"action": "goto", "url": _normalize_url(url)}]
    seen: set[str] = set()

    def add(step: dict[str, Any]) -> None:
        key = json.dumps(step, sort_keys=True)
        if key not in seen:
            seen.add(key)
            steps.append(step)

    for item in spec_steps or []:
        action = item.get("action")
        if action == "goto" and item.get("url"):
            add({"action": "goto", "url": _normalize_url(str(item["url"]))})
        elif action == "click" and item.get("selector"):
            add({"action": "click", "selector": str(item["selector"])})
        elif action == "fill" and item.get("selector") is not None:
            add({"action": "fill", "selector": str(item["selector"]), "value": str(item.get("value", ""))})
        elif action == "click_text" and item.get("text"):
            add({"action": "click_text", "text": str(item["text"])})
        elif action == "click_role" and item.get("role") and item.get("name"):
            add({"action": "click_role", "role": str(item["role"]), "name": str(item["name"])})
        elif action in {"assert_visible", "assert_text_visible"}:
            if item.get("selector"):
                add({"action": "assert_visible", "selector": str(item["selector"])})
            if item.get("text"):
                add({"action": "assert_text", "text": str(item["text"])})

    ctx = context or {}
    for selector in ctx.get("selectors", []):
        add({"action": "assert_visible", "selector": str(selector)})
    for text in ctx.get("texts", []):
        add({"action": "assert_text", "text": str(text)})

    base = _normalize_url(url)
    origin = re.match(r"^(https?://[^/]+)", base)
    origin_prefix = origin.group(1) if origin else base.rstrip("/")
    for href in ctx.get("hrefs", []):
        if href.startswith(("http://", "https://")):
            target = href
        elif href.startswith("/"):
            target = origin_prefix + href
        else:
            continue
        add({"action": "assert_link", "href": target})

    if len(steps) == 1:
        add({"action": "screenshot", "name": "loaded.png"})
    else:
        add({"action": "screenshot", "name": "final.png"})
    return steps


def _context_label(context: dict[str, Any] | None, context_sources: list[str] | None = None) -> str:
    ctx = context or {}
    parts: list[str] = []
    if context_sources:
        parts.append("Sources: " + ", ".join(Path(source).name for source in context_sources[:3]))
    if ctx.get("selectors"):
        parts.append("Expected selectors: " + ", ".join(str(item) for item in ctx["selectors"][:12]))
    if ctx.get("texts"):
        parts.append("Expected text: " + ", ".join(str(item) for item in ctx["texts"][:12]))
    if ctx.get("routes"):
        parts.append("Routes: " + ", ".join(str(item) for item in ctx["routes"][:8]))
    if ctx.get("hrefs"):
        parts.append("Links: " + ", ".join(str(item) for item in ctx["hrefs"][:8]))
    return "\n".join(parts) if parts else "No parsed code context."


@contextmanager
def _vision_backend(backend: str | None) -> Iterator[None]:
    if not backend:
        yield
        return
    prev = os.environ.get("DESCRIBE_IMAGE_BACKEND")
    os.environ["DESCRIBE_IMAGE_BACKEND"] = backend.strip().lower()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("DESCRIBE_IMAGE_BACKEND", None)
        else:
            os.environ["DESCRIBE_IMAGE_BACKEND"] = prev


def _vision_backend_ready(name: str) -> bool:
    try:
        from arka.vision.describe import _backend_ready

        return _backend_ready(name)
    except ImportError:
        return False


def _default_vision_backend() -> str:
    raw = os.environ.get("DESCRIBE_IMAGE_BACKEND", "auto").strip().lower()
    if raw in {"vllm", "gemini", "ollama", "auto"}:
        return raw
    return "auto"


def vision_enabled(
    *,
    explicit: bool | None = None,
    vllm_verify: bool = False,
) -> bool:
    if explicit is False:
        return False
    if explicit is True or vllm_verify:
        return True
    env = os.environ.get("ARKA_WEB_VERIFY_VISION", "").strip().lower()
    if env in {"0", "false", "no", "off"}:
        return False
    if env in {"1", "true", "yes", "on"}:
        return True
    return False


def resolve_vision_backend(
    *,
    vision_backend: str | None = None,
    vllm_verify: bool = False,
) -> str | None:
    if vllm_verify:
        return "vllm"
    backend = (vision_backend or _default_vision_backend()).strip().lower()
    if backend not in {"vllm", "gemini", "ollama", "auto"}:
        raise ValueError("vision_backend must be vllm, gemini, ollama, or auto")
    return backend


def build_vision_verify_prompt(
    *,
    context: dict[str, Any] | None,
    context_sources: list[str] | None,
    step: dict[str, Any],
    page_title: str,
    current_url: str,
) -> str:
    context_block = _context_label(context, context_sources)
    step_block = json.dumps(step, sort_keys=True)
    return (
        "You are verifying a live website screenshot against local UI code expectations.\n"
        f"Page title: {page_title or 'unknown'}\n"
        f"Current URL: {current_url}\n"
        f"Verification step: {step_block}\n\n"
        "Code context:\n"
        f"{context_block}\n\n"
        "Check whether:\n"
        "- expected UI elements from the code context are visible\n"
        "- the interaction outcome matches the code/spec intent\n"
        "- there are no obvious errors, broken layout, or unreadable overlaps\n\n"
        "Reply with ONLY valid JSON:\n"
        '{"pass": true, "expected_elements_visible": ["..."], "missing_elements": ["..."], '
        '"interaction_outcome": "brief", "layout_issues": ["..."], "errors_visible": ["..."], '
        '"confidence": 0.0, "reason": "brief explanation"}'
    )


def parse_vision_verdict(raw: object) -> dict[str, Any]:
    data: dict[str, Any]
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw or "").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = VISION_JSON_RE.search(text)
            if not match:
                lowered = text.lower()
                passed = not re.search(
                    r"\b(?:fail|broken|missing|error|layout issue|not visible|does not match)\b",
                    lowered,
                )
                return {
                    "pass": passed,
                    "expected_elements_visible": [],
                    "missing_elements": [],
                    "interaction_outcome": text[:240],
                    "layout_issues": [],
                    "errors_visible": [],
                    "confidence": 0.4 if passed else 0.2,
                    "reason": text[:240] or "unstructured vision response",
                    "raw": text,
                }
            data = json.loads(match.group(0))

    passed = data.get("pass")
    if passed is None:
        verdict = str(data.get("verdict") or "").strip().lower()
        passed = verdict in {"good", "pass", "passed", "ok"}
    issues = data.get("layout_issues") or data.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    missing = data.get("missing_elements") or []
    if not isinstance(missing, list):
        missing = [str(missing)]
    errors_visible = data.get("errors_visible") or []
    if not isinstance(errors_visible, list):
        errors_visible = [str(errors_visible)]
    visible = data.get("expected_elements_visible") or []
    if not isinstance(visible, list):
        visible = [str(visible)]
    confidence_raw = data.get("confidence", 0.5)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 0.5
    if missing or errors_visible or issues:
        passed = False
    return {
        "pass": bool(passed),
        "expected_elements_visible": visible,
        "missing_elements": missing,
        "interaction_outcome": str(data.get("interaction_outcome") or "").strip(),
        "layout_issues": issues,
        "errors_visible": errors_visible,
        "confidence": confidence,
        "reason": str(data.get("reason") or data.get("summary") or "").strip(),
        "raw": data,
    }


def verify_screenshot_with_vision(
    screenshot: str,
    *,
    context: dict[str, Any] | None,
    context_sources: list[str] | None,
    step: dict[str, Any],
    page_title: str,
    current_url: str,
    vision_backend: str | None,
) -> dict[str, Any]:
    from arka.vision.describe import describe_source

    prompt = build_vision_verify_prompt(
        context=context,
        context_sources=context_sources,
        step=step,
        page_title=page_title,
        current_url=current_url,
    )
    with _vision_backend(vision_backend):
        raw = describe_source(screenshot, prompt)
    verdict = parse_vision_verdict(raw)
    verdict["screenshot"] = screenshot
    verdict["vision_backend"] = vision_backend or _default_vision_backend()
    return verdict


def run_vision_verification(
    *,
    screenshots: list[dict[str, Any]],
    context: dict[str, Any] | None,
    context_sources: list[str] | None,
    page_title: str,
    current_url: str,
    vision_backend: str | None,
) -> dict[str, Any]:
    if not screenshots:
        return {
            "enabled": False,
            "status": "skipped",
            "pass": True,
            "reason": "no screenshots captured",
            "checks": [],
            "vision_backend": vision_backend,
        }

    checks: list[dict[str, Any]] = []
    for item in screenshots:
        try:
            verdict = verify_screenshot_with_vision(
                item["path"],
                context=context,
                context_sources=context_sources,
                step=item.get("step", {"action": "screenshot"}),
                page_title=page_title,
                current_url=current_url,
                vision_backend=vision_backend,
            )
            checks.append({**item, **verdict})
        except Exception as exc:
            checks.append(
                {
                    **item,
                    "pass": False,
                    "status": "error",
                    "reason": str(exc),
                    "errors_visible": [str(exc)],
                    "layout_issues": [],
                    "missing_elements": [],
                    "expected_elements_visible": [],
                    "confidence": 0.0,
                }
            )

    failed = [row for row in checks if not row.get("pass")]
    return {
        "enabled": True,
        "status": "failed" if failed else "passed",
        "pass": not failed,
        "vision_backend": vision_backend or _default_vision_backend(),
        "checks": checks,
        "failed": len(failed),
        "total": len(checks),
    }


def _capture_step_screenshot(page: Any, target: Path, prefix: str) -> str:
    shot = screenshot_path(prefix, target)
    page.screenshot(path=str(shot), full_page=True)
    return str(shot.resolve())


def _step_screenshot_prefix(index: int, step: dict[str, Any]) -> str:
    action = str(step.get("action", "step"))
    suffix = action
    if step.get("selector"):
        suffix = f"{action}-{re.sub(r'[^a-z0-9]+', '-', str(step['selector']).lower())[:40]}"
    elif step.get("text"):
        suffix = f"{action}-{re.sub(r'[^a-z0-9]+', '-', str(step['text']).lower())[:40]}"
    return f"{index:02d}-{suffix}"


def verify(
    url: str,
    *,
    context_path: str | None = None,
    spec_path: str | None = None,
    repo: str | None = None,
    headless: bool = True,
    output: str | None = None,
    settle_seconds: float | None = None,
    vision: bool | None = None,
    vision_backend: str | None = None,
    vllm_verify: bool = False,
) -> dict[str, Any]:
    """Run code-informed interaction checks against a live URL."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Install browser checks with: pip install playwright && playwright install chromium"
        ) from exc

    parsed_context: dict[str, Any] = {"selectors": [], "texts": [], "routes": [], "hrefs": []}
    context_sources: list[str] = []
    if context_path:
        parsed = parse_code_context(context_path)
        parsed_context = parsed
        context_sources.append(parsed["source"])
    if repo:
        for candidate in find_repo_context(repo, url):
            extra = parse_code_context(candidate)
            context_sources.append(extra["source"])
            for key in ("selectors", "texts", "routes", "hrefs"):
                for value in extra.get(key, []):
                    if value not in parsed_context[key]:
                        parsed_context[key].append(value)

    spec_steps = parse_spec(spec_path) if spec_path else []
    steps = build_interaction_plan(url, context=parsed_context, spec_steps=spec_steps)

    target = Path(output).expanduser() if output else Path(tempfile.mkdtemp(prefix="arka-verify-web-"))
    if output is None:
        atexit.register(shutil.rmtree, target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    settle = float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "1.5")) if settle_seconds is None else settle_seconds
    if settle < 0 or settle > 60:
        raise ValueError("settle_seconds must be between 0 and 60")

    console_errors: list[str] = []
    network_failures: list[dict[str, Any]] = []
    step_results: list[dict[str, Any]] = []
    screenshots: list[str] = []
    vision_frames: list[dict[str, Any]] = []
    current_url = _normalize_url(url)
    page_title = ""
    http_status: int | None = None
    passed = True
    use_vision = vision_enabled(explicit=vision, vllm_verify=vllm_verify)
    resolved_backend = resolve_vision_backend(vision_backend=vision_backend, vllm_verify=vllm_verify) if use_vision else None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: network_failures.append(
                {"url": request.url, "method": request.method, "failure": request.failure or "unknown"}
            ),
        )

        for index, step in enumerate(steps, 1):
            action = step["action"]
            record: dict[str, Any] = {"step": index, "action": action, "status": "passed"}
            try:
                if action == "goto":
                    current_url = _normalize_url(str(step["url"]))
                    response = page.goto(current_url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(int(settle * 1000))
                    http_status = response.status if response else http_status
                    page_title = page.title()
                    record["url"] = current_url
                elif action == "click":
                    page.locator(str(step["selector"])).click(timeout=15_000)
                elif action == "fill":
                    page.locator(str(step["selector"])).fill(str(step.get("value", "")))
                elif action == "click_text":
                    page.get_by_text(str(step["text"]), exact=False).first.click(timeout=15_000)
                elif action == "click_role":
                    page.get_by_role(str(step["role"]), name=str(step["name"])).click(timeout=15_000)
                elif action == "assert_visible":
                    page.locator(str(step["selector"])).wait_for(state="visible", timeout=10_000)
                elif action == "assert_text":
                    page.get_by_text(str(step["text"]), exact=False).first.wait_for(state="visible", timeout=10_000)
                elif action == "assert_link":
                    page.locator(f'a[href="{step["href"]}"]').first.wait_for(state="attached", timeout=10_000)
                elif action == "screenshot":
                    name = str(step.get("name", f"step-{index}"))
                    stem = Path(name).stem if name.endswith(".png") else name
                    shot = screenshot_path(stem, target)
                    page.screenshot(path=str(shot), full_page=True)
                    shot_path = str(shot.resolve())
                    screenshots.append(shot_path)
                    record["screenshot"] = shot_path
                    vision_frames.append({"path": shot_path, "step": step, "index": index})
                else:
                    raise ValueError(f"unsupported action: {action}")
                if action != "screenshot":
                    shot_path = _capture_step_screenshot(page, target, _step_screenshot_prefix(index, step))
                    screenshots.append(shot_path)
                    record["screenshot"] = shot_path
                    vision_frames.append({"path": shot_path, "step": step, "index": index})
            except Exception as exc:
                passed = False
                record["status"] = "failed"
                record["error"] = str(exc)
                try:
                    shot_path = _capture_step_screenshot(page, target, f"failure-step-{index}")
                    record["screenshot"] = shot_path
                    screenshots.append(shot_path)
                    vision_frames.append({"path": shot_path, "step": step, "index": index, "failed": True})
                except Exception:
                    pass
            step_results.append(record)
            if record["status"] == "failed":
                break

        browser.close()

    if http_status is not None and http_status >= 400:
        passed = False
    if console_errors:
        passed = False

    vision_result: dict[str, Any] = {
        "enabled": use_vision,
        "status": "skipped",
        "pass": True,
        "vision_backend": resolved_backend,
        "checks": [],
    }
    if use_vision:
        unique_frames: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for frame in vision_frames:
            path = frame["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            unique_frames.append(frame)
        vision_result = run_vision_verification(
            screenshots=unique_frames,
            context=parsed_context,
            context_sources=context_sources,
            page_title=page_title,
            current_url=current_url,
            vision_backend=resolved_backend,
        )
        if vision_result.get("enabled") and not vision_result.get("pass", True):
            passed = False

    return {
        "ok": passed,
        "url": _normalize_url(url),
        "title": page_title,
        "status": http_status,
        "context_sources": context_sources,
        "parsed": parsed_context,
        "spec_steps": len(spec_steps),
        "plan_steps": len(steps),
        "steps": step_results,
        "console_errors": console_errors,
        "network_failures": network_failures[:20],
        "screenshots": screenshots,
        "vision": vision_result,
        "artifacts": str(target.resolve()),
        "headless": headless,
    }


def nl_to_argv(text: str) -> list[str]:
    """Map natural language to verify_web_interaction argv."""
    clean = text.strip()
    if not clean:
        return []
    low = clean.lower()
    argv: list[str] = ["check"]
    urls = re.findall(r"https?://[^\s]+", clean)
    files = re.findall(r"[\w./-]+\.(?:tsx?|jsx?|spec\.(?:ts|js)|html?)", clean)
    if urls:
        argv.append(urls[0])
    if files:
        for path in files:
            if "spec" in Path(path).name.lower():
                argv.extend(["--spec", path])
            else:
                argv.extend(["--context", path])
                break
    if re.search(r"(?i)\bheadless\b", low):
        argv.append("--headless")
    if re.search(r"(?i)\b(?:vllm|vision)\b", low):
        argv.append("--vllm-verify")
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_web_interaction",
        description="Verify live website interactions using local code or test spec context",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="Verify interactions on a URL")
    p_check.add_argument("url", help="Site URL to verify")
    p_check.add_argument("--context", help="Component/source file for selector and text hints")
    p_check.add_argument("--spec", help="Playwright/Cypress spec file to extract steps")
    p_check.add_argument("--repo", help="Repo path to auto-find related UI files")
    p_check.add_argument("--output", help="Artifact directory (temporary by default)")
    p_check.add_argument("--settle", type=float, help="Seconds to wait after page load")
    p_check.add_argument("--headless", action="store_true", help="Run headless (default for CI)")
    p_check.add_argument("--headed", action="store_true", help="Show the browser window")
    p_check.add_argument(
        "--vision-backend",
        choices=["vllm", "gemini", "ollama", "auto"],
        help="Vision backend for screenshot verification (default: DESCRIBE_IMAGE_BACKEND or auto)",
    )
    p_check.add_argument(
        "--vision",
        action="store_true",
        help="Enable vLLM/vision verification of captured screenshots",
    )
    p_check.add_argument(
        "--no-vision",
        action="store_true",
        help="Disable screenshot verification even when ARKA_WEB_VERIFY_VISION=1",
    )
    p_check.add_argument(
        "--vllm-verify",
        action="store_true",
        help="Enable vision verification using the vLLM backend (Qwen2-VL via describe_source)",
    )
    p_check.add_argument("--json", action="store_true")
    p_check.add_argument("--open-ui", action="store_true", help="Push report to Output Viewer")

    p_parse = sub.add_parser("parse", help="Parse code/spec context without running the browser")
    p_parse.add_argument("--context", help="Component/source file")
    p_parse.add_argument("--spec", help="Playwright/Cypress spec file")
    p_parse.add_argument("--repo", help="Repo path to auto-find related UI files")
    p_parse.add_argument("--url", default="http://127.0.0.1:3000", help="URL used when building a plan")
    p_parse.add_argument("--json", action="store_true")

    sub.add_parser("check-deps", help="Verify Playwright is available")
    return parser


def cmd_check_deps(_args: argparse.Namespace) -> int:
    from arka.core.output_layout import error, list_items, section, success

    issues: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        issues.append("playwright not installed (pip install playwright)")
    else:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                browser.close()
        except Exception as exc:
            issues.append(f"chromium launch failed: {exc}")
    ready: list[str] = []
    if vision_enabled():
        ready = [name for name in ("vllm", "gemini", "ollama") if _vision_backend_ready(name)]
        if not ready:
            issues.append("vision enabled but no describe backend ready (set DESCRIBE_IMAGE_BACKEND or VLLM_START_CMD)")
    section("Verify web interaction check")
    if issues:
        error("Dependencies missing")
        list_items(issues)
        return 1
    success("playwright available")
    if vision_enabled():
        success(f"vision verification available ({', '.join(ready)})")
    return 0


def _print_result(result: dict[str, Any], *, json_mode: bool, open_ui: bool) -> None:
    if json_mode:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    from arka.core.output_layout import error, info, push_to_viewer, result_box, success, table

    if result.get("ok"):
        success(f"Verified {result.get('url')}")
    else:
        error(f"Verification failed for {result.get('url')}")
    rows = [
        ("HTTP", str(result.get("status"))),
        ("Title", str(result.get("title") or "")),
        ("Steps", f"{sum(1 for s in result.get('steps', []) if s.get('status') == 'passed')}/{len(result.get('steps', []))}"),
        ("Console errors", str(len(result.get("console_errors", [])))),
        ("Network failures", str(len(result.get("network_failures", [])))),
    ]
    vision = result.get("vision") or {}
    if vision.get("enabled"):
        rows.append(("Vision", f"{vision.get('status')} ({vision.get('vision_backend')})"))
        rows.append(("Vision checks", f"{vision.get('total', 0) - vision.get('failed', 0)}/{vision.get('total', 0)}"))
    info(table(["Metric", "Value"], rows))
    failed = [step for step in result.get("steps", []) if step.get("status") != "passed"]
    if failed:
        result_box("Failed steps", json.dumps(failed, indent=2))
    if result.get("console_errors"):
        result_box("Console errors", "\n".join(result["console_errors"][:10]))
    if result.get("screenshots"):
        result_box("Screenshots", "\n".join(result["screenshots"]))
    if vision.get("enabled") and vision.get("checks"):
        failed_checks = [row for row in vision["checks"] if not row.get("pass")]
        if failed_checks:
            result_box("Vision failures", json.dumps(failed_checks, indent=2))
    if open_ui or os.environ.get("ARKA_OPEN_UI") == "1":
        push_to_viewer(json.dumps(result, indent=2))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        argv = ["--help"]
    if argv and argv[0] not in {"check", "parse", "check-deps", "-h", "--help"} and not argv[0].startswith("-"):
        if argv[0].startswith("http") or "://" in argv[0]:
            argv = ["check", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "check-deps":
        return cmd_check_deps(args)

    if args.cmd == "parse":
        context = parse_code_context(args.context) if args.context else {"selectors": [], "texts": [], "routes": [], "hrefs": []}
        sources = [context["source"]] if args.context else []
        if args.repo:
            for candidate in find_repo_context(args.repo, args.url):
                extra = parse_code_context(candidate)
                sources.append(extra["source"])
                for key in ("selectors", "texts", "routes", "hrefs"):
                    for value in extra.get(key, []):
                        if value not in context[key]:
                            context[key].append(value)
        spec_steps = parse_spec(args.spec) if args.spec else []
        plan = build_interaction_plan(args.url, context=context, spec_steps=spec_steps)
        payload = {"context_sources": sources, "parsed": context, "spec_steps": spec_steps, "plan": plan}
        print(json.dumps(payload if args.json else plan, indent=2))
        return 0

    if args.cmd == "check":
        headless = True
        if args.headed:
            headless = False
        elif args.headless:
            headless = True
        vision: bool | None
        if args.no_vision:
            vision = False
        elif args.vision or args.vllm_verify:
            vision = True
        else:
            vision = None
        try:
            result = verify(
                args.url,
                context_path=args.context,
                spec_path=args.spec,
                repo=args.repo,
                headless=headless,
                output=args.output,
                settle_seconds=args.settle,
                vision=vision,
                vision_backend=args.vision_backend,
                vllm_verify=args.vllm_verify,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        _print_result(result, json_mode=args.json, open_ui=args.open_ui)
        return 0 if result.get("ok") else 1

    parser.print_help()
    return 2
