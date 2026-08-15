"""Interactive blog brief — ask clarifying questions before writing."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BlogBrief:
    topic: str = ""
    audience: str = ""
    demo_url: str = ""
    highlights: list[str] = field(default_factory=list)
    tone: str = "first-person journal"
    publish_devto: bool | None = None
    angle: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_focus(self) -> str:
        parts: list[str] = []
        if self.topic:
            parts.append(f"Topic: {self.topic}")
        if self.audience:
            parts.append(f"Audience: {self.audience}")
        if self.demo_url:
            parts.append(f"Demo URL: {self.demo_url}")
        if self.highlights:
            parts.append("Highlight: " + "; ".join(self.highlights))
        if self.tone:
            parts.append(f"Tone: {self.tone}")
        if self.angle:
            parts.append(f"Angle: {self.angle}")
        if self.publish_devto is True:
            parts.append("Publish to dev.to after writing.")
        elif self.publish_devto is False:
            parts.append("Save locally only — do not assume dev.to publish.")
        return "\n".join(parts)


_QUESTIONS: dict[str, str] = {
    "topic": "What is this blog about? (project name or one-line pitch)",
    "audience": "Who is the audience? (e.g. developers, DevOps, beginners)",
    "demo_url": "Any demo or live URL to include? (press Enter to skip)",
    "highlights": "Top 2–3 features or learnings to highlight? (comma-separated)",
    "tone": "Tone? [1] first-person dev journal  [2] technical deep-dive  [3] launch announcement (default 1)",
    "publish_devto": "Publish to dev.to after writing? [y/N]",
    "angle": "What's the hook or unique angle? (optional — Enter to skip)",
}

_TONE_MAP = {
    "1": "first-person dev journal",
    "2": "technical deep-dive",
    "3": "launch announcement",
    "first-person": "first-person dev journal",
    "journal": "first-person dev journal",
    "technical": "technical deep-dive",
    "deep-dive": "technical deep-dive",
    "launch": "launch announcement",
    "announcement": "launch announcement",
}


def _first_url(text: str) -> str:
    match = re.search(r"https?://[^\s\"'<>)\]]+", text or "")
    return match.group(0).rstrip(".,)") if match else ""


def _project_name(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            return match.group(1).strip()
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
            name = payload.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return root.name


def extract_topic_from_text(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    patterns = (
        r"(?i)write\s+(?:a\s+)?blog(?:\s+post)?\s+(?:about|on|for)\s+['\"]?([^'\"?\n]+?)['\"]?(?:\?|$|\s+and|\s+with)",
        r"(?i)blog(?:\s+post)?\s+(?:about|on|for)\s+['\"]?([^'\"?\n]+?)['\"]?(?:\?|$|\s+and|\s+with)",
        r"(?i)(?:about|on|for)\s+['\"]?([^'\"?\n]+?)['\"]?\s+(?:blog|dev\.?to)",
    )
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            return match.group(1).strip(" .'\"")
    quoted = re.findall(r"""['"]([^'"]+)['"]""", clean)
    if quoted:
        return quoted[0].strip()
    return ""


def infer_brief_from_context(
    ctx: dict[str, Any],
    *,
    user_text: str = "",
) -> BlogBrief:
    root = Path(str(ctx.get("root") or ".")).expanduser()
    brief = BlogBrief()
    brief.topic = extract_topic_from_text(user_text) or _project_name(root)

    readme = str(ctx.get("existing_readme") or "")
    brief.demo_url = _first_url(readme) or _first_url(str(ctx.get("existing_blog") or ""))

    commits = str(ctx.get("recent_commits") or "").splitlines()
    if commits:
        brief.highlights = [line.split(maxsplit=1)[-1] for line in commits[:3] if line.strip()]

    if re.search(r"(?i)\b(?:publish|post)\b.*\bdev\.?to\b|\bdev\.?to\b.*\b(?:publish|post)\b", user_text):
        brief.publish_devto = True
    if re.search(r"(?i)\bfirst.?person\b", user_text):
        brief.tone = "first-person dev journal"
    if re.search(r"(?i)\b(?:deep.?dive|technical)\b", user_text):
        brief.tone = "technical deep-dive"

    if re.search(r"(?i)\b(?:beginners?|newcomers?)\b", user_text):
        brief.audience = "beginners"
    elif re.search(r"(?i)\bdevelopers?\b", user_text):
        brief.audience = "developers"

    return brief


def missing_brief_fields(brief: BlogBrief, *, require_publish: bool = False) -> list[str]:
    missing: list[str] = []
    if not (brief.topic or "").strip():
        missing.append("topic")
    if not (brief.audience or "").strip():
        missing.append("audience")
    if require_publish and brief.publish_devto is None:
        missing.append("publish_devto")
    return missing


def _prompt(question: str, *, default: str = "") -> str:
    if not sys.stdin.isatty():
        return default
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except EOFError:
        return default
    return answer or default


def _apply_answer(brief: BlogBrief, field_name: str, answer: str) -> None:
    value = (answer or "").strip()
    if field_name == "topic":
        brief.topic = value
    elif field_name == "audience":
        brief.audience = value
    elif field_name == "demo_url":
        brief.demo_url = value
    elif field_name == "highlights":
        brief.highlights = [part.strip() for part in value.split(",") if part.strip()]
    elif field_name == "tone":
        key = value.lower() or "1"
        brief.tone = _TONE_MAP.get(key, value or "first-person dev journal")
    elif field_name == "publish_devto":
        brief.publish_devto = value.lower() in {"y", "yes", "true", "1"}
    elif field_name == "angle":
        brief.angle = value


def interview_brief(
    brief: BlogBrief,
    *,
    fields: list[str] | None = None,
    interactive: bool | None = None,
    assume_defaults: bool = False,
) -> tuple[BlogBrief, list[str]]:
    """Ask the user for missing blog details. Returns (brief, questions_asked)."""
    is_tty = sys.stdin.isatty() if interactive is None else bool(interactive)
    ask_fields: list[str] = []
    if not (brief.topic or "").strip():
        ask_fields.append("topic")
    if not (brief.audience or "").strip():
        ask_fields.append("audience")
    if brief.publish_devto is None:
        ask_fields.append("publish_devto")
    if not brief.demo_url:
        ask_fields.append("demo_url")
    if not brief.highlights:
        ask_fields.append("highlights")
    ask_fields.append("angle")
    if fields:
        ask_fields = [f for f in fields if f in _QUESTIONS or f in ask_fields]

    asked: list[str] = []
    if not is_tty or assume_defaults:
        if not brief.audience:
            brief.audience = "developers"
        if brief.publish_devto is None:
            brief.publish_devto = False
        return brief, asked

    if not ask_fields:
        return brief, asked

    print("I'll ask a few questions before writing the blog:\n")
    for field_name in ask_fields:
        question = _QUESTIONS.get(field_name, field_name)
        default = ""
        if field_name == "topic" and brief.topic:
            default = brief.topic
        if field_name == "demo_url" and brief.demo_url:
            default = brief.demo_url
        if field_name == "highlights" and brief.highlights:
            default = ", ".join(brief.highlights)
        if field_name == "tone":
            default = "1"
        if field_name == "publish_devto":
            default = "n"
        answer = _prompt(question, default=default)
        if field_name in {"demo_url", "angle"} and not answer:
            continue
        _apply_answer(brief, field_name, answer)
        asked.append(field_name)

    if not brief.audience:
        brief.audience = "developers"
    return brief, asked


def prepare_blog_brief(
    ctx: dict[str, Any],
    *,
    user_text: str = "",
    focus: str = "",
    interactive: bool | None = None,
    assume_defaults: bool = False,
) -> tuple[BlogBrief, str]:
    """Infer brief, optionally interview, return brief + focus string for the LLM."""
    brief = infer_brief_from_context(ctx, user_text=user_text)
    if focus:
        brief.angle = focus
    brief, _ = interview_brief(
        brief,
        interactive=interactive,
        assume_defaults=assume_defaults,
    )
    focus_text = brief.as_focus()
    return brief, focus_text
