#!/usr/bin/env python3
"""Obtain a Pollinations API key via Selenium and save it to Arka .env.

Opens https://enter.pollinations.ai/keys in Brave using a dedicated isolated
profile (not your default Brave/Chrome profile). Login, captcha, and email
verification may require manual steps — the script pauses until you press Enter.

Browser launch follows the linkedin_connection_bot pattern: Brave is started
via subprocess with --remote-debugging-port, then Selenium attaches via
debuggerAddress (avoids macOS Mach rendezvous / chromedriver spawn failures).

Requires: pip install selenium webdriver-manager

Launch (from Arka checkout root):
  python3 scripts/pollinations_api_key_selenium.py
  arka ai_video setup-pollinations
  arka ai_video setup-pollinations --create

Options:
  BRAVE_BINARY=/path/to/Brave python3 scripts/pollinations_api_key_selenium.py
  python3 scripts/pollinations_api_key_selenium.py --create   # create a new secret key
  python3 scripts/pollinations_api_key_selenium.py --headless # headless (login usually needs visible browser)

Profile: ~/.arka/pollinations-brave-profile (override with --profile or POLLINATIONS_BRAVE_PROFILE)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

POLLINATIONS_KEYS_URL = "https://enter.pollinations.ai/keys"
POLLINATIONS_HOME_URL = "https://enter.pollinations.ai/"
DEFAULT_BRAVE_PROFILE = Path.home() / ".arka" / "pollinations-brave-profile"
KEY_RE = re.compile(r"\b((?:pk|sk)_[A-Za-z0-9_-]{16,})\b")

# Prefer server-side secret keys; pk_ publishable keys still work for Arka backends.
KEY_PRIORITY = ("sk_", "pk_")

# LinkedIn bot pattern: launch browser via subprocess + attach Selenium on debug port.
DEBUG_PORT_RANGE = (9332, 9432)
PROFILE_DIRECTORY = "Default"
MAX_DRIVER_AUTO_FIX_ATTEMPTS = 2
DRIVER_MISMATCH_MARKERS = (
    "this version of chromedriver only supports chrome version",
    "current browser version is",
    "chromedriver version",
    "version mismatch",
)
CHROMIUM_UPDATE_SUPPRESSION_ARGS = (
    "--disable-component-update",
    "--disable-features=AutofillServerCommunication,OptimizationHints",
)

_browser_process: subprocess.Popen | None = None
_browser_debug_port: int | None = None


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _mask_key(key: str) -> str:
    key = key.strip()
    if len(key) <= 8:
        return "pk_…"
    return f"{key[:3]}…{key[-4:]}"


def _target_env_path() -> Path:
    from arka.paths import checkout_root, env_file

    root = checkout_root()
    if root and (root / ".env").is_file():
        return root / ".env"
    if root:
        return root / ".env"
    return env_file()


def _write_env_key(key: str) -> Path:
    """Update POLLINATIONS_API_KEY in the target .env (no duplicates)."""
    path = _target_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            kept.append(line)
            continue
        env_key = stripped.split("=", 1)[0].strip()
        if env_key in {"POLLINATIONS_API_KEY", "POLLINATIONS_KEY"}:
            continue
        kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()
    kept.append(f"POLLINATIONS_API_KEY={key}")

    text = "\n".join(kept)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")
    os.environ["POLLINATIONS_API_KEY"] = key
    return path


def _pick_best_key(keys: list[str]) -> str | None:
    seen: set[str] = set()
    unique = []
    for key in keys:
        key = key.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    for prefix in KEY_PRIORITY:
        for key in unique:
            if key.startswith(prefix):
                return key
    return unique[0] if unique else None


def _extract_keys_from_page(driver) -> list[str]:
    keys: list[str] = []
    try:
        page = driver.page_source or ""
    except Exception:
        page = ""
    keys.extend(KEY_RE.findall(page))

    for element in driver.find_elements("css selector", "input[type='text'], code, pre, span, div"):
        try:
            for attr in ("value", "textContent", "innerText"):
                raw = element.get_attribute(attr) if attr != "textContent" else element.text
                if raw:
                    keys.extend(KEY_RE.findall(raw))
        except Exception:
            continue
    return keys


def _needs_login(driver) -> bool:
    url = (driver.current_url or "").lower()
    if any(token in url for token in ("/login", "/signin", "/sign-in", "/auth")):
        return True
    body = (driver.page_source or "").lower()
    login_markers = (
        "sign in with github",
        "sign in with google",
        "continue with github",
        "log in",
        "sign up",
    )
    if any(marker in body for marker in login_markers) and "/keys" not in url:
        return True
    return False


def _wait_for_keys_page(driver, *, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = driver.current_url or ""
        if "/keys" in url and not _needs_login(driver):
            return
        time.sleep(1.0)
    raise TimeoutError(
        f"Timed out waiting for Pollinations keys page ({POLLINATIONS_KEYS_URL}). "
        "Complete login/signup in the browser, then press Enter."
    )


def _click_create_secret_key(driver) -> bool:
    xpaths = (
        "//button[contains(., 'API Key')]",
        "//button[contains(., 'Create') and contains(., 'Key')]",
        "//*[self::button or self::a][contains(., '🔑')]",
    )
    for xpath in xpaths:
        try:
            buttons = driver.find_elements("xpath", xpath)
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                label = (btn.text or "").strip()
                if "App Key" in label:
                    continue
                btn.click()
                time.sleep(1.5)
                return True
        except Exception:
            continue
    return False


def _submit_create_dialog(driver) -> bool:
    submit_xpaths = (
        "//button[contains(., 'Create')]",
        "//button[@type='submit']",
    )
    for xpath in submit_xpaths:
        try:
            for btn in driver.find_elements("xpath", xpath):
                if not btn.is_displayed():
                    continue
                label = (btn.text or "").lower()
                if "cancel" in label or "delete" in label:
                    continue
                btn.click()
                time.sleep(2.0)
                return True
        except Exception:
            continue
    return False


def _create_secret_key(driver) -> str | None:
    if not _click_create_secret_key(driver):
        _log("Could not find 'Create API Key' button — create one manually in the browser.")
        return None
    _submit_create_dialog(driver)
    for _ in range(20):
        keys = _extract_keys_from_page(driver)
        created = _pick_best_key([k for k in keys if k.startswith("sk_")])
        if created:
            return created
        time.sleep(0.5)
    return None


def _default_profile_dir() -> str:
    for env_key in ("POLLINATIONS_BRAVE_PROFILE", "BRAVE_USER_DATA_DIR"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return str(Path(val).expanduser())
    return str(DEFAULT_BRAVE_PROFILE)


def _find_brave_binary() -> str | None:
    env = os.environ.get("BRAVE_BINARY", "").strip()
    if env and Path(env).is_file():
        return env
    candidates = [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        str(Path.home() / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/snap/bin/brave",
        "/opt/brave.com/brave/brave-browser",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    from shutil import which

    for name in ("brave-browser", "brave"):
        found = which(name)
        if found:
            return found
    return None


def _find_chromium_fallback() -> str | None:
    """Optional fallback when Brave is not installed (Chrome, Chromium, Playwright)."""
    env = os.environ.get("CHROME_BINARY", "").strip()
    if env and Path(env).is_file():
        return env
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    from shutil import which

    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = which(name)
        if found:
            return found
    pw_cache = Path.home() / "Library/Caches/ms-playwright"
    if pw_cache.is_dir():
        rel_bins = (
            "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
            "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        )
        for chromium_root in sorted(pw_cache.glob("chromium-*"), reverse=True):
            for rel in rel_bins:
                exe = chromium_root / rel
                if exe.is_file():
                    return str(exe)
    return None


def _browser_major_version(binary: str) -> str | None:
    import subprocess

    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        match = re.search(r"\b(\d+)\.", text)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def _browser_full_version(binary: str) -> str | None:
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        match = re.search(r"(\d+\.\d+\.\d+\.\d+|\d+\.\d+\.\d+|\d+\.\d+|\d+)", text)
        return match.group(1) if match else None
    except Exception:
        return None


def _selenium_cache_arch() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    if sys.platform.startswith("linux"):
        return "linux64"
    return "win64"


def _find_cached_chromedriver(major_version: str) -> str | None:
    cache_root = Path.home() / ".cache" / "selenium" / "chromedriver" / _selenium_cache_arch()
    if not cache_root.is_dir():
        return None
    candidates: list[tuple[str, str]] = []
    for entry in cache_root.iterdir():
        if not entry.name.startswith(f"{major_version}."):
            continue
        driver_path = entry / "chromedriver"
        if driver_path.is_file() and os.access(driver_path, os.X_OK):
            candidates.append((entry.name, str(driver_path)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _resolve_chrome_type(browser_binary: str):
    from webdriver_manager.core.os_manager import ChromeType

    name = Path(browser_binary).name.lower()
    if "brave" in name:
        return ChromeType.BRAVE
    if "edge" in name or "microsoft" in name:
        return ChromeType.MSEDGE
    if "chromium" in name:
        return ChromeType.CHROMIUM
    return ChromeType.GOOGLE


def _resolve_chromedriver_path(browser_binary: str, *, force_refresh: bool = False) -> str:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

    major = _browser_major_version(browser_binary)
    full = _browser_full_version(browser_binary)
    if not major:
        raise RuntimeError(f"Could not detect browser version for {browser_binary}")

    if not force_refresh:
        cached = _find_cached_chromedriver(major)
        if cached:
            return cached

    chrome_type = _resolve_chrome_type(browser_binary)
    errors: list[str] = []
    try:
        path = ChromeDriverManager(chrome_type=chrome_type, driver_version=major).install()
        if path and Path(path).is_file():
            return path
    except Exception as exc:
        errors.append(str(exc))

    try:
        options = Options()
        options.binary_location = browser_binary
        if full:
            options.browser_version = full
        driver = webdriver.Chrome(options=options)
        try:
            service = getattr(driver, "service", None)
            path = getattr(service, "path", None) if service else None
            if path and Path(path).is_file():
                return path
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception as exc:
        errors.append(str(exc))

    cached = _find_cached_chromedriver(major)
    if cached:
        return cached
    detail = "; ".join(errors[:2]) if errors else "no download source succeeded"
    raise RuntimeError(f"Could not resolve chromedriver for browser {full or major}: {detail}")


def _is_driver_mismatch_error(error: BaseException) -> bool:
    message = str(error).lower()
    if not any(marker in message for marker in DRIVER_MISMATCH_MARKERS):
        return False
    return "chromedriver" in message or "browser version" in message


def _find_free_port(start: int = DEBUG_PORT_RANGE[0], end: int = DEBUG_PORT_RANGE[1]) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free browser debug port found.")


def _wait_for_debug_port(port: int, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                json.load(response)
                return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.5)
    raise TimeoutError(f"Browser did not start on debug port {port}.")


def _remove_stale_profile_locks(profile_dir: str) -> None:
    lock_names = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    if os.name == "nt":
        lock_names.append("lockfile")
    for lock_name in lock_names:
        lock_path = Path(profile_dir) / lock_name
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass


def _launch_browser_process(
    browser_binary: str,
    port: int,
    profile_dir: str,
    *,
    headless: bool,
) -> subprocess.Popen:
    profile = str(Path(profile_dir).expanduser())
    Path(profile).mkdir(parents=True, exist_ok=True)
    args = [
        browser_binary,
        f"--user-data-dir={profile}",
        f"--profile-directory={PROFILE_DIRECTORY}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ]
    if headless:
        args.extend(["--headless=new", "--disable-gpu", "--window-size=1280,900"])
    else:
        args.append("--start-maximized")
    for flag in CHROMIUM_UPDATE_SUPPRESSION_ARGS:
        if flag not in args:
            args.append(flag)
    args.append("about:blank")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _connect_via_debug_port(port: int, browser_binary: str, *, force_refresh: bool = False):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service as ChromeService

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    options.binary_location = browser_binary
    version = _browser_full_version(browser_binary)
    if version:
        options.browser_version = version
    service = ChromeService(
        executable_path=_resolve_chromedriver_path(browser_binary, force_refresh=force_refresh)
    )
    return webdriver.Chrome(service=service, options=options)


def _terminate_browser_process() -> None:
    global _browser_process, _browser_debug_port
    proc = _browser_process
    _browser_process = None
    _browser_debug_port = None
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _launch_chromium_browser(
    browser_binary: str,
    profile_dir: str,
    *,
    headless: bool,
    force_driver_refresh: bool = False,
):
    global _browser_process, _browser_debug_port
    port = _find_free_port()
    _browser_debug_port = port
    _browser_process = _launch_browser_process(
        browser_binary, port, profile_dir, headless=headless
    )
    _wait_for_debug_port(port)
    driver = _connect_via_debug_port(
        port, browser_binary, force_refresh=force_driver_refresh
    )
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
    except Exception:
        pass
    return driver


def _resolve_browser_binary() -> str:
    brave_binary = _find_brave_binary()
    if brave_binary:
        _log(f"Using Brave: {brave_binary}")
        return brave_binary
    fallback = _find_chromium_fallback()
    if fallback:
        _log(f"Brave not found; using Chromium fallback: {fallback}")
        return fallback
    raise RuntimeError(
        "No Chromium-based browser found. Install Brave (https://brave.com) "
        "and set BRAVE_BINARY if needed, or set CHROME_BINARY for a Chromium fallback."
    )


def _build_driver(*, headless: bool, profile_dir: str):
    try:
        from selenium.common.exceptions import WebDriverException
    except ImportError as exc:
        raise RuntimeError(
            "Selenium not installed. Run: pip install selenium webdriver-manager"
        ) from exc

    browser_binary = _resolve_browser_binary()
    profile = str(Path(profile_dir or _default_profile_dir()).expanduser())
    Path(profile).mkdir(parents=True, exist_ok=True)
    _remove_stale_profile_locks(profile)

    mode = "headless" if headless else "headful"
    _log(f"Launching browser ({mode}, isolated profile: {profile})")

    last_error: BaseException | None = None
    driver_auto_fix_attempts = 0
    force_driver_refresh = False

    for attempt in range(3):
        try:
            return _launch_chromium_browser(
                browser_binary,
                profile,
                headless=headless,
                force_driver_refresh=force_driver_refresh,
            )
        except (WebDriverException, TimeoutError, RuntimeError, OSError) as exc:
            last_error = exc
            _terminate_browser_process()
            if (
                _is_driver_mismatch_error(exc)
                and driver_auto_fix_attempts < MAX_DRIVER_AUTO_FIX_ATTEMPTS
            ):
                driver_auto_fix_attempts += 1
                _log(
                    f"Chromedriver mismatch — auto-fixing for browser "
                    f"{_browser_full_version(browser_binary) or 'unknown'} …"
                )
                _resolve_chromedriver_path(browser_binary, force_refresh=True)
                _remove_stale_profile_locks(profile)
                force_driver_refresh = True
                time.sleep(2)
                continue
            time.sleep(2)

    raise RuntimeError(f"Failed to start browser: {last_error}") from last_error


def obtain_key(*, create: bool = False, headless: bool = False, profile_dir: str = "") -> str:
    driver = _build_driver(headless=headless, profile_dir=profile_dir)
    try:
        _log(f"Opening {POLLINATIONS_KEYS_URL}")
        driver.get(POLLINATIONS_KEYS_URL)
        time.sleep(2.0)

        if _needs_login(driver):
            _log("")
            _log("Sign in at enter.pollinations.ai (GitHub/Google). Captcha/email may be required.")
            _log("When you reach the API keys page, press Enter here to continue …")
            input()

        driver.get(POLLINATIONS_KEYS_URL)
        _wait_for_keys_page(driver)

        keys = _extract_keys_from_page(driver)
        chosen = _pick_best_key(keys)

        if create or not chosen:
            _log("Looking for an existing key or creating a new secret key …")
            created = _create_secret_key(driver)
            if created:
                chosen = created
            else:
                keys = _extract_keys_from_page(driver)
                chosen = _pick_best_key(keys)

        if not chosen:
            _log("")
            _log("No API key found on the page.")
            _log("Create a secret key manually (🔑 + API Key), copy it, then press Enter …")
            input()
            keys = _extract_keys_from_page(driver)
            chosen = _pick_best_key(keys)

        if not chosen:
            raise RuntimeError(
                "Could not detect a Pollinations API key (pk_ or sk_). "
                f"Open {POLLINATIONS_KEYS_URL} and create one manually."
            )
        return chosen
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        _terminate_browser_process()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Pollinations API key via Selenium")
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create a new secret API key if none is visible",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Brave headless (not recommended — login usually needs a visible browser)",
    )
    parser.add_argument(
        "--profile",
        default=_default_profile_dir(),
        help=(
            "Brave user-data-dir (isolated profile; default: ~/.arka/pollinations-brave-profile). "
            "Override with POLLINATIONS_BRAVE_PROFILE or BRAVE_USER_DATA_DIR."
        ),
    )
    args = parser.parse_args(argv)

    try:
        key = obtain_key(create=args.create, headless=args.headless, profile_dir=args.profile)
    except RuntimeError as exc:
        _log(f"Error: {exc}")
        return 1

    env_path = _write_env_key(key)
    _log(f"Saved POLLINATIONS_API_KEY={_mask_key(key)} → {env_path}")
    _log("Verify: python -m arka.media.ai_video check")
    print(_mask_key(key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
