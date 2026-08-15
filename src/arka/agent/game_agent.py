"""Vision-driven browser game agent with pattern learning and lightweight RL (experimental)."""
from __future__ import annotations

import json
import os
import random
import re
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator

from arka.agent.game_control import execute_game_action
from arka.core.screenshot_paths import screenshot_path
from arka.agent.game_learning import (
    action_key,
    compute_reward,
    domain_from_url,
    load_game_state,
    parse_action_key,
    q_best_action,
    q_epsilon,
    q_update,
    recall_pattern_hints,
    remember_pattern,
    save_game_state,
    screen_fingerprint,
    screenshot_hash,
)

DEFAULT_TURNS = 10
EXPLORE_KEYS = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " ", "w", "a", "s", "d"]

AGENT_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def default_turns() -> int:
    raw = os.environ.get("ARKA_GAME_AGENT_TURNS", str(DEFAULT_TURNS)).strip()
    try:
        return max(1, min(100, int(raw)))
    except ValueError:
        return DEFAULT_TURNS


def learn_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("ARKA_GAME_LEARN_PATTERNS", "1").strip().lower() not in {"0", "false", "no", "off"}


def rl_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("ARKA_GAME_RL", "1").strip().lower() not in {"0", "false", "no", "off"}


@contextmanager
def vision_backend(backend: str | None) -> Iterator[None]:
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


def build_agent_prompt(
    *,
    turn: int,
    max_turns: int,
    pattern_hints: list[dict[str, Any]],
    title: str,
) -> str:
    hint_lines: list[str] = []
    for row in pattern_hints[:3]:
        actions = row.get("actions") or []
        if actions:
            seq = ", ".join(action_key(a) for a in actions[:4])
            hint_lines.append(f"- {row.get('screen_hint') or 'prior session'}: {seq}")
        elif row.get("screen_hint"):
            hint_lines.append(f"- memory: {row['screen_hint'][:200]}")
    hints_block = "\n".join(hint_lines) if hint_lines else "- none yet"
    return (
        "You are playing a browser game. Look at the screenshot and choose ONE next action.\n"
        f"Turn {turn}/{max_turns}. Page title: {title or 'unknown'}.\n"
        "Known successful patterns for this site:\n"
        f"{hints_block}\n\n"
        "Reply with ONLY valid JSON:\n"
        '{"action":{"type":"key|click|wait","key":"ArrowUp","selector":"canvas","index":0,"ms":500},"reason":"brief"}\n'
        "Prefer key presses for gameplay; click Play/Start/canvas to focus when menus appear."
    )


def parse_agent_action(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty vision response")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = AGENT_JSON_RE.search(text)
        if not match:
            raise ValueError(f"could not parse JSON action from: {text[:200]}")
        data = json.loads(match.group(0))
    action = data.get("action") if isinstance(data, dict) else None
    if not isinstance(action, dict):
        raise ValueError("vision response missing action object")
    kind = str(action.get("type", "")).lower()
    if kind not in {"key", "click", "wait"}:
        raise ValueError(f"unsupported action type: {kind!r}")
    return action


def _describe_screenshot(path: str, prompt: str) -> str:
    from arka.vision.describe import describe_source

    return describe_source(path, prompt)


def _random_explore_action() -> dict[str, Any]:
    key = random.choice(EXPLORE_KEYS)
    return {"type": "key", "key": key, "purpose": "rl explore"}


def run_agent_turn(
    page: Any,
    *,
    turn: int,
    max_turns: int,
    pattern_hints: list[dict[str, Any]],
    game_state: dict[str, Any],
    vision_backend_name: str | None,
    use_rl: bool,
    manual_reward: float | None,
    prev_score: int | None,
    prev_shot_hash: str,
) -> dict[str, Any]:
    screen_key = screen_fingerprint(page)
    chosen: dict[str, Any] | None = None
    source = "vision"

    if use_rl and random.random() < q_epsilon():
        chosen = _random_explore_action()
        source = "explore"
    elif use_rl:
        best = q_best_action(game_state, screen_key)
        if best and best[1] > 0.1:
            chosen = parse_action_key(best[0])
            source = "q_table"

    title = ""
    try:
        title = page.title() or ""
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix="arka-game-agent-") as tmp:
        shot = str(screenshot_path(f"turn-{turn:03d}", tmp))
        page.screenshot(path=shot, full_page=False)
        if chosen is None:
            prompt = build_agent_prompt(
                turn=turn,
                max_turns=max_turns,
                pattern_hints=pattern_hints,
                title=title,
            )
            with vision_backend(vision_backend_name):
                raw = _describe_screenshot(shot, prompt)
            chosen = parse_agent_action(raw)

    event = execute_game_action(page, chosen)
    event["source"] = source
    event["screen_key"] = screen_key
    page.wait_for_timeout(350)

    reward, reward_signals = compute_reward(
        page,
        prev_score=prev_score,
        prev_shot_hash=prev_shot_hash,
        turn=turn,
        manual_reward=manual_reward,
    )
    next_key = screen_fingerprint(page)
    if use_rl:
        q_update(game_state, screen_key, action_key(chosen), reward, next_key)

    event["reward"] = reward
    event["reward_signals"] = reward_signals
    event["next_screen_key"] = next_key
    return event


def run_agent(
    url: str,
    *,
    turns: int | None = None,
    vision_backend: str | None = None,
    learn: bool | None = None,
    rl: bool | None = None,
    headless: bool = False,
    settle_seconds: float | None = None,
    auto_start: bool = True,
    manual_reward: float | None = None,
) -> dict[str, Any]:
    from arka.agent.play_website_game import _normalize_url, _run_auto_start, _settle_seconds

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Install browser game support with: pip install playwright && playwright install chromium"
        ) from exc

    target = _normalize_url(url)
    domain = domain_from_url(target)
    max_turns = turns if turns is not None else default_turns()
    do_learn = learn_enabled(learn)
    do_rl = rl_enabled(rl)
    game_state = load_game_state(domain)
    hints = recall_pattern_hints(domain, url=target)

    errors: list[str] = []
    turn_log: list[dict[str, Any]] = []
    total_reward = 0.0
    prev_score: int | None = None
    prev_shot_hash = ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(target, wait_until="load", timeout=30_000)
        page.wait_for_timeout(int(_settle_seconds(settle_seconds) * 1000))
        if auto_start:
            _run_auto_start(page, max_actions=4)
        prev_shot_hash = screenshot_hash(page)

        for turn in range(1, max_turns + 1):
            try:
                event = run_agent_turn(
                    page,
                    turn=turn,
                    max_turns=max_turns,
                    pattern_hints=hints,
                    game_state=game_state,
                    vision_backend_name=vision_backend,
                    use_rl=do_rl,
                    manual_reward=manual_reward,
                    prev_score=prev_score,
                    prev_shot_hash=prev_shot_hash,
                )
            except Exception as exc:
                event = {"turn": turn, "status": "failed", "error": str(exc), "source": "vision"}
            turn_log.append({"turn": turn, **event})
            total_reward += float(event.get("reward") or 0.0)
            from arka.agent.game_learning import extract_score_value

            prev_score = extract_score_value(page) or prev_score
            prev_shot_hash = event.get("next_screen_key") or screenshot_hash(page)

        title = page.title()
        browser.close()

    successful = [row for row in turn_log if row.get("status") == "passed"]
    if do_learn and successful and total_reward > 0:
        remember_pattern(
            domain,
            url=target,
            actions=[row.get("action", row) for row in successful if isinstance(row.get("action"), dict)]
            or [{"type": "key", "key": "ArrowUp"}],
            reward=total_reward,
            screen_hint=title or domain,
        )
    if do_rl or do_learn:
        save_game_state(domain, game_state)

    status = response.status if response else None
    return {
        "url": target,
        "domain": domain,
        "title": title,
        "status": status,
        "headless": headless,
        "turns": max_turns,
        "vision_backend": vision_backend or os.environ.get("DESCRIBE_IMAGE_BACKEND", "auto"),
        "learn": do_learn,
        "rl": do_rl,
        "total_reward": round(total_reward, 3),
        "turns_log": turn_log,
        "pattern_hints_used": len(hints),
        "console_errors": errors,
        "experimental": True,
        "ok": bool(status and status < 400 and not errors),
        "message": f"Agent played {max_turns} turn(s) on {target} (reward={total_reward:.2f}, experimental)",
    }
