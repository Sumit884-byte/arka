#!/usr/bin/env python3
"""Day / interval research — research a topic for a full day or custom duration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_DURATION = "8h"
DEFAULT_INTERVAL = "30m"
MAX_ROUNDS_HARD = 200

ANGLE_SYSTEM = """You plan the next research angle for a long-running research session.
Return ONLY valid JSON (no markdown fences):
{
  "angle": "short specific sub-question",
  "why": "one sentence",
  "extends": ["chunk ids or angle titles this builds on"],
  "target_words": 280,
  "focus_points": ["what this round must establish", "second point"]
}
Rules:
- Prefer angles that EXTEND open questions or thin evidence from the running state
- Do not repeat covered angles; deepen or connect related subtopics instead
- Stay tightly related to the main topic
- Prefer concrete, searchable questions over vague themes
- target_words: integer 180–420 — more words when evidence is thin or the angle is foundational; fewer when narrowing a detail
- focus_points: 2–4 bullets the executor must cover (not generic filler)
"""

ROUND_SYSTEM = """You are writing one research round note for a multi-hour research session.
You are given: web sources, a running research state, retrieved prior chunks, and planner guidance (target length + focus points).
Rules:
- Focus on the assigned angle, but IMPROVE and EXTEND related prior findings when retrieved chunks apply
- Explicitly connect new evidence to prior chunks (e.g. "Building on battery findings…")
- Reconcile contradictions; strengthen weak claims; fill open questions when possible
- Do not paste prior notes verbatim — synthesize forward
- Match the planner's target word count (±15%)
- Start with ## <angle title>
- Include a short **Links to prior research** bullet list when you used retrieved chunks
- End with a Sources: bullet list when URLs/titles are available
"""

CHUNK_EXTRACT_SYSTEM = """Extract a compact memory chunk from one research round.
Return ONLY valid JSON (no markdown fences):
{
  "summary": "2-3 sentence summary of new findings",
  "key_points": ["bullet", "bullet", "bullet"],
  "open_questions": ["what is still unclear"],
  "entities": ["brands", "techs", "metrics"],
  "tags": ["short", "topic", "tags"]
}
Rules:
- Capture only what THIS round established
- open_questions should be actionable follow-ups
- tags: 3–6 lowercase keywords for retrieval
"""

STATE_UPDATE_SYSTEM = """Update the running research state for a multi-hour session.
Return ONLY valid JSON (no markdown fences):
{
  "thesis": "one paragraph current understanding",
  "themes": [{"name": "theme", "status": "solid|thin|contested", "notes": "1-2 sentences"}],
  "open_questions": ["..."],
  "confident_findings": ["..."],
  "next_gaps": ["best gaps to research next"]
}
Rules:
- Merge prior state with the newest chunk — do not discard solid findings
- Mark contradictions as contested
- Keep lists short (max 8 items each)
"""

DIGEST_SYSTEM = """You synthesize a multi-round research session into a clear day-research digest.
You are given the running research state plus memory chunks from each subtopic.
Rules:
- Organize by themes (not round numbers)
- Show how later rounds improved or extended earlier chunks
- Highlight key findings, open questions, and practical takeaways
- Call out contradictions or thin evidence
- Keep it readable (800–1400 words)
- End with Next angles to explore
"""

IMAGE_SEARCH_SYSTEM = """You choose Unsplash stock-photo search queries for a research PDF.
Return ONLY valid JSON:
{"images":[{"file":"cover","query":"..."},{"file":"insight","query":"..."},{"file":"compare","query":"..."}]}
Rules:
- Exactly 3 images with file names: cover, insight, compare
- query: 2–6 words suitable for Unsplash photo search (real objects/scenes, not abstract art prompts)
- cover: broad establishing photo for the topic
- insight: close detail or contextual scene for a key finding
- compare: side-by-side friendly subject (products, places, people at work) when relevant
- No AI-art language (no "illustration", "diagram", "infographic", "render", "3d")
- Stay factual and photographic
"""


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def sessions_root() -> Path:
    return _config_dir() / "day-research" / "sessions"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_duration(text: str | None, *, default: str = DEFAULT_DURATION) -> int:
    """Parse duration like 8h, 90m, 1d, 'entire day' → seconds."""
    raw = (text or default).strip().lower()
    if not raw:
        raw = default
    if re.search(r"(?i)\b(?:entire\s+day|all\s+day|full\s+day|a\s+day|1\s*day|one\s+day)\b", raw) or raw in {
        "day",
        "today",
    }:
        # Workday default; override with DAY_RESEARCH_DAY_HOURS
        hours = float(os.environ.get("DAY_RESEARCH_DAY_HOURS", "8") or "8")
        return max(60, int(hours * 3600))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhd]|sec|secs|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours|day|days)?", raw)
    if not m:
        raise ValueError(f"Unrecognized duration: {text!r} (try 8h, 90m, day)")
    amount = float(m.group(1))
    unit = (m.group(2) or "h").lower()
    if unit.startswith("s"):
        seconds = amount
    elif unit.startswith("m"):
        seconds = amount * 60
    elif unit.startswith("h"):
        seconds = amount * 3600
    else:
        seconds = amount * 86400
    return max(60, int(seconds))


def parse_interval(text: str | None, *, default: str = DEFAULT_INTERVAL) -> int:
    return parse_duration(text or default, default=default)


def session_slug(topic: str) -> str:
    base = re.sub(r"[^\w\s-]", "", (topic or "").strip().lower())
    base = re.sub(r"[-\s]+", "-", base).strip("-")[:40] or "topic"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{base}"


def session_dir(session_id: str) -> Path:
    return sessions_root() / session_id


def session_path(session_id: str) -> Path:
    return session_dir(session_id) / "session.json"


def notes_path(session_id: str) -> Path:
    return session_dir(session_id) / "notes.md"


def stop_flag(session_id: str) -> Path:
    return session_dir(session_id) / "STOP"


def images_dir(session_id: str) -> Path:
    return session_dir(session_id) / "images"


def pdf_path(session_id: str) -> Path:
    return session_dir(session_id) / "research.pdf"


def digest_path(session_id: str) -> Path:
    return session_dir(session_id) / "digest.md"


def chunks_path(session_id: str) -> Path:
    return session_dir(session_id) / "chunks.json"


def state_path(session_id: str) -> Path:
    return session_dir(session_id) / "state.json"


def load_session(session_id: str) -> dict[str, Any] | None:
    path = session_path(session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_session(session: dict[str, Any]) -> None:
    sid = str(session["id"])
    root = session_dir(sid)
    root.mkdir(parents=True, exist_ok=True)
    session_path(sid).write_text(json.dumps(session, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_sessions() -> list[dict[str, Any]]:
    root = sessions_root()
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/session.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def active_session() -> dict[str, Any] | None:
    for row in list_sessions():
        if row.get("status") == "running":
            return row
    return None


def resolve_session_id(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    active = active_session()
    if active:
        return str(active["id"])
    rows = list_sessions()
    return str(rows[0]["id"]) if rows else None


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


_LLM_ERROR_RE = re.compile(
    r"(?i)^(?:\[LLM error:|[Errno\s]+\d+\]|Traceback \(most recent call last\)|"
    r"Read-only file system:|OSError:|PermissionError:)"
)


def _looks_like_runtime_error(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _LLM_ERROR_RE.search(t):
        return True
    # Single-line OSError dumps sometimes land as the whole "completion"
    if re.fullmatch(r"\[Errno \d+\][^\n]{0,200}", t):
        return True
    return False


DEFAULT_ROUND_WORDS = 280
MIN_ROUND_WORDS = 150
MAX_ROUND_WORDS = 450

# Planner: strong model — angles, word budgets, state strategy, image direction
# Executor: cheaper model — round prose, chunk extract, digest aggregation
_LLM_ROLES: dict[str, dict[str, Any]] = {
    "planner": {"skill": "day_research_planner", "task": "agent", "temperature": 0.35},
    "executor": {"skill": "day_research_executor", "task": "summarize", "temperature": 0.55},
}


def clamp_target_words(value: Any, *, default: int = DEFAULT_ROUND_WORDS) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(MIN_ROUND_WORDS, min(MAX_ROUND_WORDS, n))


def _llm(
    system: str,
    user: str,
    *,
    role: str = "executor",
    temperature: float | None = None,
) -> str:
    cfg = _LLM_ROLES.get(role) or _LLM_ROLES["executor"]
    temp = cfg["temperature"] if temperature is None else temperature
    try:
        from arka.llm.cli import llm_complete

        out = (
            llm_complete(
                system,
                user,
                temp,
                task=str(cfg["task"]),
                skill=str(cfg["skill"]),
            )
            or ""
        ).strip()
        if _looks_like_runtime_error(out):
            print(f"LLM error ({role}, ignored): {out[:200]}", file=sys.stderr)
            return ""
        return out
    except ImportError:
        pass
    try:
        from arka.agent.core import _llm as core_llm

        out = (core_llm(system, user, temperature=temp, task=str(cfg["task"])) or "").strip()
        if _looks_like_runtime_error(out):
            print(f"LLM error ({role}, ignored): {out[:200]}", file=sys.stderr)
            return ""
        return out
    except Exception as exc:
        print(f"LLM error ({role}): {exc}", file=sys.stderr)
        return ""


def _web_context(query: str, *, deep: bool = True) -> str:
    try:
        from arka.agent.core import _research_web_context

        return (_research_web_context(query, deep=deep) or "").strip()
    except Exception as exc:
        return f"[web error: {exc}]"


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def load_chunks(session_id: str) -> list[dict[str, Any]]:
    path = chunks_path(session_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_chunks(session_id: str, chunks: list[dict[str, Any]]) -> None:
    path = chunks_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state(session_id: str) -> dict[str, Any]:
    path = state_path(session_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(session_id: str, state: dict[str, Any]) -> None:
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


_STOPWORDS = frozenset(
    "a an the and or but if in on of to for with from by as at is are was were be been "
    "this that these those it its into about over under than then so not no yes do does "
    "did doing done can could should would will just also more most other such only own "
    "same too very what when where which who how why".split()
)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{2,}", (text or "").lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _chunk_text_blob(chunk: dict[str, Any]) -> str:
    parts = [
        str(chunk.get("angle") or ""),
        str(chunk.get("summary") or ""),
        " ".join(str(x) for x in (chunk.get("key_points") or [])),
        " ".join(str(x) for x in (chunk.get("open_questions") or [])),
        " ".join(str(x) for x in (chunk.get("entities") or [])),
        " ".join(str(x) for x in (chunk.get("tags") or [])),
    ]
    return " ".join(parts)


def score_chunk(query: str, chunk: dict[str, Any]) -> float:
    q = _tokenize(query)
    if not q:
        return 0.0
    blob = _tokenize(_chunk_text_blob(chunk))
    if not blob:
        return 0.0
    overlap = len(q & blob)
    # Prefer richer chunks and recent ones slightly
    richness = min(1.0, len(blob) / 40.0)
    recency = min(1.0, float(chunk.get("round") or 0) / 20.0)
    return overlap + 0.25 * richness + 0.15 * recency


def retrieve_chunks(
    session_id: str,
    query: str,
    *,
    limit: int = 4,
    exclude_rounds: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Lexical retrieval over prior subtopic chunks (no embedding dependency)."""
    exclude = exclude_rounds or set()
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in load_chunks(session_id):
        if int(chunk.get("round") or 0) in exclude:
            continue
        scored.append((score_chunk(query, chunk), chunk))
    scored.sort(key=lambda row: row[0], reverse=True)
    # Keep chunks with any signal; if none, fall back to most recent
    hits = [c for s, c in scored if s > 0][:limit]
    if hits:
        return hits
    recent = [c for _, c in scored[:limit]]
    return recent


def format_chunks_for_prompt(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "(no prior chunks yet)"
    blocks: list[str] = []
    for chunk in chunks:
        cid = chunk.get("id") or f"r{chunk.get('round')}"
        points = chunk.get("key_points") or []
        opens = chunk.get("open_questions") or []
        blocks.append(
            f"### Chunk {cid} — {chunk.get('angle')}\n"
            f"Summary: {chunk.get('summary')}\n"
            f"Key points: {'; '.join(str(p) for p in points) or '(none)'}\n"
            f"Open questions: {'; '.join(str(p) for p in opens) or '(none)'}\n"
            f"Tags: {', '.join(str(t) for t in (chunk.get('tags') or []))}"
        )
    return "\n\n".join(blocks)


def format_state_for_prompt(state: dict[str, Any]) -> str:
    if not state:
        return "(empty — first rounds establish the baseline)"
    themes = state.get("themes") or []
    theme_lines = []
    for row in themes[:8]:
        if isinstance(row, dict):
            theme_lines.append(
                f"- {row.get('name')} [{row.get('status')}]: {row.get('notes')}"
            )
    return (
        f"Thesis: {state.get('thesis') or '(none)'}\n"
        f"Themes:\n{chr(10).join(theme_lines) or '- (none)'}\n"
        f"Confident findings: {'; '.join(str(x) for x in (state.get('confident_findings') or [])[:8]) or '(none)'}\n"
        f"Open questions: {'; '.join(str(x) for x in (state.get('open_questions') or [])[:8]) or '(none)'}\n"
        f"Next gaps: {'; '.join(str(x) for x in (state.get('next_gaps') or [])[:8]) or '(none)'}"
    )


def _heuristic_chunk(angle: str, body: str, round_no: int) -> dict[str, Any]:
    """Fallback when LLM JSON extract fails — still persist usable memory."""
    text = re.sub(r"\s+", " ", body or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]
    summary = " ".join(sentences[:2])[:500] or text[:400]
    tags = sorted(list(_tokenize(f"{angle} {summary}")))[:8]
    return {
        "summary": summary,
        "key_points": sentences[:3] or [summary],
        "open_questions": [],
        "entities": [],
        "tags": tags,
        "round": round_no,
        "angle": angle,
    }


def extract_chunk(angle: str, body: str, round_no: int) -> dict[str, Any]:
    raw = _llm(
        CHUNK_EXTRACT_SYSTEM,
        f"Angle: {angle}\nRound: {round_no}\n\nRound note:\n{body[:5000]}",
        role="executor",
    )
    data = _extract_json(raw) or {}
    if not data.get("summary"):
        data = _heuristic_chunk(angle, body, round_no)
    chunk = {
        "id": f"r{round_no}",
        "round": round_no,
        "angle": angle,
        "summary": str(data.get("summary") or "").strip(),
        "key_points": [str(x).strip() for x in (data.get("key_points") or []) if str(x).strip()][:8],
        "open_questions": [
            str(x).strip() for x in (data.get("open_questions") or []) if str(x).strip()
        ][:8],
        "entities": [str(x).strip() for x in (data.get("entities") or []) if str(x).strip()][:12],
        "tags": [str(x).strip().lower() for x in (data.get("tags") or []) if str(x).strip()][:8],
        "created_at": _iso(_now()),
        "excerpt": (body or "")[:1200],
    }
    if not chunk["key_points"]:
        chunk["key_points"] = [chunk["summary"]]
    if not chunk["tags"]:
        chunk["tags"] = sorted(list(_tokenize(f"{angle} {chunk['summary']}")))[:8]
    return chunk


def update_research_state(session: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    sid = str(session["id"])
    prior = load_state(sid)
    raw = _llm(
        STATE_UPDATE_SYSTEM,
        f"Topic: {session['topic']}\n\nPrior state JSON:\n{json.dumps(prior, ensure_ascii=False)[:6000]}\n\n"
        f"Newest chunk JSON:\n{json.dumps(chunk, ensure_ascii=False)[:4000]}",
        role="planner",
    )
    data = _extract_json(raw) or {}
    if not data.get("thesis"):
        # Merge heuristically so progress never stalls
        findings = list(prior.get("confident_findings") or [])
        if chunk.get("summary"):
            findings.append(str(chunk["summary"]))
        opens = list(dict.fromkeys([*(prior.get("open_questions") or []), *(chunk.get("open_questions") or [])]))
        data = {
            "thesis": prior.get("thesis")
            or f"Researching {session['topic']}: {chunk.get('summary', '')}",
            "themes": prior.get("themes")
            or [{"name": chunk.get("angle"), "status": "thin", "notes": chunk.get("summary")}],
            "open_questions": opens[:8],
            "confident_findings": findings[-8:],
            "next_gaps": opens[:5] or list(prior.get("next_gaps") or []),
        }
    data["updated_at"] = _iso(_now())
    data["rounds_incorporated"] = int(session.get("rounds_done") or chunk.get("round") or 0)
    save_state(sid, data)
    return data


def backfill_chunks_from_notes(session: dict[str, Any]) -> int:
    """Create chunks for legacy notes that predate chunk memory."""
    sid = str(session["id"])
    existing = {int(c.get("round") or 0) for c in load_chunks(sid)}
    notes = notes_path(sid)
    if not notes.is_file():
        return 0
    text = notes.read_text(encoding="utf-8")
    parts = re.split(r"\n(?=<!-- round \d+)", text)
    created = 0
    chunks = load_chunks(sid)
    for part in parts:
        m = re.match(r"<!-- round (\d+) @ ([^>]+) -->\s*", part.strip())
        if not m:
            continue
        round_no = int(m.group(1))
        if round_no in existing:
            continue
        body = part[m.end() :].strip()
        heading = re.search(r"^##\s+(.+)$", body, re.M)
        angle = heading.group(1).strip() if heading else f"round {round_no}"
        chunk = extract_chunk(angle, body, round_no)
        chunks.append(chunk)
        existing.add(round_no)
        created += 1
    if created:
        chunks.sort(key=lambda c: int(c.get("round") or 0))
        save_chunks(sid, chunks)
        # Refresh state from latest chunk
        update_research_state(session, chunks[-1])
    return created


def plan_next_angle(session: dict[str, Any]) -> str:
    sid = str(session["id"])
    covered = session.get("angles") or []
    state = load_state(sid)
    # Retrieve chunks around open gaps so the next angle extends prior work
    gap_query = " ".join(
        str(x)
        for x in [
            *(state.get("open_questions") or [])[:5],
            *(state.get("next_gaps") or [])[:5],
            session["topic"],
        ]
    )
    related = retrieve_chunks(sid, gap_query or session["topic"], limit=5)
    user = (
        f"Topic: {session['topic']}\n"
        f"Prior angles ({len(covered)}):\n"
        + ("\n".join(f"- {a}" for a in covered[-40:]) if covered else "- (none yet)")
        + "\n\nRunning research state:\n"
        + format_state_for_prompt(state)
        + "\n\nRelevant prior chunks:\n"
        + format_chunks_for_prompt(related)
        + "\n\nPick the next angle that extends or improves prior subtopics."
    )
    raw = _llm(ANGLE_SYSTEM, user, role="planner")
    data = _extract_json(raw) or {}
    angle = str(data.get("angle") or "").strip()
    target_words = clamp_target_words(data.get("target_words"))
    focus_points = [str(x).strip() for x in (data.get("focus_points") or []) if str(x).strip()][:6]
    if not angle:
        gaps = state.get("next_gaps") or state.get("open_questions") or []
        if gaps:
            angle = str(gaps[0])
        else:
            n = len(covered) + 1
            angle = f"{session['topic']} — deep dive angle {n}"
        target_words = DEFAULT_ROUND_WORDS
    # Stash planner metadata for the upcoming round
    session["_planned_extends"] = data.get("extends") or [c.get("id") for c in related[:3]]
    session["_planned_words"] = target_words
    session["_planned_focus"] = focus_points or [str(data.get("why") or angle)]
    return angle


def run_round(session: dict[str, Any], *, deep: bool = True) -> dict[str, Any]:
    sid = str(session["id"])
    # Ensure legacy sessions get chunk memory before we retrieve
    if not load_chunks(sid) and notes_path(sid).is_file():
        try:
            backfill_chunks_from_notes(session)
        except Exception as exc:
            print(f"Chunk backfill skipped: {exc}", file=sys.stderr)

    angle = plan_next_angle(session)
    sources = _web_context(f"{session['topic']}: {angle}", deep=deep)
    related = retrieve_chunks(sid, f"{session['topic']} {angle}", limit=4)
    state = load_state(sid)
    target_words = clamp_target_words(session.get("_planned_words"))
    focus_points = session.get("_planned_focus") or []
    focus_block = "\n".join(f"- {p}" for p in focus_points) if focus_points else "- (cover the angle thoroughly)"
    user = (
        f"Main topic: {session['topic']}\n"
        f"This round's angle: {angle}\n"
        f"Planner target length: ~{target_words} words\n"
        f"Planner focus points:\n{focus_block}\n"
        f"Planner extends: {session.get('_planned_extends') or []}\n\n"
        f"Running research state:\n{format_state_for_prompt(state)}\n\n"
        f"Retrieved prior chunks (use these to improve/extend):\n"
        f"{format_chunks_for_prompt(related)}\n\n"
        f"New web sources:\n{sources or '(no web sources)'}\n"
    )
    body = _llm(ROUND_SYSTEM, user, role="executor")
    if not body:
        body = f"## {angle}\n\nCould not generate this round — check LLM / network.\n"

    round_no = int(session.get("rounds_done") or 0) + 1
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    used_ids = [str(c.get("id")) for c in related if c.get("id")]
    link_line = ""
    if used_ids:
        link_line = f"\n<!-- used_chunks: {', '.join(used_ids)} -->\n"
    block = f"\n\n<!-- round {round_no} @ {stamp} -->{link_line}\n{body.strip()}\n"
    notes = notes_path(sid)
    notes.parent.mkdir(parents=True, exist_ok=True)
    if not notes.is_file():
        notes.write_text(f"# Day research: {session['topic']}\n", encoding="utf-8")
    with notes.open("a", encoding="utf-8") as fh:
        fh.write(block)

    chunk = extract_chunk(angle, body, round_no)
    chunk["used_chunks"] = used_ids
    chunks = load_chunks(sid)
    chunks = [c for c in chunks if int(c.get("round") or 0) != round_no]
    chunks.append(chunk)
    chunks.sort(key=lambda c: int(c.get("round") or 0))
    save_chunks(sid, chunks)

    session.setdefault("angles", []).append(angle)
    session["rounds_done"] = round_no
    session["last_round_at"] = _iso(_now())
    session["updated_at"] = _iso(_now())
    session["chunk_count"] = len(chunks)
    session.pop("_planned_extends", None)
    session.pop("_planned_words", None)
    session.pop("_planned_focus", None)
    save_session(session)

    state = update_research_state(session, chunk)
    print(
        f"  memory: {len(chunks)} chunks · retrieved {len(related)} · "
        f"open questions {len(state.get('open_questions') or [])}",
        flush=True,
    )
    return {
        "round": round_no,
        "angle": angle,
        "chars": len(body),
        "retrieved": used_ids,
        "chunk_id": chunk.get("id"),
    }


def _routine_id_for(session_id: str) -> str:
    # launchd label-safe, stable per session
    slug = re.sub(r"[^a-z0-9]+", "", session_id.lower())[:24] or "session"
    return f"dayresearch-{slug}"


def _schedule_persistent(session: dict[str, Any]) -> str | None:
    """Install a reboot-surviving timer that calls `day_research due`."""
    sid = str(session["id"])
    interval_m = max(1, int(session.get("interval_seconds") or 1800) // 60)
    schedule = f"every {interval_m}m"
    action = f"day_research due --session {sid}"
    rid = _routine_id_for(sid)
    try:
        from arka.integrations.routines import routine_add

        routine_add(schedule, action, name=rid, auto_install=True)
    except Exception as exc:
        print(f"Warning: could not install persistent schedule: {exc}", file=sys.stderr)
        print(f'  Manual: arka routines add {schedule} {shlex.quote(action)} --install --name {rid}')
        return None
    session["routine_id"] = rid
    session["scheduler"] = "routine"
    session["updated_at"] = _iso(_now())
    save_session(session)
    return rid


def _unschedule_persistent(session: dict[str, Any] | None) -> None:
    if not session:
        return
    rid = str(session.get("routine_id") or _routine_id_for(str(session.get("id") or "")))
    if not rid:
        return
    try:
        from arka.integrations.routines import routine_remove

        routine_remove(rid)
    except Exception:
        pass


def _seconds_since_last_round(session: dict[str, Any]) -> float | None:
    raw = session.get("last_round_at")
    if not raw:
        return None
    try:
        return (_now() - _parse_iso(str(raw))).total_seconds()
    except Exception:
        return None


def _build_digest_text(session: dict[str, Any]) -> str:
    sid = str(session["id"])
    if not load_chunks(sid) and notes_path(sid).is_file():
        try:
            backfill_chunks_from_notes(session)
        except Exception:
            pass
    notes = notes_path(sid)
    body = notes.read_text(encoding="utf-8") if notes.is_file() else ""
    state = load_state(sid)
    chunks = load_chunks(sid)
    chunk_briefs = format_chunks_for_prompt(chunks[-12:])
    digest = _llm(
        DIGEST_SYSTEM,
        f"Topic: {session['topic']}\nRounds: {session.get('rounds_done', 0)}\n\n"
        f"Running research state:\n{format_state_for_prompt(state)}\n\n"
        f"Memory chunks:\n{chunk_briefs}\n\n"
        f"Full notes (tail):\n{body[-16000:]}",
        role="executor",
    )
    if not digest:
        digest = body or f"# {session['topic']}\n\nNo notes yet.\n"
    out = digest_path(sid)
    out.write_text(digest.strip() + "\n", encoding="utf-8")
    return digest.strip()


def _default_image_searches(session: dict[str, Any]) -> list[dict[str, str]]:
    topic = str(session.get("topic") or "research").strip()
    angles = [str(a) for a in (session.get("angles") or [])[-3:] if str(a).strip()]
    insight_hint = angles[-1] if angles else topic
    return [
        {"file": "cover", "query": f"{topic} editorial"},
        {"file": "insight", "query": insight_hint[:60]},
        {"file": "compare", "query": f"{topic} comparison"},
    ]


def _plan_image_searches(session: dict[str, Any], digest: str) -> list[dict[str, str]]:
    defaults = _default_image_searches(session)
    raw = _llm(
        IMAGE_SEARCH_SYSTEM,
        f"Topic: {session['topic']}\nAngles: {', '.join((session.get('angles') or [])[-8:])}\n\n"
        f"Digest excerpt:\n{digest[:3000]}",
        role="planner",
    )
    data = _extract_json(raw) or {}
    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, list) or not images:
        return defaults
    out: list[dict[str, str]] = []
    for i, row in enumerate(images[:3]):
        if not isinstance(row, dict):
            continue
        query = str(row.get("query") or row.get("prompt") or "").strip()
        if not query:
            continue
        file_stem = re.sub(r"[^\w-]+", "", str(row.get("file") or defaults[i]["file"])) or defaults[i]["file"]
        out.append({"file": file_stem, "query": query})
    return out or defaults


def _existing_image_path(root: Path, stem: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = root / f"{stem}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 1000:
            return candidate
    return None


def _generate_session_images(session: dict[str, Any], digest: str) -> list[Path]:
    """Fetch landscape Unsplash photos for the research PDF (no AI image generation)."""
    if session.get("pdf_images") is False:
        return []
    sid = str(session["id"])
    root = images_dir(sid)
    root.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    credits: list[dict[str, str]] = []

    try:
        from arka.media.unsplash import access_key, download_photo, search_photos, setup_hint
    except ImportError as exc:
        print(f"Unsplash module unavailable: {exc}", file=sys.stderr)
        return []

    if not access_key():
        print(f"PDF images skipped — {setup_hint()}", file=sys.stderr)
        return []

    searches = _plan_image_searches(session, digest)
    used_photo_ids: set[str] = set()
    for spec in searches:
        stem = spec["file"]
        existing = _existing_image_path(root, stem)
        if existing:
            saved.append(existing)
            continue
        query = spec["query"]
        try:
            hits = search_photos(query, count=5, orientation="landscape")
        except SystemExit as exc:
            print(f"PDF images skipped: {exc}", file=sys.stderr)
            return saved
        except Exception as exc:
            print(f"  unsplash search skipped ({stem}): {exc}", file=sys.stderr)
            continue
        photo = next((p for p in hits if p.id and p.id not in used_photo_ids), None)
        if not photo:
            print(f"  unsplash: no photo for {stem!r} ({query!r})", file=sys.stderr)
            continue
        used_photo_ids.add(photo.id)
        out = root / f"{stem}.jpg"
        try:
            download_photo(photo, out)
            saved.append(out)
            credits.append(
                {
                    "file": stem,
                    "query": query,
                    "photographer": photo.photographer,
                    "photographer_url": photo.photographer_url,
                    "photo_url": photo.url,
                    "description": photo.description or photo.alt_description or query,
                }
            )
            print(f"  unsplash ({stem}): {query!r} — {photo.photographer}")
        except Exception as exc:
            print(f"  unsplash download skipped ({stem}): {exc}", file=sys.stderr)

    session["image_paths"] = [str(p) for p in saved]
    if credits:
        session["image_credits"] = credits
        credits_path = root / "credits.json"
        credits_path.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    session["updated_at"] = _iso(_now())
    save_session(session)
    return saved


def _escape_pdf(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_inline_md(text: str) -> str:
    """Minimal markdown → reportlab Paragraph markup."""
    t = _escape_pdf(text or "")
    t = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<link href="{_escape_pdf(m.group(2))}" color="#2563eb">{m.group(1)}</link>',
        t,
    )
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier" size="9" color="#475569">\1</font>', t)
    return t


def _pdf_styles(base: Any, colors: Any) -> dict[str, Any]:
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle

    return {
        "Title": ParagraphStyle(
            "DRTitle",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=30,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6,
        ),
        "Kicker": ParagraphStyle(
            "DRKicker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#6366f1"),
            spaceAfter=4,
            letterSpacing=1.2,
        ),
        "Subtitle": ParagraphStyle(
            "DRSubtitle",
            parent=base["Normal"],
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=14,
        ),
        "Heading1": ParagraphStyle(
            "DRH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=14,
            spaceAfter=8,
        ),
        "Heading2": ParagraphStyle(
            "DRH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#1e40af"),
            spaceBefore=12,
            spaceAfter=6,
            borderPadding=(0, 0, 4, 0),
        ),
        "Heading3": ParagraphStyle(
            "DRH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#334155"),
            spaceBefore=10,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "DRBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "Bullet": ParagraphStyle(
            "DRBullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            leftIndent=16,
            bulletIndent=6,
            spaceAfter=4,
        ),
        "Quote": ParagraphStyle(
            "DRQuote",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569"),
            leftIndent=18,
            borderColor=colors.HexColor("#cbd5e1"),
            borderWidth=0,
            borderPadding=(0, 0, 0, 8),
            spaceAfter=8,
        ),
        "Meta": ParagraphStyle(
            "DRMeta",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=8,
        ),
        "Caption": ParagraphStyle(
            "DRCaption",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#94a3b8"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "SourceLabel": ParagraphStyle(
            "DRSourceLabel",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_LEFT,
        ),
        "SourceLink": ParagraphStyle(
            "DRSourceLink",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#2563eb"),
            alignment=TA_RIGHT,
        ),
        "SectionLabel": ParagraphStyle(
            "DRSection",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=6,
            spaceAfter=10,
        ),
    }


_PRIOR_LINKS_RE = re.compile(r"(?i)^\*{0,2}links to prior research\*{0,2}:?\s*$")
_HTML_COMMENT_RE = re.compile(r"^<!--.*-->\s*$")


def _short_source_label(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").replace("www.", "")
    path = (parsed.path or "").strip("/")
    if path and len(path) > 36:
        path = path[:33] + "…"
    return f"{host}/{path}" if path else host or url


def _parse_source_bullet(stripped: str) -> str | None:
    """Return URL if line is a source bullet (bare URL or markdown link)."""
    bare = re.match(r"^[-*]\s+(https?://\S+)\s*$", stripped)
    if bare:
        return bare.group(1).rstrip(".,;)")
    linked = re.match(r"^[-*]\s+\[(?:[^\]]*)\]\((https?://[^)]+)\)\s*$", stripped)
    if linked:
        return linked.group(1).strip()
    return None


def _source_link_row(url: str, styles: dict[str, Any], content_width: float) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    label = _escape_pdf(_short_source_label(url))
    href = _escape_pdf(url)
    link_text = _escape_pdf(url if len(url) <= 72 else url[:69] + "…")
    left = Paragraph(label, styles["SourceLabel"])
    right = Paragraph(
        f'<link href="{href}" color="#2563eb">{link_text}</link>',
        styles["SourceLink"],
    )
    table = Table(
        [[left, right]],
        colWidths=[content_width * 0.38, content_width * 0.62],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    return table


def _md_to_flowables(
    text: str,
    styles: dict[str, Any],
    *,
    content_width: float = 6.3 * 72,
    defer_sources: bool = False,
) -> list[Any]:
    from reportlab.platypus import HRFlowable, Paragraph, Spacer

    flow: list[Any] = []
    in_sources = False
    in_prior_links = False
    collected_sources: list[str] = []
    seen_sources: set[str] = set()

    def _append_sources_block() -> None:
        if not collected_sources:
            return
        flow.append(Spacer(1, 8))
        flow.append(Paragraph("<b>Sources</b>", styles["Heading3"]))
        for url in collected_sources:
            flow.append(_source_link_row(url, styles, content_width))

    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if not in_sources and not in_prior_links:
                flow.append(Spacer(1, 4))
            in_prior_links = False
            continue
        if _HTML_COMMENT_RE.match(stripped):
            in_prior_links = False
            continue
        if _PRIOR_LINKS_RE.match(stripped):
            in_prior_links = True
            in_sources = False
            continue
        if in_prior_links:
            if re.match(r"^[-*]\s+", stripped):
                continue
            if re.match(r"(?i)^\*{0,2}sources:\*{0,2}\s*$", stripped):
                in_prior_links = False
            elif re.match(r"^#{1,6}\s+", stripped) or re.fullmatch(r"\*{2}.+\*{2}", stripped):
                in_prior_links = False
            else:
                continue
        if re.match(r"^#{1,6}\s+", stripped):
            in_sources = False
            in_prior_links = False
            level = len(re.match(r"^(#+)", stripped).group(1))  # type: ignore[union-attr]
            content = re.sub(r"^#+\s*", "", stripped)
            key = "Heading1" if level == 1 else "Heading2" if level == 2 else "Heading3"
            flow.append(Paragraph(_format_inline_md(content), styles[key]))
            continue
        if re.fullmatch(r"\*{2}(.+?)\*{2}", stripped):
            in_sources = False
            in_prior_links = False
            flow.append(Paragraph(_format_inline_md(stripped), styles["Heading2"]))
            continue
        if stripped in {"---", "***", "___"}:
            in_sources = False
            in_prior_links = False
            flow.append(Spacer(1, 4))
            flow.append(HRFlowable(width="100%", thickness=0.5, color=styles["Body"].textColor, lineCap="round"))
            flow.append(Spacer(1, 6))
            continue
        if stripped.startswith(">"):
            in_sources = False
            in_prior_links = False
            quote = re.sub(r"^>\s*", "", stripped)
            flow.append(Paragraph(_format_inline_md(quote), styles["Quote"]))
            continue
        if re.match(r"(?i)^\*{0,2}sources:\*{0,2}\s*$", stripped):
            in_sources = True
            if not defer_sources:
                flow.append(Spacer(1, 2))
                flow.append(Paragraph("<b>Sources</b>", styles["Heading3"]))
            continue
        source_url = _parse_source_bullet(stripped)
        if source_url:
            in_sources = True
            if defer_sources:
                if source_url not in seen_sources:
                    seen_sources.add(source_url)
                    collected_sources.append(source_url)
            else:
                flow.append(_source_link_row(source_url, styles, content_width))
            continue
        if re.match(r"^[-*]\s+", stripped):
            in_sources = False
            in_prior_links = False
            item = re.sub(r"^[-*]\s+", "", stripped)
            flow.append(Paragraph(f"• {_format_inline_md(item)}", styles["Bullet"]))
            continue
        num = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if num:
            in_sources = False
            in_prior_links = False
            flow.append(Paragraph(f"{num.group(1)}. {_format_inline_md(num.group(2))}", styles["Bullet"]))
            continue
        in_sources = False
        in_prior_links = False
        flow.append(Paragraph(_format_inline_md(stripped), styles["Body"]))
    if defer_sources:
        _append_sources_block()
    return flow


def _image_by_stem(image_paths: list[Path]) -> dict[str, Path]:
    return {p.stem: p for p in image_paths}


def _pdf_cover_page(topic: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch

    def _draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        w, h = letter
        canvas.setFillColor(colors.HexColor("#4f46e5"))
        canvas.rect(0, h - 0.22 * inch, w, 0.22 * inch, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#eef2ff"))
        canvas.rect(0, h - 1.35 * inch, w, 1.13 * inch, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#6366f1"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(doc.leftMargin, h - 0.55 * inch, "ARKA DAY RESEARCH")
        canvas.setFillColor(colors.HexColor("#0f172a"))
        canvas.setFont("Helvetica-Bold", 11)
        title = (topic or "Research")[:72]
        canvas.drawString(doc.leftMargin, h - 0.85 * inch, title)
        canvas.restoreState()

    return _draw


def _pdf_body_page(topic: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch

    short = (topic or "Research")[:56]

    def _draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        w, _h = letter
        canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 0.62 * inch, w - doc.rightMargin, 0.62 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#94a3b8"))
        canvas.drawString(doc.leftMargin, 0.42 * inch, short)
        canvas.drawRightString(w - doc.rightMargin, 0.42 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return _draw


def _load_image_credits(session: dict[str, Any], sid: str) -> dict[str, dict[str, str]]:
    credits_by_file = {
        str(row.get("file") or ""): row for row in (session.get("image_credits") or []) if isinstance(row, dict)
    }
    if credits_by_file:
        return credits_by_file
    credits_file = images_dir(sid) / "credits.json"
    if not credits_file.is_file():
        return {}
    try:
        loaded = json.loads(credits_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, list):
        return {}
    return {str(row.get("file") or ""): row for row in loaded if isinstance(row, dict)}


def _scaled_image_dims(img: Path, max_width: float, *, max_height: float | None = None) -> tuple[float, float]:
    """Fit image to max_width preserving aspect ratio."""
    from reportlab.lib.utils import ImageReader

    try:
        iw, ih = ImageReader(str(img)).getSize()
    except Exception:
        return max_width, max_width * 0.5625
    if not iw or not ih:
        return max_width, max_width * 0.5625
    aspect = iw / ih
    width = max_width
    height = width / aspect
    cap = max_height if max_height is not None else max_width * 0.72
    if height > cap:
        height = cap
        width = height * aspect
    return width, height


def _append_image_block(
    story: list[Any],
    img: Path,
    *,
    styles: dict[str, Any],
    credits_by_file: dict[str, dict[str, str]],
    max_width: float,
    max_height: float | None = None,
) -> None:
    from reportlab.platypus import Image, KeepTogether, Paragraph, Spacer

    try:
        width, height = _scaled_image_dims(img, max_width, max_height=max_height)
        block: list[Any] = [
            Spacer(1, 4),
            Image(str(img), width=width, height=height, hAlign="CENTER"),
        ]
        credit = credits_by_file.get(img.stem)
        if credit:
            who = _escape_pdf(str(credit.get("photographer") or "Unknown"))
            block.append(
                Paragraph(
                    f'Photo: {who} on <link href="https://unsplash.com" color="#2563eb">Unsplash</link>',
                    styles["Caption"],
                )
            )
        block.append(Spacer(1, 6))
        story.append(KeepTogether(block))
    except Exception:
        pass


def export_pdf(session: dict[str, Any], *, with_images: bool | None = None) -> Path | None:
    """Write research.pdf from digest/notes + optional Unsplash stock photos."""
    sid = str(session["id"])
    if session.get("pdf") is False:
        return None
    want_images = session.get("pdf_images", True) if with_images is None else with_images
    digest = ""
    dpath = digest_path(sid)
    if dpath.is_file() and dpath.stat().st_size > 40:
        digest = dpath.read_text(encoding="utf-8")
    else:
        digest = _build_digest_text(session)

    image_paths: list[Path] = []
    if want_images:
        image_paths = _generate_session_images(session, digest)

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        print("reportlab not installed — PDF skipped (pip install reportlab)", file=sys.stderr)
        return None

    topic = str(session.get("topic") or "Research")
    out = pdf_path(sid)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=1.05 * inch,
        bottomMargin=0.85 * inch,
        title=f"Day research — {topic}",
        author="Arka",
    )
    content_width = letter[0] - doc.leftMargin - doc.rightMargin
    base = getSampleStyleSheet()
    styles = _pdf_styles(base, colors)
    credits_by_file = _load_image_credits(session, sid)
    images = _image_by_stem(image_paths)

    story: list[Any] = []
    # Cover
    story.append(Spacer(1, 1.15 * inch))
    story.append(Paragraph("DAY RESEARCH", styles["Kicker"]))
    story.append(Paragraph(_format_inline_md(topic.title() if topic.islower() else topic), styles["Title"]))
    story.append(
        Paragraph(
            _escape_pdf(
                f"{session.get('rounds_done', 0)} research rounds · "
                f"{session.get('status', 'unknown')} · "
                f"{datetime.now().strftime('%B %d, %Y')}"
            ),
            styles["Subtitle"],
        )
    )
    if images.get("cover"):
        _append_image_block(
            story,
            images["cover"],
            styles=styles,
            credits_by_file=credits_by_file,
            max_width=content_width,
            max_height=3.6 * inch,
        )
    story.append(PageBreak())

    # Digest
    story.append(Paragraph("Executive digest", styles["SectionLabel"]))
    story.append(HRFlowable(width="28%", thickness=2, color=colors.HexColor("#6366f1"), spaceAfter=8))
    if images.get("insight"):
        _append_image_block(
            story,
            images["insight"],
            styles=styles,
            credits_by_file=credits_by_file,
            max_width=content_width * 0.92,
            max_height=2.8 * inch,
        )
    story.extend(_md_to_flowables(digest, styles, content_width=content_width))
    if images.get("compare"):
        _append_image_block(
            story,
            images["compare"],
            styles=styles,
            credits_by_file=credits_by_file,
            max_width=content_width * 0.96,
            max_height=3.0 * inch,
        )

    notes = notes_path(sid)
    if notes.is_file():
        story.append(PageBreak())
        story.append(Paragraph("Appendix — round notes", styles["SectionLabel"]))
        story.append(HRFlowable(width="28%", thickness=2, color=colors.HexColor("#6366f1"), spaceAfter=8))
        appendix = notes.read_text(encoding="utf-8")
        if len(appendix) > 12000:
            appendix = appendix[:12000] + "\n\n…(truncated)"
        story.extend(_md_to_flowables(appendix, styles, content_width=content_width, defer_sources=True))

    doc.build(story, onFirstPage=_pdf_cover_page(topic), onLaterPages=_pdf_body_page(topic))
    session["pdf_path"] = str(out)
    session["updated_at"] = _iso(_now())
    save_session(session)
    return out


def _maybe_export_pdf(session: dict[str, Any]) -> None:
    if session.get("pdf") is False:
        return
    try:
        path = export_pdf(session)
        if path:
            print(f"  PDF: {path}")
    except Exception as exc:
        print(f"  PDF export failed: {exc}", file=sys.stderr)


def _finalize_session(session: dict[str, Any], status: str) -> None:
    _mark_status(session, status)
    _unschedule_persistent(session)
    _maybe_export_pdf(load_session(str(session["id"])) or session)


def _session_expired(session: dict[str, Any]) -> bool:
    try:
        return _now() >= _parse_iso(str(session["ends_at"]))
    except Exception:
        return True


def _should_stop(session: dict[str, Any]) -> bool:
    if stop_flag(str(session["id"])).is_file():
        return True
    if session.get("status") in {"stopped", "completed"}:
        return True
    if _session_expired(session):
        return True
    if int(session.get("rounds_done") or 0) >= MAX_ROUNDS_HARD:
        return True
    return False


def _mark_status(session: dict[str, Any], status: str) -> None:
    session["status"] = status
    session["updated_at"] = _iso(_now())
    if status in {"stopped", "completed"}:
        session["finished_at"] = _iso(_now())
        session["pid"] = None
    save_session(session)


def cmd_start(args: argparse.Namespace) -> int:
    topic = " ".join(args.topic).strip()
    if not topic:
        print("Usage: day_research start <topic> [--for 8h|day] [--every 30m]", file=sys.stderr)
        return 1

    existing = active_session()
    if existing and not args.force:
        print(
            f"Already running: {existing['id']} — {existing['topic']}\n"
            f"Stop it first: arka day_research stop\n"
            f"Or force a new session with --force",
            file=sys.stderr,
        )
        return 1
    if existing and args.force:
        _unschedule_persistent(existing)
        _mark_status(existing, "stopped")

    try:
        duration_s = parse_duration(args.duration)
        interval_s = parse_interval(args.every)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if interval_s > duration_s:
        interval_s = max(60, duration_s // 2)

    pdf_enabled = not bool(getattr(args, "no_pdf", False))
    pdf_images = not bool(getattr(args, "no_images", False))
    use_daemon = bool(getattr(args, "daemon", False))

    started = _now()
    ends = started + timedelta(seconds=duration_s)
    sid = session_slug(topic)
    session: dict[str, Any] = {
        "id": sid,
        "topic": topic,
        "status": "running",
        "duration_seconds": duration_s,
        "interval_seconds": interval_s,
        "started_at": _iso(started),
        "ends_at": _iso(ends),
        "rounds_done": 0,
        "angles": [],
        "deep": not args.light,
        "pid": None,
        "pdf": pdf_enabled,
        "pdf_images": pdf_images,
        "scheduler": "daemon" if use_daemon else "routine",
        "updated_at": _iso(started),
    }
    notes = notes_path(sid)
    notes.parent.mkdir(parents=True, exist_ok=True)
    images_dir(sid).mkdir(parents=True, exist_ok=True)
    notes.write_text(
        f"# Day research: {topic}\n\n"
        f"_Started {started.astimezone().strftime('%Y-%m-%d %H:%M')} · "
        f"runs until {ends.astimezone().strftime('%Y-%m-%d %H:%M')} · "
        f"every {interval_s // 60}m · "
        f"PDF={'on' if pdf_enabled else 'off'} "
        f"(images={'on' if pdf_images else 'off'})_\n",
        encoding="utf-8",
    )
    save_session(session)

    print(f"Started day research [{sid}]")
    print(f"  topic:    {topic}")
    print(f"  duration: {duration_s // 3600}h {(duration_s % 3600) // 60}m")
    print(f"  every:    {interval_s // 60}m (persisted aggregation)")
    print(f"  notes:    {notes}")
    print(f"  pdf:      {pdf_path(sid)} ({'default on' if pdf_enabled else 'off'})")
    print("  status:   arka day_research status")
    print("  digest:   arka day_research digest")
    print("  stop:     arka day_research stop")

    # First aggregation immediately so progress exists even if machine sleeps soon
    if not getattr(args, "skip_first", False):
        try:
            info = run_round(session, deep=session["deep"])
            print(f"\nRound {info['round']}: {info['angle']}")
            session = load_session(sid) or session
            _maybe_export_pdf(session)
        except Exception as exc:
            print(f"First round failed (will retry on schedule): {exc}", file=sys.stderr)

    if args.once:
        session = load_session(sid) or session
        if _session_expired(session):
            _finalize_session(session, "completed")
        return 0

    if args.foreground:
        return _run_loop(load_session(sid) or session)

    if use_daemon:
        return _spawn_background(load_session(sid) or session)

    rid = _schedule_persistent(load_session(sid) or session)
    if rid:
        print(f"  schedule: launchd/systemd routine {rid} (survives reboot)")
        print("  tip:      progress is on disk after every 30m tick + PDF refresh")
    return 0


def _python() -> str:
    return sys.executable or "python3"


def _spawn_background(session: dict[str, Any]) -> int:
    sid = str(session["id"])
    log = session_dir(sid) / "daemon.log"
    cmd = [_python(), "-m", "arka.agent.day_research", "run-loop", "--session", sid]
    with log.open("a", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(Path.home()),
        )
    session["pid"] = proc.pid
    session["updated_at"] = _iso(_now())
    save_session(session)
    print(f"  background pid: {proc.pid}")
    print(f"  log: {log}")
    return 0


def _run_loop(session: dict[str, Any]) -> int:
    sid = str(session["id"])
    session["pid"] = os.getpid()
    save_session(session)

    def _handle_signal(signum: int, _frame: Any) -> None:
        stop_flag(sid).write_text(f"signal {signum}\n", encoding="utf-8")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while True:
        fresh = load_session(sid) or session
        if _should_stop(fresh):
            status = "stopped" if stop_flag(sid).is_file() or fresh.get("status") == "stopped" else "completed"
            _finalize_session(fresh, status)
            print(f"Session {sid} {status} after {fresh.get('rounds_done', 0)} rounds.")
            return 0
        try:
            info = run_round(fresh, deep=bool(fresh.get("deep", True)))
            print(f"Round {info['round']}: {info['angle']}", flush=True)
            _maybe_export_pdf(load_session(sid) or fresh)
        except Exception as exc:
            print(f"Round failed: {exc}", file=sys.stderr, flush=True)
        fresh = load_session(sid) or fresh
        if _should_stop(fresh):
            continue
        interval = int(fresh.get("interval_seconds") or parse_interval(DEFAULT_INTERVAL))
        # Sleep in chunks so STOP is responsive
        deadline = time.time() + interval
        while time.time() < deadline:
            if stop_flag(sid).is_file():
                break
            time.sleep(min(5.0, max(0.5, deadline - time.time())))


def cmd_run_loop(args: argparse.Namespace) -> int:
    session = load_session(args.session)
    if not session:
        print(f"Unknown session: {args.session}", file=sys.stderr)
        return 1
    return _run_loop(session)


def cmd_tick(args: argparse.Namespace) -> int:
    sid = resolve_session_id(args.session)
    if not sid:
        print("No research session. Start one: arka day_research start <topic>", file=sys.stderr)
        return 1
    session = load_session(sid)
    if not session:
        print(f"Unknown session: {sid}", file=sys.stderr)
        return 1
    if session.get("status") != "running":
        print(f"Session already ended ({session.get('status')}).")
        return 0
    if _should_stop(session):
        _finalize_session(session, "completed")
        print("Duration reached — session completed + PDF refreshed.")
        return 0
    info = run_round(session, deep=bool(session.get("deep", True)))
    print(f"Round {info['round']}: {info['angle']}")
    session = load_session(sid) or session
    _maybe_export_pdf(session)
    if _session_expired(session):
        _finalize_session(session, "completed")
        print("Duration reached — session completed.")
    return 0


def cmd_due(args: argparse.Namespace) -> int:
    """Idempotent scheduled tick — safe after reboot; skips if interval not elapsed."""
    sid = resolve_session_id(args.session)
    if not sid:
        return 0
    session = load_session(sid)
    if not session:
        return 0
    if session.get("status") != "running":
        _unschedule_persistent(session)
        return 0
    if stop_flag(sid).is_file() or _session_expired(session):
        _finalize_session(session, "completed" if _session_expired(session) else "stopped")
        print(f"Session {sid} finalized.")
        return 0

    interval = int(session.get("interval_seconds") or 1800)
    elapsed = _seconds_since_last_round(session)
    # Allow a little skew; skip if we already aggregated recently
    if elapsed is not None and elapsed < max(60, interval - 30) and not getattr(args, "force", False):
        print(f"Not due yet ({int(elapsed)}s since last round; interval {interval}s).")
        return 0

    info = run_round(session, deep=bool(session.get("deep", True)))
    print(f"Round {info['round']}: {info['angle']}")
    session = load_session(sid) or session
    _maybe_export_pdf(session)
    if _session_expired(session):
        _finalize_session(session, "completed")
        print("Duration reached — session completed.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    sid = resolve_session_id(args.session)
    if not sid:
        print("No day-research sessions yet.")
        print('Start: arka day_research start "your topic" --for day')
        return 0
    session = load_session(sid)
    if not session:
        print(f"Unknown session: {sid}", file=sys.stderr)
        return 1
    # Daemon-only staleness; routine scheduler has no long-lived pid
    if (
        session.get("status") == "running"
        and session.get("scheduler") == "daemon"
        and session.get("pid")
        and not _pid_alive(int(session["pid"]))
    ):
        if _session_expired(session) or stop_flag(sid).is_file():
            _finalize_session(session, "completed" if _session_expired(session) else "stopped")
            session = load_session(sid) or session
        else:
            session["status"] = "stale"
            save_session(session)

    ends = _parse_iso(str(session["ends_at"]))
    remaining = max(0, int((ends - _now()).total_seconds()))
    print(f"Session:   {session['id']}")
    print(f"Topic:     {session['topic']}")
    print(f"Status:    {session.get('status')}")
    print(f"Rounds:    {session.get('rounds_done', 0)}")
    print(f"Chunks:    {len(load_chunks(sid))} (retrieval memory)")
    print(f"Interval:  {int(session.get('interval_seconds', 0)) // 60}m")
    print(f"Scheduler: {session.get('scheduler', 'routine')}"
          + (f" ({session.get('routine_id')})" if session.get("routine_id") else ""))
    print(f"Remaining: {remaining // 3600}h {(remaining % 3600) // 60}m")
    print(f"Notes:     {notes_path(sid)}")
    print(f"State:     {state_path(sid)}")
    print(f"PDF:       {session.get('pdf_path') or pdf_path(sid)}")
    state = load_state(sid)
    if state.get("open_questions"):
        print("Open questions:")
        for q in (state.get("open_questions") or [])[:5]:
            print(f"  - {q}")
    angles = session.get("angles") or []
    if angles:
        print("Recent angles:")
        for angle in angles[-5:]:
            print(f"  - {angle}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    rows = list_sessions()
    if not rows:
        print("No day-research sessions.")
        return 0
    for row in rows[: int(args.limit or 20)]:
        print(
            f"{row.get('status', '?'):10}  {row.get('rounds_done', 0):3} rounds  "
            f"{row.get('id')}  —  {row.get('topic')}"
        )
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    sid = resolve_session_id(args.session)
    if not sid:
        print("No active session to stop.")
        return 0
    session = load_session(sid)
    if not session:
        print(f"Unknown session: {sid}", file=sys.stderr)
        return 1
    stop_flag(sid).write_text("user stop\n", encoding="utf-8")
    pid = session.get("pid")
    if pid and _pid_alive(int(pid)):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    _finalize_session(session, "stopped")
    print(f"Stopped {sid}")
    print(f"Digest: arka day_research digest --session {sid}")
    print(f"PDF:    {pdf_path(sid)}")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    sid = resolve_session_id(args.session)
    if not sid:
        print("No research session.", file=sys.stderr)
        return 1
    session = load_session(sid)
    if not session:
        print(f"Unknown session: {sid}", file=sys.stderr)
        return 1
    notes = notes_path(sid)
    if not notes.is_file() or notes.stat().st_size < 40:
        print("No notes yet — wait for a few rounds.", file=sys.stderr)
        return 1
    digest = _build_digest_text(session)
    print(digest)
    print(f"\nSaved: {digest_path(sid)}")
    if not getattr(args, "no_pdf", False):
        # Force PDF on for explicit digest unless user disabled
        if session.get("pdf") is False and not getattr(args, "pdf", False):
            pass
        else:
            session["pdf"] = True
            if getattr(args, "no_images", False):
                session["pdf_images"] = False
            path = export_pdf(session)
            if path:
                print(f"PDF: {path}")
    return 0


def cmd_pdf(args: argparse.Namespace) -> int:
    sid = resolve_session_id(args.session)
    if not sid:
        print("No research session.", file=sys.stderr)
        return 1
    session = load_session(sid)
    if not session:
        print(f"Unknown session: {sid}", file=sys.stderr)
        return 1
    session["pdf"] = True
    if getattr(args, "no_images", False):
        session["pdf_images"] = False
    elif getattr(args, "images", False):
        session["pdf_images"] = True
        # Force regenerate Unsplash photos
        for p in images_dir(sid).glob("*"):
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                try:
                    p.unlink()
                except OSError:
                    pass
        session.pop("image_credits", None)
    path = export_pdf(session)
    if not path:
        print("PDF export failed.", file=sys.stderr)
        return 1
    print(f"PDF: {path}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    sid = resolve_session_id(args.session)
    if not sid:
        print("No research session.", file=sys.stderr)
        return 1
    notes = notes_path(sid)
    if not notes.is_file():
        print("No notes file yet.", file=sys.stderr)
        return 1
    text = notes.read_text(encoding="utf-8")
    if args.tail and len(text) > args.tail:
        print(text[-args.tail :])
    else:
        print(text)
    return 0


_DURATION_NL = re.compile(
    r"(?i)\b(?:"
    r"(?:for\s+)?(?:the\s+)?(?:entire|whole|full)\s+day|"
    r"all\s*day|"
    r"a\s+full\s+day|"
    r"for\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|days?|d)"
    r")\b"
)
_EVERY_NL = re.compile(
    r"(?i)\bevery\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b"
)


def _is_day_research_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.match(r"(?i)^(?:day[-_ ]?research|interval[-_ ]?research|research[-_ ]session)\b", t):
        return True
    if re.search(r"(?i)\b(?:day[-_ ]research|interval[-_ ]research|research\s+session)\b", t):
        return True
    # research <topic> for <duration> / all day
    if re.search(r"(?i)\b(?:research|investigate|deep\s*dive|study)\b", t) and _DURATION_NL.search(t):
        # avoid youtube / agent_research one-shots without duration intent already covered
        if re.search(r"(?i)\byoutube\b", t):
            return False
        return True
    if re.search(r"(?i)\bresearch\b.+\b(?:all\s*day|entire\s+day|full\s+day)\b", t):
        return True
    return False


def _extract_topic(text: str) -> str:
    t = text.strip()
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:arka\s+)?(?:day[-_ ]?research|interval[-_ ]?research|research[-_ ]session)\s+",
        "",
        t,
    )
    t = re.sub(r"(?i)^\s*(?:start|begin|run)\s+", "", t)
    t = re.sub(
        r"(?i)^(research|investigate|deep\s*dive(?:\s+into)?|study)\s+(?:on\s+|about\s+|into\s+)?",
        "",
        t,
    )
    t = _DURATION_NL.sub(" ", t)
    t = _EVERY_NL.sub(" ", t)
    t = re.sub(
        r"(?i)\b(?:for\s+)?(?:the\s+)?(?:entire|whole|full)\s+day\b|\ball\s*day\b|\btoday\b|\bplease\b|\bnow\b",
        " ",
        t,
    )
    t = re.sub(r"(?i)\b(?:in\s+the\s+background|foreground|once)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -:")
    return t


def _nl_duration(text: str) -> str | None:
    if re.search(r"(?i)\b(?:entire|whole|full)\s+day\b|\ball\s*day\b|\ba\s+day\b|\btoday\b", text):
        return "day"
    m = _DURATION_NL.search(text)
    if not m or not m.group(1):
        return None
    amount, unit = m.group(1), m.group(2).lower()
    if unit.startswith("d"):
        return f"{amount}d"
    if unit.startswith("h"):
        return f"{amount}h"
    return f"{amount}m"


def _nl_every(text: str) -> str | None:
    m = _EVERY_NL.search(text)
    if not m:
        return None
    amount, unit = m.group(1), m.group(2).lower()
    if unit.startswith("h"):
        return f"{amount}h"
    return f"{amount}m"


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_day_research_request(t):
        return []
    if re.search(r"(?i)\b(?:status|progress)\b", t):
        return ["status"]
    if re.search(r"(?i)\b(?:stop|cancel|end)\b", t) and not _DURATION_NL.search(t):
        return ["stop"]
    if re.search(r"(?i)\b(?:digest|summarize|summary)\b", t) and not _DURATION_NL.search(t):
        return ["digest"]
    if re.search(r"(?i)\b(?:pdf|export\s+pdf|make\s+pdf)\b", t) and not _DURATION_NL.search(t):
        return ["pdf"]
    if re.search(r"(?i)\b(?:show|notes|open notes)\b", t) and not _DURATION_NL.search(t):
        return ["show"]
    if re.search(r"(?i)\b(?:tick|run once|one round)\b", t) and not re.search(
        r"(?i)\b(?:research|investigate|study)\b.+\b(?:for|every)\b", t
    ):
        return ["tick"]
    if re.search(r"(?i)\b(?:list(?:\s+sessions)?|sessions)\b", t):
        topic_guess = _extract_topic(t)
        if not topic_guess or topic_guess.lower() in {"list", "sessions", "list sessions"}:
            return ["list"]

    topic = _extract_topic(t)
    # bare "day research" / "day research status" already handled
    if not topic or topic.lower() in {"start", "begin", "run"}:
        return ["status"]

    argv = ["start", topic]
    dur = _nl_duration(t)
    if dur:
        argv.extend(["--for", dur])
    else:
        argv.extend(["--for", "day"])
    every = _nl_every(t)
    if every:
        argv.extend(["--every", every])
    if re.search(r"(?i)\bforeground\b", t):
        argv.append("--foreground")
    if re.search(r"(?i)\b(?:once|one\s+round|single\s+round)\b", t):
        argv.append("--once")
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka day_research",
        description="Research a topic for an entire day or a custom time interval",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start", help="Start a day/interval research session")
    p_start.add_argument("topic", nargs="+")
    p_start.add_argument("--for", dest="duration", default="day", help="Duration: day, 8h, 90m, …")
    p_start.add_argument("--every", default=DEFAULT_INTERVAL, help="Round interval (default 30m)")
    p_start.add_argument("--foreground", action="store_true", help="Run in this terminal")
    p_start.add_argument(
        "--daemon",
        action="store_true",
        help="Use in-process background loop instead of reboot-safe launchd/systemd schedule",
    )
    p_start.add_argument("--once", action="store_true", help="Run a single round then exit")
    p_start.add_argument("--skip-first", action="store_true", help="Do not run the first round immediately")
    p_start.add_argument("--light", action="store_true", help="Lighter web scrape per round")
    p_start.add_argument("--force", action="store_true", help="Start even if another session is running")
    p_start.add_argument("--no-pdf", action="store_true", help="Disable PDF aggregation export")
    p_start.add_argument("--no-images", action="store_true", help="PDF without Unsplash photos")
    p_start.set_defaults(func=cmd_start)

    p_loop = sub.add_parser("run-loop", help=argparse.SUPPRESS)
    p_loop.add_argument("--session", required=True)
    p_loop.set_defaults(func=cmd_run_loop)

    p_due = sub.add_parser("due", help="Scheduled aggregation tick (idempotent, reboot-safe)")
    p_due.add_argument("--session", "-s", help="Session id")
    p_due.add_argument("--force", action="store_true", help="Run even if interval not elapsed")
    p_due.set_defaults(func=cmd_due)

    p_pdf = sub.add_parser("pdf", help="Export research PDF (Unsplash photos by default)")
    p_pdf.add_argument("--session", "-s", help="Session id")
    p_pdf.add_argument("--no-images", action="store_true")
    p_pdf.add_argument("--images", action="store_true", help="Force regenerate images")
    p_pdf.set_defaults(func=cmd_pdf)

    for name, fn, help_text in (
        ("tick", cmd_tick, "Run one research round"),
        ("status", cmd_status, "Show active/latest session"),
        ("stop", cmd_stop, "Stop the running session"),
        ("digest", cmd_digest, "Synthesize notes into a digest + PDF"),
        ("show", cmd_show, "Print accumulated notes"),
        ("list", cmd_list, "List sessions"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--session", "-s", help="Session id")
        if name == "show":
            p.add_argument("--tail", type=int, default=0)
        if name == "list":
            p.add_argument("--limit", type=int, default=20)
        if name == "digest":
            p.add_argument("--no-pdf", action="store_true")
            p.add_argument("--pdf", action="store_true")
            p.add_argument("--no-images", action="store_true")
        p.set_defaults(func=fn)

    p_parse = sub.add_parser("parse", help="NL → argv (internal)")
    p_parse.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1
    if args.cmd == "parse":
        out = nl_to_argv(" ".join(args.text))
        if not out:
            return 1
        print(" ".join(shlex.quote(a) for a in out))
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
