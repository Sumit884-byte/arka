"""Open browser website games in a headed Playwright window (MVP play/search)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arka.core.screenshot_paths import resolve_screenshot_output

DEFAULT_SETTLE_SECONDS = 2.5
DEFAULT_HEADED_WAIT_SECONDS = 300
MAX_HEADED_WAIT_SECONDS = 3600

PLAY_WEBSITE_GAME_CLI_HEADS = frozenset(
    {"play_website_game", "play-website-game", "website_game", "website-game", "browser_game"}
)
_EXPLICIT_PREFIX = re.compile(
    r"(?i)^(?:arka\s+)?(?:play[_-]?website[_-]?game|website[_-]?game|browser[_-]?game)\s+"
)


def _settle_seconds(value: float | None = None) -> float:
    if value is not None:
        return max(0.0, min(60.0, float(value)))
    raw = os.environ.get("ARKA_BROWSER_SETTLE_SECONDS", str(DEFAULT_SETTLE_SECONDS)).strip()
    try:
        return max(0.0, min(60.0, float(raw)))
    except ValueError:
        return DEFAULT_SETTLE_SECONDS


def _normalize_url(url: str) -> str:
    text = url.strip()
    if not text:
        raise ValueError("URL is required")
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    parsed = urlparse(text)
    if not parsed.netloc:
        raise ValueError(f"Invalid URL: {url!r}")
    return text


def _search_query(query: str) -> str:
    text = query.strip()
    if not text:
        raise ValueError("search query is required")
    lower = text.lower()
    if "game" not in lower:
        text = f"{text} online browser game"
    return text


def search_games(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    from arka.agent.chat import duckduckgo_search

    results: list[dict[str, str]] = []
    for row in duckduckgo_search(_search_query(query), max_results=max(1, min(max_results, 10))):
        link = str(row.get("link") or "").strip()
        if not link.startswith("http"):
            continue
        results.append(
            {
                "url": link,
                "title": str(row.get("title") or "").strip(),
                "snippet": str(row.get("snippet") or "").strip(),
            }
        )
    return results


def pick_game_url(query: str, *, max_results: int = 5) -> dict[str, str] | None:
    results = search_games(query, max_results=max_results)
    if not results:
        return None
    query_l = query.lower()
    for row in results:
        hay = f"{row.get('title', '')} {row.get('snippet', '')} {row.get('url', '')}".lower()
        if any(token in hay for token in re.findall(r"[a-z0-9]+", query_l) if len(token) > 2):
            return row
    return results[0]


def _run_auto_start(page: Any, *, max_actions: int = 4) -> list[dict[str, Any]]:
    from arka.agent.game_control import execute_game_action, plan_gameplay

    strategy = plan_gameplay(page, depth="smoke", max_actions=max_actions)
    events: list[dict[str, Any]] = []
    for action in strategy["actions"]:
        kind = str(action.get("type", "")).lower()
        try:
            event = execute_game_action(page, action)
            row: dict[str, Any] = {"action": kind, "status": event.get("status", "passed")}
            if action.get("purpose"):
                row["purpose"] = str(action["purpose"])
            events.append(row)
        except Exception as exc:
            events.append({"action": kind, "status": "failed", "error": str(exc)})
    return events


def open_game(
    url: str,
    *,
    headless: bool = False,
    settle_seconds: float | None = None,
    wait_seconds: int | None = None,
    auto_start: bool = False,
    screenshot: str | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Install browser game support with: pip install playwright && playwright install chromium"
        ) from exc

    target = _normalize_url(url)
    settle = _settle_seconds(settle_seconds)
    errors: list[str] = []
    auto_actions: list[dict[str, Any]] = []

    if wait_seconds is None:
        if headless:
            wait_seconds = 0
        else:
            raw = os.environ.get("ARKA_WEBSITE_GAME_WAIT_SECONDS", str(DEFAULT_HEADED_WAIT_SECONDS)).strip()
            try:
                wait_seconds = max(0, min(MAX_HEADED_WAIT_SECONDS, int(raw)))
            except ValueError:
                wait_seconds = DEFAULT_HEADED_WAIT_SECONDS
    else:
        wait_seconds = max(0, min(MAX_HEADED_WAIT_SECONDS, int(wait_seconds)))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(target, wait_until="load", timeout=30_000)
        page.wait_for_timeout(int(settle * 1000))
        title = page.title()
        if auto_start:
            auto_actions = _run_auto_start(page)
        shot_path = None
        if screenshot:
            shot_path = str(screenshot)
            page.screenshot(path=shot_path, full_page=True)
        elif headless:
            shot_path = str(resolve_screenshot_output(None, prefix="website-game-headless"))
            page.screenshot(path=shot_path, full_page=True)
        if wait_seconds > 0 and not headless:
            page.wait_for_timeout(wait_seconds * 1000)
        browser.close()

    status = response.status if response else None
    ok = bool(status and status < 400 and not errors)
    return {
        "url": target,
        "status": status,
        "title": title,
        "headless": headless,
        "wait_seconds": wait_seconds,
        "auto_start": auto_start,
        "auto_actions": auto_actions,
        "console_errors": errors,
        "screenshot": shot_path,
        "ok": ok,
        "message": (
            f"Loaded {target} ({title or 'untitled'})"
            + (" — close the browser window when finished." if not headless and wait_seconds == 0 else "")
        ),
    }


def play_website_game_result(
    *,
    url: str | None = None,
    query: str | None = None,
    headless: bool = False,
    wait_seconds: int | None = None,
    auto_start: bool = False,
    open_best: bool = True,
    agent: bool = False,
    agent_turns: int | None = None,
    vision_backend: str | None = None,
    learn: bool | None = None,
    rl: bool | None = None,
) -> dict[str, Any]:
    if agent and url:
        from arka.agent.game_agent import run_agent

        return run_agent(
            url,
            turns=agent_turns,
            vision_backend=vision_backend,
            learn=learn,
            rl=rl,
            headless=headless,
            auto_start=auto_start,
        )
    if url:
        return open_game(
            url,
            headless=headless,
            wait_seconds=wait_seconds,
            auto_start=auto_start,
        )
    if not query:
        raise ValueError("url or query is required")
    picked = pick_game_url(query)
    if not picked:
        return {"query": query, "ok": False, "message": f"No browser game found for {query!r}", "results": []}
    results = search_games(query)
    payload: dict[str, Any] = {"query": query, "picked": picked, "results": results}
    if open_best:
        opened = open_game(
            picked["url"],
            headless=headless,
            wait_seconds=wait_seconds,
            auto_start=auto_start,
        )
        payload.update(opened)
        payload["ok"] = opened.get("ok", False)
    else:
        payload["ok"] = True
        payload["message"] = f"Found {len(results)} result(s); best match: {picked.get('title') or picked['url']}"
    return payload


def _argv_from_explicit_prefix(text: str) -> list[str]:
    match = _EXPLICIT_PREFIX.match(text.strip())
    if not match:
        return []
    rest = text.strip()[match.end() :].strip()
    if not rest:
        return ["check"]
    try:
        return shlex.split(rest, posix=True)
    except ValueError:
        return rest.split()


def is_play_website_game_cli_argv(argv: list[str]) -> bool:
    """True for ``arka play_website_game …`` style argv."""
    return bool(argv) and argv[0] in PLAY_WEBSITE_GAME_CLI_HEADS


def run_play_website_game_cli(argv: list[str]) -> int:
    """Execute ``arka play_website_game …`` without NL routing."""
    return main(argv[1:])


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    explicit = _argv_from_explicit_prefix(t)
    if explicit:
        return explicit

    url = re.search(r"https?://[^\s\"']+", t)
    if url and re.search(
        r"(?i)\b(?:ai\s+)?agent\b.*\b(?:play|open|run)\b|\b(?:play|open|run)\b.*\b(?:ai\s+)?agent\b",
        t,
    ):
        argv = ["agent", url.group(0)]
        if re.search(r"(?i)\b(?:no[\s-]?learn|without\s+learning)\b", t):
            argv.append("--no-learn")
        elif re.search(r"(?i)\b(?:learn|learning)\b", t):
            argv.append("--learn")
        if re.search(r"(?i)\bheadless\b", t):
            argv.append("--headless")
        return argv

    if url and re.search(
        r"(?i)\b(?:play|open|launch|start)\b.*\b(?:website|browser|online|web)\s+game\b|\b(?:website|browser|online|web)\s+game\b.*\b(?:at|on|url)\b",
        t,
    ):
        argv = ["open", url.group(0)]
        if re.search(r"(?i)\b(?:auto[\s-]?start|click\s+start|start\s+game)\b", t):
            argv.append("--auto-start")
        if re.search(r"(?i)\bheadless\b", t):
            argv.append("--headless")
        return argv

    if url and re.search(r"(?i)\b(?:play|open)\b.*\bgame\b", t) and not re.search(
        r"(?i)\b(?:check|test|verify|record|capture|qa)\b", t
    ):
        argv = ["open", url.group(0)]
        if re.search(r"(?i)\b(?:auto[\s-]?start|click\s+start)\b", t):
            argv.append("--auto-start")
        return argv

    m = re.search(
        r"(?i)(?:play|open|find|search(?:\s+for)?)\s+(?:a\s+|an\s+|the\s+)?(?P<query>.+?)\s+(?:online|browser|website)\s+game\b",
        t,
    )
    if m:
        return ["search", m.group("query").strip(), "--open"]

    m = re.search(r"(?i)(?:play|open)\s+(?P<query>[a-z0-9][\w\s-]{1,60}?)\s+online\b", t)
    if m:
        return ["search", m.group("query").strip(), "--open"]

    m = re.search(r"(?i)(?:search|find)\s+(?:for\s+)?(?P<query>.+?\bgame\b.*)$", t)
    if m:
        argv = ["search", m.group("query").strip()]
        if re.search(r"(?i)\b(?:open|launch|play)\b", t):
            argv.append("--open")
        return argv

    if re.search(r"(?i)\b(?:website|browser|online)\s+game\b", t) and not url:
        cleaned = re.sub(
            r"(?i)\b(?:arka\s+)?(?:please\s+)?(?:play|open|launch|start|find|search(?:\s+for)?)\b",
            "",
            t,
        )
        cleaned = re.sub(r"(?i)\b(?:website|browser|online|web)\s+game\b", "", cleaned).strip(" :,-")
        if cleaned:
            return ["search", cleaned, "--open"]
    return []


def cmd_check(_args: argparse.Namespace) -> int:
    from arka.core.output_layout import error, list_items, section, success

    issues: list[str] = []
    try:
        import playwright  # noqa: F401
    except ImportError:
        issues.append("playwright not installed (pip install playwright)")
    else:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                browser.close()
        except Exception as exc:
            issues.append(f"chromium launch failed: {exc}")
    try:
        from arka.agent.chat import duckduckgo_search

        _ = duckduckgo_search
    except ImportError as exc:
        issues.append(f"search dependency unavailable: {exc}")
    if issues:
        section("Play website game check")
        error("Dependencies missing")
        list_items(issues)
        return 1
    section("Play website game check")
    success("playwright + search available")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="play_website_game",
        description="Open or search browser games in a headed Playwright window",
    )
    sub = p.add_subparsers(dest="cmd")

    p_open = sub.add_parser("open", help="Open a game URL in the browser")
    p_open.add_argument("url", help="Game URL (https://…)")
    p_open.add_argument("--headless", action="store_true", help="Run headless (CI/tests)")
    p_open.add_argument("--wait", type=int, default=None, help="Seconds to keep browser open (headed)")
    p_open.add_argument("--settle", type=float, default=None, help="Seconds to wait after page load")
    p_open.add_argument("--auto-start", action="store_true", help="Try clicking Play/Start and focus canvas")
    p_open.add_argument("--screenshot", help="Screenshot path (always captured in headless mode)")
    p_open.add_argument("--json", action="store_true")

    p_search = sub.add_parser("search", help="Search for an online browser game")
    p_search.add_argument("query", help='e.g. "snake game"')
    p_search.add_argument("--open", action="store_true", help="Open the best search result")
    p_search.add_argument("--headless", action="store_true")
    p_search.add_argument("--wait", type=int, default=None)
    p_search.add_argument("--auto-start", action="store_true")
    p_search.add_argument("--max-results", type=int, default=5)
    p_search.add_argument("--json", action="store_true")

    p_agent = sub.add_parser("agent", help="Vision agent loop with pattern learning + RL (experimental)")
    p_agent.add_argument("url", help="Game URL (https://…)")
    p_agent.add_argument("--turns", type=int, default=None, help="Agent turns (default ARKA_GAME_AGENT_TURNS or 10)")
    p_agent.add_argument(
        "--vision-backend",
        choices=["vllm", "gemini", "ollama", "auto"],
        default=None,
        help="Vision backend for screenshots (default DESCRIBE_IMAGE_BACKEND)",
    )
    p_agent.add_argument("--headless", action="store_true", help="Run headless (CI/tests)")
    p_agent.add_argument("--no-auto-start", action="store_true", help="Skip menu/canvas auto-start heuristics")
    p_agent.add_argument("--learn", action="store_true", help="Store successful action patterns (default on)")
    p_agent.add_argument("--no-learn", action="store_true", help="Disable pattern learning")
    p_agent.add_argument("--no-rl", action="store_true", help="Disable epsilon-greedy Q-table RL")
    p_agent.add_argument("--reward", type=float, default=None, help="Manual reward signal per turn (experimental)")
    p_agent.add_argument("--json", action="store_true")

    sub.add_parser("check", help="Verify Playwright and search dependencies")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        argv = ["--help"]
    if argv and argv[0] not in {"open", "search", "agent", "check", "-h", "--help"} and not argv[0].startswith("-"):
        if argv[0].startswith("http") or "://" in argv[0]:
            argv = ["open", *argv]
        elif re.search(r"(?i)\bgame\b", " ".join(argv)):
            argv = ["search", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args)
    try:
        if args.cmd == "open":
            result = open_game(
                args.url,
                headless=args.headless,
                settle_seconds=args.settle,
                wait_seconds=args.wait,
                auto_start=args.auto_start,
                screenshot=args.screenshot,
            )
        elif args.cmd == "search":
            results = search_games(args.query, max_results=args.max_results)
            if args.open:
                picked = pick_game_url(args.query, max_results=args.max_results)
                if not picked:
                    if args.json:
                        print(json.dumps({"query": args.query, "results": results, "ok": False}, indent=2))
                    else:
                        from arka.core.output_layout import error

                        error(f"No browser game found for {args.query!r}")
                    return 1
                result = open_game(
                    picked["url"],
                    headless=args.headless,
                    wait_seconds=args.wait,
                    auto_start=args.auto_start,
                )
                result["query"] = args.query
                result["picked"] = picked
                result["results"] = results
            else:
                result = {"query": args.query, "results": results, "ok": bool(results)}
                if results:
                    result["picked"] = pick_game_url(args.query, max_results=args.max_results)
        elif args.cmd == "agent":
            from arka.agent.game_agent import run_agent

            learn = False if args.no_learn else True if args.learn else None
            backend = None if args.vision_backend in {None, "auto"} else args.vision_backend
            result = run_agent(
                args.url,
                turns=args.turns,
                vision_backend=backend,
                learn=learn,
                rl=not args.no_rl,
                headless=args.headless,
                auto_start=not args.no_auto_start,
                manual_reward=args.reward,
            )
        else:
            parser.print_help()
            return 0
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        from arka.core.output_layout import error, result_box, success, table

        if args.cmd == "search" and not args.open:
            rows = [
                (row.get("title") or row.get("url") or "", row.get("url") or "")
                for row in result.get("results", [])
            ]
            result_box(
                f"Game search: {args.query}",
                f"{len(rows)} result(s)",
            )
            if rows:
                table(["Title", "URL"], rows)
            picked = result.get("picked")
            if picked:
                success(f"Best match: {picked.get('title') or picked.get('url')}")
        else:
            title = result.get("title") or result.get("url") or "Game"
            body_lines = [result.get("message") or f"Loaded {result.get('url')} — {title}"]
            if args.cmd == "agent":
                passed = sum(1 for row in result.get("turns_log", []) if row.get("status") == "passed")
                body_lines.append(f"Agent: {passed}/{result.get('turns', 0)} turn(s), reward={result.get('total_reward', 0)}")
            if result.get("screenshot"):
                body_lines.append(f"Screenshot: {result['screenshot']}")
            if result.get("auto_actions"):
                passed = sum(1 for row in result["auto_actions"] if row.get("status") == "passed")
                body_lines.append(f"Auto-start: {passed}/{len(result['auto_actions'])} action(s)")
            if result.get("console_errors"):
                body_lines.append(f"Console errors: {len(result['console_errors'])}")
            result_box("Browser game", "\n".join(body_lines))
            if result.get("ok", True):
                success(str(result.get("url") or title))
            else:
                error(str(result.get("message") or "Game session failed"))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
