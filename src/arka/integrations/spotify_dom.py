#!/usr/bin/env python3
"""Spotify web DOM control via Playwright (play/pause/next/prev/dom).

Prefer one session per shell command: search-play (search + first result + play).
Fish play_spotify uses search-play for Brave; avoid resolve then play separately.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from pathlib import Path

ACTION_SELECTORS: dict[str, list[str]] = {
    "play": [
        'button[data-testid="play-button"]',
        'button[data-testid="control-button-playpause"][aria-label*="Play"]',
        'button[aria-label="Play"]',
        '[title="Play"]',
        'button[data-testid="control-button-playpause"]',
    ],
    "pause": [
        'button[data-testid="control-button-playpause"][aria-label*="Pause"]',
        'button[aria-label="Pause"]',
        'button[data-testid="control-button-playpause"]',
    ],
    "next": [
        'button[data-testid="control-button-skip-forward"]',
        'button[aria-label*="Next"]',
    ],
    "prev": [
        'button[data-testid="control-button-skip-back"]',
        'button[aria-label*="Previous"]',
    ],
}


def _click_first(page, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=1500):
                loc.click(timeout=3000)
                return sel
        except Exception:
            continue
    return None


FIRST_TRACK_SELECTORS = [
    'div[data-testid="track-list"] div[data-testid="track-row"] a[href*="/track/"]',
    'div[data-testid="track-list"] a[href*="/track/"]',
    'a[href*="/track/"]',
]

ROW_PLAY_SELECTORS = [
    'div[data-testid="track-list"] div[data-testid="track-row"] button[data-testid="play-button"]',
    'div[data-testid="track-list"] button[data-testid="play-button"]',
    'div[data-testid="track-row"] button[data-testid="play-button"]',
    'section [role="row"] button[data-testid="play-button"]',
]


def _extract_track_id(href: str | None) -> str | None:
    if not href:
        return None
    m = re.search(r"/track/([a-zA-Z0-9]{10,})", href)
    return m.group(1) if m else None


def _first_track_id(page, timeout_ms: int = 15000) -> str | None:
    deadline = timeout_ms / 1000.0
    step = 0.5
    waited = 0.0
    while waited < deadline:
        for sel in FIRST_TRACK_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    tid = _extract_track_id(loc.get_attribute("href", timeout=2000))
                    if tid:
                        return tid
            except Exception:
                continue
        page.wait_for_timeout(int(step * 1000))
        waited += step
    return None


def search_play(page, query: str, dom_path: Path) -> int:
    encoded = urllib.parse.quote(query.strip())
    url = f"https://open.spotify.com/search/{encoded}/tracks"
    print(f"Search: {query}")
    print(f"Navigating: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)

    track_id = _first_track_id(page, timeout_ms=18000)
    if track_id:
        embed = f"https://open.spotify.com/embed/track/{track_id}?go=1"
        print(f"First result track: {track_id}")
        page.goto(embed, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        clicked = _click_first(page, ACTION_SELECTORS["play"])
        if clicked:
            print(f"DOM play OK: {clicked}")
            _save_dom(page, dom_path)
            return 0

    # Fallback: play button on first row in search results
    clicked = _click_first(page, ROW_PLAY_SELECTORS)
    if not clicked:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        clicked = _click_first(page, ROW_PLAY_SELECTORS)
    if clicked:
        print(f"Search row play OK: {clicked}")
        page.wait_for_timeout(800)
        _save_dom(page, dom_path)
        return 0

    _save_dom(page, dom_path)
    print("Error: no track found in search results", file=sys.stderr)
    return 1


def _target_url(track_id: str | None, url: str | None) -> str:
    if url:
        return url
    if track_id:
        return f"https://open.spotify.com/embed/track/{track_id}?go=1"
    return "https://open.spotify.com"


def _save_dom(page, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page.content(), encoding="utf-8")


def _brave_profile_dirs() -> list[Path]:
    """Snap Brave uses ~/snap/brave/<rev>/; deb uses ~/.config/BraveSoftware/."""
    home = Path.home()
    dirs: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p)
        if key not in seen:
            seen.add(key)
            dirs.append(p)

    snap_root = home / "snap/brave"
    if snap_root.is_dir():
        current = snap_root / "current" / ".config/BraveSoftware/Brave-Browser"
        add(current)
        revs = sorted(
            (d for d in snap_root.iterdir() if d.is_dir() and d.name.isdigit()),
            key=lambda p: int(p.name),
            reverse=True,
        )
        for rev in revs:
            add(rev / ".config/BraveSoftware/Brave-Browser")
        add(snap_root / "common" / ".config/BraveSoftware/Brave-Browser")

    add(home / ".config/BraveSoftware/Brave-Browser")
    return dirs


def _brave_singleton_locked(profile: Path) -> bool:
    """Brave uses a symlink SingletonLock; snap builds often break resolve() but lock is present."""
    lock = profile / "SingletonLock"
    return lock.is_symlink() or lock.exists()


def _brave_active_profile_dir() -> Path | None:
    for profile in _brave_profile_dirs():
        if _brave_singleton_locked(profile):
            return profile
    return None


def _brave_is_running() -> bool:
    if _brave_active_profile_dir() is not None:
        return True
    # Snap/brave processes without a visible lock file yet
    try:
        import subprocess

        r = subprocess.run(
            ["pgrep", "-f", r"(/snap/brave/|brave-browser|/opt/brave\.com/brave/brave)"],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _brave_launch_profile_dir() -> Path:
    active = _brave_active_profile_dir()
    if active:
        return active
    for profile in _brave_profile_dirs():
        if profile.is_dir():
            return profile
    return Path.home() / ".config/BraveSoftware/Brave-Browser"


def _discover_cdp_urls() -> list[str]:
    urls: list[str] = []
    if os.environ.get("SPOTIFY_CDP_URL"):
        urls.append(os.environ["SPOTIFY_CDP_URL"].rstrip("/"))

    for profile in _brave_profile_dirs():
        port_file = profile / "DevToolsActivePort"
        if port_file.is_file():
            lines = port_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if lines and lines[0].strip().isdigit():
                urls.append(f"http://127.0.0.1:{lines[0].strip()}")

    for port in ("9222", "9223", "9224"):
        urls.append(f"http://127.0.0.1:{port}")

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _pick_cdp_page(browser) -> tuple[object, str]:
    """Prefer an open Spotify tab; else the most recently opened tab."""
    spotify_pages = []
    all_pages = []
    for ctx in browser.contexts:
        for pg in ctx.pages:
            all_pages.append(pg)
            if "spotify.com" in (pg.url or ""):
                spotify_pages.append(pg)
    if spotify_pages:
        return spotify_pages[-1], "cdp-spotify-tab"
    if all_pages:
        return all_pages[-1], "cdp-active-tab"
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    return ctx.new_page(), "cdp-new-tab"


def _connect_existing_brave(playwright) -> tuple[object, object, str] | None:
    last_err: Exception | None = None
    for cdp in _discover_cdp_urls():
        try:
            browser = playwright.chromium.connect_over_cdp(cdp)
            page, mode = _pick_cdp_page(browser)
            print(f"Connected to Brave via {cdp} ({mode})", file=sys.stderr)
            return page, browser, mode
        except Exception as exc:
            last_err = exc
            continue
    if last_err and os.environ.get("SPOTIFY_CDP_DEBUG"):
        print(f"CDP connect failed: {last_err}", file=sys.stderr)
    return None


def _cdp_setup_hint() -> None:
    active = _brave_active_profile_dir()
    kind = "snap Brave" if active and "snap/brave" in str(active) else "Brave"
    print(
        f"To control your already-open {kind} window, restart it with remote debugging:",
        file=sys.stderr,
    )
    print(
        "  brave --remote-debugging-port=9222    # snap",
        file=sys.stderr,
    )
    print(
        "  brave-browser --remote-debugging-port=9222",
        file=sys.stderr,
    )
    print(
        "  Or: spotify_brave_debug",
        file=sys.stderr,
    )
    print(
        "  (Log into Spotify in that window once; play_spotify will reuse the same session.)",
        file=sys.stderr,
    )
    print(
        "Optional: export SPOTIFY_CDP_URL=http://127.0.0.1:9222",
        file=sys.stderr,
    )


def _get_page(playwright, headless: bool):
    attached = _connect_existing_brave(playwright)
    if attached:
        return attached

    brave_path = shutil_which("brave") or shutil_which("brave-browser")
    user_data = _brave_launch_profile_dir()

    if _brave_is_running():
        _cdp_setup_hint()
        profile = _brave_active_profile_dir()
        if profile:
            print(f"  Active profile: {profile}", file=sys.stderr)
        print(
            "Error: Brave is running but Playwright cannot attach (no debug port).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if brave_path and user_data.is_dir():
        ctx = playwright.chromium.launch_persistent_context(
            str(user_data),
            executable_path=brave_path,
            headless=False,
            args=["--profile-directory=Default"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"Browser mode: Brave profile {user_data}", file=sys.stderr)
        return page, ctx, "persistent"

    browser = playwright.chromium.launch(headless=headless)
    print("Browser mode: ephemeral Chromium", file=sys.stderr)
    return browser.new_page(), browser, "ephemeral"


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def run(
    action: str,
    track_id: str | None,
    url: str | None,
    dom_path: str,
    search_query: str | None = None,
) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: playwright not installed. Run: install_skill_deps", file=sys.stderr)
        return 1

    headless = action == "dom"
    target = _target_url(track_id, url)

    out = Path(dom_path).expanduser()

    with sync_playwright() as p:
        page, handle, mode = _get_page(p, headless=headless)
        print(f"Browser mode: {mode}")

        if action == "search-play":
            if not search_query:
                print("Error: search-play requires a query", file=sys.stderr)
                return 1
            return search_play(page, search_query, out)

        if action == "dom" or track_id or url:
            print(f"Navigating: {target}")
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)

        _save_dom(page, out)
        print(f"DOM saved: {out}")

        if action == "dom":
            return 0

        selectors = ACTION_SELECTORS.get(action, ACTION_SELECTORS["play"])
        clicked = _click_first(page, selectors)
        if clicked:
            print(f"DOM click OK: {clicked}")
            page.wait_for_timeout(800)
            _save_dom(page, out)
            return 0

        # Embed fallback: large center play control
        if action == "play":
            clicked = _click_first(page, ['button:has(svg)', '[role="button"]'])
            if clicked:
                print(f"DOM click fallback: {clicked}")
                return 0

        print(f"Error: no DOM control found for action '{action}'", file=sys.stderr)
        print(f"  Inspect DOM at: {out}", file=sys.stderr)
        return 1


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: spotify_dom.py <play|pause|next|prev|dom> [track_id_or_url] [--dom-out path]",
            file=sys.stderr,
        )
        return 1

    action = sys.argv[1].lower()
    track_id = None
    url = None
    dom_path = os.path.expanduser("~/.config/fish/spotify-dom.html")

    args = sys.argv[2:]
    search_query = None
    query_parts: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--dom-out" and i + 1 < len(args):
            dom_path = args[i + 1]
            i += 2
        elif action in ("search-play", "resolve") and not args[i].startswith("-"):
            query_parts.append(args[i])
            i += 1
        elif args[i].startswith("http"):
            url = args[i]
            i += 1
        elif not args[i].startswith("-"):
            if len(args[i]) == 22 and args[i].isalnum():
                track_id = args[i]
            else:
                url = args[i]
            i += 1
        else:
            i += 1

    if action == "search-play":
        if not query_parts:
            print("Usage: spotify_dom.py search-play <query>", file=sys.stderr)
            return 1
        search_query = " ".join(query_parts)

    if action == "resolve":
        if not query_parts:
            print("Usage: spotify_dom.py resolve <query>", file=sys.stderr)
            return 1
        search_query = " ".join(query_parts)

    if action not in (*ACTION_SELECTORS.keys(), "dom", "search-play", "resolve"):
        print(f"Unknown action: {action}", file=sys.stderr)
        return 1

    if action == "resolve":
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            page, handle, mode = _get_page(p, headless=False)
            print(f"Browser mode: {mode}", file=sys.stderr)
            encoded = urllib.parse.quote(search_query.strip())
            page.goto(
                f"https://open.spotify.com/search/{encoded}/tracks",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            tid = _first_track_id(page, timeout_ms=18000)
            if tid:
                print(tid)
                return 0
            print("Error: could not resolve track from search", file=sys.stderr)
            return 1

    return run(action, track_id, url, dom_path, search_query)


if __name__ == "__main__":
    sys.exit(main())
