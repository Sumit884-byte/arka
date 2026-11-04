"""Official event recaps: YouTube keynote transcript mixed with web search."""

from __future__ import annotations

import re
from datetime import datetime

# slug, brand, aliases, YouTube search template, official channel hints
TECH_EVENTS: tuple[tuple[str, str, tuple[str, ...], str, tuple[str, ...]], ...] = (
    ("gtc", "nvidia", ("gtc", "nvidia gtc"), "NVIDIA GTC {year} official full keynote Jensen Huang", ("nvidia",)),
    ("wwdc", "apple", ("wwdc",), "Apple WWDC {year} official keynote", ("apple",)),
    ("apple-event", "apple", ("apple event", "apple launch", "apple keynote"), "Apple Event {year} official keynote", ("apple",)),
    ("google-io", "google", ("google i/o", "google io", "i/o"), "Google I/O {year} official keynote", ("google",)),
    ("made-by-google", "google", ("made by google",), "Made by Google {year} official keynote", ("google",)),
    ("build", "microsoft", ("microsoft build", "ms build"), "Microsoft Build {year} official keynote", ("microsoft",)),
    ("ignite", "microsoft", ("microsoft ignite", "ms ignite"), "Microsoft Ignite {year} official keynote", ("microsoft",)),
    ("reinvent", "amazon", ("re:invent", "reinvent", "aws reinvent"), "AWS re:Invent {year} official keynote", ("aws", "amazon")),
    ("connect", "meta", ("meta connect",), "Meta Connect {year} official keynote", ("meta",)),
    ("unpacked", "samsung", ("samsung unpacked", "unpacked"), "Samsung Unpacked {year} official", ("samsung",)),
    ("ces", "ces", ("ces", "consumer electronics show"), "CES {year} official keynotes", ("ces",)),
    ("mwc", "mwc", ("mwc", "mobile world congress"), "MWC {year} official keynote", ("mwc", "gsma")),
    ("computex", "computex", ("computex",), "Computex {year} official keynote", ("computex",)),
    ("hot-chips", "hot-chips", ("hot chips",), "Hot Chips {year} official", ("hot chips",)),
    ("devday", "openai", ("devday", "dev day", "openai devday"), "OpenAI DevDay {year} official", ("openai",)),
    ("tesla-ai", "tesla", ("tesla ai day", "we robot", "tesla event"), "Tesla {year} official keynote", ("tesla",)),
    ("snapdragon", "qualcomm", ("snapdragon summit",), "Qualcomm Snapdragon Summit {year} official", ("qualcomm",)),
    ("intel", "intel", ("intel innovation", "intel event"), "Intel Innovation {year} official keynote", ("intel",)),
    ("amd", "amd", ("amd advancing ai", "amd event"), "AMD Advancing AI {year} official keynote", ("amd",)),
    ("kubecon", "cncf", ("kubecon",), "KubeCon {year} official keynote", ("cncf", "kubecon")),
    ("dreamforce", "salesforce", ("dreamforce",), "Dreamforce {year} official keynote", ("salesforce",)),
    ("adobe-max", "adobe", ("adobe max",), "Adobe MAX {year} official keynote", ("adobe",)),
    ("dockercon", "docker", ("dockercon",), "DockerCon {year} official keynote", ("docker",)),
)

_LAUNCH_BRANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("apple", ("apple",)),
    ("google", ("google", "made by google")),
    ("samsung", ("samsung",)),
    ("microsoft", ("microsoft",)),
    ("meta", ("meta", "facebook")),
    ("nvidia", ("nvidia",)),
    ("tesla", ("tesla",)),
    ("openai", ("openai",)),
    ("amazon", ("amazon", "aws")),
    ("amd", ("amd",)),
    ("intel", ("intel",)),
    ("qualcomm", ("qualcomm",)),
)

_LAUNCH_ASK_RE = re.compile(
    r"(?i)(?:"
    r"\bwhat\s+(?:did|has|happened)?\s*(?:at\s+|in\s+|during\s+)?"
    r"(?:apple|google|samsung|microsoft|meta|nvidia|tesla|openai|amazon|aws)\s+"
    r"(?:launch|announce|reveal|unveil|drop|event|keynote|gtc|wwdc|i/?o|build)"
    r"|"
    r"\b(?:apple|google|samsung|microsoft|meta|nvidia|tesla|openai)\s+"
    r"(?:launched|announced|revealed|unveiled|event|keynote|launch|gtc)\b"
    r"|"
    r"\bwhat\s+happened\b.+\b(?:gtc|wwdc|ces|i/?o|build|re:?invent|connect|unpacked)\b"
    r"|"
    r"\bwwdc\b|\bmade\s+by\s+google\b|\bgtc\b|\bkubecon\b|\bces\b|\bre:?invent\b"
    r")"
)


def tech_event_cases() -> list[tuple[str, str, str, str]]:
    """(question, slug, brand, youtube_needle) for every catalog event."""
    rows: list[tuple[str, str, str, str]] = []
    for slug, brand, aliases, template, _channels in TECH_EVENTS:
        alias = aliases[0]
        question = f"what happened in {alias}"
        needle = template.split("{year}")[0].strip()
        rows.append((question, slug, brand, needle))
        if alias != slug and " " not in alias:
            rows.append((f"what happened at {slug} 2026", slug, brand, needle))
    extra = (
        ("what happened in nvidia gtc", "gtc", "nvidia", "NVIDIA GTC"),
        ("what happened at nvidia gtc 2026", "gtc", "nvidia", "NVIDIA GTC"),
        ("what apple launched in 2026", "apple-event", "apple", "Apple Event"),
        ("what happened in apple launch event", "apple-event", "apple", "Apple Event"),
        ("what happened at wwdc", "wwdc", "apple", "Apple WWDC"),
        ("what happened at google i/o", "google-io", "google", "Google I/O"),
        ("what happened at microsoft build", "build", "microsoft", "Microsoft Build"),
        ("what happened at aws re:invent", "reinvent", "amazon", "AWS re:Invent"),
        ("what happened at meta connect", "connect", "meta", "Meta Connect"),
        ("what happened at samsung unpacked", "unpacked", "samsung", "Samsung Unpacked"),
        ("what happened at openai devday", "devday", "openai", "OpenAI DevDay"),
    )
    rows.extend(extra)
    return rows


def launch_year(question: str) -> str:
    match = re.search(r"\b(20[2-3]\d)\b", question or "")
    if match:
        return match.group(1)
    return str(datetime.now().year)


def launch_brand(question: str) -> str:
    event = match_tech_event(question)
    if event:
        return event[1]
    low = (question or "").lower()
    for brand, aliases in _LAUNCH_BRANDS:
        if any(re.search(rf"\b{re.escape(alias)}\b", low) for alias in aliases):
            return brand
    return ""


def match_tech_event(question: str) -> tuple[str, str, tuple[str, ...], str, tuple[str, ...]] | None:
    low = (question or "").lower()
    ranked: list[tuple[int, tuple[str, str, tuple[str, ...], str, tuple[str, ...]]]] = []
    for row in TECH_EVENTS:
        slug, _brand, aliases, _template, _channels = row
        for alias in aliases:
            if alias in low or (len(alias) <= 6 and re.search(rf"\b{re.escape(alias)}\b", low)):
                ranked.append((len(alias), row))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def is_launch_recap_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if match_tech_event(q):
        return True
    if _LAUNCH_ASK_RE.search(q):
        return True
    return bool(launch_brand(q) and re.search(r"(?i)\b(launch|launched|announce|keynote|event|gtc)\b", q))


def official_youtube_query(question: str) -> str:
    year = launch_year(question)
    event = match_tech_event(question)
    if event:
        return event[3].format(year=year)
    brand = launch_brand(question) or "apple"
    if brand == "apple":
        return f"Apple Event {year} official keynote"
    if brand == "google":
        return f"Made by Google {year} official keynote"
    return f"{brand} {year} official keynote launch"


# Typical full-keynote length when the upload has no duration metadata.
_EVENT_KEYNOTE_MINUTES: dict[str, int] = {
    "gtc": 120,
    "wwdc": 110,
    "apple-event": 80,
    "google-io": 100,
    "made-by-google": 75,
    "build": 90,
    "ignite": 90,
    "reinvent": 100,
    "connect": 80,
    "unpacked": 70,
    "ces": 90,
    "mwc": 60,
    "computex": 60,
    "hot-chips": 45,
    "devday": 70,
    "tesla-ai": 80,
    "snapdragon": 60,
    "intel": 70,
    "amd": 70,
    "kubecon": 45,
    "dreamforce": 90,
    "adobe-max": 80,
    "dockercon": 45,
}


def _hit_duration(hit: tuple) -> int:
    if len(hit) >= 4:
        try:
            return max(0, int(hit[3] or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def expected_keynote_seconds(question: str) -> int:
    event = match_tech_event(question)
    minutes = _EVENT_KEYNOTE_MINUTES.get(event[0], 70) if event else 70
    return minutes * 60


def score_official_video(
    title: str,
    channel: str,
    *,
    brand: str,
    year: str,
    question: str = "",
    duration_sec: int = 0,
) -> int:
    title_l = (title or "").lower()
    channel_l = (channel or "").lower()
    score = 0
    event = match_tech_event(question) if question else None
    channel_hints = event[4] if event else dict(_LAUNCH_BRANDS).get(brand, (brand,))
    if any(hint in channel_l for hint in channel_hints):
        score += 12
    if brand and brand in title_l:
        score += 3
    if event and any(alias in title_l for alias in event[2]):
        score += 6
    if any(token in title_l for token in ("keynote", "event", "launch", "official", "gtc")):
        score += 5
    if "full" in title_l and any(token in title_l for token in ("keynote", "event", "gtc")):
        score += 6
    if year and year in title_l:
        score += 4
    if duration_sec >= 2400:
        score += 16
    elif duration_sec >= 1500:
        score += 12
    elif duration_sec >= 900:
        score += 7
    elif duration_sec >= 480:
        score += 2
    elif duration_sec:
        score -= 14
    if any(bad in title_l for bad in ("reaction", "leak", "rumor", "rumour", "unofficial", "concept", "we bought")):
        score -= 10
    if any(bad in title_l for bad in ("trailer", "teaser", "in 5 min", "in 10 min", "shorts")):
        score -= 10
    if "highlights" in title_l and "official" not in title_l:
        score -= 6
    return score


def pick_official_video(
    hits: list[tuple],
    *,
    brand: str,
    year: str,
    question: str = "",
) -> tuple[str, str, str, int] | None:
    def _score(hit: tuple) -> int:
        return score_official_video(
            hit[1],
            hit[2],
            brand=brand,
            year=year,
            question=question,
            duration_sec=_hit_duration(hit),
        )

    ranked = sorted(hits, key=_score, reverse=True)
    for hit in ranked:
        video_id, title, channel = hit[0], hit[1], hit[2]
        if _score(hit) < 8:
            continue
        if video_id:
            return video_id, title, channel, _hit_duration(hit)
    if not ranked:
        return None
    hit = ranked[0]
    return hit[0], hit[1], hit[2], _hit_duration(hit)


def looks_like_video_description(text: str, *, duration_sec: int = 0) -> bool:
    """True when captions look like a YouTube about-box, not spoken keynote."""
    body = (text or "").strip()
    words = len(body.split())
    if words < 80:
        return True
    if duration_sec >= 900 and words < max(400, duration_sec // 12):
        return True
    if len(re.findall(r"https?://", body)) >= 2 and words < 400:
        return True
    if re.search(r"(?i)\b(subscribe|follow us|shop now|learn more at|visit (?:our|nvidia|apple)\.com)\b", body) and words < 280:
        return True
    spoken = len(re.findall(r"(?i)\b(thank you|thanks|let me|let's|all right|alright|next up|um+|uh+)\b", body))
    if duration_sec >= 1800 and spoken < 2 and words < 900:
        return True
    return False


def briefing_targets(duration_sec: int) -> tuple[int, int, int]:
    """Return (minutes, heading_count, word_target) from keynote runtime."""
    minutes = max(1, int(round(max(0, duration_sec) / 60))) if duration_sec else 25
    headings = max(3, min(18, max(3, minutes // 7)))
    words = max(180, min(2400, minutes * 16))
    return minutes, headings, words


def infer_keynote_seconds(transcript: str, *, duration_sec: int = 0, question: str = "") -> int:
    spoken_sec = int(len((transcript or "").split()) / 2.2)
    if duration_sec >= 480:
        return duration_sec
    if spoken_sec >= 900:
        return spoken_sec
    if duration_sec:
        return duration_sec
    if spoken_sec >= 180:
        return spoken_sec
    return expected_keynote_seconds(question)


def sample_keynote_transcript(transcript: str, *, duration_sec: int = 0) -> str:
    """Keep opening, middle announcements, and close — not only the first 12k chars."""
    text = (transcript or "").strip()
    if not text:
        return ""
    words = text.split()
    minutes = max(1, duration_sec // 60) if duration_sec else max(1, len(words) // 140)
    budget_words = max(2_400, min(14_000, minutes * 90))
    if len(words) <= budget_words:
        return text
    regions = 10
    span = max(1, len(words) // regions)
    take = max(120, min(span, budget_words // regions))
    parts: list[str] = []
    for i in range(regions):
        start = i * span
        chunk = words[start : start + take]
        if chunk:
            parts.append(" ".join(chunk))
    return "\n\n[…later in the keynote…]\n\n".join(parts)


_SMASHED_HEADING_RE = re.compile(
    r"(?m)^((?:iPhone|iPad|Watch|Mac|AirPods|Siri|Vision|Infrastructure|Vera|NVIDIA|Jensen)[^\n.!?]{0,60}|"
    r"[A-Z][A-Za-z0-9&/+.-]+(?:\s+[A-Z][A-Za-z0-9&/+.-]+){0,6})\s+"
    r"(?=(?:Apple|Google|Samsung|Microsoft|Meta|NVIDIA|Nvidia|The|To|This|Users|Key)\s+"
    r"(?:introduced|unveiled|announced|debuts|debuted|utilizes|uses|combines|"
    r"support|iPhone|device|system|officially))"
)


def format_launch_briefing(text: str) -> str:
    """Unstick smashed section titles: 'iPhone 18 Pro Apple introduced' → heading + sentence."""
    body = (text or "").strip()
    if not body:
        return body
    body = _SMASHED_HEADING_RE.sub(r"\1\n\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def launch_rewrite_prompt(
    question: str,
    *,
    title: str = "",
    url: str = "",
    transcript: str = "",
    web_context: str = "",
    duration_sec: int = 0,
) -> tuple[str, str]:
    minutes, headings, words = briefing_targets(duration_sec)
    system = (
        "You write an event recap from an official keynote transcript and web reports. "
        "Prefer the spoken transcript for what was announced on stage; use search for dates, "
        "reception, and links. Ignore YouTube description boilerplate "
        "(subscribe links, ecosystem slogans, 'learn more at'). "
        "Write in clear prose — not spoken stage language, not glued search snippets. "
        "Start with one complete sentence that names the event. "
        "Then use a markdown heading on its own line for each announcement. "
        "Never glue a heading onto the next sentence "
        "(wrong: \"iPhone 18 Pro Apple introduced the iPhone 18 Pro\"). "
        "Cover the whole keynote — opening, mid-event products, and close — "
        "not only the first ten minutes of company history. "
        "Do not invent products that are not in the sources. "
        "No 'as of my last update'. Start with [FROM SEARCH]."
    )
    sampled = sample_keynote_transcript(transcript, duration_sec=duration_sec)
    parts = [f"User question: {question.strip()}"]
    if title or url:
        runtime = f"{minutes} minutes" if minutes else ""
        line = f"Official video: {title}\n{url}".strip()
        if runtime:
            line += f"\nRuntime: {runtime}"
        parts.append(line)
    if sampled:
        parts.append(f"Keynote transcript:\n{sampled}")
    if web_context.strip():
        parts.append(f"Web search results:\n{web_context[:4000]}")
    parts.append(
        f"This keynote lasted about {minutes} minutes. "
        f"Write a recap with about {headings} headings and about {words} words. "
        "Mix the transcript and search into one AI-written recap. "
        "First line must be a full overview sentence, not a product name. "
        "Cite a couple of source links. End with the YouTube link when one is provided."
    )
    return system, "\n\n".join(parts)


def fetch_official_transcript(question: str) -> tuple[str, str, str, int]:
    """Return (watch_url, title, transcript, duration_sec) or empties."""
    try:
        from arka.youtube.transcript import fetch_transcript_text, youtube_search
    except ImportError:
        return "", "", "", 0
    brand = launch_brand(question) or "apple"
    year = launch_year(question)
    try:
        hits = youtube_search(official_youtube_query(question), limit=8, with_duration=True)
    except TypeError:
        try:
            hits = youtube_search(official_youtube_query(question), limit=8)
        except BaseException:
            return "", "", "", 0
    except BaseException:
        return "", "", "", 0

    def _score(hit: tuple) -> int:
        return score_official_video(
            hit[1],
            hit[2],
            brand=brand,
            year=year,
            question=question,
            duration_sec=_hit_duration(hit),
        )

    ranked = sorted(hits or [], key=_score, reverse=True)
    for hit in ranked[:5]:
        video_id, title, _channel = hit[0], hit[1], hit[2]
        if not video_id or _score(hit) < 8:
            continue
        duration_sec = _hit_duration(hit)
        try:
            transcript = fetch_transcript_text(video_id, research=True, allow_whisper=False) or ""
        except Exception:
            transcript = ""
        if looks_like_video_description(transcript, duration_sec=duration_sec):
            continue
        if len(transcript.split()) < 80:
            continue
        return f"https://www.youtube.com/watch?v={video_id}", title, transcript, duration_sec
    return "", "", "", 0


def summarize_official_launch(question: str, *, web_context: str = "") -> str:
    """Official YouTube transcript mixed with search → rewritten briefing."""
    if not is_launch_recap_question(question):
        return ""
    url, title, transcript, duration_sec = fetch_official_transcript(question)
    if not transcript.strip() and not (web_context or "").strip():
        return ""
    if not transcript.strip():
        return ""
    duration_sec = infer_keynote_seconds(transcript, duration_sec=duration_sec, question=question)
    system, user = launch_rewrite_prompt(
        question,
        title=title,
        url=url,
        transcript=transcript,
        web_context=web_context,
        duration_sec=duration_sec,
    )
    try:
        from arka.output import llm_user_answer

        reply = (
            llm_user_answer(
                system,
                user,
                task="chat",
                skill="web_answer",
                temperature=0.2,
                suffix=url if url else "",
            )
            or ""
        ).strip()
    except ImportError:
        try:
            from arka.llm.fallback import llm_complete
        except ImportError:
            return ""
        reply = (
            llm_complete(
                system,
                user,
                task="chat",
                skill="web_answer",
                temperature=0.2,
            )
            or ""
        ).strip()
    if not reply:
        return ""
    if not reply.lstrip().upper().startswith("[FROM SEARCH]"):
        reply = f"[FROM SEARCH]\n{reply}"
    reply = format_launch_briefing(reply)
    if url and url not in reply:
        reply = f"{reply.rstrip()}\n\n{url}"
    return reply
