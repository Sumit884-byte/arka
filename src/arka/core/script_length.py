"""Screenplay, podcast, and script length guidance — pages, runtime, word targets."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

_WORDS_PER_PAGE_MIN = 200
_WORDS_PER_PAGE_MAX = 300

_SCRIPT_RE = re.compile(
    r"(?i)\b("
    r"screenplay|screenwriting|script\s+for|write\s+(?:a\s+)?script|"
    r"(?:podcast|movie|tv|television|episode|pilot|film|drama|audio|stage)\s+script|"
    r"podcast\s+script|movie\s+script|tv\s+script|television\s+script|"
    r"episode\s+script|pilot\s+script|film\s+script|stage\s+play|"
    r"dialogue\s+for|shooting\s+script|spec\s+script|"
    r"\bscript\b.*\b(?:minute|min|hour|page|act|teaser)\b"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"shell\s+script|python\s+script|bash\s+script|javascript|typescript|"
    r"install\s+script|build\s+script|deployment\s+script|"
    r"transcript\s+of|read\s+the\s+transcript"
    r")\b"
)

_DURATION_RE = re.compile(
    r"(?i)\b(\d+)\s*[- ]?(?:minute|min|hour|hr|h)\b"
)
_RUNTIME_RE = re.compile(
    r"(?i)\b(\d+)\s*[- ]?(?:page|pg|pages)\b"
)

_FORMAT_HINT_RE = [
    (re.compile(r"(?i)\b(?:network|broadcast|commercial|sitcom)\b"), "network_tv"),
    (re.compile(r"(?i)\b(?:streaming|premium\s+cable|hbo|netflix|no\s+ads?)\b"), "streaming"),
    (re.compile(r"(?i)\b(?:dialogue[- ]heavy|talky|rapid\s+dialogue|drama)\b"), "dialogue_drama"),
    (re.compile(r"(?i)\b(?:action|sci[- ]?fi|visual|set\s+piece|blockbuster)\b"), "action_scifi"),
    (re.compile(r"(?i)\b(?:podcast|audio\s+drama|narrated)\b"), "podcast"),
    (re.compile(r"(?i)\b(?:feature\s+film|movie|cinema)\b"), "feature_film"),
    (re.compile(r"(?i)\b(?:short\s+film|short)\b"), "short_film"),
]


@dataclass(frozen=True)
class ScriptTarget:
    format_id: str
    label: str
    runtime_minutes: int | None
    pages_min: int
    pages_max: int
    words_min: int
    words_max: int
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_id": self.format_id,
            "label": self.label,
            "runtime_minutes": self.runtime_minutes,
            "pages_min": self.pages_min,
            "pages_max": self.pages_max,
            "words_min": self.words_min,
            "words_max": self.words_max,
            "notes": self.notes,
        }


# 1-hour TV baselines from industry rule: ~1 page = 1 minute screen time.
_ONE_HOUR_TARGETS: dict[str, ScriptTarget] = {
    "network_tv": ScriptTarget(
        "network_tv",
        "Network broadcast TV (1 hr with ads)",
        60,
        42,
        48,
        7500,
        9500,
        "Teaser + 4–5 acts; 12–15 minutes of commercial breaks.",
    ),
    "streaming": ScriptTarget(
        "streaming",
        "Streaming / premium cable (1 hr)",
        60,
        52,
        60,
        9500,
        12000,
        "Full 55–60 minutes without ad breaks; longer scene buildup.",
    ),
    "dialogue_drama": ScriptTarget(
        "dialogue_drama",
        "Dialogue-heavy drama (1 hr)",
        60,
        58,
        68,
        12000,
        16000,
        "Fast dialogue inflates page count while keeping ~60 min runtime.",
    ),
    "action_scifi": ScriptTarget(
        "action_scifi",
        "Action-heavy / sci-fi (1 hr)",
        60,
        40,
        50,
        5000,
        8000,
        "Visual action lines consume pages but screen quickly.",
    ),
}


def _enabled() -> bool:
    return os.environ.get("SCRIPT_LENGTH_GUIDE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def is_script_writing_request(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean or _EXCLUDE_RE.search(clean):
        return False
    return bool(_SCRIPT_RE.search(clean))


def _parse_duration_minutes(text: str) -> int | None:
    clean = " ".join((text or "").split())
    for m in _DURATION_RE.finditer(clean):
        n = int(m.group(1))
        token = m.group(0).lower()
        if "hour" in token or token.endswith("h") or token.endswith("hr"):
            return n * 60
        return n
    if re.search(r"(?i)\bhalf[- ]hour\b", clean):
        return 30
    if re.search(r"(?i)\bone[- ]hour\b|\b1[- ]hour\b|\b60[- ]minute\b", clean):
        return 60
    if re.search(r"(?i)\b90[- ]minute\b|\b1\.5\s*hours?\b", clean):
        return 90
    return None


def _parse_page_target(text: str) -> int | None:
    m = _RUNTIME_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1))


def _infer_format_id(text: str) -> str:
    for pattern, fmt in _FORMAT_HINT_RE:
        if pattern.search(text or ""):
            return fmt
    if re.search(r"(?i)\bpodcast\b", text or ""):
        return "podcast"
    if re.search(r"(?i)\b(?:movie|film|feature)\b", text or ""):
        return "feature_film"
    return "streaming"


def _scale_pages(base: ScriptTarget, runtime_minutes: int) -> tuple[int, int]:
    ratio = runtime_minutes / 60.0
    pmin = max(1, round(base.pages_min * ratio))
    pmax = max(pmin, round(base.pages_max * ratio))
    return pmin, pmax


def _scale_words(base: ScriptTarget, runtime_minutes: int) -> tuple[int, int]:
    ratio = runtime_minutes / 60.0
    wmin = max(500, round(base.words_min * ratio))
    wmax = max(wmin, round(base.words_max * ratio))
    return wmin, wmax


def _podcast_target(runtime_minutes: int) -> ScriptTarget:
    # Spoken audio ~140–180 wpm; use 150 wpm midpoint for script word count.
    words = round(runtime_minutes * 150)
    return ScriptTarget(
        "podcast",
        f"Podcast script (~{runtime_minutes} min spoken)",
        runtime_minutes,
        0,
        0,
        max(400, words - 500),
        words + 500,
        "Podcasts use word count, not screenplay pages. Allow intro/outro and ad markers.",
    )


def _feature_film_target(runtime_minutes: int) -> ScriptTarget:
    pages_min = max(1, round(runtime_minutes * 0.9))
    pages_max = max(pages_min, round(runtime_minutes * 1.1))
    wmin = pages_min * _WORDS_PER_PAGE_MIN
    wmax = pages_max * _WORDS_PER_PAGE_MAX
    return ScriptTarget(
        "feature_film",
        f"Feature film (~{runtime_minutes} min)",
        runtime_minutes,
        pages_min,
        pages_max,
        wmin,
        wmax,
        "Standard margins yield ~200–300 words/page; action vs dialogue shifts density.",
    )


def _short_film_target(runtime_minutes: int) -> ScriptTarget:
    runtime_minutes = min(runtime_minutes, 30)
    pages_min = max(1, round(runtime_minutes * 0.95))
    pages_max = max(pages_min, round(runtime_minutes * 1.05))
    return ScriptTarget(
        "short_film",
        f"Short film (~{runtime_minutes} min)",
        runtime_minutes,
        pages_min,
        pages_max,
        pages_min * _WORDS_PER_PAGE_MIN,
        pages_max * _WORDS_PER_PAGE_MAX,
        "Keep a single A-story; one turning point.",
    )


def resolve_script_target(text: str) -> ScriptTarget | None:
    if not _enabled() or not is_script_writing_request(text):
        return None
    runtime = _parse_duration_minutes(text) or 60
    fmt = _infer_format_id(text)
    page_hint = _parse_page_target(text)

    if fmt == "podcast":
        target = _podcast_target(runtime)
    elif fmt == "feature_film":
        target = _feature_film_target(runtime or 90)
    elif fmt == "short_film":
        target = _short_film_target(runtime or 15)
    elif fmt in _ONE_HOUR_TARGETS:
        base = _ONE_HOUR_TARGETS[fmt]
        pmin, pmax = _scale_pages(base, runtime)
        wmin, wmax = _scale_words(base, runtime)
        target = ScriptTarget(
            base.format_id,
            f"{base.label.split('(')[0].strip()} (~{runtime} min)",
            runtime,
            pmin,
            pmax,
            wmin,
            wmax,
            base.notes,
        )
    else:
        base = _ONE_HOUR_TARGETS["streaming"]
        pmin, pmax = _scale_pages(base, runtime)
        wmin, wmax = _scale_words(base, runtime)
        target = ScriptTarget(
            base.format_id,
            f"TV/streaming script (~{runtime} min)",
            runtime,
            pmin,
            pmax,
            wmin,
            wmax,
            base.notes,
        )

    if page_hint and target.pages_min == 0:
        wmin = page_hint * _WORDS_PER_PAGE_MIN
        wmax = page_hint * _WORDS_PER_PAGE_MAX
        return ScriptTarget(
            target.format_id,
            target.label,
            target.runtime_minutes,
            page_hint,
            page_hint,
            wmin,
            wmax,
            target.notes,
        )
    if page_hint:
        wmin = page_hint * _WORDS_PER_PAGE_MIN
        wmax = page_hint * _WORDS_PER_PAGE_MAX
        return ScriptTarget(
            target.format_id,
            target.label,
            target.runtime_minutes,
            page_hint,
            page_hint,
            wmin,
            wmax,
            target.notes,
        )
    return target


def script_length_addon(text: str, *, limit_chars: int = 2200) -> str:
    """System-prompt block for script/podcast/movie writing requests."""
    target = resolve_script_target(text)
    if target is None:
        return ""
    page_line = ""
    if target.pages_max > 0:
        page_line = (
            f"Target length: **{target.pages_min}–{target.pages_max} pages** "
            f"(~{target.runtime_minutes or '?'} min screen time at 1 page ≈ 1 minute).\n"
        )
    else:
        page_line = f"Target runtime: **~{target.runtime_minutes} minutes** spoken audio.\n"
    block = (
        "Script length guidance (industry formatting):\n"
        f"- Format: {target.label}\n"
        f"{page_line}"
        f"- Estimated word count: **{target.words_min:,}–{target.words_max:,} words** "
        f"(screenplay margins ≈ {_WORDS_PER_PAGE_MIN}–{_WORDS_PER_PAGE_MAX} words/page).\n"
        f"- Notes: {target.notes}\n"
        "Write in proper script format (scene headings, action, character cues, dialogue). "
        "Use white space like a real screenplay — do not prose-pack pages. "
        "For TV: include Teaser + act breaks. Match the target page/word band unless the user "
        "gave an explicit page or word cap."
    )
    if len(block) > limit_chars:
        return block[:limit_chars].rstrip() + "…"
    return block


def list_format_targets() -> list[dict[str, Any]]:
    out = [t.to_dict() for t in _ONE_HOUR_TARGETS.values()]
    out.extend(
        [
            _podcast_target(30).to_dict(),
            _podcast_target(60).to_dict(),
            _feature_film_target(90).to_dict(),
            _short_film_target(15).to_dict(),
        ]
    )
    return out
