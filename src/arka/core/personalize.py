#!/usr/bin/env python3
"""Onboarding profile + rule-based skill recommendations for new Arka users."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def load_env_file() -> None:
        pass


VALID_INTERESTS = frozenset(
    {
        "finance",
        "pdf",
        "voice",
        "dev",
        "productivity",
        "research",
        "google",
        "memory",
        "media",
    }
)
VALID_EXPERIENCE = frozenset({"beginner", "intermediate"})
VALID_PLATFORMS = frozenset({"mac", "linux", "windows"})

INTEREST_LABELS: dict[str, str] = {
    "finance": "Stocks, currency, market news",
    "pdf": "PDF merge, compress, ask questions",
    "voice": "Wake word, speech-to-text, TTS",
    "dev": "GitHub, Docker, repo health, PR checks",
    "productivity": "Reminders, routines, daily brief",
    "research": "Web search, YouTube research, data Q&A",
    "google": "Gmail, Calendar, OAuth",
    "memory": "Remember facts, recall context",
    "media": "YouTube, slides, video, thumbnails",
}

# Top built-in skills mapped to interest tags (rule-based recommendations).
SKILL_CATALOG: dict[str, dict[str, Any]] = {
    "pdf_tools": {
        "interests": ["pdf", "productivity"],
        "description": "Merge, split, compress, and edit PDFs",
        "example": "pdf_tools merge a.pdf b.pdf -o combined.pdf",
        "beginner": True,
    },
    "pdf_ask": {
        "interests": ["pdf", "research"],
        "description": "Ask questions about ingested PDFs",
        "example": 'pdf_ask --doc resume.pdf "summarize skills"',
        "beginner": True,
        "requires_env": ["GEMINI_API_KEY"],
    },
    "stocks": {
        "interests": ["finance"],
        "description": "Stock quotes, fundamentals, and market context",
        "example": "stocks AAPL",
        "beginner": True,
        "requires_env": ["GROQ_API_KEY"],
    },
    "currency_convert": {
        "interests": ["finance", "productivity"],
        "description": "Convert amounts between currencies",
        "example": "currency_convert 100 USD to INR",
        "beginner": True,
    },
    "kalshi": {
        "interests": ["finance"],
        "description": "Kalshi prediction market odds and trending markets",
        "example": "kalshi search bitcoin",
        "beginner": True,
    },
    "kaggle": {
        "interests": ["research", "productivity"],
        "description": "Download and search Kaggle datasets",
        "example": "kaggle download titanic",
        "beginner": True,
        "requires_env": ["KAGGLE_USERNAME", "KAGGLE_KEY"],
    },
    "daily_brief": {
        "interests": ["finance", "productivity", "research"],
        "description": "Morning weather + tech headlines",
        "example": "daily_brief tech",
        "beginner": True,
    },
    "price_check": {
        "interests": ["finance", "productivity"],
        "description": "Compare product prices across retailers",
        "example": "price_check iPhone 16",
        "beginner": True,
    },
    "google": {
        "interests": ["google", "productivity"],
        "description": "Gmail unread, calendar, and drafts",
        "example": "google gmail --unread --summarize",
        "beginner": False,
    },
    "remind": {
        "interests": ["productivity"],
        "description": "Schedule reminders that fire when you're back",
        "example": "remind in 30m stretch",
        "beginner": True,
    },
    "routines": {
        "interests": ["productivity"],
        "description": "Recurring scheduled tasks",
        "example": 'routines add daily 9am "check email"',
        "beginner": False,
    },
    "unified_memory": {
        "interests": ["memory", "productivity"],
        "description": "Remember facts and recall by goal",
        "example": 'unified_memory remember "I prefer dark mode"',
        "beginner": True,
    },
    "session_memory": {
        "interests": ["memory"],
        "description": "Persistent markdown notes (MEMORY.md)",
        "example": 'session_memory remember "project uses pytest"',
        "beginner": False,
    },
    "youtube_research": {
        "interests": ["research", "media"],
        "description": "Search YouTube and summarize transcripts",
        "example": 'youtube_research "python asyncio" --limit 3',
        "beginner": True,
    },
    "youtube_download": {
        "interests": ["media"],
        "description": "Download a single YouTube video or audio",
        "example": "youtube_download dQw4w9WgXcQ --audio",
        "beginner": True,
    },
    "compose_slides": {
        "interests": ["media", "productivity"],
        "description": "Generate slide decks from a topic",
        "example": "compose_slides climate change",
        "beginner": False,
        "requires_env": ["GEMINI_API_KEY"],
    },
    "compose_video": {
        "interests": ["media"],
        "description": "Compose a narrated video from a topic",
        "example": "compose_video intro to Rust",
        "beginner": False,
        "requires_env": ["GEMINI_API_KEY"],
    },
    "convert_media": {
        "interests": ["media"],
        "description": "Convert between video, audio, and image formats",
        "example": "convert_media clip.mp4 --to mp3",
        "beginner": True,
    },
    "search_web": {
        "interests": ["research"],
        "description": "DuckDuckGo web search from the terminal",
        "example": "search_web rust async tutorials",
        "beginner": True,
    },
    "data_ask": {
        "interests": ["research", "dev"],
        "description": "Ask questions about CSV/JSON in a folder",
        "example": "data_ask reports/",
        "beginner": False,
        "requires_env": ["GROQ_API_KEY"],
    },
    "generate_data": {
        "interests": ["research", "dev"],
        "description": "Generate sample CSV/JSON datasets",
        "example": "generate_data 50 users as csv",
        "beginner": True,
    },
    "github_repo": {
        "interests": ["dev"],
        "description": "Clone, summarize, and inspect GitHub repos",
        "example": "github_repo summarize owner/repo",
        "beginner": False,
    },
    "repo_health": {
        "interests": ["dev"],
        "description": "Lint and test health checks for a repo",
        "example": "repo_health",
        "beginner": False,
    },
    "docker_status": {
        "interests": ["dev"],
        "description": "List containers and tail logs",
        "example": "docker_status",
        "beginner": False,
    },
    "pr_check": {
        "interests": ["dev"],
        "description": "Summarize pull request changes",
        "example": "pr_check https://github.com/org/repo/pull/42",
        "beginner": False,
        "requires_env": ["GITHUB_TOKEN"],
    },
    "select_model": {
        "interests": ["dev", "productivity"],
        "description": "Recommend LLM models for your hardware",
        "example": "select_model --apply",
        "beginner": True,
    },
    "voice": {
        "interests": ["voice"],
        "description": "Wake word listener and voice agent",
        "example": "arka listen",
        "beginner": False,
        "os": ["darwin"],
    },
    "chart": {
        "interests": ["research", "finance"],
        "description": "Plot line, bar, pie, and scatter charts",
        "example": "chart line 1,2,3,5,8",
        "beginner": True,
    },
    "ascii_art": {
        "interests": ["media", "dev"],
        "description": "ASCII banners from text or images",
        "example": 'ascii_art "HELLO"',
        "beginner": True,
    },
    "bookmarks": {
        "interests": ["productivity", "research"],
        "description": "Save and recall URLs",
        "example": "bookmarks save https://example.com",
        "beginner": True,
    },
    "competitions": {
        "interests": ["research", "dev"],
        "description": "Find hackathons and ML competitions",
        "example": "competitions search computer vision",
        "beginner": True,
    },
    "gemini_cli": {
        "interests": ["research", "dev"],
        "description": "Google Gemini CLI for quick prompts",
        "example": "gemini explain asyncio",
        "beginner": True,
    },
    "agent_hub": {
        "interests": ["dev", "productivity"],
        "description": "Shared MCP, memory, and skills for ollama launch agents",
        "example": "agent_hub sync && agent_hub launch claude",
        "beginner": False,
    },
}

_PERSONALIZE_TRIGGERS = re.compile(
    r"(?i)\b(?:"
    r"personalize(?:\s+me)?|"
    r"recommend\s+skills?|"
    r"what\s+skills?\s+should\s+i\s+use|"
    r"which\s+skills?\s+(?:fit|match|suit)\s+me|"
    r"get\s+started\s+with\s+arka|"
    r"onboard(?:ing)?\s+(?:me\s+)?(?:to\s+)?arka|"
    r"skill\s+recommendations?"
    r")\b"
)


def profile_path() -> Path:
    return config_dir() / "personalize.json"


def _sanitize_token(text: str, *, max_len: int = 48) -> str:
    text = re.sub(r"[^\w\s-]", "", (text or "").strip().lower())
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:max_len]


def _detect_platform() -> str:
    plat = sys.platform
    if plat == "darwin":
        return "mac"
    if plat.startswith("linux"):
        return "linux"
    if plat in ("win32", "cygwin"):
        return "windows"
    return "linux"


def _has_api_keys() -> bool:
    keys = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    return any(os.environ.get(k, "").strip() for k in keys)


def _uses_fish() -> bool:
    return shutil_which("fish") is not None


def shutil_which(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


def default_profile() -> dict[str, Any]:
    return {
        "interests": [],
        "experience": "beginner",
        "platforms": [_detect_platform()],
        "has_api_keys": _has_api_keys(),
        "uses_fish": _uses_fish(),
        "completed_at": None,
        "onboarding_done": False,
    }


def load_profile() -> dict[str, Any]:
    path = profile_path()
    if not path.is_file():
        return default_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_profile()
    if not isinstance(data, dict):
        return default_profile()
    base = default_profile()
    base.update({k: v for k, v in data.items() if k in base or k in ("interests",)})
    interests = base.get("interests") or []
    if isinstance(interests, str):
        interests = [i.strip() for i in interests.split(",") if i.strip()]
    base["interests"] = [i for i in interests if i in VALID_INTERESTS]
    exp = str(base.get("experience", "beginner")).lower()
    base["experience"] = exp if exp in VALID_EXPERIENCE else "beginner"
    platforms = base.get("platforms") or []
    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.split(",") if p.strip()]
    base["platforms"] = [p for p in platforms if p in VALID_PLATFORMS] or [_detect_platform()]
    return base


def save_profile(profile: dict[str, Any]) -> None:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "interests": [i for i in profile.get("interests", []) if i in VALID_INTERESTS],
        "experience": profile.get("experience", "beginner"),
        "platforms": [p for p in profile.get("platforms", []) if p in VALID_PLATFORMS],
        "has_api_keys": bool(profile.get("has_api_keys")),
        "uses_fish": bool(profile.get("uses_fish")),
        "completed_at": profile.get("completed_at"),
        "onboarding_done": bool(profile.get("onboarding_done")),
    }
    path.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")


def reset_profile() -> None:
    path = profile_path()
    if path.is_file():
        path.unlink()


@dataclass
class ScoredSkill:
    name: str
    score: float
    description: str
    example: str
    gate_ok: bool
    gate_label: str


def _gate_for_catalog_entry(name: str, meta: dict[str, Any]) -> tuple[bool, str]:
    os_filter = meta.get("os") or []
    if os_filter:
        plat = _detect_platform()
        if plat not in os_filter:
            return False, f"os gate ({plat})"

    for env_name in meta.get("requires_env") or []:
        if not os.environ.get(str(env_name), "").strip():
            return False, f"missing env: {env_name}"

    for bin_name in meta.get("requires_bins") or []:
        if not shutil_which(str(bin_name)):
            return False, f"missing binary: {bin_name}"

    return True, ""


def _format_gate_label(reason: str) -> str:
    if not reason:
        return ""
    m = re.search(r"missing env:\s*(\S+)", reason, re.I)
    if m:
        return f"needs {m.group(1)}"
    m = re.search(r"missing binary:\s*(\S+)", reason, re.I)
    if m:
        return f"needs {m.group(1)}"
    if reason.startswith("os gate"):
        return reason
    return reason


def score_skills(profile: dict[str, Any], *, limit: int = 10) -> list[ScoredSkill]:
    interests = set(profile.get("interests") or [])
    experience = str(profile.get("experience", "beginner")).lower()
    platform = (profile.get("platforms") or [_detect_platform()])[0]

    ranked: list[ScoredSkill] = []
    for name, meta in SKILL_CATALOG.items():
        tags = set(meta.get("interests") or [])
        overlap = len(interests & tags)
        if interests and overlap == 0:
            continue
        specificity = overlap / len(tags) if tags else 0.0
        score = overlap * 2.0 + specificity
        if name in interests:
            score += 1.0
        if experience == "beginner" and meta.get("beginner"):
            score += 0.25
        os_filter = meta.get("os") or []
        if os_filter and platform not in os_filter:
            score -= 2.0

        gate_ok, gate_reason = _gate_for_catalog_entry(name, meta)
        ranked.append(
            ScoredSkill(
                name=name,
                score=score,
                description=str(meta.get("description") or ""),
                example=str(meta.get("example") or name),
                gate_ok=gate_ok,
                gate_label=_format_gate_label(gate_reason),
            )
        )

    ranked.sort(key=lambda s: (-s.score, s.name))
    if interests:
        ranked = [s for s in ranked if s.score > 0]
    return ranked[:limit]


def is_personalize_query(cmd: str) -> bool:
    return bool(_PERSONALIZE_TRIGGERS.search((cmd or "").strip()))


def nl_to_argv(cmd: str) -> list[str] | None:
    clean = (cmd or "").strip()
    if not is_personalize_query(clean):
        return None
    low = clean.lower()
    if re.search(r"\bquick\s*start\b", low):
        return ["quickstart"]
    if re.search(r"\b(?:status|show|my)\s+profile\b", low) or low.strip() in {
        "personalize status",
        "my profile",
    }:
        return ["status"]
    if re.search(r"\brecommend\b", low):
        return ["recommend"]
    if re.search(r"\b(?:wizard|onboard|setup|questionnaire)\b", low):
        return ["wizard"]
    return ["recommend"]


def _interest_keys() -> list[str]:
    return sorted(VALID_INTERESTS)


def _append_interest_pick(picks: list[str], idx: int) -> None:
    keys = _interest_keys()
    if 1 <= idx <= len(keys):
        key = keys[idx - 1]
        if key not in picks:
            picks.append(key)


def _parse_interest_input(raw: str) -> list[str]:
    """Parse wizard interest input: names, comma/space lists, or digit runs like 123."""
    text = (raw or "").strip().lower()
    if not text:
        return []

    picks: list[str] = []
    # Consecutive digits without separators: each digit is an option number (1-9).
    if text.isdigit() and len(text) > 1:
        for ch in text:
            if ch.isdigit():
                _append_interest_pick(picks, int(ch))
        return picks

    for part in re.split(r"[,;\s]+", text):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            _append_interest_pick(picks, int(part))
        else:
            token = _sanitize_token(part)
            if token in VALID_INTERESTS and token not in picks:
                picks.append(token)
    return picks


def _parse_interest_list(raw: str) -> list[str]:
    return _parse_interest_input(raw)


def run_wizard(
    *,
    interests: list[str] | None = None,
    experience: str | None = None,
    platforms: list[str] | None = None,
    non_interactive: bool = False,
) -> dict[str, Any]:
    profile = load_profile()

    if interests is not None:
        profile["interests"] = [i for i in interests if i in VALID_INTERESTS]
    elif not non_interactive and sys.stdin.isatty():
        print("What do you want to use Arka for? (comma-separated numbers)")
        for idx, key in enumerate(sorted(VALID_INTERESTS), start=1):
            print(f"  {idx}. {key} — {INTEREST_LABELS.get(key, key)}")
        raw = input("> ").strip()
        profile["interests"] = _parse_interest_input(raw)
    elif not profile.get("interests"):
        profile["interests"] = ["productivity", "research"]

    if experience and experience in VALID_EXPERIENCE:
        profile["experience"] = experience
    elif not non_interactive and sys.stdin.isatty():
        print("\nExperience level? (1=beginner, 2=intermediate)")
        choice = input("> ").strip()
        profile["experience"] = "intermediate" if choice == "2" else "beginner"
    else:
        profile["experience"] = profile.get("experience") or "beginner"

    if platforms:
        profile["platforms"] = [p for p in platforms if p in VALID_PLATFORMS]
    else:
        profile["platforms"] = [_detect_platform()]

    profile["has_api_keys"] = _has_api_keys()
    profile["uses_fish"] = _uses_fish()
    profile["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    profile["onboarding_done"] = True
    save_profile(profile)
    return profile


def format_profile_summary(profile: dict[str, Any]) -> str:
    interests = profile.get("interests") or []
    exp = profile.get("experience", "beginner")
    if interests:
        return f"{', '.join(interests)} ({exp})"
    return f"not set ({exp})"


def print_recommendations(profile: dict[str, Any] | None = None, *, limit: int = 8) -> int:
    profile = profile or load_profile()
    print(f"Your profile: {format_profile_summary(profile)}")
    print()
    print("Recommended skills:")
    recs = score_skills(profile, limit=limit)
    if not recs:
        print("  (no matches — run: arka personalize wizard)")
        return 0
    for idx, sk in enumerate(recs, start=1):
        gate = f" [{sk.gate_label}]" if not sk.gate_ok and sk.gate_label else ""
        if not sk.gate_ok and not sk.gate_label:
            gate = " [unavailable]"
        print(f"  {idx}. {sk.name}{gate} — {sk.description}")
        print(f"     Try: {sk.example}")
    return 0


def print_status() -> int:
    profile = load_profile()
    print(f"Profile file: {profile_path()}")
    print(f"Interests:    {', '.join(profile.get('interests') or []) or '(none)'}")
    print(f"Experience:   {profile.get('experience', 'beginner')}")
    print(f"Platforms:    {', '.join(profile.get('platforms') or [])}")
    print(f"API keys:     {'yes' if profile.get('has_api_keys') else 'no'}")
    print(f"Uses fish:    {'yes' if profile.get('uses_fish') else 'no'}")
    print(f"Onboarding:   {'done' if profile.get('onboarding_done') else 'not done'}")
    if profile.get("completed_at"):
        print(f"Completed:    {profile['completed_at']}")
    return 0


def print_quickstart() -> int:
    profile = load_profile()
    recs = score_skills(profile, limit=3)
    print("Get started with Arka (5 steps):")
    print()
    print("  1. arka setup          — config dirs + venv + chat deps")
    print("  2. arka doctor         — verify install and API keys")
    print("  3. arka personalize wizard — pick interests for skill tips")
    print("  4. arka personalize recommend — see ranked skills for you")
    print("  5. Try a top skill:")
    if recs:
        for sk in recs[:3]:
            gate = f" ({sk.gate_label})" if not sk.gate_ok and sk.gate_label else ""
            print(f"       {sk.example}{gate}")
    else:
        print('       arka ask "what is Rust?"')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arka onboarding — save interests and get skill recommendations"
    )
    sub = parser.add_subparsers(dest="cmd")

    p_wizard = sub.add_parser("wizard", help="Interactive onboarding questionnaire")
    p_wizard.add_argument("--interests", help="Comma-separated interest tags")
    p_wizard.add_argument("--experience", choices=sorted(VALID_EXPERIENCE))
    p_wizard.add_argument("--platform", choices=sorted(VALID_PLATFORMS))
    p_wizard.add_argument("--yes", "-y", action="store_true", help="Non-interactive defaults")

    sub.add_parser("recommend", help="Show ranked skill recommendations")
    sub.add_parser("status", help="Show saved profile")
    sub.add_parser("reset", help="Clear saved profile")
    sub.add_parser("quickstart", help="Print 5-step get-started checklist")

    p_parse = sub.add_parser("parse", help="Parse NL into personalize argv (internal)")
    p_parse.add_argument("text")

    args = parser.parse_args(argv if argv is not None else [])
    cmd = args.cmd

    if cmd is None:
        cmd = "wizard"
        args = argparse.Namespace(
            cmd="wizard",
            interests=None,
            experience=None,
            platform=None,
            yes=not sys.stdin.isatty(),
        )

    if cmd == "parse":
        out = nl_to_argv(args.text)
        if out:
            print(" ".join(out))
        return 0

    if cmd == "wizard":
        interests = _parse_interest_list(args.interests) if args.interests else None
        platforms = [args.platform] if getattr(args, "platform", None) else None
        non_interactive = bool(
            getattr(args, "yes", False)
            or interests
            or getattr(args, "experience", None)
            or not sys.stdin.isatty()
        )
        profile = run_wizard(
            interests=interests,
            experience=getattr(args, "experience", None),
            platforms=platforms,
            non_interactive=non_interactive,
        )
        print(f"✓ Profile saved — {format_profile_summary(profile)}")
        print()
        return print_recommendations(profile)

    if cmd == "recommend":
        return print_recommendations()

    if cmd == "status":
        return print_status()

    if cmd == "reset":
        reset_profile()
        print(f"✓ Cleared {profile_path()}")
        return 0

    if cmd == "quickstart":
        return print_quickstart()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
