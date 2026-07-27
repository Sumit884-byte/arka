#!/usr/bin/env python3
"""Daily non-overlapping reading on any topic — tracked concepts, configurable length."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from datetime import date
from pathlib import Path
from typing import Any

from arka.agent.daily_reading_builtins import BUILTIN_TRACKS

WORDS_PER_MINUTE = 200
DEFAULT_TRACK = "health"

READING_SYSTEM_TEMPLATE = """You write clear, engaging daily reading on: {topic}.

Audience: {audience}

Rules:
- Cover ONLY the assigned concepts listed under "Today's concepts". Do not introduce other major topics.
- Do not repeat concepts listed under "Already covered".
- Use markdown: one H2 per concept, practical takeaways, and concrete examples.
- Be accurate and specific; avoid hype and unsupported claims.
{extra_rules}
- End with a line exactly like: CONCEPTS: id1, id2, id3
"""

INIT_SYSTEM_PROMPT = """You design a non-overlapping daily reading curriculum.

Output ONLY valid JSON (no markdown fences) with this shape:
{
  "title": "Short track title",
  "topic": "One-line topic description",
  "audience": "Who this is for",
  "disclaimer": "Optional caveat or empty string",
  "pillars": ["pillar_a", "pillar_b", "pillar_c"],
  "concepts": {
    "pillar_a": [{"id": "slug.unique_name", "title": "Concept title"}, ...],
    "pillar_b": [...],
    "pillar_c": [...]
  }
}

Rules:
- Provide exactly 3 pillars unless the topic clearly needs 2 or 4 (max 4).
- Each pillar: 12–18 concepts with stable dotted ids (lowercase, no spaces).
- Concepts must not overlap; together they should span the topic comprehensively.
- ids must be unique across the whole curriculum.
"""

_TECH_EXCLUDE = re.compile(
    r"(?i)\b(?:"
    r"repo\s+health|code\s+health|service\s+health|database\s+health|"
    r"docker|kubernetes|server\s+health|system\s+health\s+check|"
    r"reading\s+time|read\s+a\s+file|file\s+reading"
    r")\b"
)


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def tracks_root() -> Path:
    return _config_dir() / "daily-reading" / "tracks"


def global_settings_path() -> Path:
    return _config_dir() / "daily-reading" / "settings.json"


def track_slug(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (name or "").strip().lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:64] or "track"


def track_dir(slug: str) -> Path:
    return tracks_root() / track_slug(slug)


def curriculum_path(slug: str) -> Path:
    return track_dir(slug) / "curriculum.json"


def state_path(slug: str) -> Path:
    return track_dir(slug) / "state.json"


def lessons_dir(slug: str) -> Path:
    return track_dir(slug) / "lessons"


def load_global_settings() -> dict[str, Any]:
    path = global_settings_path()
    default: dict[str, Any] = {"active_track": DEFAULT_TRACK, "default_minutes": 40}
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("active_track", DEFAULT_TRACK)
    data.setdefault("default_minutes", 40)
    return data


def save_global_settings(data: dict[str, Any]) -> None:
    path = global_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_curriculum(slug: str) -> dict[str, Any] | None:
    norm = track_slug(slug)
    if norm in BUILTIN_TRACKS and not curriculum_path(norm).is_file():
        return dict(BUILTIN_TRACKS[norm])
    path = curriculum_path(norm)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_curriculum(slug: str, data: dict[str, Any]) -> Path:
    root = track_dir(slug)
    root.mkdir(parents=True, exist_ok=True)
    path = curriculum_path(slug)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def list_tracks() -> list[str]:
    slugs = set(BUILTIN_TRACKS)
    root = tracks_root()
    if root.is_dir():
        for path in root.iterdir():
            if path.is_dir() and (path / "curriculum.json").is_file():
                slugs.add(path.name)
    return sorted(slugs)


def curriculum_pillars(curriculum: dict[str, Any]) -> tuple[str, ...]:
    pillars = curriculum.get("pillars")
    if isinstance(pillars, list) and pillars:
        return tuple(str(p) for p in pillars)
    concepts = curriculum.get("concepts") or {}
    if isinstance(concepts, dict):
        return tuple(concepts.keys())
    return ("general",)


def all_concepts(curriculum: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    concepts = curriculum.get("concepts") or {}
    if not isinstance(concepts, dict):
        return out
    for pillar in curriculum_pillars(curriculum):
        for row in concepts.get(pillar, []):
            if isinstance(row, dict) and row.get("id"):
                out.append({**row, "pillar": pillar})
    return out


def load_state(slug: str) -> dict[str, Any]:
    path = state_path(slug)
    default: dict[str, Any] = {"covered": [], "sessions": []}
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("covered", [])
    data.setdefault("sessions", [])
    return data


def save_state(slug: str, data: dict[str, Any]) -> None:
    path = state_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def target_words(minutes: int) -> int:
    return max(800, minutes * WORDS_PER_MINUTE)


def concepts_per_session(minutes: int) -> int:
    if minutes >= 55:
        return 5
    if minutes >= 35:
        return 4
    return 3


def select_next_concepts(
    curriculum: dict[str, Any],
    covered: set[str],
    *,
    minutes: int,
) -> list[dict[str, str]]:
    need = concepts_per_session(minutes)
    pillars = curriculum_pillars(curriculum)
    concepts_map = curriculum.get("concepts") or {}
    selected: list[dict[str, str]] = []
    uncovered_by_pillar: dict[str, list[dict[str, str]]] = {}
    for pillar in pillars:
        rows = concepts_map.get(pillar, []) if isinstance(concepts_map, dict) else []
        uncovered_by_pillar[pillar] = [
            {**row, "pillar": pillar}
            for row in rows
            if isinstance(row, dict) and row.get("id") and row["id"] not in covered
        ]

    while len(selected) < need:
        progressed = False
        for pillar in pillars:
            pool = uncovered_by_pillar.get(pillar, [])
            if pool and len(selected) < need:
                selected.append(pool.pop(0))
                progressed = True
        if not progressed:
            break

    if len(selected) < need:
        for row in all_concepts(curriculum):
            if row["id"] not in covered and row not in selected:
                selected.append(row)
            if len(selected) >= need:
                break
    return selected[:need]


def parse_minutes(text: str) -> int | None:
    low = (text or "").lower()
    m = re.search(r"\b(\d+)\s*(?:min(?:ute)?s?|m)\b", low)
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*hr\b|\b1\s*hour\b|\b60\s*min", low):
        return 60
    return None


def _parse_concepts_line(text: str) -> list[str]:
    m = re.search(r"(?im)^CONCEPTS:\s*(.+)$", text)
    if not m:
        return []
    return [part.strip() for part in m.group(1).split(",") if part.strip()]


def _llm_complete(system_prompt: str, user: str, *, skill: str = "daily_reading") -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system_prompt,
            user,
            temperature=0.55,
            task="chat",
            skill=skill,
        ).strip()
    except ImportError:
        pass
    from arka.agent.core import _llm

    return _llm(system_prompt, user, temperature=0.55, task="chat").strip()


def reading_system_prompt(curriculum: dict[str, Any]) -> str:
    topic = str(curriculum.get("topic") or curriculum.get("title") or "the topic")
    audience = str(curriculum.get("audience") or "motivated learners")
    extra = ""
    disclaimer = str(curriculum.get("disclaimer") or "").strip()
    if disclaimer:
        extra = f"- Include this disclaimer near the top: {disclaimer}"
    return READING_SYSTEM_TEMPLATE.format(
        topic=topic,
        audience=audience,
        extra_rules=extra,
    )


def generate_reading(
    curriculum: dict[str, Any],
    concepts: list[dict[str, str]],
    *,
    minutes: int,
    covered: list[str],
) -> str:
    if not concepts:
        raise RuntimeError("No concepts left — run: arka daily_reading reset --track <name>")
    words = target_words(minutes)
    concept_block = "\n".join(
        f"- {row['id']}: {row['title']} ({row['pillar']})" for row in concepts
    )
    covered_block = "\n".join(f"- {cid}" for cid in covered[-40:]) or "(none yet)"
    user = (
        f"Reading time target: ~{minutes} minutes (~{words} words).\n\n"
        f"Today's concepts:\n{concept_block}\n\n"
        f"Already covered (do NOT re-teach these as new sections):\n{covered_block}\n\n"
        "Write today's reading now."
    )
    raw = _llm_complete(reading_system_prompt(curriculum), user)
    if not raw:
        raise RuntimeError("LLM returned empty response")
    return raw


def generate_curriculum(topic: str, *, pillars: list[str] | None = None) -> dict[str, Any]:
    pillar_hint = ""
    if pillars:
        pillar_hint = f"\nUse these pillar names: {', '.join(pillars)}"
    user = f"Topic: {topic.strip()}{pillar_hint}\n\nDesign the curriculum JSON now."
    raw = _llm_complete(INIT_SYSTEM_PROMPT, user)
    if not raw:
        raise RuntimeError("LLM returned empty curriculum")
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse curriculum JSON: {exc}") from exc
    if not isinstance(data, dict) or not data.get("concepts"):
        raise RuntimeError("Curriculum JSON missing concepts")
    data.setdefault("title", topic.strip())
    data.setdefault("topic", topic.strip())
    data.setdefault("audience", "motivated learners")
    data.setdefault("disclaimer", "")
    if not data.get("pillars"):
        data["pillars"] = list((data.get("concepts") or {}).keys())
    return data


def resolve_track(args_track: str | None) -> str:
    if args_track:
        return track_slug(args_track)
    return track_slug(load_global_settings().get("active_track") or DEFAULT_TRACK)


def _today_iso() -> str:
    return date.today().isoformat()


def _lesson_file(slug: str, day: str) -> Path:
    return lessons_dir(slug) / f"{day}.md"


def cmd_init(args: argparse.Namespace) -> int:
    topic = " ".join(args.topic).strip()
    if not topic:
        print("Usage: daily_reading init <topic>", file=sys.stderr)
        return 1
    slug = track_slug(args.track or topic)
    if curriculum_path(slug).is_file() and not args.force:
        print(f"Track {slug!r} already exists. Use --force to replace.", file=sys.stderr)
        return 1
    pillars = [p.strip() for p in (args.pillars or "").split(",") if p.strip()] or None
    try:
        curriculum = generate_curriculum(topic, pillars=pillars)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = save_curriculum(slug, curriculum)
    settings = load_global_settings()
    settings["active_track"] = slug
    save_global_settings(settings)
    total = len(all_concepts(curriculum))
    print(f"Created track: {slug}")
    print(f"  title: {curriculum.get('title')}")
    print(f"  concepts: {total}")
    print(f"  curriculum: {path}")
    return 0


def cmd_list_tracks(_args: argparse.Namespace) -> int:
    active = load_global_settings().get("active_track", DEFAULT_TRACK)
    for slug in list_tracks():
        cur = load_curriculum(slug)
        count = len(all_concepts(cur)) if cur else 0
        mark = " *" if slug == active else ""
        title = (cur or {}).get("title") or slug
        print(f"{slug}\t{count} concepts\t{title}{mark}")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    slug = track_slug(args.track)
    if not load_curriculum(slug):
        print(f"Unknown track: {slug}. Run: arka daily_reading init <topic>", file=sys.stderr)
        return 1
    settings = load_global_settings()
    settings["active_track"] = slug
    save_global_settings(settings)
    print(f"Active track: {slug}")
    return 0


def cmd_today(args: argparse.Namespace) -> int:
    slug = resolve_track(getattr(args, "track", None))
    curriculum = load_curriculum(slug)
    if not curriculum:
        print(f"Unknown track: {slug}. Run: arka daily_reading init <topic>", file=sys.stderr)
        return 1

    settings = load_global_settings()
    minutes = int(args.minutes or settings.get("default_minutes") or 40)
    state = load_state(slug)
    covered_set = set(state.get("covered") or [])
    today = _today_iso()

    if (
        not args.force
        and state.get("sessions")
        and state["sessions"][-1].get("date") == today
    ):
        path = _lesson_file(slug, today)
        if path.is_file():
            print(path.read_text(encoding="utf-8"))
            print("\n(already generated today — use --force for a new lesson)", file=sys.stderr)
            return 0

    concepts = select_next_concepts(curriculum, covered_set, minutes=minutes)
    if not concepts:
        print(f"Track {slug!r} complete. Run: arka daily_reading reset --track {slug}", file=sys.stderr)
        return 1

    try:
        reading = generate_reading(curriculum, concepts, minutes=minutes, covered=list(covered_set))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parsed_ids = _parse_concepts_line(reading)
    concept_ids = [row["id"] for row in concepts]
    used_ids = [cid for cid in parsed_ids if cid in concept_ids] or concept_ids

    for cid in used_ids:
        covered_set.add(cid)
    state["covered"] = sorted(covered_set)
    state["sessions"].append({"date": today, "minutes": minutes, "concepts": used_ids})
    save_state(slug, state)

    title = str(curriculum.get("title") or slug)
    disclaimer = str(curriculum.get("disclaimer") or "").strip()
    header = (
        f"# Daily reading — {title} ({today})\n\n"
        f"**Track:** {slug}  \n"
        f"**Estimated reading time:** ~{minutes} minutes  \n"
        f"**Concepts:** {', '.join(used_ids)}\n\n"
    )
    if disclaimer:
        header += f"> {disclaimer}\n\n"
    body = reading if reading.lstrip().startswith("# Daily reading") else header + reading
    lessons_dir(slug).mkdir(parents=True, exist_ok=True)
    _lesson_file(slug, today).write_text(body + "\n", encoding="utf-8")

    if args.json:
        print(
            json.dumps(
                {
                    "track": slug,
                    "date": today,
                    "minutes": minutes,
                    "concepts": used_ids,
                    "path": str(_lesson_file(slug, today)),
                    "reading": reading,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(body)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    slug = resolve_track(getattr(args, "track", None))
    curriculum = load_curriculum(slug)
    if not curriculum:
        print(f"Unknown track: {slug}", file=sys.stderr)
        return 1
    state = load_state(slug)
    covered = state.get("covered") or []
    total = len(all_concepts(curriculum))
    settings = load_global_settings()
    default_min = settings.get("default_minutes", 40)
    print(f"Track: {slug} — {curriculum.get('title') or slug}")
    print(f"Concepts covered: {len(covered)} / {total}")
    print(f"Default reading length: {default_min} minutes (~{target_words(default_min)} words)")
    if state.get("sessions"):
        last = state["sessions"][-1]
        print(f"Last session: {last.get('date')} ({last.get('minutes')} min)")
        print(f"  concepts: {', '.join(last.get('concepts') or [])}")
    remaining = total - len(set(covered))
    days_left = max(1, remaining // concepts_per_session(default_min))
    print(f"Estimated days remaining: ~{days_left}")
    return 0


def cmd_upcoming(args: argparse.Namespace) -> int:
    slug = resolve_track(getattr(args, "track", None))
    curriculum = load_curriculum(slug)
    if not curriculum:
        print(f"Unknown track: {slug}", file=sys.stderr)
        return 1
    settings = load_global_settings()
    minutes = int(args.minutes or settings.get("default_minutes") or 40)
    concepts = select_next_concepts(curriculum, set(load_state(slug).get("covered") or []), minutes=minutes)
    if not concepts:
        print("Curriculum complete — reset to start over.")
        return 0
    print(f"Next session (~{minutes} min) on track {slug}:")
    for row in concepts:
        print(f"  [{row['pillar']}] {row['id']} — {row['title']}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    slug = resolve_track(getattr(args, "track", None))
    path = state_path(slug)
    if path.is_file():
        path.unlink()
    root = lessons_dir(slug)
    if root.is_dir():
        for lesson in root.glob("*.md"):
            lesson.unlink()
    print(f"Progress reset for track: {slug}")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    slug = resolve_track(getattr(args, "track", None))
    settings = load_global_settings()
    minutes = int(args.minutes or settings.get("default_minutes") or 40)
    when = args.when or "08:00"
    cmd = f"daily_reading today --track {slug} --minutes {minutes}"
    print("Schedule daily reading with Arka routines:")
    print(f'  arka routines add daily {shlex.quote(when)} {shlex.quote(cmd)} --install')
    return 0


def cmd_set_default(args: argparse.Namespace) -> int:
    settings = load_global_settings()
    settings["default_minutes"] = int(args.minutes)
    save_global_settings(settings)
    print(f"Default reading length set to {args.minutes} minutes.")
    return 0


def _extract_topic_from_reading_request(text: str) -> str | None:
    t = text.strip()
    patterns = (
        r"(?i)(?:\d+\s*(?:min(?:ute)?s?|m)|1\s*hr|1\s*hour)\s+(?:reading|lesson)\s+(?:on\s+)?(.+)$",
        r"(?i)(?:daily|today'?s?)\s+(?:reading|lesson)\s+(?:on\s+)?(.+)$",
        r"(?i)(?:reading|lesson)\s+(?:on\s+)?(.+)$",
    )
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            topic = m.group(1).strip()
            topic = re.sub(r"(?i)\b(?:for|about)\s+", "", topic).strip()
            topic = re.sub(r"(?i)\b(?:please|today|now)\b", "", topic).strip()
            if topic and len(topic) > 2:
                return topic
    return None


def _is_reading_request(text: str) -> bool:
    t = text.strip()
    if not t or _TECH_EXCLUDE.search(t):
        return False
    if re.match(
        r"(?i)^(?:daily[-_ ]?reading|health[-_ ]?reading|wellness[-_ ]?reading)\b", t
    ):
        return True
    if re.search(r"(?i)\b(?:health|wellness)[-_ ]reading\b", t):
        return True
    if re.search(r"(?i)\b(?:daily|today'?s?)\s+(?:reading|lesson)\b", t):
        return True
    if re.search(r"(?i)\b(?:\d+\s*(?:min(?:ute)?s?|m)|1\s*hr|1\s*hour)\b", t) and re.search(
        r"(?i)\b(?:reading|lesson)\b", t
    ):
        return True
    if t.lower() in {"daily reading", "health reading", "wellness reading", "daily_reading"}:
        return True
    return False


def _append_track(argv: list[str], text: str) -> list[str]:
    if any(a in ("--track", "-t") for a in argv):
        return argv
    if re.search(r"(?i)\b(?:health|wellness|fitness|diet|exercise|nutrition)\b", text):
        if argv and argv[0] not in ("--track", "-t"):
            return ["--track", DEFAULT_TRACK, *argv]
        return argv
    topic = _extract_topic_from_reading_request(text)
    if topic:
        slug = track_slug(topic)
        if load_curriculum(slug):
            return ["--track", slug, *argv]
    return argv


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_reading_request(t):
        return []
    if re.search(r"(?i)\b(?:list\s+tracks?|tracks?\s+list)\b", t):
        return ["list-tracks"]
    if re.search(r"(?i)\b(?:status|progress)\b", t):
        return _append_track(["status"], t)
    if re.search(r"(?i)\b(?:upcoming|next concepts|what'?s next)\b", t):
        argv = ["upcoming"]
        minutes = parse_minutes(t)
        if minutes:
            argv.extend(["--minutes", str(minutes)])
        return _append_track(argv, t)
    if re.search(r"(?i)\b(?:schedule|routine|daily at)\b", t):
        argv = ["schedule"]
        minutes = parse_minutes(t)
        if minutes:
            argv.extend(["--minutes", str(minutes)])
        m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
        if m:
            argv.extend(["--when", m.group(1)])
        return _append_track(argv, t)
    if re.search(r"(?i)\breset\b", t):
        return _append_track(["reset"], t)
    if re.search(r"(?i)\binit\b", t) or re.search(r"(?i)\bcreate\s+(?:a\s+)?track\b", t):
        topic = _extract_topic_from_reading_request(t) or re.sub(r"(?i)^(?:init|create track)\s+", "", t).strip()
        if topic:
            return ["init", topic]
    argv = ["today"]
    topic = _extract_topic_from_reading_request(t)
    if topic:
        slug = track_slug(topic)
        if load_curriculum(slug):
            argv.extend(["--track", slug])
        elif slug != DEFAULT_TRACK:
            return ["init", topic]
    minutes = parse_minutes(t)
    if minutes:
        argv.extend(["--minutes", str(minutes)])
    if re.search(r"(?i)\b(?:force|again|new lesson)\b", t):
        argv.append("--force")
    return _append_track(argv, t)


def main(argv: list[str] | None = None, *, default_track: str | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka daily_reading",
        description="Daily non-overlapping reading on any topic",
    )
    parser.add_argument("--track", "-t", help="Reading track slug")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="Create a new reading track from a topic")
    p_init.add_argument("topic", nargs="+")
    p_init.add_argument("--track", help="Custom slug (default: derived from topic)")
    p_init.add_argument("--pillars", help="Comma-separated pillar names")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    sub.add_parser("list-tracks", help="List reading tracks").set_defaults(func=cmd_list_tracks)

    p_use = sub.add_parser("use", help="Set active track")
    p_use.add_argument("track")
    p_use.set_defaults(func=cmd_use)

    p_today = sub.add_parser("today", help="Generate today's reading")
    p_today.add_argument("--minutes", "-m", type=int)
    p_today.add_argument("--force", action="store_true")
    p_today.add_argument("--json", action="store_true")
    p_today.set_defaults(func=cmd_today)

    p_status = sub.add_parser("status", help="Show track progress")
    p_status.set_defaults(func=cmd_status)

    p_up = sub.add_parser("upcoming", help="Preview next concepts")
    p_up.add_argument("--minutes", "-m", type=int)
    p_up.set_defaults(func=cmd_upcoming)

    p_reset = sub.add_parser("reset", help="Clear progress for a track")
    p_reset.set_defaults(func=cmd_reset)

    p_sched = sub.add_parser("schedule", help="Print routines command")
    p_sched.add_argument("--minutes", "-m", type=int)
    p_sched.add_argument("--when", default="08:00")
    p_sched.set_defaults(func=cmd_schedule)

    p_default = sub.add_parser("set-default", help="Set default reading length")
    p_default.add_argument("minutes", type=int)
    p_default.set_defaults(func=cmd_set_default)

    p_parse = sub.add_parser("parse", help="NL → argv (internal)")
    p_parse.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if not args.cmd:
        return cmd_today(argparse.Namespace(track=None, minutes=None, force=False, json=False))
    if args.cmd == "parse":
        argv_out = nl_to_argv(" ".join(args.text))
        if not argv_out:
            return 1
        print(" ".join(shlex.quote(a) for a in argv_out))
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
