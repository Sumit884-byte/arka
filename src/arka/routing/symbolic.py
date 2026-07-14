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


def route_design_from_screenshot(cmd: str) -> str | None:
    try:
        from arka.agent.design_from_screenshot import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_describe_video(cmd: str) -> str | None:
    try:
        from arka.vision.video import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "describe_video " + " ".join(shlex.quote(a) for a in argv)


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


def route_open_url(cmd: str) -> str | None:
    try:
        from arka.integrations.open_url import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


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


def route_price_check(cmd: str) -> str | None:
    try:
        from arka.agent.price_sources import is_price_check_query
    except ImportError:
        return None
    if not is_price_check_query(cmd):
        return None
    rest = re.sub(r"(?i)^price_check\s+", "", cmd).strip() or cmd.strip()
    return f"price_check {shlex.quote(rest)}"


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
    try:
        argv = nl_to_argv(cmd.strip())
    except ValueError:
        return None
    if not argv:
        return None
    return "currency_convert " + " ".join(shlex.quote(a) for a in argv)


def is_timezone_convert_request(text: str) -> bool:
    """True when NL looks like datetime/timezone conversion, not currency."""
    clean = (text or "").strip()
    if not clean:
        return False
    try:
        from arka.integrations.timezone_convert import wants_timezone_convert
    except ImportError:
        return False
    return wants_timezone_convert(clean)


def route_convert(cmd: str) -> str | None:
    """Disambiguate convert NL: timezone wins when args look like timezones."""
    hit = route_timezone_convert(cmd)
    if hit:
        return hit
    return route_currency_convert(cmd)


def route_timezone_convert(cmd: str) -> str | None:
    try:
        from arka.integrations.timezone_convert import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_kalshi(cmd: str) -> str | None:
    try:
        from arka.integrations.kalshi import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_kaggle(cmd: str) -> str | None:
    try:
        from arka.integrations.kaggle import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_convert_media(cmd: str) -> str | None:
    try:
        from arka.media.convert_media import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "convert_media " + " ".join(shlex.quote(a) for a in argv)


def route_compose_slides(cmd: str) -> str | None:
    try:
        from arka.media.compose_slides import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "compose_slides " + " ".join(shlex.quote(a) for a in argv)


def route_compose_video(cmd: str) -> str | None:
    try:
        from arka.media.compose_video import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "compose_video " + " ".join(shlex.quote(a) for a in argv)


def route_ascii_art(cmd: str) -> str | None:
    try:
        from arka.agent.ascii_art import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "ascii_art " + " ".join(shlex.quote(a) for a in argv)


def route_astronomy(cmd: str) -> str | None:
    try:
        from arka.agent.astronomy import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "astronomy " + " ".join(shlex.quote(a) for a in argv)


def route_compose_3d(cmd: str) -> str | None:
    try:
        from arka.media.compose_3d import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "compose_3d " + " ".join(shlex.quote(a) for a in argv)


def route_three_d(cmd: str) -> str | None:
    """Backward-compatible alias for compose_3d."""
    return route_compose_3d(cmd)


def route_metallurgy(cmd: str) -> str | None:
    try:
        from arka.agent.metallurgy import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "metallurgy " + " ".join(shlex.quote(a) for a in argv)


def route_flow(cmd: str) -> str | None:
    try:
        from arka.agent.flow import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "flow " + " ".join(shlex.quote(a) for a in argv)


def route_fact_check(cmd: str) -> str | None:
    try:
        from arka.agent.fact_check import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "fact_check " + " ".join(shlex.quote(a) for a in argv)


def route_quiz_practice(cmd: str) -> str | None:
    try:
        from arka.agent.quiz_practice import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "quiz_practice " + " ".join(shlex.quote(a) for a in argv)


def route_council(cmd: str) -> str | None:
    try:
        from arka.agent.council import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "council " + " ".join(shlex.quote(a) for a in argv)


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


from arka.routing.file_size import route_find_files_by_size  # noqa: F401 — re-export


def route_gmail_draft(cmd: str) -> str | None:
    try:
        from arka.integrations.google_workspace import build_gmail_draft_argv_from_nl
    except ImportError:
        return None
    argv = build_gmail_draft_argv_from_nl(cmd)
    if not argv:
        return None
    return " ".join(shlex.quote(a) for a in argv)


def route_post_x(cmd: str) -> str | None:
    try:
        from arka.integrations.x_post import build_post_x_argv_from_nl
    except ImportError:
        return None
    argv = build_post_x_argv_from_nl(cmd)
    if not argv:
        return None
    return "post_x " + " ".join(shlex.quote(a) for a in argv)


def route_learned(cmd: str) -> str | None:
    try:
        from arka.routing.learned import match_learned, route_management_command, wants_route_management
    except ImportError:
        return None
    if wants_route_management(cmd):
        managed = route_management_command(cmd)
        return managed or None
    hit = match_learned(cmd)
    return hit or None


_BRIEF_RE = re.compile(
    r"(?i)\b("
    r"(?:daily|morning|news)\s+brief|"
    r"today['']?s\s+(?:tech\s+)?brief|"
    r"(?:daily|morning|news|today['']?s)\s+tech\s+brief|"
    r"tech\s+brief(?:\s+(?:personalized(?:\s+for\s+me)?|for\s+me))?|"
    r"personalized\s+(?:tech\s+)?brief"
    r")\b"
)


def route_daily_brief(cmd: str) -> str | None:
    if _BRIEF_RE.search(cmd):
        return "daily_brief"
    return None


def route_competitions(cmd: str) -> str | None:
    try:
        from arka.agent.competitions import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_bookmarks(cmd: str) -> str | None:
    try:
        from arka.agent.bookmarks import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_repo_health(cmd: str) -> str | None:
    try:
        from arka.agent.repo_health import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_repo_context(cmd: str) -> str | None:
    try:
        from arka.agent.repo_context import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_repo_map(cmd: str) -> str | None:
    try:
        from arka.agent.repo_context import wants_repo_context
        from arka.agent.repo_map import route_command
    except ImportError:
        return None
    if wants_repo_context(cmd):
        return None
    route = route_command(cmd)
    return route or None


def route_pr_check(cmd: str) -> str | None:
    try:
        from arka.agent.pr_check import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_generate_data(cmd: str) -> str | None:
    try:
        from arka.agent.generate_data import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_view_data(cmd: str) -> str | None:
    try:
        from arka.agent.view_data import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_data_ask(cmd: str) -> str | None:
    try:
        from arka.agent.data_ask import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_docker_status(cmd: str) -> str | None:
    try:
        from arka.integrations.docker_status import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_heartbeat(cmd: str) -> str | None:
    try:
        from arka.integrations.heartbeat import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_jsonkit(cmd: str) -> str | None:
    try:
        from arka.core.jsonkit import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_clipboard_history(cmd: str) -> str | None:
    try:
        from arka.integrations.clipboard_history import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_personalize(cmd: str) -> str | None:
    try:
        from arka.core.personalize import is_personalize_query, nl_to_argv
    except ImportError:
        return None
    if not is_personalize_query(cmd):
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return "personalize recommend"
    return "personalize " + " ".join(shlex.quote(a) for a in argv)


def route_provider_select(cmd: str) -> str | None:
    try:
        from arka.llm.provider_select import is_provider_select_query, nl_to_argv
    except ImportError:
        return None
    clean = cmd.strip()
    if not is_provider_select_query(clean):
        return None
    argv = nl_to_argv(clean)
    if not argv:
        return "provider show"
    return "provider " + " ".join(__import__("shlex").quote(a) for a in argv)


def route_model_select(cmd: str) -> str | None:
    try:
        from arka.llm.model_advisor import is_model_select_query, nl_to_argv
    except ImportError:
        return None
    clean = cmd.strip()
    if not is_model_select_query(clean):
        return None
    argv = nl_to_argv(clean)
    if not argv:
        return "select_model"
    return "select_model " + " ".join(shlex.quote(a) for a in argv)


def route_stt_install(cmd: str) -> str | None:
    try:
        from arka.agent.stt_install import route_command
    except ImportError:
        return None
    return route_command(cmd)


def route_free_credits(cmd: str) -> str | None:
    try:
        from arka.agent.free_credits import route_command
    except ImportError:
        return None
    return route_command(cmd)


def route_life_sciences(cmd: str) -> str | None:
    clean = cmd.lower()
    m = re.search(r"(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)(?:\s+(\S+))?", cmd)
    if m:
        sub = m.group(2).lower()
        extra = (m.group(3) or "").strip()
        return f"life_sciences {sub} {extra}".strip()

    m = re.search(
        r"(?i)\b(?:install|setup)\s+(pubmed|single[- ]cell(?:[- ]rna[- ]qc)?|nextflow(?:[- ]development)?|scvi(?:[- ]tools)?|life[- ]sciences?)\b",
        cmd,
    )
    if m:
        token = m.group(1).lower().replace(" ", "-")
        mapping = {
            "pubmed": "life_sciences install pubmed",
            "single-cell": "life_sciences install single-cell-rna-qc",
            "single-cell-rna-qc": "life_sciences install single-cell-rna-qc",
            "nextflow": "life_sciences install nextflow-development",
            "nextflow-development": "life_sciences install nextflow-development",
            "scvi": "life_sciences install scvi-tools",
            "scvi-tools": "life_sciences install scvi-tools",
            "life-sciences": "life_sciences list",
            "life-science": "life_sciences list",
        }
        return mapping.get(token)

    if re.search(r"(?i)\b(life[- ]sciences?|biomedical research tools|bioinformatics tools)\b", clean):
        return "life_sciences list"
    return None


def route_platform_howto(cmd: str) -> str | None:
    try:
        from arka.routing.platform_howto import is_platform_howto_question
    except ImportError:
        return None
    if is_platform_howto_question(cmd):
        return f"platform_howto {cmd.strip()}"
    return None


def route_interesting_fact(cmd: str) -> str | None:
    try:
        from arka.routing.interesting_fact import is_interesting_fact_request
    except ImportError:
        return None
    if is_interesting_fact_request(cmd):
        return f"interesting_fact {cmd.strip()}"
    return None


def route_fugu(cmd: str) -> str | None:
    try:
        from arka.integrations.fugu import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_gemini_cli(cmd: str) -> str | None:
    try:
        from arka.integrations.gemini_cli import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_harvard_ark(cmd: str) -> str | None:
    try:
        from arka.integrations.harvard_ark import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_elon(cmd: str) -> str | None:
    try:
        from arka.agent.personas.base import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_persona(cmd: str) -> str | None:
    return route_elon(cmd)


def route_mcp(cmd: str) -> str | None:
    try:
        from arka.integrations.mcp_manager import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "mcp " + " ".join(shlex.quote(a) for a in argv)


def route_agent_hub(cmd: str) -> str | None:
    try:
        from arka.integrations.agent_hub import nl_to_argv
    except ImportError:
        return None
    argv = nl_to_argv(cmd.strip())
    if not argv:
        return None
    return "agent_hub " + " ".join(shlex.quote(a) for a in argv)


def route_dev_tools(cmd: str) -> str | None:
    try:
        from arka.agent.dev_tools import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_mode(cmd: str) -> str | None:
    try:
        from arka.core.mode import route_mode_nl
    except ImportError:
        return None
    return route_mode_nl(cmd.strip())


def route_code_project(cmd: str) -> str | None:
    try:
        from arka.core.code_project import route_code_nl
    except ImportError:
        return None
    return route_code_nl(cmd.strip())


def route_self_improve(cmd: str) -> str | None:
    try:
        from arka.agent.self_improve import route_command
    except ImportError:
        return None
    line = route_command(cmd.strip())
    return line or None


def route_help(cmd: str) -> str | None:
    clean = cmd.strip().lower()
    if clean in ("help", "skills", "?"):
        return "help"
    return None


def route_offline_extras(cmd: str) -> str | None:
    """Try supplemental NL routes not always available via fish bridge."""
    for fn in (
        route_help,
        route_self_improve,
        route_mode,
        route_design_from_screenshot,
        route_code_project,
        route_heartbeat,
        route_jsonkit,
        route_agent_hub,
        route_mcp,
        route_clipboard_history,
        route_learned,
        route_competitions,
        route_bookmarks,
        route_pr_check,
        route_repo_health,
        route_repo_context,
        route_repo_map,
        route_generate_data,
        route_view_data,
        route_describe_screen,
        route_describe_video,
        route_describe_image,
        route_currency_convert,
        route_timezone_convert,
        route_convert,
        route_data_ask,
        route_docker_status,
        route_daily_brief,
        route_model_select,
        route_stt_install,
        route_free_credits,
        route_dev_tools,
        route_provider_select,
        route_personalize,
        route_life_sciences,
        route_interesting_fact,
        route_platform_howto,
        route_fugu,
        route_gemini_cli,
        route_harvard_ark,
        route_persona,
        route_elon,
        route_gmail_draft,
        route_post_x,
        route_find_files_by_size,
        route_kalshi,
        route_kaggle,
        route_remind,
        route_routines,
        route_fact_check,
        route_quiz_practice,
        route_council,
        route_compose_3d,
        route_three_d,
        route_chart,
        route_drawing,
        route_generate_thumbnail,
        route_ascii_art,
        route_astronomy,
        route_metallurgy,
        route_flow,
        route_generate_image,
        route_download,
        route_convert_media,
        route_compose_slides,
        route_compose_video,
        route_timer,
        route_open_url,
        route_search_web,
        route_price_check,
        route_product_reviewer,
        route_agent_skills,
    ):
        hit = fn(cmd)
        if hit:
            return hit
    return None
