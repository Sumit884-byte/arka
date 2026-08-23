"""Cached podcast episode timelines — prep, questions, and recording flow."""

from __future__ import annotations

import os
import re
from typing import Any

_INSPIRATION_RE = re.compile(
    r"(?i)\b("
    r"podcast\s+(?:idea|ideas|inspiration|outline|plan|timeline|prep|preparation|questions?)|"
    r"(?:what|which)\s+(?:questions?|topics?)\s+(?:to\s+)?(?:ask|cover).*podcast|"
    r"how\s+to\s+prepare\s+(?:for\s+)?(?:a\s+)?podcast|"
    r"podcast\s+episode\s+(?:plan|outline|structure|format)|"
    r"interview\s+questions?\s+for\s+(?:my\s+)?podcast|"
    r"start\s+(?:a\s+)?podcast\s+episode|"
    r"plan\s+(?:a\s+)?podcast\s+episode|"
    r"podcast\s+show\s+notes?\s+outline"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"transcript\s+of|transcript\s+ask|convert.*podcast.*book|"
    r"noise\s+remove|media_transform|shell\s+script|python\s+script"
    r")\b"
)

_FORMAT_HINT_RE = [
    (re.compile(r"(?i)\b(?:interview|guest|conversation with)\b"), "interview"),
    (re.compile(r"(?i)\b(?:solo|monologue|commentary|hot take)\b"), "solo"),
    (re.compile(r"(?i)\b(?:co[- ]host|two hosts|panel|debate)\b"), "co_host"),
    (re.compile(r"(?i)\b(?:story|narrative|true crime|docuseries)\b"), "narrative"),
    (re.compile(r"(?i)\b(?:tutorial|how to|learn|course|explainer)\b"), "educational"),
    (re.compile(r"(?i)\b(?:news|weekly roundup|headlines|current events)\b"), "news"),
    (re.compile(r"(?i)\b(?:founder|startup|builder|indie hacker)\b"), "founder"),
]


def _enabled() -> bool:
    return os.environ.get("PODCAST_INSPIRATION_CACHE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def _parse_runtime_minutes(text: str) -> int:
    m = re.search(r"(?i)\b(\d+)\s*[- ]?(?:minute|min)\b", text or "")
    if m:
        return max(5, int(m.group(1)))
    if re.search(r"(?i)\bhalf[- ]hour\b", text or ""):
        return 30
    if re.search(r"(?i)\b(?:one[- ]hour|1[- ]hour|60[- ]minute)\b", text or ""):
        return 60
    if re.search(r"(?i)\b(?:90[- ]minute|1\.5\s*hours?)\b", text or ""):
        return 90
    return 45


def _scale_minutes(block: str, base_runtime: int, target_runtime: int) -> str:
    if base_runtime <= 0 or target_runtime == base_runtime:
        return block
    ratio = target_runtime / base_runtime

    def repl(match: re.Match[str]) -> str:
        start = int(match.group(1))
        end = int(match.group(2))
        return f"{max(1, round(start * ratio))}:{max(1, round(end * ratio)):02d}"

    scaled = re.sub(r"\b(\d{1,2}):(\d{2})\b", repl, block)
    return scaled.replace(f"~{base_runtime} min", f"~{target_runtime} min")


ARCHETYPES: list[dict[str, Any]] = [
    {
        "id": "interview",
        "title": "Interview podcast",
        "aliases": ["interview podcast", "guest interview", "conversation podcast", "talk show"],
        "runtime_minutes": 45,
        "timeline": """## Episode timeline (~45 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Research** | T-7 to T-2 days | Guest background, recent work, controversy to avoid |
| **Outreach & prep doc** | T-3 days | Send topic areas + 5 seed questions; confirm pronouns/timezone |
| **Pre-show** | T-30 min | Mic check, water, outline visible, record backup |
| **Cold open** | 0:00–1:00 | Hook clip or thesis of the episode |
| **Intro** | 1:00–3:00 | Show name, guest cred, episode promise |
| **Warm-up** | 3:00–8:00 | Easy rapport — origin story, current focus |
| **Core interview** | 8:00–35:00 | 3–4 themed blocks with follow-ups |
| **Lightning / audience** | 35:00–40:00 | Quick takes or listener question |
| **Close** | 40:00–43:00 | Key takeaway, where to find guest |
| **Outro / CTA** | 43:00–45:00 | Subscribe, next episode tease, credits |
| **Post** | T+24 h | Transcribe, show notes, clip 2–3 shorts |""",
        "prepare": """## How to prepare
- Read guest’s last 3 interviews — note **questions already asked** so yours feel fresh.
- Build a **one-page brief**: 5 must-hit topics, 3 follow-up probes each, 2 graceful outs.
- Prepare **A/B cold open**: quote from guest OR surprising stat about the topic.
- Test recording chain; export 10 sec of room tone for post.""",
        "questions": """## What to ask (expandable)

**Warm-up**
- What are you working on that most people misunderstand?
- What did your path look like before [known thing]?

**Core (pick 3–4 themes)**
- What decision would you make differently with hindsight?
- Where do experts disagree on [topic] — and where do you land?
- What’s a concrete example from the last 90 days?
- What should beginners ignore? What should they not skip?

**Challenge / depth**
- Strongest counterargument to your view?
- What metric or signal changed your mind?

**Close**
- What resource or person should listeners follow next?
- What question do you wish more interviewers asked you?""",
    },
    {
        "id": "solo",
        "title": "Solo commentary",
        "aliases": ["solo podcast", "monologue podcast", "solo episode", "commentary podcast"],
        "runtime_minutes": 25,
        "timeline": """## Episode timeline (~25 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Outline** | T-2 days | One thesis + 3 supporting beats |
| **Script beats** | T-1 day | Bullet script, not word-for-word unless narrative |
| **Record** | 0:00–22:00 | Hook (60s) → context → 3 beats → takeaway |
| **Outro** | 22:00–25:00 | CTA + recap in one sentence |
| **Post** | T+24 h | Title A/B options, one audiogram clip |""",
        "prepare": """## How to prepare
- Write the **last sentence first** (the takeaway), then reverse-outline.
- Record standing up; mark **pause points** for edits.
- Keep a “cut list” of tangents — move to next episode.""",
        "questions": """## What to cover (solo prompts)
- What changed your mind this week/month?
- One mistake + lesson + what you’d do now
- “Most people think X; actually Y because…”
- Tool, book, or habit you’re testing — honest review
- Answer a listener question (real or composite)""",
    },
    {
        "id": "co_host",
        "title": "Co-hosted discussion",
        "aliases": ["co-host podcast", "two hosts", "panel podcast", "debate podcast"],
        "runtime_minutes": 40,
        "timeline": """## Episode timeline (~40 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Topic brief** | T-3 days | Shared doc: thesis, host A angle, host B angle |
| **Pre-show** | T-15 min | Align on off-limits topics + who leads each segment |
| **Intro** | 0:00–3:00 | Both hosts + episode stakes |
| **Segment 1** | 3:00–15:00 | Host A leads, B pushes back |
| **Segment 2** | 15:00–27:00 | Host B leads, A pushes back |
| **Synthesis** | 27:00–35:00 | Where you agree, where you don’t, listener takeaway |
| **Outro** | 35:00–40:00 | CTA |""",
        "prepare": """## How to prepare
- Assign **devil’s advocate** roles upfront — avoids pile-on agreeing.
- Shared outline with **handoff cues** (“over to you for…”).
- Record separate tracks if possible.""",
        "questions": """## Discussion prompts
- Best vs worst take on [topic] you’ve heard this week
- Predictions with a revisit date
- “Explain like I’m smart but new to [field]”
- Rank 3 options; defend the ranking
- What would change your mind?""",
    },
    {
        "id": "narrative",
        "title": "Narrative / story podcast",
        "aliases": ["story podcast", "narrative podcast", "true crime", "audio documentary"],
        "runtime_minutes": 30,
        "timeline": """## Episode timeline (~30 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Reporting** | T-14+ days | Interviews, documents, scene details |
| **Structure pass** | T-5 days | Cold open scene → act breaks → reveal |
| **Script draft** | T-2 days | Full script with scene headings |
| **Record VO** | Session | Narration + room tone + pickups |
| **Sound design** | Post | Music beds, SFX, pacing |
| **Fact-check** | Pre-publish | Names, dates, legal sensitivity |""",
        "prepare": """## How to prepare
- Identify **scene openers** you can dramatize in 30 seconds.
- Map **act turns** — new information every 7–9 minutes.
- Log tape: who, where, date, consent on record.""",
        "questions": """## Story angles / questions
- What did the protagonist want vs what blocked them?
- Smallest detail that unlocks the whole story
- Who disagrees with the official version — why?
- What’s the cost of the ending?
- What remains unresolved on purpose?""",
    },
    {
        "id": "educational",
        "title": "Educational / how-to",
        "aliases": ["educational podcast", "how to podcast", "tutorial podcast", "learn podcast"],
        "runtime_minutes": 35,
        "timeline": """## Episode timeline (~35 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Learning objective** | T-3 days | One skill listener can try in 24 h |
| **Outline** | T-2 days | Hook → prerequisites → steps → pitfalls → recap |
| **Examples** | T-1 day | 2 concrete demos or case studies |
| **Record** | 0:00–32:00 | Teach in layers; signpost “step 2 of 5” |
| **Recap + homework** | 32:00–35:00 | Checklist + link to resources |
| **Post** | T+24 h | Show notes with timestamps + links |""",
        "prepare": """## How to prepare
- Define **one actionable outcome** — cut everything else for part 2.
- Prepare analogies for the hardest concept.
- Anticipate top 3 “stupid questions” — answer them proudly.""",
        "questions": """## Teaching prompts
- What do people get wrong on day one?
- Minimal setup to try this tonight
- Common failure mode + fix
- Cheap vs pro approach — when to upgrade
- What to learn next after this episode""",
    },
    {
        "id": "news",
        "title": "News roundup",
        "aliases": ["news podcast", "weekly roundup", "headlines podcast", "current events podcast"],
        "runtime_minutes": 20,
        "timeline": """## Episode timeline (~20 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Source sweep** | T-24 h | 5–7 trusted sources + one contrarian |
| **Selection** | T-3 h | Pick 3 stories max — one global, one industry, one wildcard |
| **Record** | 0:00–18:00 | Context → why it matters → “so what for you” |
| **Outro** | 18:00–20:00 | Next week preview + CTA |""",
        "prepare": """## How to prepare
- Write **one-line thesis** per story before recording.
- Keep links in a shared doc for show notes.
- Date-stamp everything — news ages fast.""",
        "questions": """## Segment prompts
- What happened (60 sec max)?
- Who wins / loses?
- What’s the non-obvious second-order effect?
- What should listeners watch next week?
- Quick hot take — label it as opinion""",
    },
    {
        "id": "founder",
        "title": "Founder / startup stories",
        "aliases": ["founder podcast", "startup podcast", "indie hacker podcast", "builder podcast"],
        "runtime_minutes": 50,
        "timeline": """## Episode timeline (~50 min)

| Phase | When | Focus |
| --- | --- | --- |
| **Guest research** | T-5 days | Product, funding, prior interviews, metrics public |
| **Pre-interview** | T-2 days | Confirm no-go zones (fundraising, layoffs) |
| **Record** | 0:00–48:00 | Origin → first users → inflection → today → advice |
| **Outro** | 48:00–50:00 | Where to try the product |
| **Post** | T+48 h | Clips on build-in-public angle |""",
        "prepare": """## How to prepare
- Read guest’s **launch post** and most recent changelog.
- Prepare **specific numbers questions** — politely accept “can’t share.”
- Have a “failure story” prompt ready — founders open up after that.""",
        "questions": """## Founder interview bank
- First 10 users — how did you find them manually?
- What almost killed the company?
- What do you know now that you’d tell yourself at day 0?
- Build vs distribute — where did you spend too little time?
- What’s overrated advice in your space?""",
    },
]


def is_podcast_inspiration_request(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean or _EXCLUDE_RE.search(clean):
        return False
    if _INSPIRATION_RE.search(clean):
        return True
    if re.search(r"(?i)\bpodcast\b", clean) and re.search(
        r"(?i)\b(?:prepare|prep|questions?|timeline|outline|plan|ideas?|inspiration|structure)\b",
        clean,
    ):
        return True
    return False


def match_archetype(text: str) -> dict[str, Any] | None:
    clean = _normalize(text)
    if not clean:
        return None
    for pattern, fmt_id in _FORMAT_HINT_RE:
        if pattern.search(text or ""):
            for arch in ARCHETYPES:
                if arch["id"] == fmt_id:
                    return arch
    best: dict[str, Any] | None = None
    best_score = 0
    for arch in ARCHETYPES:
        for alias in arch["aliases"]:
            alias_norm = _normalize(alias)
            if alias_norm in clean:
                score = len(alias_norm)
                if score > best_score:
                    best_score = score
                    best = arch
    return best or ARCHETYPES[0]


def wants_cached_podcast_inspiration(text: str) -> bool:
    if not _enabled() or not is_podcast_inspiration_request(text):
        return False
    clean = _normalize(text)
    if len(clean.split()) <= 10:
        return True
    return bool(
        re.search(
            r"(?i)\b(?:prepare|prep|questions?|timeline|outline|plan|ideas?|inspiration|what to ask|how to)\b",
            text or "",
        )
    )


def cached_inspiration(text: str, *, runtime_minutes: int | None = None) -> str | None:
    if not _enabled() or not is_podcast_inspiration_request(text):
        return None
    arch = match_archetype(text)
    if not arch:
        return None
    runtime = runtime_minutes or _parse_runtime_minutes(text) or int(arch.get("runtime_minutes") or 45)
    base_runtime = int(arch.get("runtime_minutes") or 45)
    prompt = " ".join((text or "").split()).strip()
    timeline = _scale_minutes(str(arch.get("timeline") or ""), base_runtime, runtime)
    parts = [
        f"## Request\n{prompt or arch['title']}\n",
        f"## Format\n**{arch['title']}** (`{arch['id']}`) — cached podcast timeline (expand any section)\n",
        timeline.strip(),
        str(arch.get("prepare") or "").strip(),
        str(arch.get("questions") or "").strip(),
        "## Expand next\n"
        "- Add guest-specific research questions\n"
        "- Swap segment lengths for your actual runtime\n"
        "- Generate a full script: ask for a `podcast script` with your target minutes",
    ]
    return "\n\n".join(p for p in parts if p).strip()


def list_archetypes() -> list[dict[str, Any]]:
    return [
        {
            "id": a["id"],
            "title": a["title"],
            "aliases": list(a["aliases"]),
            "default_runtime_minutes": a.get("runtime_minutes"),
        }
        for a in ARCHETYPES
    ]


def status() -> dict[str, object]:
    return {
        "enabled": _enabled(),
        "count": len(ARCHETYPES),
        "ids": [a["id"] for a in ARCHETYPES],
    }
