"""Shared offline NL patterns for Python router (mirrors fish symbolic routes)."""

from __future__ import annotations

import re
import shlex
from pathlib import Path


def route_greeting(cmd: str) -> str | None:
    try:
        from arka.integrations.greeting import route_greeting as route_command
    except ImportError:
        return None
    return route_command(cmd)


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


def route_batch(cmd: str) -> str | None:
    try:
        from arka.agent.batch import route_command
    except ImportError:
        return None
    return route_command(cmd)


def route_config_share(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:share|export|send|copy)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:arka\s+)?config(?:uration)?s?\b", cmd):
        return None
    return "config share export"


def route_semantic_alert(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:alert|notify|remind)\s+me\b", cmd) or not re.search(r"(?i)\b(?:when|whenever|once|after)\b", cmd):
        return None
    event = re.sub(r"(?i)^.*?\b(?:when|once|after)\b\s+", "", cmd).strip() or "deadline"
    return "semantic_alert " + shlex.quote(event)


def route_usage_dashboard(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:usage|skill\s+usage)\b", cmd) and re.search(r"(?i)\b(?:dashboard|visuali[sz]e|report)\b", cmd):
        return "usage dashboard"
    return None


def route_symbolic_image(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:comparison|split[- ]panel|before\s+and\s+after|compose)\b", cmd) or not re.search(r"(?i)\b(?:image|visual|graphic|illustration)\b", cmd):
        return None
    return "symbolic_image comparison"


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

def route_background_remove(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(remove|erase|delete)\b.*\bbackground\b|\bbackground\s+removal\b", cmd):
        return None
    paths = re.findall(r"(?:^|\s)([^\s]+\.(?:png|jpe?g|webp))\b", cmd, re.I)
    return "background_remove " + shlex.quote(paths[0]) if paths else "background_remove"

def route_iterate(cmd: str) -> str | None:
    m = re.search(r"(?i)\biterate\s+(\d+)\s+(.+)$", cmd.strip())
    if m:
        return "iterate " + m.group(1) + " " + m.group(2)
    m = re.search(r"(?i)\b(?:run|repeat)\s+(.+?)\s+every\s+(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)\b", cmd.strip())
    if m:
        factor = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600}[m.group(3).lower()]
        return f"loop {float(m.group(2)) * factor:g} {m.group(1)}"
    return None


def route_loop_engineering(cmd: str) -> str | None:
    """Route explicit engineering-loop language to the reusable planner."""
    if not re.search(r"(?i)\b(?:loop\s+engineering|engineering\s+loop|iterative\s+engineering)\b", cmd):
        return None
    match = re.search(r"(?i)\b(?:for|with)\s+(\d+)\s+iterations?\b", cmd)
    iterations = f" --iterations {match.group(1)}" if match else ""
    task = re.sub(r"(?i)\b(?:loop\s+engineering|engineering\s+loop|iterative\s+engineering)\b", "", cmd).strip()
    task = re.sub(r"(?i)\b(?:for|with)\s+\d+\s+iterations?\b", "", task).strip()
    return "loop-engineering" + iterations + (f" {task}" if task else "")


def route_ultra_fast(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:ultra\s*fast|fast\s+development|multitask).*(?:priority|iteration|iterate)|\bpriority\s+(?:0|1)\b|\bauto(?:matic)?\s+priority\b", cmd):
        suffix = " --auto-priority" if re.search(r"(?i)\b(?:auto|automatic|all)\s+priorit(?:y|ize)|prioritize\s+everything", cmd) else ""
        return "ultra_fast " + cmd + suffix
    return None

def route_env_setup(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:create|generate|make)\s+(?:a\s+)?(?:safe\s+)?\.env\b", cmd):
        return "env_setup"
    return None

def route_research_math(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:research|reproducible|auditable)\s+math\b|\bwrite\s+(?:a\s+)?math(?:ematical)?\s+script\b", cmd):
        return "research_math " + cmd.split("math", 1)[-1].strip()
    return None

def route_prompt_optimize(cmd: str) -> str | None:
    m = re.search(r"(?i)\b(?:optimize|improve|rewrite)\s+(?:this\s+)?prompt\s*[:\-]?\s*(.+)$", cmd.strip())
    return "prompt_optimize " + m.group(1) if m else None

def route_deploy(cmd: str) -> str | None:
    if re.search(r"(?i)\bdeploy\s+(?:this\s+)?(?:app|site|project|backend|api)\s+(?:to|on)\s+(?:vercel|netlify|railway|render)\b", cmd):
        platform = re.search(r"(?i)\b(vercel|netlify|railway|render)\b", cmd).group(1).lower()
        return f"deploy --platform {platform}"
    return None

def route_geo_seo(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:geo|ai\s+search|seo)\s+(?:seo\s+)?(?:audit|analy[sz]e|check)\b", cmd):
        return "geo_seo"
    return None

def route_templates(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:list|show|choose|use)\b.*\b(?:prompt|workflow|loop)\s+templates?\b|\b(?:list|show)\s+(?:arka\s+)?templates?\b", cmd):
        return "template list"
    return None


def route_blocks(cmd: str) -> str | None:
    try:
        from arka.agent.blocks import route_command
    except ImportError:
        route_command = None
    if route_command:
        create_route = route_command(cmd)
        if create_route:
            return create_route
    if not re.search(r"(?i)\b(?:reusable|app|ui|code)\s+blocks?\b|\b(?:login|sign\s*up|payment|password\s+reset|oauth|webhook|subscription|crypto\s+wallet|web3\s+wallet)\s+(?:block|component|starter|page)", cmd):
        return None
    if re.search(r"(?i)\b(?:list|available)\b", cmd):
        return "blocks list"
    for name, words in (("auth_login", r"login|sign\s*in"), ("auth_signup", r"sign\s*up|signup|register"), ("auth_password_reset", r"password\s+reset|forgot\s+password"), ("auth_oauth", r"oauth|social\s+login"), ("auth_email_verification", r"email\s+verification|verify\s+email"), ("payments_subscription", r"subscription|recurring\s+payment"), ("payments_paypal", r"paypal"), ("webhook_receiver", r"webhook"), ("web3_wallet", r"(?:crypto|web3|blockchain)\s+wallet|wallet"), ("payments_stripe", r"payment|stripe|checkout")):
        if re.search(rf"(?i)\b(?:{words})\b", cmd):
            return f"blocks show {name}"
    return "blocks list"

def route_optimize(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:optimize|evolve)\b.*\b(?:objective|parameters?|function)\b", cmd):
        return "optimize " + cmd
    return None

def route_design_flow(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:design|plan)\s+(?:this|a|an)?\s*(?:project|feature|app|workflow)\b", cmd):
        return "design plan " + cmd
    return None

def route_repo_reverse(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:reverse engineer|reverse-engineer|turn|convert)\b.*\b(?:repo|repository|codebase)\b", cmd):
        return "repo_reverse"
    return None

def route_browser_check(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:check|inspect|verify|test)\b.*\b(?:browser|rendered|frontend|ui)\b", cmd):
        urls = re.findall(r"https?://[^\s]+", cmd)
        return "browser_check " + (urls[0] if urls else "http://127.0.0.1:3000")
    return None


def route_app_automation(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:automate|automation|test)\b", cmd) or not re.search(r"(?i)\b(?:app|website|webs+app|browser)\b", cmd):
        return None
    urls = re.findall(r"https?://[^\s]+", cmd)
    return "automate " + (urls[0] if urls else "http://127.0.0.1:3000")


def route_design_from_screenshot(cmd: str) -> str | None:
    try:
        from arka.agent.design_from_screenshot import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_frontend_loop(cmd: str) -> str | None:
    try:
        from arka.agent.frontend_loop import route_command
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


def route_video_evidence(cmd: str) -> str | None:
    try:
        from arka.agent.video_evidence import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_download(cmd: str) -> str | None:
    try:
        from arka.core.code_project import looks_like_repo_edit

        if looks_like_repo_edit(cmd):
            return None
    except ImportError:
        pass
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


def route_site_summary(cmd: str) -> str | None:
    try:
        from arka.integrations.site_summary import route_site_summary as route_command
    except ImportError:
        return None
    return route_command(cmd.strip())


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


def route_visual_inspection(cmd: str) -> str | None:
    """Prefer local pixel inspection over web research for captured visuals."""
    if not re.search(r"(?i)\b(?:analy[sz]e|inspect|review|diagnos|find|fix|check)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:visual|pixel|screenshot|frame|gameplay|animation|render(?:ing)?|ui|frontend)\b", cmd):
        return None
    source = re.search(r"(?:~|/|\./|\.\./)?[^\s'\"]+\.(?:png|jpe?g|webp|gif|mp4|webm)\b", cmd, re.I)
    if source:
        return "frontend_loop review " + shlex.quote(source.group(0))
    directory = re.search(r"(?:frames?|screenshots?|recordings?)\s+(?:in|at|from)\s+([^\s]+)", cmd, re.I)
    if directory:
        return "frontend_loop review " + shlex.quote(directory.group(1))
    # Do not manufacture a URL or send the request to web search.
    return "frontend_loop review screenshots"


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


def route_model_to_image(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:render|turn|convert|generate)\b.*\b(?:3d|model|mesh)\b.*\b(?:image|png|picture|render)\b", cmd):
        return None
    path = re.search(r"(?:~|/|\./|\.\./)?[^\s]+\.(?:obj|stl|glb|gltf)\b", cmd, re.I)
    if not path:
        return None
    source = path.group(0)
    route = f"model_to_image {shlex.quote(source)} --output {shlex.quote(Path(source).stem + '-render.png')}"
    task = re.search(r"(?i)\b(?:for|to show|from)\s+(.+)$", cmd)
    return route + (f" --task {shlex.quote(task.group(1))}" if task else "")


def route_three_d(cmd: str) -> str | None:
    """Backward-compatible alias for compose_3d."""
    return route_compose_3d(cmd)


def route_text_to_3d(cmd: str) -> str | None:
    try:
        from arka.agent.text_to_3d import route_command
    except ImportError:
        return None
    return route_command(cmd)


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


def route_media_transform(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:convert|turn|transform)\b.*\b(?:podcast|playlist|audio|video|media)\b.*\b(?:book|podcast|audio)\b", cmd):
        return None
    target = "book" if re.search(r"(?i)\bbook\b", cmd) else "podcast"
    source = re.search(r"https?://\S+|[\w./~-]+\.(?:mp3|mp4|wav|m4a|mov|txt|md)", cmd, re.I)
    if not source:
        return None
    stem = Path(source.group(0).split("?")[0]).stem or "output"
    return f"media_transform {shlex.quote(source.group(0))} --to {target} --output {shlex.quote(stem + ('.md' if target == 'book' else '.mp3'))}"


def route_competitions(cmd: str) -> str | None:
    try:
        from arka.agent.competitions import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_scene_3d(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:scene|environment|world)\b", cmd) or not re.search(r"(?i)\b(?:3d|three\.js|model|human|character|asset)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:create|build|generate|compose|use|place)\b", cmd):
        return None
    models = re.findall(r"(?:https?://[^\s]+|[^\s]+\.(?:glb|gltf))", cmd, re.I)
    if not models:
        return None
    return "scene_3d " + shlex.quote(cmd) + (" --model " + " --model ".join(shlex.quote(m) for m in models) if models else "")


def route_rig_3d(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:rig|rigging|skeleton|pose|skinned)\b", cmd) or not re.search(r"(?i)\b(?:3d|model|character|human|avatar)\b", cmd):
        return None
    model = re.search(r"(?:https?://[^\s]+|[^\s]+\.(?:glb|gltf))", cmd, re.I)
    if not model:
        return None
    return "rig_3d " + shlex.quote("Rig inspection") + " --model " + shlex.quote(model.group(0))


def route_parallax_2d(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:parallax|2\.5d|2d\s+to\s+3d|2d\s+depth)\b", cmd):
        return None
    layers = re.findall(r"(?:https?://[^\s]+|[^\s]+\.(?:png|jpe?g|webp|svg))", cmd, re.I)
    if not layers:
        return None
    return "parallax_2d " + shlex.quote("Parallax scene") + " " + " ".join("--layer " + shlex.quote(layer) for layer in layers)


def route_visual_diagnose(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:describe|diagnos|find|fix|review|analy[sz]e)\b", cmd) or not re.search(r"(?i)\b(?:visual|image|screenshot|frame|ui|gameplay)\b", cmd):
        return None
    image = re.search(r"(?:~|/|\./|\.\./)?[^\s]+\.(?:png|jpe?g|webp|gif)\b", cmd, re.I)
    if not image:
        return None
    return "visual_diagnose " + shlex.quote(image.group(0))


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


def route_observability(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:signoz|observability|telemetry|otel|opentelemetry)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:check|doctor|diagnos|improv|setup|status|working|health)\w*\b", cmd):
        return None
    return "observability doctor"

def route_telemetry_connector(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:production|prod)\b.*\b(?:telemetry|errors?|traces?)\b.*\b(?:codebase|code|repo|repository)\b", cmd):
        return "telemetry-connect"
    return None


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


def route_background_processes(cmd: str) -> str | None:
    try:
        from arka.agent.background import route_command
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


def route_model_host_setup(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:best|recommended|optimize|strongest)\b.*\b(?:local\s+)?(?:model|llm)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:setup|set\s+up|configure|host|serve)\b.*\b(?:ai|llm|model|ollama|vllm|lm\s*studio)\b", cmd):
        return None
    host = "ollama" if re.search(r"(?i)\bollama\b", cmd) else "vllm" if re.search(r"(?i)\bvllm\b", cmd) else "lmstudio" if re.search(r"(?i)\blm\s*studio\b", cmd) else "openai-compatible"
    if re.search(r"(?i)\b(?:doctor|check|status)\b", cmd):
        return f"model doctor {host}"
    return f"model setup {host}"


def route_free_models(cmd: str) -> str | None:
    free_model_query = re.search(
        r"(?i)\b(?:free|no[- ]cost|zero[- ]cost)\b.*\b(?:models?|llms?|providers?)\b",
        cmd,
    ) or re.search(r"(?i)\b(?:models?|llms?)\b.*\b(?:free|no[- ]cost|zero[- ]cost)\b", cmd)
    exact_access_query = re.search(
        r"(?i)\b(?:can\s+i\s+)?access\b.*\b(?:gpt|chatgpt|codex|model)\b.*\bfree\b",
        cmd,
    ) or re.search(r"(?i)\b(?:gpt|chatgpt|codex)\b.*\bfree\b", cmd)
    if free_model_query or exact_access_query:
        if re.search(r"(?i)\b(?:chatgpt|openai|gpt|codex)\b", cmd):
            model = re.search(r"(?i)\b(gpt[- ]?[0-9]+(?:\.[0-9]+)?(?:\s+luna)?)\b", cmd)
            if model:
                from arka.llm.free_models import normalize_model_name
                canonical = normalize_model_name(model.group(1))
                suffix = " --model " + shlex.quote(canonical)
            else:
                suffix = ""
            select = " --select" if model else ""
            return "free_models --provider openai" + suffix + select
        return "free_models"
    return None

def route_model_optimizer(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:setup|configure)\b.*\b(?:best|recommended|local)\s+(?:model|llm)\b", cmd):
        backend = "vllm" if re.search(r"(?i)\bvllm\b", cmd) else "lmstudio" if re.search(r"(?i)\blm\s*studio\b", cmd) else "ollama"
        apply = " --apply" if re.search(r"(?i)\bapply|save|write\b", cmd) else ""
        return f"model-optimizer setup --backend {backend}{apply}"
    if re.search(r"(?i)\b(?:model\s+recommend|recommend\s+(?:a|the)?\s*model|best\s+model\s+for\s+my\s+hardware)\b", cmd):
        return "model-optimizer recommend"
    match = re.search(r"(?i)\b(?:switch|use)\s+(?:to\s+)?model\s+([\w./:-]+)", cmd)
    return f"model-optimizer switch {match.group(1)}" if match else None

def route_train_plan(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:train|fine[- ]?tune|qlora|lora)\b.*\b(?:model|llm|dataset)\b", cmd):
        return "train-plan plan " + cmd
    return None

def route_stock_analyze(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:analy[sz]e|report|inspect)\b.*\b(?:stock|market|ohlcv|price\s+data)\b", cmd):
        files = re.findall(r"(?:^|\s)([^\s]+\.csv)\b", cmd, re.I)
        return "stock-analyze " + files[0] if files else "stock-analyze"
    return None

def route_code_convert(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:convert|translate|rewrite)\b.*\b(?:code|script|python|javascript|typescript|rust|go|java)\b", cmd):
        langs = "python javascript typescript rust go java cpp ruby"
        target = next((lang for lang in langs.split() if re.search(rf"\b{lang}\b", cmd, re.I)), "python")
        files = re.findall(r"(?:^|\s)([^\s]+\.(?:py|js|ts|rs|go|java|cpp|rb))\b", cmd, re.I)
        return f"code-convert {files[0]} {target}" if files else f"code-convert . {target}"
    return None

def route_design_resources(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:design|ui|ux|frontend)\b.*\b(?:resources?|inspiration|templates?|icons?|fonts?)\b", cmd):
        return "design-resources show"
    return None

def route_edge(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:edge|raspberry\s*pi|embedded|constrained\s+device|offline\s+device)\b.*\b(?:model|llm|arka|run|inference)\b", cmd):
        return "edge recommend"
    return None

def route_judge_demo(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:judge|reviewer|evaluator)\b.*\b(?:demo|test|sandbox|instance|without\s+rebuild)\b", cmd):
        return "judge-demo init"
    return None


def route_repo_graph(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:repo|repository|codebase)\b.*\b(?:graph|dependencies|priority|priorities|centrality)\b", cmd):
        return "repo_graph"
    return None

def route_workspace(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:workspace|microservices?|micro-frontends?|service\s+map|developer\s+workspace)\b", cmd) and re.search(r"(?i)\b(?:map|scan|discover|list|inspect|show|create)\b", cmd):
        return "workspace"
    return None

def route_structure(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:improve|audit|clean|review|organize|fix)\b.*\b(?:file|project|repo|repository|folder)\s+structure\b", cmd):
        return "structure"
    return None

def route_dev_workflow(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:change\s+impact|impact\s+analysis|what\s+could.*break)\b", cmd):
        return "dev-workflow impact"
    if re.search(r"(?i)\b(?:test\s+gaps?|missing\s+tests?|tests?\s+missing)\b", cmd):
        return "dev-workflow test-gaps"
    if re.search(r"(?i)\b(?:sync|stale|update)\b.*\b(?:docs?|documentation)\b", cmd):
        return "dev-workflow docs-sync"
    return None

def route_graphify(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:graphify|graph|visuali[sz]e)\b.*\b(?:repo|repository|codebase|dependencies|services?)\b", cmd):
        return "graphify"
    return None

def route_spreadsheet(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:create|make|generate|build)\b.*\b(?:spreadsheet|workbook|xlsx|excel)\b", cmd):
        return "spreadsheet " + cmd
    return None

def route_teammate_review(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:ai\s+teammate|coderabbit|greptile|cross[- ]service|entire\s+codebase)\b", cmd) and re.search(r"(?i)\b(?:review|check|audit|break)\b", cmd):
        return "teammate-review"
    return None

def route_society(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:ai\s+society|multi[- ]agent\s+(?:society|simulation)|agents?)\b", cmd) and re.search(r"(?i)\b(?:collaborat|debate|vote|simulate|deliberat)\w*\b", cmd):
        return "society " + cmd
    return None
    return None


def route_data_collect(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:collect|gather|scrape)\b.*\bdata\b|\bdata\b.*\b(?:collect|gather|scrape)\b", cmd):
        return None
    clean = re.sub(r"(?i)\b(?:arka\s+)?(?:auto\s+)?(?:collect|gather|scrape)\s+(?:data\s+)?", "", cmd).strip()
    if re.search(r"(?i)\b(?:all|every|total|how\s+many)\b", cmd):
        clean = re.sub(r"(?i)^\s*(?:all|every)\s+(?:the\s+)?data\s+(?:about|on|for)\s+", "", clean).strip()
        return "data catalog about " + (clean or "research topic")
    return "data collect " + (clean or "research topic")


def route_exercise_dataset(cmd: str) -> str | None:
    try:
        from arka.agent.exercise_dataset import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_github_dataset(cmd: str) -> str | None:
    try:
        from arka.agent.github_dataset import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


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


def route_sandbox(cmd: str) -> str | None:
    clean = re.sub(r"\s+", " ", cmd.strip().lower())
    if not clean:
        return None
    if re.search(r"\b(list|show)\b.*\bsandboxes?\b", clean):
        return "sandbox list"
    if re.search(r"\b(create|make|start)\b.*\bsandbox\b", clean):
        match = re.search(r"sandbox\s+([a-z][a-z0-9_-]{0,63})\b", clean)
        return "sandbox create " + (match.group(1) if match else "default")
    match = re.search(r"\b(?:destroy|delete|remove)\s+sandbox\s+([a-z][a-z0-9_-]{0,63})\b", clean)
    if match:
        return "sandbox destroy " + match.group(1)
    if "sandbox status" in clean or re.search(r"\bstatus\b.*\bsandbox\b", clean):
        match = re.search(r"sandbox\s+([a-z][a-z0-9_-]{0,63})\b", clean)
        return "sandbox status" + (" " + match.group(1) if match else "")
    return None


def route_text_edit(cmd: str) -> str | None:
    clean = cmd.strip()
    low = clean.lower()
    if not re.search(r"\b(inspect|find|remove|delete|erase)\b.*\btext\b|\btext\b.*\b(remove|inspect|find)\b", low):
        return None
    match = re.search(r"\b(?:in|from)\s+([\w./~-]+)", clean, re.I)
    quoted = re.search(r"[\"']([^\"']+)[\"']", clean)
    if not match or not quoted:
        return None
    action = "inspect" if re.search(r"\b(inspect|find)\b", low) else "remove"
    extra = " --all --yes" if action == "remove" and re.search(r"\b(all|every)\b", low) else ""
    if action == "remove" and re.search(r"\b(remove|delete|erase)\b", low) and "--yes" not in low:
        return f"text {action} {shlex.quote(match.group(1))} {shlex.quote(quoted.group(1))}"
    return f"text {action} {shlex.quote(match.group(1))} {shlex.quote(quoted.group(1))}{extra}"


def route_surgical_edit(cmd: str) -> str | None:
    if not re.search(r"\b(?:surgical|keyword[- ]first|precise)\b.*\b(?:edit|change|replace)\b|\bedit\b.*\b(?:only|after)\b.*\b(?:search|find)\b", cmd, re.I):
        return None
    quoted = re.findall(r"[\"']([^\"']+)[\"']", cmd)
    path = re.search(r"(?:in|from|file)\s+([\w./~-]+)", cmd, re.I)
    if not path or len(quoted) < 2:
        return None
    return "surgical_edit edit " + shlex.quote(path.group(1)) + " " + shlex.quote(quoted[0]) + " " + shlex.quote(quoted[1])


def route_ideate(cmd: str) -> str | None:
    if not re.search(r"\b(?:ideate|idea|brainstorm)\b", cmd, re.I) or not re.search(r"\b(?:open[- ]source|github|trending|project|tool)\b", cmd, re.I):
        return None
    topic = re.sub(r"(?i)\b(?:arka\s+)?(?:ideate|brainstorm|ideas?)\b", "", cmd).strip() or "open source tools"
    return "ideate " + shlex.quote(topic)


def route_cool_build(cmd: str) -> str | None:
    if not re.search(r"\b(?:build|make|create)\b.*\b(?:something cool|cool project|cool app|cool features?|great features?)\b", cmd, re.I):
        return None
    idea = re.sub(r"(?i)\b(?:build|make|create)\b", "", cmd).strip()
    return "build_something_cool " + shlex.quote(idea or "a useful small app")


def route_play(cmd: str) -> str | None:
    if re.search(r"(?i)\b(?:agent\s+)?(?:societ(?:y|ies)|teams?)\b.*\b(?:compete|battle|race)\b", cmd):
        return "play tournament --group society=agent-1,agent-2 --group team=agent-3,agent-4"
    if re.search(r"(?i)\b(?:battle|fight|compete)\b.*\b(?:ai|agent|car|vehicle|game)\b|\b(?:ai|agent)\s+(?:cars?|vehicles?)\b.*\b(?:battle|fight|race)\b", cmd):
        return "play battle " + cmd
    if not re.search(r"\b(?:play|benchmark)\b.*\bchess\b|\bchess\b.*\b(?:play|benchmark|game)\b", cmd, re.I):
        return None
    moves = re.findall(r"\b[a-h][1-8][a-h][1-8]\b", cmd.lower())
    return "play chess --moves " + " ".join(moves) if moves else "play chess --moves e2e4"


def route_game_studio(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:create|build|make|scaffold|generate)\b", cmd) or not re.search(r"(?i)\b(?:awesome|polished|beautiful|browser|video|2d|3d)?\s*game\b", cmd):
        return None
    if re.search(r"(?i)\b(?:battle|chess|benchmark|play)\b", cmd):
        return None
    title = re.sub(r"(?i)\b(?:arka\s+)?(?:create|build|make|scaffold|generate)\b", "", cmd).strip() or "Neon Core"
    return "game create " + title


def route_game_control(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:check|test|play|record|capture)\b", cmd) or not re.search(r"(?i)\b(?:game|gameplay|video\s+game)\b", cmd) or not re.search(r"https?://|localhost|127\.0\.0\.1", cmd):
        return None
    url = re.search(r"https?://[^\s]+|(?:localhost|127\.0\.0\.1):\d+", cmd, re.I)
    command = "game check " + (url.group(0) if url else "")
    if re.search(r"(?i)\b(?:record|capture)\b.*\b(?:video|gameplay|animation|session)\b|\bgameplay\s+recording\b", cmd):
        command += " --record"
    if re.search(r"(?i)\b(?:verify|check|inspect|review)\b.*\b(?:visuals?|graphics?|frames?|screenshots?|before\s+(?:done|saying\s+done))\b|\bbefore\s+saying\s+done\b", cmd):
        command += " --verify"
    return command


def route_vision_evidence(cmd: str) -> str | None:
    if not re.search(r"\b(?:ocr|text\s+in\s+image|image\s+evidence)\b", cmd, re.I) or not re.search(r"\b(?:vllm|model|compare|combine|answer)\b", cmd, re.I):
        return None
    image = re.search(r"[\w./~-]+\.(?:png|jpe?g|webp|gif)\b", cmd, re.I)
    if not image:
        return None
    question = re.sub(r"(?i)\b(?:use|compare|ocr|vllm|model|image|evidence)\b", "", cmd).strip() or "What does this image show?"
    return "vision_evidence " + shlex.quote(image.group(0)) + " " + shlex.quote(question)


def route_url_app(cmd: str) -> str | None:
    if not re.search(r"\b(?:analy[sz]e|review|audit|improve)\b.*\b(?:app|website|design|ui)\b", cmd, re.I):
        return None
    url = re.search(r"https?://[^\s'\"]+", cmd, re.I)
    return "url_app " + shlex.quote(url.group(0)) if url else None


def route_ui_copy(cmd: str) -> str | None:
    clean = cmd.strip().lower()
    if not re.search(r"\b(?:duplicate|same|repeated|unique)\b.*\b(?:button|chip|ui|label|phrase|text)\b|\b(?:button|chip)\b.*\b(?:same|duplicate|repeated)\b", clean):
        return None
    path = re.search(r"(?:in|under|at)\s+([\w./~-]+)", cmd, re.I)
    return "ui_copy " + shlex.quote(path.group(1) if path else ".")


def route_web_screenshot(cmd: str) -> str | None:
    if not re.search(r"\b(?:screenshot|snapshot|capture)(?:s)?\b.*(?:\b(?:website|site|webpage|url)\b|https?://)|\b(?:website|site|webpage)\b.*\b(?:screenshot|snapshot|capture)\b", cmd, re.I):
        return None
    url = re.search(r"https?://[^\s'\"]+", cmd, re.I)
    if not url:
        return None
    low = cmd.lower()
    viewport = "all"
    for name in ("pc", "tablet", "mobile"):
        if name in low:
            viewport = name
            break
    return f"web_screenshot {shlex.quote(url.group(0))} --viewport {viewport}"


def route_spline(cmd: str) -> str | None:
    if not re.search(r"\bspline\b", cmd, re.I) or not re.search(r"\b(?:guide|use|embed|integrat|3d|model|scene)\w*\b", cmd, re.I):
        return None
    low = cmd.lower()
    topic = "web"
    for key, words in {"react": ("react", "next"), "performance": ("performance", "speed", "fast"), "responsive": ("responsive", "tablet", "mobile"), "accessibility": ("accessibility", "accessible", "a11y")}.items():
        if any(word in low for word in words):
            topic = key
            break
    return "spline " + topic


def route_three_js_model(cmd: str) -> str | None:
    try:
        from arka.agent.three_js_model import route_command
    except ImportError:
        return None
    route = route_command(cmd)
    return route or None


def route_multi_llm(cmd: str) -> str | None:
    if not re.search(r"\b(?:multiple|several|different|many)\s+(?:llms?|models?)\b|\b(?:llm|model)\s+(?:variants?|alternatives?)\b", cmd, re.I):
        return None
    prompt = re.sub(r"(?i)\b(?:run|ask|use|generate)\b.*?\b(?:multiple|several|different|many)\s+(?:llms?|models?)\b", "", cmd).strip()
    return "multi_llm " + shlex.quote(prompt or cmd)


def route_agent_race(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:race|compete|competition)\b", cmd) or not re.search(r"(?i)\b(?:agents?|models?)\b", cmd):
        return None
    task = re.sub(r"(?i)\b(?:race|compete|competition)\b", "", cmd).strip()
    return "race " + shlex.quote(task) + " --models " + shlex.quote("gemini/gemini-2.5-flash,groq/llama-3.3-70b-versatile")


def route_app_check(cmd: str) -> str | None:
    if not re.search(r"\b(?:build|test|validate|check|run)\b.*\b(?:app|project|repo|application)\b", cmd, re.I):
        return None
    run = " --run" if re.search(r"\b(?:build|test|run)\b", cmd, re.I) else ""
    path = re.search(r"(?:in|at|under)\s+([\w./~-]+)", cmd, re.I)
    return "app_check " + shlex.quote(path.group(1) if path else ".") + run


def route_github_actions(cmd: str) -> str | None:
    if not re.search(r"\b(?:github\s+actions?|actions?\s+workflow|gha)\b", cmd, re.I):
        return None
    path = re.search(r"(?:in|at|under)\s+([\w./~-]+)", cmd, re.I)
    root = shlex.quote(path.group(1) if path and path.group(1).lower() not in {"this", "the", "current", "repo"} else ".")
    if re.search(r"\b(?:status|failed|failure|production)\b", cmd, re.I):
        action = "status"
    else:
        action = "new" if re.search(r"\b(?:create|add|scaffold|setup)\b", cmd, re.I) else "inspect"
    return f"github_actions {action} {root}"


def route_parallel(cmd: str) -> str | None:
    if not re.search(r"\b(?:parallel|concurrently|at the same time)\b", cmd, re.I) or not re.search(r"\b(?:skills?|tasks?|commands?)\b", cmd, re.I):
        return None
    quoted = re.findall(r"[\"']([^\"']+)[\"']", cmd)
    if len(quoted) < 2:
        return None
    return "parallel " + " ".join("--job " + shlex.quote(job) for job in quoted)


def route_script_understanding(cmd: str) -> str | None:
    if not re.search(r"\b(?:understand|learn|remember|explain|know)\b.*\b(?:script|program|tool|code)\b", cmd, re.I):
        return None
    path = re.search(r"(?:script|file|program)\s+([\w./~-]+)", cmd, re.I)
    if not path:
        return None
    return "understand_script remember " + shlex.quote(path.group(1))


def route_super_replica(cmd: str) -> str | None:
    if not re.search(r"\b(?:super\s+replica|repo(?:sitory)?\s+(?:patterns?|advisor|architecture|conventions?)|startup\s+architecture|analy[sz]e\s+(?:this\s+)?repo)\b", cmd, re.I):
        return None
    path = re.search(r"(?:repo|repository|project)\s+([\w./~-]+)", cmd, re.I)
    root = path.group(1) if path and path.group(1).lower() not in {"this", "the", "current", "for"} else "."
    return "super_replica " + shlex.quote(root)


def route_pdf_interactive(cmd: str) -> str | None:
    if not re.search(r"\b(?:pdf|document)\b.*\b(?:interactive|website|webpage|site)\b|\binteractive\b.*\bpdf\b", cmd, re.I):
        return None
    path = re.search(r"[\w./~-]+\.pdf\b", cmd, re.I)
    if not path:
        return None
    suffix = " --ultra" if re.search(r"\b(?:ultra|rich|immersive|3d|animated)\b", cmd, re.I) else ""
    return "pdf_interactive " + shlex.quote(path.group(0)) + suffix


def route_media_quiz(cmd: str) -> str | None:
    if not re.search(r"\b(?:media|image|video|audio|photo|document)\b.*\b(?:quiz|questionnaire|quiz\s+website)\b|\bquiz(?:\s+website)?\b.*\b(?:media|image|video|audio|from)\b", cmd, re.I):
        return None
    path = re.search(r"[\w./~-]+\.(?:png|jpe?g|webp|gif|mp3|wav|ogg|mp4|webm|mov|pdf)\b", cmd, re.I)
    return "media_quiz " + shlex.quote(path.group(0)) if path else None


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


def route_urlkit(cmd: str) -> str | None:
    clean = cmd.strip()
    if not clean:
        return None
    low = clean.lower()
    if re.search(r"(?i)\b(?:repair|remove|prune|clean|fix)\s+(?:broken\s+)?(?:links?|urls?)\b", low):
        return f"urlkit repair-links {shlex.quote(clean)}"
    return None


def route_word_counter(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:count|calculate|measure)\b", cmd) or not re.search(r"(?i)\b(?:words?|characters?|sentences?|reading\s+time|text)\b", cmd):
        return None
    path = re.search(r"(?:~|/|\./|\.\./)?[^\s]+\.(?:txt|md|rst|html?|json|csv)\b", cmd, re.I)
    if path:
        return "word_counter --file " + shlex.quote(path.group(0))
    quoted = re.search(r"['\"]([^'\"]+)['\"]", cmd)
    return "word_counter --text " + shlex.quote(quoted.group(1) if quoted else cmd)


def route_hallmark(cmd: str) -> str | None:
    if not re.search(r"(?i)\bhallmark\b|anti[- ]?ai[- ]?slop", cmd):
        return None
    action = "audit" if re.search(r"(?i)\baudit|review|score", cmd) else "redesign" if re.search(r"(?i)\bredesign|rebuild", cmd) else "study" if re.search(r"(?i)\bstudy|extract design", cmd) else "build"
    target = re.sub(r"(?i)\bhallmark\b|anti[- ]?ai[- ]?slop|\b(?:audit|review|score|redesign|rebuild|study|extract\s+design|build)\b|\buse\s+to\b", "", cmd).strip() or "this interface"
    target = re.sub(r"\s+", " ", target)
    return f"hallmark {action} {target}"


def route_move_file(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:move|relocate|rename)\b.*\b(?:file|script|module|\.py|\.js|\.ts|\.tsx)\b", cmd):
        return None
    match = re.search(r"(?i)\b(?:move|relocate|rename)\s+(?:the\s+)?(?:file\s+)?['\"]?([^\s'\"]+)['\"]?\s+(?:to|as|into)\s+['\"]?([^\s'\"]+)['\"]?", cmd)
    candidates = [item for item in match.groups()] if match else []
    if len(candidates) < 2:
        return None
    suffix = " --update-refs" if re.search(r"(?i)\b(?:update|fix)\s+(?:imports?|references?|links?)\b", cmd) else ""
    return "move_file " + shlex.quote(candidates[-2]) + " " + shlex.quote(candidates[-1]) + suffix


def route_hackathon(cmd: str) -> str | None:
    clean = cmd.strip()
    if not re.search(r"(?i)\b(?:hackathon|hackathons)\b", clean):
        return None
    if re.search(r"(?i)\b(?:find|discover|list|give|show)\b", clean):
        topic = re.sub(r"(?i).*?\b(?:hackathon|hackathons)\b", "", clean).strip(" :-") or "technology"
        return "hackathon find " + topic
    topic = re.sub(r"(?i).*?\b(?:hackathon|hackathons)\b", "", clean).strip(" :-")
    if not topic:
        topic = re.sub(r"(?i)\b(?:hackathon|hackathons)\b.*$", "", clean).strip(" :-")
        topic = re.sub(r"(?i)^(?:participate|join|enter)\s+(?:in\s+)?(?:a\s+)?", "", topic).strip()
    topic = topic or "technology"
    return "hackathon plan " + topic


def route_lint_project(cmd: str) -> str | None:
    try:
        from arka.agent.lint_project import route_command
    except ImportError:
        return None
    route = route_command(cmd.strip())
    return route or None


def route_coding_tui(cmd: str) -> str | None:
    try:
        from arka.agent.coding_tui import route_command
    except ImportError:
        return None
    line = route_command(cmd.strip())
    return line or None


def route_self_improve(cmd: str) -> str | None:
    try:
        from arka.agent.self_improve import route_command
    except ImportError:
        return None
    line = route_command(cmd.strip())
    return line or None


def route_help(cmd: str) -> str | None:
    clean = cmd.strip().lower()
    if clean in ("help", "?"):
        return "help"
    if clean in ("skills", "capabilities"):
        return "capabilities"
    if re.search(r"(?i)^(what can arka do|what does arka do)\s*$", clean):
        return "capabilities"
    if re.search(
        r"(?i)(tell\s+(?:me\s+)?(?:about\s+)?(?:all\s+)?(?:your\s+)?skills?|"
        r"tell\s+your\s+skills?|(list|show)\s+(?:me\s+)?(?:all\s+)?(?:your\s+)?skills?|"
        r"what\s+(?:are\s+)?(?:all\s+)?your\s+skills?)",
        clean,
    ):
        return "capabilities"
    return None


def route_sessions(cmd: str) -> str | None:
    """Route conversational session-management requests."""
    clean = re.sub(r"\s+", " ", cmd.strip().lower())
    if clean in {"session", "sessions", "session status", "show session status"}:
        return "session status"
    if re.search(r"\b(list|show)\b.*\bsessions?\b", clean) or clean in {
        "my sessions",
        "list my sessions",
    }:
        return "session list"
    if re.search(r"\b(clear|reset|forget)\b.*\bsession\b", clean):
        return "session reset cli default"
    if re.search(r"\b(resume|continue)\b.*\bsession\b", clean):
        return "session resume cli default"
    return None


def route_hybrid_models(cmd: str) -> str | None:
    """Route requests to combine local/offline and hosted models."""
    clean = " ".join((cmd or "").split()).lower()
    if re.search(r"(?i)\b(?:auto[- ]?configure|autoconfigure|setup)\b.*\b(?:popular\s+)?mcp\b|\bmcp\b.*\b(?:catalog|available\s+servers)\b", clean):
        return "mcp-auto list" if re.search(r"(?i)\b(?:list|show|available|catalog)\b", clean) else "mcp-auto configure"
    match = re.search(r"(?i)\b(?:use|run|create)\b.*\b(?:coding|feature|bugfix|frontend|api)\s+workflow\b", clean)
    if match:
        kind = next((item for item in ("feature", "bugfix", "frontend", "api") if item in clean), "feature")
        return "coding-workflow " + kind
    if re.search(r"(?i)\b(?:copy|fill|sync|project|populate)\b.*\b(?:arka|our)\s+\.env\b|\b\.env\b.*\b(?:local\s+llm|project)\b", clean):
        return "env-bridge ."
    if re.search(r"(?i)\b(?:flashattention|flash\s+attention|tensor\s+split|row[- ]level|multi[- ]gpu|ds4|co[- ]engine)\b", clean):
        return "backend capabilities"
    if re.search(r"(?i)\b(?:speculative|mtp|draft\s+model)\b.*\b(?:decode|token|inference|configure|enable|use)\b", clean):
        return "speculative vllm"
    if re.search(r"(?i)\b(?:grounded|anti[- ]hallucination|no hallucinat)\b", clean):
        return "grounding"
    if re.search(r"(?i)\b(?:quantiz|quantis|compress)\w*\b.*\b(?:model|llm|gguf)\b|\bgguf\b.*\b(?:q4|q5|q8|quant)\b", clean):
        return "quantize " + cmd
    if re.search(r"(?i)\b(?:cost|spend|latency|performance|token)\b.*\b(?:guardrail|budget|limit|monitor|track)\b", clean):
        return "guardrails status"
    if re.search(r"\b(?:run|use|execute)\b.*\b(?:only\s+)?local\s+(?:llm|model)s?\b|\brun-only-local-llm\b", clean):
        return "local-llm " + cmd
    if not re.search(r"\b(?:local|offline)\b", clean) or not re.search(r"\b(?:hosted|cloud|online)\b", clean):
        return None
    if re.search(r"\b(?:status|available|which|list)\b", clean):
        return "hybrid status"
    if re.search(r"\b(?:parallel|together|both|ensemble)\b", clean):
        return "hybrid run --policy parallel " + cmd
    if re.search(r"\b(?:hosted|cloud).*\b(?:first|priority)\b", clean):
        return "hybrid run --policy hosted-first " + cmd
    return "hybrid status"


def route_integration_setup(cmd: str) -> str | None:
    """Route setup/status requests for the unified integration wizard."""
    clean = " ".join((cmd or "").split()).lower()
    if not re.search(r"\b(?:integration|integrations|provider|api|connect|configure|setup|set\s+up)\b", clean):
        return None
    try:
        from arka.agent.integration_setup import ALIASES, PROVIDERS

        provider_names = sorted({*PROVIDERS, *ALIASES}, key=len, reverse=True)
    except ImportError:
        provider_names = []
    providers = "|".join(re.escape(name) for name in provider_names)
    if not providers:
        return None
    match = re.search(rf"\b({providers})\b", clean)
    if re.search(r"\b(?:list|show|available)\b.*\bintegrations?\b", clean):
        return "integration list"
    if re.search(r"\b(?:doctor|diagnose|check)\b.*\bintegrations?\b", clean):
        return "integration doctor"
    if not match:
        return None
    provider = match.group(1)
    if re.search(r"\b(?:remove|delete|clear|forget)\b", clean):
        return f"integration remove {provider}"
    if re.search(r"\b(?:setup|set\s+up|configure|connect|enable|add)\b", clean):
        return f"integration setup {provider}"
    return None


def route_offline_extras(cmd: str) -> str | None:
    """Try supplemental NL routes not always available via fish bridge."""
    from arka.core.skill_settings import is_disabled

    def allowed(route: str) -> bool:
        return not is_disabled(route.split()[0].replace("-", "_"))

    for fn in (
        route_greeting,
        route_coding_tui,
        route_scene_3d,
        route_rig_3d,
        route_parallax_2d,
        route_text_to_3d,
        route_three_js_model,
        route_hybrid_models,
        route_help,
        route_sessions,
        route_model_host_setup,
        route_model_optimizer,
        route_train_plan,
        route_stock_analyze,
        route_code_convert,
        route_design_resources,
        route_edge,
        route_judge_demo,
        route_free_models,
        route_integration_setup,
        route_sandbox,
        route_text_edit,
        route_move_file,
        route_surgical_edit,
        route_word_counter,
        route_ideate,
        route_cool_build,
        route_hackathon,
        route_game_studio,
        route_game_control,
        route_play,
        route_hallmark,
        route_vision_evidence,
        route_video_evidence,
        route_url_app,
        route_visual_inspection,
        route_visual_diagnose,
        route_ui_copy,
        route_web_screenshot,
        route_app_automation,
        route_spline,
        route_three_js_model,
        route_multi_llm,
        route_agent_race,
        # Specific intent must precede the broad "build/check this app" route.
        route_frontend_loop,
        route_design_from_screenshot,
        route_code_project,
        route_repo_health,
        route_observability,
        route_telemetry_connector,
        route_app_check,
        route_github_actions,
        route_parallel,
        route_script_understanding,
        route_super_replica,
        route_pdf_interactive,
        route_media_quiz,
        route_self_improve,
        route_mode,
        route_urlkit,
        route_lint_project,
        route_heartbeat,
        route_background_processes,
        route_jsonkit,
        route_agent_hub,
        route_mcp,
        route_clipboard_history,
        route_learned,
        route_competitions,
        route_bookmarks,
        route_pr_check,
        route_repo_context,
        route_repo_map,
        route_repo_graph,
        route_workspace,
        route_structure,
        route_dev_workflow,
        route_graphify,
        route_spreadsheet,
        route_teammate_review,
        route_society,
        route_generate_data,
        route_exercise_dataset,
        route_github_dataset,
        route_data_collect,
        route_view_data,
        route_describe_screen,
        route_describe_video,
        route_describe_image,
        route_background_remove,
        route_iterate,
        route_loop_engineering,
        route_ultra_fast,
        route_env_setup,
        route_research_math,
        route_prompt_optimize,
        route_deploy,
        route_geo_seo,
        route_templates,
        route_blocks,
        route_optimize,
        route_design_flow,
        route_repo_reverse,
        route_browser_check,
        route_currency_convert,
        route_timezone_convert,
        route_convert,
        route_media_transform,
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
        route_batch,
        route_config_share,
        route_semantic_alert,
        route_usage_dashboard,
        route_symbolic_image,
        route_routines,
        route_fact_check,
        route_quiz_practice,
        route_council,
        route_model_to_image,
        route_text_to_3d,
        route_compose_3d,
        route_scene_3d,
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
        route_site_summary,
        route_open_url,
        route_visual_inspection,
        route_search_web,
        route_price_check,
        route_product_reviewer,
        route_agent_skills,
    ):
        hit = fn(cmd)
        if hit and allowed(hit):
            return hit
    return None
