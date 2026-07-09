"""Shared offline NL patterns for Python router (mirrors fish symbolic routes)."""

from __future__ import annotations

import re
import shlex


def route_remind(cmd: str) -> str | None:
    try:
        from arka.integrations.remind import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "remind " + " ".join(shlex.quote(a) for a in argv)


def route_routines(cmd: str) -> str | None:
    try:
        from arka.integrations.routines import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "routines " + " ".join(shlex.quote(a) for a in argv)


def route_chart(cmd: str) -> str | None:
    try:
        from arka.charts.plot import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "chart " + " ".join(shlex.quote(a) for a in argv)


def route_drawing(cmd: str) -> str | None:
    try:
        from arka.documents.drawing import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "drawing_ask " + " ".join(shlex.quote(a) for a in argv)


def route_describe_screen(cmd: str) -> str | None:
    try:
        from arka.vision.screen import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "describe_screen " + " ".join(shlex.quote(a) for a in argv)


def route_describe_image(cmd: str) -> str | None:
    try:
        from arka.vision.describe import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "describe_image " + " ".join(shlex.quote(a) for a in argv)


def route_download(cmd: str) -> str | None:
    clean = cmd.lower()
    if re.search(r"(?i)download\s+and\s+install", clean):
        return None
    if re.search(r"(?i)(youtube\s+bulk|playlist\?list=|youtu\.be/|youtube\.com/watch)", clean):
        return None
    url_m = re.search(r"https?://[^\s\"']+", cmd)
    if url_m:
        url = url_m.group(0).rstrip(".,)")
        if re.search(r"(?i)\b(download|save|fetch|grab|wget|curl)\b", clean):
            return f"download_file {shlex.quote(url)}"
        if cmd.strip() == url:
            return f"download_file {shlex.quote(url)}"
    m = re.match(r"(?i)^(?:download\s+|wget\s+|curl\s+-o\s+|download\s+(?:this|the)\s+)(.+)$", cmd.strip())
    if m:
        target = m.group(1).strip()
        if target:
            return "download_file " + shlex.quote(target)
    return None


def route_timer(cmd: str) -> str | None:
    clean = cmd.lower().strip()
    if not re.search(r"\b(timer|countdown)\b", clean):
        return None
    rest = re.sub(r"(?i)^(?:please\s+)?(?:set\s+a\s+)?(?:timer|countdown)\s+(?:for\s+)?", "", cmd).strip()
    return f"timer {rest}" if rest else "timer"


def route_search_web(cmd: str) -> str | None:
    clean = cmd.lower()
    m = re.search(
        r"(?i)(?:search\s+(?:the\s+)?(?:web|internet)(?:\s+for)?|google\s+(?:search\s+)?(?:for\s+)?|"
        r"look\s+up\s+(?:on\s+)?(?:google|the\s+web)(?:\s+for)?)\s+(.+)",
        cmd,
    )
    if m:
        return f"search_web {shlex.quote(m.group(1).strip())}"
    if re.search(r"(?i)^search\s+(?!files?\b|my\s+files?\b)", clean):
        rest = re.sub(r"(?i)^search\s+", "", cmd).strip()
        if rest and not re.search(r"\bfiles?\b", rest, re.I):
            return f"search_web {shlex.quote(rest)}"
    return None


def route_product_reviewer(cmd: str) -> str | None:
    clean = cmd.lower().strip()
    triggers = [
        r"(?i)\b(?:product\s+reviewer|review\s+this\s+product|check\s+(?:the\s+)?ingredients|"
        r"ingredient\s+check|analyze\s+ingredients|ingredients?\s+review)\b",
        r"(?i)\b(?:is\s+this|are\s+these)\s+.+\s+good\s+for\s+",
        r"(?i)\bis\s+.+\s+(?:vegan|cruelty[- ]free|safe\s+for\s+sensitive\s+skin)\b",
        r"(?i)\b(?:what(?:'s| is)\s+in|ingredients?\s+(?:of|in))\s+",
    ]
    matched = any(re.search(pat, clean) for pat in triggers)
    if not matched:
        return None
    rest = re.sub(
        r"(?i)^(?:please\s+)?(?:product\s+reviewer|review\s+this\s+product|"
        r"check\s+(?:the\s+)?ingredients|ingredient\s+check|analyze\s+ingredients|"
        r"ingredients?\s+review)\s*",
        "",
        cmd,
    ).strip()
    if rest:
        return f"product_reviewer {shlex.quote(rest)}"
    return "product_reviewer"


def route_agent_skills(cmd: str) -> str | None:
    clean = cmd.lower().strip()
    patterns: list[tuple[str, str]] = [
        (r"(?i)\b(?:code\s+agent|agent\s+code)\b", "agent_code"),
        (r"(?i)\b(?:browser\s+agent|agent\s+browser)\b", "agent_browser"),
        (r"(?i)\b(?:agent\s+research|research\s+agent)\b", "agent_research"),
        (r"(?i)\b(?:meeting\s+agent|summarize\s+(?:these\s+)?meeting\s+notes)\b", "meeting_agent"),
        (r"(?i)\b(?:study\s+agent|help\s+me\s+study)\b", "study_agent"),
        (r"(?i)\b(?:compare\s+agent|agent\s+compare)\b", "compare_agent"),
        (r"(?i)\b(?:product\s+reviewer|review\s+this\s+product|check\s+(?:the\s+)?ingredients|"
         r"ingredient\s+check|analyze\s+ingredients)\b", "product_reviewer"),
        (r"(?i)\b(?:agent\s+fanout|fanout\s+agent|parallel\s+agent)\b", "agent_fanout"),
        (r"(?i)\b(?:agent\s+watch|watch\s+agent)\b", "agent_watch"),
        (r"(?i)\bsupermemory\b", "supermemory"),
        (r"(?i)\bsemantic\s+memory\b", "semantic_memory"),
        (r"(?i)\b(?:set\s+my\s+location|my\s+location\s+is|i\s+am\s+in)\b", "set_location"),
        (r"(?i)\b(?:download\s+map|offline\s+map|map\s+download)\b", "map_download"),
        (r"(?i)\b(?:pause|resume|next|skip)\s+(?:spotify|music|song|track)\b", "spotify_control"),
        (r"(?i)\b(?:transcript\s+ask|ask\s+(?:my\s+)?(?:podcast|transcript|recording))\b", "transcript_ask"),
        (r"(?i)\b(?:media\s+ask|ask\s+(?:about\s+)?(?:this\s+)?(?:video|audio|media))\b", "media_ask"),
        (r"(?i)\b(?:pdf\s+list|list\s+(?:ingested\s+)?(?:pdfs?|documents?))\b", "pdf_list"),
        (r"(?i)\b(?:rag\s+setup|setup\s+rag|turboquant\s+setup)\b", "rag_setup"),
        (r"(?i)\b(?:rag\s+status|check\s+rag)\b", "rag_status"),
    ]
    for pat, skill in patterns:
        if re.search(pat, clean):
            rest = re.sub(pat, "", cmd, count=1, flags=re.I).strip()
            if rest and skill not in {
                "rag_setup",
                "rag_status",
                "pdf_list",
                "spotify_control",
                "set_location",
                "map_download",
            }:
                return f"{skill} {shlex.quote(rest)}"
            return skill
    return None


def route_currency_convert(cmd: str) -> str | None:
    try:
        from arka.integrations.currency import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "currency_convert " + " ".join(shlex.quote(a) for a in argv)


def route_compose_video(cmd: str) -> str | None:
    try:
        from arka.media.compose_video import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "compose_video " + " ".join(shlex.quote(a) for a in argv)


def route_generate_image(cmd: str) -> str | None:
    try:
        from arka.generate.image import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "generate_image " + " ".join(shlex.quote(a) for a in argv)


def route_generate_thumbnail(cmd: str) -> str | None:
    try:
        from arka.media.thumbnail import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "generate_thumbnail generate " + " ".join(shlex.quote(a) for a in argv)


def route_offline_extras(cmd: str) -> str | None:
    """Try supplemental NL routes not always available via fish bridge."""
    for fn in (
        route_currency_convert,
        route_remind,
        route_routines,
        route_chart,
        route_drawing,
        route_describe_screen,
        route_describe_image,
        route_generate_thumbnail,
        route_generate_image,
        route_download,
        route_compose_video,
        route_timer,
        route_search_web,
        route_product_reviewer,
        route_agent_skills,
    ):
        hit = fn(cmd)
        if hit:
            return hit
    return None
