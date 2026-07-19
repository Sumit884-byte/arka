"""Headless game smoke checks: load a game, play safe actions, verify it responds."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

PLAY_DEPTHS = {"smoke", "standard", "deep"}
MAX_WAIT_MS = 10_000
DEFAULT_VERIFY_FRAME_LIMIT = 3


def parse_duration(value: str | int | float | None) -> int:
    """Parse a duration into seconds, capped to a safe local QA window."""
    if value is None or value == "":
        return 0
    if isinstance(value, int | float):
        return max(0, min(600, int(value)))
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|second|seconds|m|min|mins|minute|minutes)?", text)
    if not match:
        raise ValueError("duration must look like 30s, 2m, or 90")
    number = float(match.group(1))
    unit = match.group(2) or "s"
    seconds = number / 1000 if unit == "ms" else number * 60 if unit.startswith("m") else number
    return max(0, min(600, int(seconds)))


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


def _page_text(page: Any) -> str:
    try:
        text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        return ""
    return " ".join(str(text).split())[:2000]


def _session_wait_actions(duration_seconds: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    remaining_ms = max(0, duration_seconds * 1000)
    sample = 1
    while remaining_ms > 0:
        chunk = min(MAX_WAIT_MS, remaining_ms)
        actions.append({"type": "wait", "ms": chunk, "purpose": f"long-session observation chunk {sample}"})
        remaining_ms -= chunk
        sample += 1
    return actions


def plan_gameplay(
    page: Any,
    *,
    url: str = "",
    depth: str = "auto",
    max_actions: int | None = None,
    duration_seconds: int = 0,
) -> dict[str, Any]:
    """Choose how long and what edge cases to try for a headless game check."""
    text = _page_text(page)
    lower = f"{url} {text}".lower()
    inferred = depth if depth in PLAY_DEPTHS else "standard"
    reasons = ["default standard coverage"]
    if depth == "auto":
        if re.search(r"\b(?:boss|level|mission|quest|multiplayer|battle|race|physics|3d|three\.js|webgl)\b", lower):
            inferred = "deep"
            reasons = ["complex/gameplay-heavy page hints"]
        elif re.search(r"\b(?:demo|menu|prototype|simple|starter)\b", lower):
            inferred = "smoke"
            reasons = ["simple/prototype page hints"]
    actions: list[dict[str, Any]] = []
    for selector in ("button", "[role=button]", "a[href]"):
        locator = page.locator(selector)
        for button_index in range(min(5, locator.count())):
            candidate = locator.nth(button_index)
            if candidate.is_visible():
                label = (candidate.inner_text() or "").strip().lower()
                if any(word in label for word in ("play", "start", "begin", "launch", "continue", "game", "resume")):
                    actions.append({"type": "click", "selector": selector, "index": button_index, "purpose": "enter gameplay from menu"})
                    break
    actions.append({"type": "click", "selector": "canvas", "purpose": "focus game canvas"})
    core_keys = ["ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft", "w", "a", "s", "d", " "]
    if inferred == "smoke":
        core_keys = ["ArrowUp", "ArrowRight", " "]
    elif inferred == "deep":
        core_keys.extend(["Enter", "Escape", "p", "r"])
    actions.extend({"type": "key", "key": key, "purpose": "movement/control edge case"} for key in core_keys)
    if inferred in {"standard", "deep"}:
        actions.extend(
            [
                {"type": "click", "selector": "canvas", "position": "top-left", "purpose": "canvas boundary click"},
                {"type": "click", "selector": "canvas", "position": "bottom-right", "purpose": "canvas boundary click"},
                {"type": "wait", "ms": 1000, "purpose": "observe animation after input"},
            ]
        )
    if inferred == "deep":
        actions.extend(
            [
                {"type": "key", "key": "ArrowUp", "purpose": "repeat input stability"},
                {"type": "key", "key": "ArrowUp", "purpose": "repeat input stability"},
                {"type": "wait", "ms": 1500, "purpose": "longer gameplay observation"},
            ]
        )
    if duration_seconds:
        actions.extend(_session_wait_actions(duration_seconds))
    if max_actions:
        actions = actions[: max(1, max_actions)]
    return {
        "depth": inferred,
        "requested_depth": depth,
        "duration_seconds": duration_seconds,
        "wait_chunk_limit_ms": MAX_WAIT_MS,
        "reason": "; ".join(reasons),
        "edge_cases": [
            "menu/start controls",
            "canvas focus",
            "arrow-key movement",
            "WASD movement",
            "action key",
            "boundary clicks" if inferred != "smoke" else "short smoke path",
            "pause/reset keys" if inferred == "deep" else "basic animation settle",
        ],
        "actions": actions,
    }


def _parse_visual_diagnosis(raw: object) -> dict[str, Any]:
    """Normalize visual_diagnose output into a verdict/issues/fixes shape."""
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw or "").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            lowered = text.lower()
            verdict = "needs_fix" if re.search(r"\b(?:needs_fix|needs fix|issue|bug|broken|unreadable|overlap|clipped)\b", lowered) else "unknown"
            return {"verdict": verdict, "issues": [text] if verdict == "needs_fix" and text else [], "fixes": [], "raw": text}
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]
    fixes = data.get("fixes", [])
    if not isinstance(fixes, list):
        fixes = [str(fixes)]
    verdict = str(data.get("verdict") or ("needs_fix" if issues else "good")).strip().lower()
    severity = str(data.get("severity") or "").strip().lower()
    if severity in {"medium", "high", "critical"} and verdict == "good":
        verdict = "needs_fix"
    return {"verdict": verdict, "severity": severity, "issues": issues, "fixes": fixes, "raw": raw}


def verify_game_visuals(screenshots: list[str], *, frame_limit: int = DEFAULT_VERIFY_FRAME_LIMIT) -> dict[str, Any]:
    """Run a post-play visual diagnosis before saying the game check passed."""
    unique: list[str] = []
    for shot in screenshots:
        if shot and shot not in unique:
            unique.append(shot)
    if len(unique) > frame_limit:
        unique = [unique[0], *unique[-(frame_limit - 1):]] if frame_limit > 1 else unique[-1:]
    checked: list[dict[str, Any]] = []
    try:
        from arka.agent.visual_diagnose import diagnose
    except ImportError as exc:
        return {"enabled": True, "status": "failed", "verdict": "unavailable", "reason": f"visual diagnosis unavailable: {exc}", "checked": []}
    for image in unique:
        try:
            result = diagnose(image)
            parsed = _parse_visual_diagnosis(result.get("diagnosis") if isinstance(result, dict) else result)
            checked.append({"image": image, **parsed})
        except Exception as exc:
            checked.append({"image": image, "verdict": "unavailable", "issues": [str(exc)], "fixes": [], "raw": str(exc)})
    bad = [row for row in checked if row.get("verdict") != "good"]
    return {
        "enabled": True,
        "status": "failed" if bad else "passed",
        "verdict": "needs_fix" if bad else "good",
        "checked": checked,
        "frame_limit": frame_limit,
    }


def check_game(
    url: str,
    actions: list[dict[str, Any]] | None = None,
    *,
    output: str | None = None,
    record: bool = False,
    play_depth: str = "auto",
    max_actions: int | None = None,
    duration_seconds: int = 0,
    verify_visuals: bool = False,
    verify_frame_limit: int = DEFAULT_VERIFY_FRAME_LIMIT,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install game checks with: pip install playwright && playwright install chromium") from exc
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    target = Path(output).expanduser() if output else Path(tempfile.mkdtemp(prefix="arka-game-check-"))
    target.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(record_video_dir=str(target) if record else None)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(url, wait_until="load", timeout=30_000)
        page.wait_for_timeout(1000)
        canvas_count = page.locator("canvas").count()
        if canvas_count == 0:
            raise RuntimeError("game check expected at least one canvas element")
        initial = target / "frame-000-loaded.png"
        page.screenshot(path=str(initial))
        strategy = (
            {"depth": "custom", "requested_depth": "custom", "reason": "user-provided actions", "edge_cases": ["custom action list"], "actions": actions}
            if actions is not None
            else plan_gameplay(page, url=url, depth=play_depth, max_actions=max_actions, duration_seconds=duration_seconds)
        )
        planned = list(strategy["actions"])
        for index, action in enumerate(planned, 1):
            kind = str(action.get("type", "")).lower()
            if kind == "key":
                page.keyboard.press(str(action.get("key", "ArrowUp")))
            elif kind == "click":
                locator = page.locator(str(action.get("selector", "canvas")))
                locator.nth(int(action.get("index", 0))).click(timeout=10_000)
            elif kind == "wait":
                page.wait_for_timeout(min(MAX_WAIT_MS, max(0, int(action.get("ms", 500)))))
            else:
                raise ValueError(f"action {index}: use key, click, or wait")
            frame = target / f"frame-{index:03d}.png"
            page.screenshot(path=str(frame))
            event = {"action": kind, "status": "passed", "screenshot": str(frame)}
            if action.get("purpose"):
                event["purpose"] = str(action["purpose"])
            if action.get("key"):
                event["key"] = str(action["key"])
            events.append(event)
        screenshot = str(target / "final.png")
        page.screenshot(path=screenshot)
        if record:
            # Closing the page/context finalizes Playwright's webm file.
            video = _finalize_video(page, context)
        else:
            context.close()
            video = None
        browser.close()
    visual_errors = []
    if canvas_count == 0:
        visual_errors.append("no canvas found")
    if errors:
        visual_errors.append("browser console/page errors were captured")
    screenshots = [str(initial)] + [event["screenshot"] for event in events] + [screenshot]
    visual_verification = {"enabled": False, "status": "skipped", "verdict": "not_checked", "checked": []}
    if verify_visuals:
        visual_verification = verify_game_visuals(screenshots, frame_limit=max(1, min(10, verify_frame_limit)))
        if visual_verification.get("status") != "passed":
            visual_errors.append("visual verification did not pass")
    clicked_controls = sum(1 for event in events if event["action"] == "click" and event.get("status") == "passed")
    status = "failed" if errors or visual_errors else "passed"
    return {"url": url, "status": status, "canvas_count": canvas_count, "play_strategy": {k: v for k, v in strategy.items() if k != "actions"}, "actions": events, "clicked_controls": clicked_controls, "gameplay_started": any(event["action"] == "key" for event in events), "errors": errors, "visual_errors": visual_errors, "visual_verification": visual_verification, "screenshots": screenshots, "screenshot": screenshot, "video": video, "recording_started_before_actions": bool(record), "artifacts": str(target), "fix_prompt": "Review the captured game frames and video for layout, animation, and interaction issues; fix only the observed visual problems." if visual_errors else "Visual verification passed; no automatic visual errors detected."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka game check")
    parser.add_argument("url")
    parser.add_argument("--actions", help="JSON action list or a JSON file")
    parser.add_argument("--output")
    parser.add_argument("--record", action="store_true", help="Record gameplay video (off by default)")
    parser.add_argument("--play-depth", choices=["auto", "smoke", "standard", "deep"], default="auto", help="How much gameplay to exercise")
    parser.add_argument("--duration", "--session-duration", dest="duration", help="Additional gameplay observation time, e.g. 30s or 2m")
    parser.add_argument("--max-actions", type=int, help="Cap auto-planned actions")
    parser.add_argument("--verify", "--verify-visuals", dest="verify_visuals", action="store_true", help="Run visual diagnosis before reporting passed")
    parser.add_argument("--verify-frames", type=int, default=DEFAULT_VERIFY_FRAME_LIMIT, help="Max screenshots to visually verify")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.actions).read_text(encoding="utf-8") if args.actions and Path(args.actions).is_file() else args.actions
        actions = json.loads(raw) if raw else None
        result = check_game(
            args.url,
            actions,
            output=args.output,
            record=args.record,
            play_depth=args.play_depth,
            max_actions=args.max_actions,
            duration_seconds=parse_duration(args.duration),
            verify_visuals=args.verify_visuals,
            verify_frame_limit=args.verify_frames,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"game check: {result['status']} ({len(result['actions'])} actions, {len(result['errors'])} errors)")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
