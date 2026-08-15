"""Pattern learning and lightweight Q-table RL for browser games (experimental)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_EPSILON = 0.15
DEFAULT_ALPHA = 0.3
DEFAULT_GAMMA = 0.9
MAX_PATTERN_HINTS = 5
MAX_STORED_PATTERNS = 20

SCORE_RE = re.compile(
    r"\b(?:score|points?|high\s*score|level|lives?|time|coins?)\s*[:\-]?\s*(\d+)",
    re.I,
)


def domain_from_url(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url.strip())
    host = (parsed.netloc or parsed.path or "unknown").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def patterns_dir() -> Path:
    try:
        from arka.paths import config_dir

        base = config_dir() / "game_patterns"
    except ImportError:
        base = Path.home() / ".config" / "arka" / "game_patterns"
    base.mkdir(parents=True, exist_ok=True)
    return base


def state_path(domain: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "_", domain.lower()).strip("_") or "unknown"
    return patterns_dir() / f"{safe}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_game_state(domain: str) -> dict[str, Any]:
    path = state_path(domain)
    if not path.is_file():
        return {"domain": domain, "patterns": [], "q_table": {}, "meta": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"domain": domain, "patterns": [], "q_table": {}, "meta": {}}
    if not isinstance(data, dict):
        return {"domain": domain, "patterns": [], "q_table": {}, "meta": {}}
    data.setdefault("domain", domain)
    data.setdefault("patterns", [])
    data.setdefault("q_table", {})
    data.setdefault("meta", {})
    return data


def save_game_state(domain: str, state: dict[str, Any]) -> Path:
    path = state_path(domain)
    payload = {
        "domain": domain,
        "patterns": state.get("patterns", [])[:MAX_STORED_PATTERNS],
        "q_table": state.get("q_table", {}),
        "meta": {**dict(state.get("meta") or {}), "updated_at": _now_iso()},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def action_key(action: dict[str, Any]) -> str:
    kind = str(action.get("type", "")).lower()
    if kind == "key":
        return f"key:{action.get('key', 'ArrowUp')}"
    if kind == "click":
        return f"click:{action.get('selector', 'canvas')}:{action.get('index', 0)}"
    if kind == "wait":
        return f"wait:{action.get('ms', 500)}"
    return f"other:{kind}"


def parse_action_key(key: str) -> dict[str, Any]:
    if key.startswith("key:"):
        return {"type": "key", "key": key.split(":", 1)[1]}
    if key.startswith("click:"):
        parts = key.split(":")
        selector = parts[1] if len(parts) > 1 else "canvas"
        index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        return {"type": "click", "selector": selector, "index": index}
    if key.startswith("wait:"):
        ms = int(key.split(":", 1)[1]) if key.split(":", 1)[1].isdigit() else 500
        return {"type": "wait", "ms": ms}
    return {"type": "wait", "ms": 300}


def screen_fingerprint(page: Any) -> str:
    title = ""
    body = ""
    canvas_count = 0
    try:
        title = page.title() or ""
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=1000) or ""
    except Exception:
        pass
    try:
        canvas_count = page.locator("canvas").count()
    except Exception:
        pass
    blob = f"{title}\n{' '.join(body.split())[:400]}\ncanvas={canvas_count}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def extract_score_value(page: Any) -> int | None:
    try:
        text = page.locator("body").inner_text(timeout=1000) or ""
    except Exception:
        return None
    values = [int(m.group(1)) for m in SCORE_RE.finditer(text)]
    return max(values) if values else None


def screenshot_hash(page: Any) -> str:
    try:
        data = page.screenshot(type="png", full_page=False)
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return ""


def compute_reward(
    page: Any,
    *,
    prev_score: int | None,
    prev_shot_hash: str,
    turn: int,
    manual_reward: float | None = None,
) -> tuple[float, dict[str, Any]]:
    signals: dict[str, Any] = {}
    if manual_reward is not None:
        signals["manual"] = manual_reward
        return float(manual_reward), signals

    reward = 0.0
    score = extract_score_value(page)
    if score is not None and prev_score is not None and score > prev_score:
        delta = score - prev_score
        reward += min(1.0, delta / 10.0)
        signals["score_delta"] = delta
    elif score is not None and prev_score is None:
        signals["score_seen"] = score

    shot_hash = screenshot_hash(page)
    if shot_hash and prev_shot_hash and shot_hash != prev_shot_hash:
        reward += 0.05
        signals["screen_changed"] = True
    signals["survival_turn"] = turn
    reward += 0.01
    return reward, signals


def q_epsilon() -> float:
    raw = os.environ.get("ARKA_GAME_RL_EPSILON", str(DEFAULT_EPSILON)).strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return DEFAULT_EPSILON


def q_alpha() -> float:
    raw = os.environ.get("ARKA_GAME_RL_ALPHA", str(DEFAULT_ALPHA)).strip()
    try:
        return max(0.01, min(1.0, float(raw)))
    except ValueError:
        return DEFAULT_ALPHA


def q_gamma() -> float:
    raw = os.environ.get("ARKA_GAME_RL_GAMMA", str(DEFAULT_GAMMA)).strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return DEFAULT_GAMMA


def q_best_action(state: dict[str, Any], screen_key: str) -> tuple[str, float] | None:
    table = state.get("q_table") or {}
    row = table.get(screen_key) or {}
    if not row:
        return None
    best_key = max(row, key=lambda k: float(row[k]))
    return best_key, float(row[best_key])


def q_update(state: dict[str, Any], screen_key: str, act_key: str, reward: float, next_screen_key: str | None = None) -> None:
    table = state.setdefault("q_table", {})
    row = table.setdefault(screen_key, {})
    old = float(row.get(act_key, 0.0))
    next_max = 0.0
    if next_screen_key:
        next_row = table.get(next_screen_key) or {}
        if next_row:
            next_max = max(float(v) for v in next_row.values())
    alpha = q_alpha()
    gamma = q_gamma()
    row[act_key] = old + alpha * (reward + gamma * next_max - old)


def pattern_hints(state: dict[str, Any], *, limit: int = MAX_PATTERN_HINTS) -> list[dict[str, Any]]:
    patterns = list(state.get("patterns") or [])
    patterns.sort(key=lambda p: float(p.get("reward", 0)), reverse=True)
    return patterns[:limit]


def remember_pattern(
    domain: str,
    *,
    url: str,
    actions: list[dict[str, Any]],
    reward: float,
    screen_hint: str = "",
) -> None:
    if not actions or reward <= 0:
        return
    state = load_game_state(domain)
    entry = {
        "url": url,
        "screen_hint": screen_hint[:200],
        "actions": actions[-8:],
        "reward": round(reward, 3),
        "updated_at": _now_iso(),
    }
    patterns = [entry, *(p for p in state.get("patterns", []) if p.get("actions") != entry["actions"])]
    state["patterns"] = patterns[:MAX_STORED_PATTERNS]
    save_game_state(domain, state)
    if os.environ.get("ARKA_GAME_LEARN_PATTERNS", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    try:
        from arka.core.unified_memory import remember

        summary = (
            f"game pattern {domain}: after {screen_hint or 'gameplay'} try "
            + ", ".join(action_key(a) for a in actions[-4:])
        )
        remember(summary, layer="note")
    except Exception:
        pass


def recall_pattern_hints(domain: str, *, url: str = "") -> list[dict[str, Any]]:
    state = load_game_state(domain)
    hints = pattern_hints(state)
    if hints:
        return hints
    goal = f"browser game patterns {domain} {url}".strip()
    try:
        from arka.core.unified_memory import recall

        text = recall(goal, limit_chars=1200)
        if text and text != "(no matching memory)":
            return [{"screen_hint": text[:300], "actions": [], "reward": 0.0, "source": "memory"}]
    except Exception:
        pass
    return []
