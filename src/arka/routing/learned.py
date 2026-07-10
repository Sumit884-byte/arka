"""User-learned NL → skill routing (persisted in ~/.config/arka/learned_routes.json)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

try:
    from arka.paths import config_dir
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"


ROUTE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")
_ARGS_PLACEHOLDER = re.compile(r"\{args\}", re.I)


def learned_routes_path() -> Path:
    return config_dir() / "learned_routes.json"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _slug_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize(text)).strip("-")
    if not slug:
        slug = "route"
    if not ROUTE_ID_RE.match(slug):
        slug = f"route-{slug[:40].strip('-') or 'custom'}"
    return slug


def load_store() -> dict[str, Any]:
    path = learned_routes_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            routes = data.get("routes")
            if isinstance(routes, list):
                return {"version": 1, "routes": routes}
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "routes": []}


def save_store(store: dict[str, Any]) -> Path:
    path = learned_routes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return path


def list_routes(*, enabled_only: bool = True) -> list[dict[str, Any]]:
    routes = load_store().get("routes") or []
    if not isinstance(routes, list):
        return []
    out = [r for r in routes if isinstance(r, dict)]
    if enabled_only:
        out = [r for r in out if r.get("enabled", True) is not False]
    return out


def _find_route(store: dict[str, Any], route_id: str) -> dict[str, Any] | None:
    needle = (route_id or "").strip().lower()
    for route in store.get("routes") or []:
        if not isinstance(route, dict):
            continue
        rid = str(route.get("id") or "").lower()
        if rid == needle:
            return route
        for trig in route.get("triggers") or []:
            if _normalize(str(trig)) == needle:
                return route
    return None


def _render_skill(skill: str, rest: str) -> str:
    template = (skill or "").strip()
    rest = (rest or "").strip()
    if _ARGS_PLACEHOLDER.search(template):
        return _ARGS_PLACEHOLDER.sub(rest, template).strip()
    if rest:
        return f"{template} {rest}".strip()
    return template


def match_learned(text: str) -> str:
    """Return skill invocation for a learned route, or ''."""
    raw = (text or "").strip()
    if not raw:
        return ""
    low = _normalize(raw)

    routes = list_routes(enabled_only=True)
    routes.sort(
        key=lambda r: max((len(_normalize(t)) for t in r.get("triggers") or [""]), default=0),
        reverse=True,
    )

    for route in routes:
        skill = str(route.get("skill") or "").strip()
        if not skill:
            continue
        for trigger in route.get("triggers") or []:
            trig = _normalize(str(trigger))
            if not trig:
                continue
            if low == trig:
                return _render_skill(skill, "")
            if low.startswith(trig + " "):
                idx = low.find(trig)
                rest = raw[idx + len(trigger) :].strip() if idx >= 0 else ""
                return _render_skill(skill, rest)
            if len(trig) >= 4 and trig in low:
                idx = low.find(trig)
                rest = raw[idx + len(trigger) :].strip(" ,:-")
                return _render_skill(skill, rest)
    return ""


def learn_route(
    phrase: str,
    skill: str,
    *,
    route_id: str = "",
    note: str = "",
    extra_triggers: list[str] | None = None,
) -> dict[str, Any]:
    phrase = (phrase or "").strip()
    skill = (skill or "").strip()
    if not phrase:
        raise ValueError("phrase is required")
    if not skill:
        raise ValueError("skill line is required")

    store = load_store()
    routes = store.setdefault("routes", [])
    if not isinstance(routes, list):
        routes = []
        store["routes"] = routes

    rid = (route_id or _slug_id(phrase)).strip().lower()
    if not ROUTE_ID_RE.match(rid):
        rid = _slug_id(phrase)

    triggers = [_normalize(phrase)]
    for t in extra_triggers or []:
        nt = _normalize(t)
        if nt and nt not in triggers:
            triggers.append(nt)

    existing = _find_route(store, rid)
    if existing is None:
        existing = _find_route(store, phrase)
    if existing is not None:
        existing["skill"] = skill
        existing["triggers"] = triggers
        existing["enabled"] = True
        if note:
            existing["note"] = note
        existing["updated"] = time.time()
        save_store(store)
        return existing

    entry = {
        "id": rid,
        "triggers": triggers,
        "skill": skill,
        "enabled": True,
        "note": note.strip(),
        "created": time.time(),
        "updated": time.time(),
    }
    routes.append(entry)
    save_store(store)
    return entry


def delete_route(route_id: str) -> bool:
    needle = (route_id or "").strip().lower()
    if not needle:
        return False
    store = load_store()
    routes = store.get("routes") or []
    if not isinstance(routes, list):
        return False
    kept: list[dict[str, Any]] = []
    removed = False
    for route in routes:
        if not isinstance(route, dict):
            continue
        rid = str(route.get("id") or "").lower()
        trig_hit = any(_normalize(str(t)) == needle for t in route.get("triggers") or [])
        if rid == needle or trig_hit:
            removed = True
            continue
        kept.append(route)
    if removed:
        store["routes"] = kept
        save_store(store)
    return removed


def format_routes_text() -> str:
    routes = list_routes(enabled_only=False)
    if not routes:
        return (
            "No learned routes yet.\n\n"
            "Teach Arka:\n"
            "  arka route learn \"deploy staging\" \"agent_code run deploy.sh\"\n"
            "  arka teach route \"check servers\" \"system_monitor\"\n"
            "  arka route learn --from-trace --correct \"web_answer topic\""
        )
    lines = ["Learned routes:", ""]
    for route in routes:
        status = "on" if route.get("enabled", True) is not False else "off"
        rid = route.get("id") or "?"
        skill = route.get("skill") or ""
        triggers = route.get("triggers") or []
        trig_text = ", ".join(f'"{t}"' for t in triggers[:3])
        if len(triggers) > 3:
            trig_text += f" (+{len(triggers) - 3} more)"
        lines.append(f"- [{status}] {rid}")
        lines.append(f"  say: {trig_text}")
        lines.append(f"  run: {skill}")
        if route.get("note"):
            lines.append(f"  note: {route['note']}")
        lines.append("")
    lines.append("Manage: arka route learn | list | delete <id> | test <phrase>")
    return "\n".join(lines).strip()


def prompt_summary(*, limit: int = 12) -> str:
    routes = list_routes(enabled_only=True)
    if not routes:
        return ""
    lines: list[str] = []
    for route in routes[:limit]:
        skill = str(route.get("skill") or "").strip()
        for trig in route.get("triggers") or [][:2]:
            t = str(trig).strip()
            if t and skill:
                lines.append(f'- "{t}" -> {skill}')
    if not lines:
        return ""
    return "User-learned routes (prefer these exact mappings):\n" + "\n".join(lines)


def parse_teach_request(text: str) -> tuple[str, str] | None:
    """Parse NL like 'teach route X to Y' or 'learn that when I say X run Y'."""
    raw = (text or "").strip()
    if not raw:
        return None

    patterns = [
        r"(?i)^(?:arka\s+)?(?:teach|learn)\s+route\s+(.+?)\s+(?:to|as|->|→)\s+(.+)$",
        r"(?i)^(?:arka\s+)?(?:teach|learn)\s+(?:that\s+)?(?:when\s+i\s+say\s+)?(.+?)\s+(?:means?|should\s+run|runs?|maps?\s+to|->|→)\s+(.+)$",
        r"(?i)^(?:arka\s+)?remember\s+route\s+(.+?)\s+(?:as|->|→)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, raw)
        if m:
            phrase = m.group(1).strip().strip("\"'")
            skill = m.group(2).strip().strip("\"'")
            if phrase and skill:
                return phrase, skill
    return None


def wants_route_management(text: str) -> bool:
    low = _normalize(text)
    if re.search(r"(?i)\b(?:list|show)\s+(?:learned\s+)?routes?\b", low):
        return True
    if re.search(r"(?i)\b(?:learned\s+)?routes?\s+list\b", low):
        return True
    if parse_teach_request(text):
        return True
    return False


def route_management_command(text: str) -> str:
    low = _normalize(text)
    if re.search(r"(?i)\b(?:list|show)\s+(?:learned\s+)?routes?\b", low) or re.search(
        r"(?i)\b(?:learned\s+)?routes?\s+list\b", low
    ):
        return "route_learn list"
    taught = parse_teach_request(text)
    if taught:
        phrase, skill = taught
        return f'route_learn learn {json.dumps(phrase)} {json.dumps(skill)}'
    return ""


def learn_from_trace(*, correct: str = "", phrase: str = "") -> dict[str, Any]:
    try:
        from arka.agent.core import CACHE, load_json
    except ImportError:
        raise RuntimeError("trace support unavailable")

    entry = load_json(CACHE / "trace.json", {})
    if not isinstance(entry, dict) or not entry.get("input"):
        raise ValueError("no routing trace yet — run a request first")

    phrase = (phrase or str(entry.get("input") or "")).strip()
    skill = (correct or str(entry.get("interpreted") or "")).strip()
    if not phrase:
        raise ValueError("phrase is required")
    if not skill:
        raise ValueError("skill line is required (use --correct)")
    return learn_route(phrase, skill, note="from trace")
