#!/usr/bin/env python3
"""Generate video via Google Flow (browser) or Gemini Veo API fallback."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from arka.core.screenshot_paths import screenshot_path

DEFAULT_FLOW_URL = "https://labs.google/fx/tools/flow"
DEFAULT_GEMINI_MODEL = "veo-3.1-generate-preview"
ALLOWED_ASPECTS = {"16:9", "9:16", "1:1"}
DEFAULT_TIMEOUT = 600

_PROMPT_SELECTORS = (
    'textarea[placeholder*="Describe"]',
    'textarea[placeholder*="prompt"]',
    'textarea[aria-label*="prompt" i]',
    "textarea",
    '[contenteditable="true"]',
    '[role="textbox"]',
)
_GENERATE_SELECTORS = (
    'button:has-text("Generate")',
    'button:has-text("Create")',
    '[aria-label*="Generate" i]',
    '[data-testid*="generate" i]',
)
_FLOW_ENTRY_SELECTORS = (
    'button:has-text("Create with Google Flow")',
    'a:has-text("Create with Google Flow")',
    'button:has-text("Get started")',
    'a:has-text("Get started")',
    'button:has-text("Try Flow")',
    'a:has-text("Try Flow")',
    '[aria-label*="Create with Google Flow" i]',
    '[href*="/tools/flow/"]',
)


def _flow_url() -> str:
    return os.environ.get("GOOGLE_FLOW_URL", DEFAULT_FLOW_URL).strip() or DEFAULT_FLOW_URL


def _backend() -> str:
    return os.environ.get("GOOGLE_FLOW_BACKEND", "auto").strip().lower() or "auto"


def _gemini_key() -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "flow-video"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("GOOGLE_FLOW_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Videos" / "arka-google-flow"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp4"


def _setup_hint() -> str:
    return (
        "Google Flow video needs a backend:\n\n"
        "Option 1 — Gemini Veo API (same models as Flow, recommended):\n"
        "  1. Enable billing: https://aistudio.google.com/\n"
        "  2. Add to .env: GEMINI_API_KEY=...\n"
        "  3. Run: arka google_flow a cinematic drone shot over mountains\n\n"
        "Option 2 — Browser automation (Google sign-in required):\n"
        "  GOOGLE_FLOW_BACKEND=browser arka google_flow \"sunset over ocean\"\n"
        "  Optional: GOOGLE_FLOW_USER_DATA_DIR=~/.arka/google-flow-profile\n"
        "  Install: pip install playwright && playwright install chromium\n\n"
        "Option 3 — Open Flow UI manually:\n"
        "  arka google_flow open\n"
        "  or: arka google_flow \"prompt\" --backend open\n"
    )


def _headless() -> bool:
    return os.environ.get("GOOGLE_FLOW_HEADLESS", "0").strip().lower() in ("1", "true", "yes")


def _timeout() -> int:
    raw = os.environ.get("GOOGLE_FLOW_TIMEOUT", str(DEFAULT_TIMEOUT)).strip()
    try:
        return max(30, min(int(raw), 3600))
    except ValueError:
        return DEFAULT_TIMEOUT


def _user_data_dir() -> str:
    raw = os.environ.get("GOOGLE_FLOW_USER_DATA_DIR", "").strip()
    return str(Path(raw).expanduser()) if raw else ""


def _download_url(url: str, output: Path, timeout: int = 600) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "arka-google-flow/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("Empty download from Google Flow")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return output


def generate_gemini(
    prompt: str,
    output: Path,
    *,
    aspect: str,
    model: str,
    duration: int,
) -> Path:
    from arka.generate.video import generate_gemini as _generate_gemini

    print(f"  Gemini Veo ({model}) — Flow API fallback, may take 1–3 minutes …", file=sys.stderr)
    return _generate_gemini(prompt, output, aspect, model, duration)


def _has_prompt_field(page: Any) -> bool:
    for selector in _PROMPT_SELECTORS:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


def _is_sign_in_page(page: Any) -> bool:
    try:
        url = (page.url or "").lower()
        if "accounts.google.com" in url or "signin" in url:
            return True
        if page.locator('input[type="email"]').count() > 0:
            return True
        if page.get_by_text("Sign in", exact=False).count() > 0 and page.get_by_text(
            "AI Test Kitchen", exact=False
        ).count() > 0:
            return True
    except Exception:
        return False
    return False


def _wait_for_flow_editor(page: Any, *, timeout: int) -> bool:
    """Wait for sign-in + editor load; return True when prompt field appears."""
    deadline = time.time() + timeout
    prompted = False
    while time.time() < deadline:
        if _has_prompt_field(page):
            return True
        if _is_sign_in_page(page) and not prompted:
            print(
                "  Google sign-in required — complete login in the Chromium window "
                f"(up to {timeout}s) …",
                file=sys.stderr,
            )
            prompted = True
        elif not _is_sign_in_page(page):
            _try_open_flow_editor(page)
        page.wait_for_timeout(3000)
    return False


def _try_open_flow_editor(page: Any) -> bool:
    """Leave the marketing landing page and open the Flow editor when possible."""
    for selector in _FLOW_ENTRY_SELECTORS:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=8000)
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    return False


def _try_fill_prompt(page: Any, prompt: str) -> bool:
    for selector in _PROMPT_SELECTORS:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        target = locator.first
        try:
            target.click(timeout=5000)
            target.fill(prompt, timeout=5000)
            return True
        except Exception:
            try:
                target.click(timeout=5000)
                page.keyboard.type(prompt, delay=10)
                return True
            except Exception:
                continue
    return False


def _try_click_generate(page: Any) -> bool:
    for selector in _GENERATE_SELECTORS:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def _wait_for_video_url(page: Any, timeout: int) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for selector in ("video[src]", "video source[src]", 'a[download][href*=".mp4"]', 'a[href*=".mp4"]'):
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                href = locator.first.get_attribute("src") or locator.first.get_attribute("href")
                if href and href.startswith(("http", "blob:")):
                    return href
            except Exception:
                continue
        page.wait_for_timeout(3000)
        print("  … waiting for Flow video output", file=sys.stderr)
    return None


def generate_browser(
    prompt: str,
    output: Path,
    *,
    headless: bool,
    timeout: int,
    user_data_dir: str,
    artifacts_dir: Path,
) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser backend needs Playwright: pip install playwright && playwright install chromium"
        ) from exc

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    url = _flow_url()
    profile = user_data_dir or str(Path.home() / ".arka" / "google-flow-profile")
    Path(profile).mkdir(parents=True, exist_ok=True)
    print(f"  Google Flow browser — opening {url}", file=sys.stderr)
    print(f"  Profile: {profile} (sign in once if prompted)", file=sys.stderr)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile,
            headless=headless,
            accept_downloads=True,
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(int(float(os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", "3")) * 1000))

            _try_open_flow_editor(page)
            wait_budget = timeout if not headless else min(timeout, 120)
            if not _wait_for_flow_editor(page, timeout=wait_budget):
                shot = screenshot_path("prompt-field-missing", artifacts_dir)
                page.screenshot(path=str(shot), full_page=True)
                raise RuntimeError(
                    f"Could not reach Flow editor — sign in at {url} "
                    f"(screenshot: {shot}). Profile: {profile}"
                )

            if not _try_fill_prompt(page, prompt):
                shot = screenshot_path("prompt-field-missing", artifacts_dir)
                page.screenshot(path=str(shot), full_page=True)
                raise RuntimeError(
                    f"Could not find Flow prompt field — sign in at {url} "
                    f"(screenshot: {shot}). Profile: {profile}"
                )

            filled = screenshot_path("prompt-filled", artifacts_dir)
            page.screenshot(path=str(filled), full_page=True)
            clicked = _try_click_generate(page)
            if clicked:
                print("  Clicked Generate — waiting for video …", file=sys.stderr)
            else:
                print("  Could not click Generate — complete generation in the browser window", file=sys.stderr)

            video_url = _wait_for_video_url(page, timeout if clicked else min(timeout, 120))
            if video_url and video_url.startswith("http"):
                print(f"  Downloading video from Flow …", file=sys.stderr)
                return _download_url(video_url, output, timeout=min(timeout, 600))

            shot = screenshot_path("awaiting-download", artifacts_dir)
            page.screenshot(path=str(shot), full_page=True)
            if not headless:
                print(
                    f"  Flow is open — finish generation and download manually. Screenshot: {shot}",
                    file=sys.stderr,
                )
                page.wait_for_timeout(min(timeout, 300) * 1000)
                video_url = _wait_for_video_url(page, 60)
                if video_url and video_url.startswith("http"):
                    return _download_url(video_url, output, timeout=120)

            raise RuntimeError(
                f"Flow did not produce a downloadable video within {timeout}s "
                f"(screenshot: {shot}). Try GOOGLE_FLOW_BACKEND=gemini with GEMINI_API_KEY."
            )
        finally:
            context.close()


def open_flow(*, prompt: str = "") -> dict[str, str]:
    url = _flow_url()
    print(f"Opening Google Flow: {url}", file=sys.stderr)
    if sys.platform == "darwin":
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(url)
    result = {"flow_url": url, "mode": "open"}
    if prompt:
        result["prompt"] = prompt
        print(f"Paste this prompt in Flow:\n{prompt}", file=sys.stderr)
    return result


def generate(
    prompt: str,
    output: Path,
    *,
    aspect: str = "16:9",
    model: str | None = None,
    duration: int = 8,
    backend: str | None = None,
) -> tuple[Path | dict[str, str], str]:
    chosen = (backend or _backend()).strip().lower() or "auto"
    veo_model = model or os.environ.get("GOOGLE_FLOW_VEO_MODEL", os.environ.get("VIDEO_MODEL", DEFAULT_GEMINI_MODEL))
    errors: list[str] = []

    def _try(name: str, fn) -> tuple[Path | dict[str, str], str] | None:
        try:
            return fn(), name
        except SystemExit:
            raise
        except Exception as exc:
            errors.append(f"{name}: {str(exc)[:240]}")
            return None

    if chosen == "open":
        return open_flow(prompt=prompt), "open"

    if chosen == "gemini":
        if not _gemini_key():
            raise SystemExit(_setup_hint())
        result = _try(
            "gemini",
            lambda: generate_gemini(prompt, output, aspect=aspect, model=veo_model, duration=duration),
        )
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Gemini video generation failed")

    if chosen == "browser":
        result = _try(
            "browser",
            lambda: generate_browser(
                prompt,
                output,
                headless=_headless(),
                timeout=_timeout(),
                user_data_dir=_user_data_dir(),
                artifacts_dir=output.parent / f"{output.stem}-flow-artifacts",
            ),
        )
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Google Flow browser automation failed")

    # auto: prefer Gemini when keyed, else browser
    if _gemini_key():
        result = _try(
            "gemini",
            lambda: generate_gemini(prompt, output, aspect=aspect, model=veo_model, duration=duration),
        )
        if result:
            return result

    result = _try(
        "browser",
        lambda: generate_browser(
            prompt,
            output,
            headless=_headless(),
            timeout=_timeout(),
            user_data_dir=_user_data_dir(),
            artifacts_dir=output.parent / f"{output.stem}-flow-artifacts",
        ),
    )
    if result:
        return result

    if not _gemini_key():
        raise SystemExit(_setup_hint())
    detail = "\n".join(f"  • {e}" for e in errors if e)
    raise SystemExit(f"All Google Flow backends failed.\n{detail}\n\n{_setup_hint()}")


def google_flow_result(
    prompt: str,
    *,
    output: str | Path | None = None,
    aspect: str = "16:9",
    model: str | None = None,
    duration: int | None = None,
    backend: str | None = None,
) -> dict[str, object]:
    dur = min(max(duration or int(os.environ.get("GOOGLE_FLOW_DURATION", os.environ.get("VIDEO_DURATION", "8"))), 4), 8)
    out = Path(output).expanduser() if output else _default_output(prompt)
    saved, provider = generate(
        prompt,
        out,
        aspect=aspect,
        model=model,
        duration=dur,
        backend=backend,
    )
    if isinstance(saved, dict):
        return {"prompt": prompt, "provider": provider, **saved}
    return {
        "prompt": prompt,
        "output": str(saved),
        "provider": provider,
        "aspect": aspect,
        "duration": dur,
        "model": model or os.environ.get("GOOGLE_FLOW_VEO_MODEL", DEFAULT_GEMINI_MODEL),
        "flow_url": _flow_url(),
    }


def _is_google_flow_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(r"(?i)\bgoogle\s+flow\b", t):
        return True
    if re.search(r"(?i)\bflow\.google\b", t):
        return True
    if re.search(r"(?i)\blabs\.google(?:/fx)?/tools/flow\b", t):
        return True
    if re.search(
        r"(?i)\b(?:create|make|generate|produce)\b.*\b(?:video|movie|clip|film|scene)\b.*\b(?:in|with|using|via|on)\s+(?:google\s+)?flow\b",
        t,
    ):
        return True
    if re.search(
        r"(?i)\b(?:use|try|open)\s+(?:google\s+)?flow\b.*\b(?:to\s+)?(?:create|make|generate|produce)\b",
        t,
    ):
        return True
    return False


def _extract_prompt(text: str) -> str:
    t = text.strip()
    t = re.sub(r"(?i)^(?:arka\s+)?google[_-]?flow\s+", "", t)
    t = re.sub(r"(?i)^(?:use|try|open)\s+(?:google\s+)?flow\s+(?:to\s+)?(?:create|make|generate|produce)\s+", "", t)
    t = re.sub(
        r"(?i)^(?:create|make|generate|produce)\s+(?:a\s+)?(?:video|movie|clip|film|scene)\s+(?:in|with|using|via|on)\s+(?:google\s+)?flow\s+(?:of|about|for)?\s*",
        "",
        t,
    )
    t = re.sub(r"(?i)\b(?:in|with|using|via|on)\s+(?:google\s+)?flow\b", "", t)
    t = re.sub(r"(?i)\bgoogle\s+flow\b", "", t)
    t = re.sub(r"(?i)^(?:a\s+)?(?:video|movie|clip|film|scene)\s+", "", t.strip())
    t = re.sub(r"(?i)\b(?:for|-d|--duration)\s+\d+\s*(?:seconds?|secs?|s)?\b", "", t)
    t = re.sub(r"(?i)\b(?:aspect|-a|--aspect)\s+(?:16:9|9:16|1:1)\b", "", t)
    t = re.sub(r"(?i)\b(?:backend|--backend)\s+\w+\b", "", t)
    t = re.sub(r"\s+--\s*$", "", t)
    t = re.sub(r"(?i)^(?:of|about|for)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if t.lower() in {"google flow", "open google flow", "open flow"}:
        return ["open"]
    if not _is_google_flow_request(t):
        return []

    argv: list[str] = []
    if re.search(r"(?i)\bopen\b.*\b(?:google\s+)?flow\b", t) and not re.search(
        r"(?i)\b(?:create|make|generate|produce)\b", t
    ):
        return ["open"]

    dur = re.search(r"(?i)\b(?:for|-d|--duration)\s+(\d+)\s*(?:seconds?|secs?|s)?\b", t)
    if dur:
        argv.extend(["-d", dur.group(1)])

    aspect = re.search(r"(?i)\b(?:aspect|-a|--aspect)\s+(16:9|9:16|1:1)\b", t)
    if aspect:
        argv.extend(["-a", aspect.group(1)])

    backend = re.search(r"(?i)\b(?:backend|--backend)\s+(auto|browser|gemini|open)\b", t)
    if backend:
        argv.extend(["--backend", backend.group(1).lower()])

    prompt = _extract_prompt(t)
    if prompt:
        argv.append(prompt)
    elif not argv:
        return []
    return argv


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_open(_args: argparse.Namespace) -> int:
    payload = open_flow()
    print(json.dumps(payload, indent=2))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    aspect = args.aspect if args.aspect in ALLOWED_ASPECTS else "16:9"
    duration = min(max(args.duration, 4), 8)
    out = Path(args.output) if args.output else _default_output(args.prompt)

    print(f"Google Flow ({args.backend or _backend()}, {aspect}, {duration}s) …")
    try:
        saved, provider = generate(
            args.prompt,
            out,
            aspect=aspect,
            model=args.model,
            duration=duration,
            backend=args.backend,
        )
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if isinstance(saved, dict):
        print(json.dumps(saved, indent=2))
        return 0

    print(f"Saved ({provider}): {saved}")
    if os.environ.get("OPEN_VIDEO", "1") not in ("0", "false"):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    backend = _backend()
    print(f"GOOGLE_FLOW_BACKEND (effective default): {backend}")
    print(f"  GOOGLE_FLOW_URL: {_flow_url()}")
    if _gemini_key():
        print("  GEMINI_API_KEY: set (gemini backend available)")
    else:
        print("  GEMINI_API_KEY: not set")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        print("  playwright: installed")
    except ImportError:
        print("  playwright: not installed (needed for browser backend)")
    print(f"  GOOGLE_FLOW_HEADLESS: {_headless()}")
    print(f"  GOOGLE_FLOW_USER_DATA_DIR: {_user_data_dir() or '(none)'}")
    print(f"  GOOGLE_FLOW_VEO_MODEL: {os.environ.get('GOOGLE_FLOW_VEO_MODEL', DEFAULT_GEMINI_MODEL)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create video with Google Flow (browser) or Gemini Veo fallback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  google_flow cinematic drone shot over mountains at sunset\n"
            "  google_flow open\n"
            "  google_flow \"ocean waves\" --backend browser\n"
            "  google_flow check\n"
        ),
    )
    sub = p.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="Generate a video from a text prompt")
    p_gen.add_argument("prompt", help="Video description")
    p_gen.add_argument("-o", "--output", help="Output .mp4 path")
    p_gen.add_argument("-a", "--aspect", default=os.environ.get("GOOGLE_FLOW_ASPECT", "16:9"))
    p_gen.add_argument("-d", "--duration", type=int, default=int(os.environ.get("GOOGLE_FLOW_DURATION", "8")))
    p_gen.add_argument("-m", "--model", default=os.environ.get("GOOGLE_FLOW_VEO_MODEL", DEFAULT_GEMINI_MODEL))
    p_gen.add_argument(
        "--backend",
        choices=["auto", "browser", "gemini", "open"],
        default=None,
        help="auto | browser (Playwright) | gemini (Veo API) | open (UI only)",
    )
    p_gen.set_defaults(func=cmd_generate)

    p_open = sub.add_parser("open", help="Open Google Flow in the default browser")
    p_open.set_defaults(func=cmd_open)

    p_parse = sub.add_parser("parse", help="Parse natural language → google_flow args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify backends and dependencies")
    p_check.set_defaults(func=cmd_check)

    return p


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        build_parser().print_help()
        return 0
    if args in (["-h"], ["--help"]):
        build_parser().parse_args(["generate", "--help"])
        return 0
    if args[0] == "parse":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] == "check":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] == "open":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] not in {"generate", "-h", "--help"}:
        args = ["generate", *args]
    try:
        ns = build_parser().parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(ns, "cmd", None):
        build_parser().print_help()
        return 0
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
