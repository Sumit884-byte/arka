"""NL routing for all platforms — bundled fish router when available, Python fallbacks otherwise."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from arka.paths import fish_config as _fish_config, script_path

fish_config = _fish_config  # compatibility seam for routing tests/plugins


@dataclass
class Route:
    skill: str
    source: str = "offline"
    kind: str = "skill"


def _route_mode() -> str:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    mode = os.environ.get("ROUTE_MODE", "symbolic").lower().strip()
    aliases = {
        "llm": "ai",
        "ai-first": "ai",
        "ai_first": "ai",
        "offline_only": "symbolic_only",
        "offline-only": "symbolic_only",
        "offline": "symbolic_only",
        "only": "symbolic_only",
        "llm_only": "ai_only",
        "ai-only": "ai_only",
        "llm-only": "ai_only",
        "hybrid": "symbolic",
        "auto": "symbolic",
        "default": "symbolic",
        "": "symbolic",
    }
    mode = aliases.get(mode, mode)
    if mode not in ("symbolic", "ai", "symbolic_only", "ai_only"):
        return "symbolic"
    return mode


def route(text: str) -> Route | None:
    cmd = text.strip()
    if not cmd:
        return None

    # Resolve explicit slash aliases before integrations and broad URL/media
    # heuristics.  Otherwise `/dev-tool` can be normalized as a hostname and
    # eventually reported as a missing image or opened as `dev-tool.com`.
    slash_dev = re.match(r"^/(?:dev[-_ ]?tools?|developer[-_ ]?tools?)\b\s*(.*)$", cmd, re.I)
    if slash_dev:
        tail = slash_dev.group(1).strip()
        return Route(f"dev_tools {tail}" if tail else "dev_tools doctor", source="offline")

    try:
        from arka.telemetry import span
    except ImportError:
        span = None  # type: ignore[assignment,misc]
    from contextlib import nullcontext

    route_ctx = (
        span("arka.route", attributes={"arka.route.input": cmd[:500]})
        if span is not None
        else nullcontext()
    )
    route_start = time.perf_counter()
    with route_ctx as current:
        mode = _route_mode()
        if span is not None:
            current.set_attribute("arka.route.mode", mode)

        try:
            from arka.integrations.fugu import route_command as fugu_route_cmd

            fugu_hit = fugu_route_cmd(cmd)
            if fugu_hit:
                fugu_route = Route(fugu_hit, source="offline")
                if span is not None:
                    _finish_route_span(
                        current,
                        fugu_route,
                        decision="symbolic",
                        start=route_start,
                    )
                return fugu_route
        except ImportError:
            pass

        if mode == "symbolic_only":
            github_route = _route_github_repo(cmd)
            if github_route:
                if span is not None:
                    _finish_route_span(current, github_route, decision="symbolic", start=route_start)
                return github_route
            try:
                from arka.routing.symbolic import route_offline_extras

                extra = route_offline_extras(cmd)
                if extra:
                    sym_route = Route(extra, source="offline")
                    if span is not None:
                        _finish_route_span(
                            current,
                            sym_route,
                            decision="symbolic",
                            start=route_start,
                        )
                    return sym_route
            except ImportError:
                pass

        if mode in ("symbolic", "ai_only"):
            offline = _route_offline(cmd)
            if offline:
                if span is not None:
                    _finish_route_span(
                        current,
                        offline,
                        decision="symbolic",
                        start=route_start,
                    )
                return offline

        fish_route = _route_via_fish(cmd)
        if fish_route:
            if fish_route.kind == "llm":
                offline = _route_offline(cmd)
                if offline:
                    if span is not None:
                        _finish_route_span(
                            current,
                            offline,
                            decision="symbolic",
                            start=route_start,
                        )
                    return offline
            if not (mode == "symbolic_only" and fish_route.kind == "llm"):
                if span is not None:
                    _finish_route_span(
                        current,
                        fish_route,
                        decision="fish",
                        start=route_start,
                    )
                return fish_route

        if mode == "ai_only":
            integration = _route_ai_only_integrations(cmd)
            if integration:
                if span is not None:
                    _finish_route_span(
                        current,
                        integration,
                        decision="symbolic",
                        start=route_start,
                    )
                return integration

        fish_available = False
        try:
            from arka.fish_bridge import _find_fish

            fish_available = _find_fish() is not None
        except ImportError:
            pass

        if fish_available and mode == "ai_only":
            offline = _route_offline(cmd)
            if offline:
                if span is not None:
                    _finish_route_span(
                        current,
                        offline,
                        decision="symbolic",
                        start=route_start,
                    )
                return offline
            return None

        if mode in ("ai", "ai_only"):
            llm = _route_llm(cmd)
            if llm:
                if span is not None:
                    _finish_route_span(
                        current,
                        llm,
                        decision="llm",
                        start=route_start,
                    )
                return llm
            if mode == "ai_only":
                return None

        if mode == "symbolic_only":
            offline = _route_offline(cmd)
            if offline:
                if span is not None:
                    _finish_route_span(
                        current,
                        offline,
                        decision="symbolic",
                        start=route_start,
                    )
                return offline

        if mode not in ("symbolic", "symbolic_only", "ai_only"):
            offline = _route_offline(cmd)
            if offline:
                if span is not None:
                    _finish_route_span(
                        current,
                        offline,
                        decision="symbolic",
                        start=route_start,
                    )
                return offline

        if mode == "symbolic":
            llm = _route_llm(cmd)
            if llm and span is not None:
                _finish_route_span(
                    current,
                    llm,
                    decision="llm",
                    start=route_start,
                )
            return llm

        return None


def route_preview(text: str) -> Route | None:
    """Fast deterministic preview for `arka route` — Python symbolic only, no fish or LLM."""
    cmd = text.strip()
    if not cmd:
        return None

    slash_dev = re.match(r"^/(?:dev[-_ ]?tools?|developer[-_ ]?tools?)\b\s*(.*)$", cmd, re.I)
    if slash_dev:
        tail = slash_dev.group(1).strip()
        skill = f"dev_tools {tail}" if tail else "dev_tools doctor"
        return Route(skill, source="offline")

    try:
        from arka.integrations.fugu import route_command as fugu_route_cmd

        fugu_hit = fugu_route_cmd(cmd)
        if fugu_hit:
            return Route(fugu_hit, source="offline")
    except ImportError:
        pass

    offline = _route_offline(cmd)
    if offline:
        return Route(offline.skill, source="offline", kind="skill")
    return None


def _finish_route_span(
    current: Any,
    route_result: Route,
    *,
    decision: str,
    start: float,
) -> None:
    try:
        from arka.telemetry import mark_ok
        from arka.telemetry.metrics import record_routing_decision
        from arka.telemetry.tracing import duration_ms
    except ImportError:
        return
    elapsed = duration_ms(start)
    current.set_attribute("arka.route.source", route_result.source)
    current.set_attribute("arka.route.skill", route_result.skill[:500])
    current.set_attribute("arka.route.decision", decision)
    current.set_attribute("arka.route.latency_ms", elapsed)
    record_routing_decision(decision=decision, source=route_result.source, latency_ms=elapsed)
    mark_ok(current)


def _route_ai_only_integrations(cmd: str) -> Route | None:
    """Bundled integration NL routes that apply in ROUTE_MODE=ai_only (fish parity)."""
    try:
        from arka.routing.symbolic import route_clipboard_history

        hit = route_clipboard_history(cmd)
        if hit:
            return Route(hit, source="offline")
    except ImportError:
        pass
    return None


def _route_via_fish(cmd: str) -> Route | None:
    try:
        from arka.fish_bridge import fish_route_preview
    except ImportError:
        return None

    preview = fish_route_preview(cmd)
    if preview is None or not preview.action:
        return None

    source = preview.kind if preview.kind not in ("skill", "") else "fish"
    if preview.kind == "llm":
        source = "llm"
    elif preview.kind == "none":
        return None
    return Route(preview.action, source=source, kind=preview.kind or "skill")


def _route_llm(cmd: str) -> Route | None:
    path = script_path("arka_llm.py")
    if not path.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(path), "route", cmd],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = proc.stdout.strip()
    if not line or line == cmd:
        return None
    return Route(line, source="llm", kind="llm")


def _parse_password_name(cmd: str) -> str:
    m = re.search(r"(?:for|as|named|to)\s+(.+)$", cmd.strip(), re.I)
    if not m:
        m = re.search(r"password\s+for\s+(.+)$", cmd.strip(), re.I)
    if not m:
        return ""
    name = m.group(1).strip()
    name = re.sub(r"\s+\d{1,3}$", "", name)
    return name


def _route_chart(cmd: str) -> Route | None:
    try:
        from arka.routing.symbolic import route_chart

        skill = route_chart(cmd)
        if skill:
            return Route(skill, source="offline")
    except ImportError:
        pass
    return None


def _route_routines(cmd: str) -> Route | None:
    try:
        from arka.routing.symbolic import route_routines

        skill = route_routines(cmd)
        if skill:
            return Route(skill, source="offline")
    except ImportError:
        pass
    return None


def _route_remind(cmd: str) -> Route | None:
    try:
        from arka.routing.symbolic import route_remind

        skill = route_remind(cmd)
        if skill:
            return Route(skill, source="offline")
    except ImportError:
        pass
    return None


def _route_competitions(cmd: str) -> Route | None:
    try:
        from arka.agent.competitions import route_command, wants_competitions_search

        if wants_competitions_search(cmd):
            skill = route_command(cmd)
            if skill:
                return Route(skill, source="offline")
    except ImportError:
        pass
    return None


def _route_github_repo(cmd: str) -> Route | None:
    try:
        from arka.agent.github_repo import route_command, wants_github_repo_activity

        if wants_github_repo_activity(cmd):
            skill = route_command(cmd)
            if skill:
                return Route(skill, source="offline")
    except ImportError:
        pass
    return None


def _route_github_resume(cmd: str) -> Route | None:
    try:
        from arka.agent.github_resume import route_command, wants_github_resume

        if wants_github_resume(cmd):
            skill = route_command(cmd)
            if skill:
                return Route(skill, source="offline")
    except ImportError:
        pass
    return None


def _route_offline(cmd: str) -> Route | None:
    clean = cmd.lower()

    # Slash-prefixed developer-tool aliases are commands, not image paths or
    # web-search prompts. Resolve them before any broad URL/media heuristics.
    slash_dev = re.match(r"^/(?:dev[-_ ]?tools?|developer[-_ ]?tools?)\b\s*(.*)$", cmd, re.I)
    if slash_dev:
        tail = slash_dev.group(1).strip()
        return Route(f"dev_tools {tail}" if tail else "dev_tools doctor", source="offline")

    if clean in ("help", "?"):
        return Route("help")
    if clean in ("skills", "capabilities"):
        return Route("capabilities")

    if re.search(r"(?i)\b(clone|setup|install)\b.*\b(profession|professions)\b.*\b(projects?|repos?)\b", clean):
        return Route("profession setup")
    if re.search(r"(?i)\bprofession\s+(setup|clone|status|combine)\b", clean):
        m = re.search(r"(?i)\bprofession\s+(setup|clone|status|combine)(?:\s+(\w+))?\b", cmd)
        if m:
            sub = m.group(1).lower()
            if sub in ("setup", "clone"):
                prof = (m.group(2) or "").lower()
                return Route(f"profession setup {prof}".strip())
            return Route(f"profession {sub}")
        return Route("profession setup")

    if re.search(r"(?i)\b(list professions|profession list|what professions)\b", clean):
        return Route("profession list")

    try:
        from arka.agent.stt_install import route_command as stt_install_route

        stt_hit = stt_install_route(cmd)
        if stt_hit:
            return Route(stt_hit, source="offline")
    except ImportError:
        pass

    try:
        from arka.llm.credits_usage import route_command as credits_usage_route

        usage_hit = credits_usage_route(cmd)
        if usage_hit:
            return Route(usage_hit, source="offline")
    except ImportError:
        pass

    try:
        from arka.agent.free_credits import route_command as free_credits_route

        credits_hit = free_credits_route(cmd)
        if credits_hit:
            return Route(credits_hit, source="offline")
    except ImportError:
        pass

    try:
        from arka.core.network_proxy import route_command as proxy_route

        proxy_hit = proxy_route(cmd)
        if proxy_hit:
            return Route(proxy_hit, source="offline")
    except ImportError:
        pass

    if re.search(r"(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)\b", clean):
        m = re.search(r"(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)(?:\s+(\S+))?", cmd)
        if m:
            sub = m.group(2).lower()
            extra = (m.group(3) or "").strip()
            return Route(f"life_sciences {sub} {extra}".strip())

    if re.search(r"(?i)\b(install|setup)\s+(pubmed|single[- ]cell|nextflow|scvi|life[- ]sciences?)\b", clean):
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
            route = mapping.get(token)
            if route:
                return Route(route)

    if re.search(r"(?i)\b(life[- ]sciences?|biomedical research tools|bioinformatics tools)\b", clean):
        return Route("life_sciences list")

    # GitHub resume/profile CV requests must win before repo activity and
    # generic "my …" advisory fallbacks (e.g. "from my github profile").
    github_resume_route = _route_github_resume(cmd)
    if github_resume_route:
        return github_resume_route

    # GitHub activity language is more specific than generic profession/data
    # questions and must win before plugin/profile routing.
    github_route = _route_github_repo(cmd)
    if github_route:
        return github_route

    try:
        from arka.agent.professions import route_command

        prof_route = route_command(cmd)
        if prof_route:
            return Route(prof_route, source="offline")
    except ImportError:
        pass

    if re.match(r"^(generate|create|make)\s+(?:a |an |the |me )?(?:new )?(password|passcode)\b", clean):
        return Route("generate_password")

    if re.match(r"(save|store|remember)\s+(?:password|pass)\s+\S+\s+(?:for|as|named)\s+[a-zA-Z0-9._-]+", clean):
        m = re.match(
            r"(?:save|store|remember)\s+(?:password|pass)\s+(\S+)\s+(?:for|as|named)\s+([a-zA-Z0-9._-]+)",
            cmd,
            re.I,
        )
        if m:
            pwd, name = m.group(1), m.group(2)
            return Route(f"generate_password set {name} {shlex.quote(pwd)}")

    if re.search(r"(save|store|remember).*(password|pass).*(for|as|named)", clean) or re.search(
        r"generate.*password.*(for|named)\s+\S", clean
    ):
        name = _parse_password_name(cmd)
        if name:
            return Route(f"generate_password save {shlex.quote(name)}")
        return Route("generate_password save")

    if re.search(r"(get|show|retrieve).*(password|pass).*(for|named)", clean) or re.search(
        r"what.*password.*(for|to)\s+\S", clean
    ):
        name = _parse_password_name(cmd)
        if name:
            return Route(f"generate_password get {shlex.quote(name)}")

    if re.search(r"\b(list|show)\s+(?:my\s+|saved\s+|stored\s+)?(?:passwords?|passcodes?)\b", clean):
        return Route("generate_password list")

    if re.search(r"\b(password|passcode)\b", clean) and not re.search(r"(decrypt|protected|pdf)", clean):
        return Route("generate_password")

    if re.match(r"^/", cmd):
        forced = cmd.lstrip("/").strip() or cmd
        return Route(f"deep_web_answer {forced}")

    try:
        from arka.routing.symbolic import route_offline_extras

        extra = route_offline_extras(cmd)
        if extra:
            return Route(extra, source="offline")
    except ImportError:
        chart_route = _route_chart(cmd)
        if chart_route:
            return chart_route
        routines_route = _route_routines(cmd)
        if routines_route:
            return routines_route
        remind_route = _route_remind(cmd)
        if remind_route:
            return remind_route

    if re.search(r"(weather|forecast|temp|rain|will it rain)", clean):
        return Route(f"hyperlocal_weather {cmd}")

    if re.search(
        r"(live\s+(sports?\s+)?scores?|sports?\s+scores?|ipl\s+(live|score)|cricket\s+(live|score)|nfl\s+scores?|nba\s+scores?|match\s+score)",
        clean,
    ):
        return Route(f"sports_score {cmd}")

    if re.search(r"(^calc\s|integrate|derivative|solve\s|=\s*\d)", clean):
        return Route(f"calc {cmd}")

    third_party = _match_third_party(cmd)
    if third_party:
        return Route(third_party, source="plugin")

    try:
        from arka.core.code_project import looks_like_repo_edit

        repo_edit = looks_like_repo_edit(cmd)
    except ImportError:
        repo_edit = False

    if not repo_edit and re.search(r"(?i)\b(download|save|fetch|grab)\b", clean):
        url_m = re.search(r"https?://[^\s]+", cmd)
        if url_m:
            url = url_m.group(0)
            qurl = shlex.quote(url)
            if re.search(r"(?i)(playlist\?list=|/playlist)", url):
                return Route(f"youtube_bulk download {qurl} --wait", source="offline")
            if re.search(r"(?i)(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", url):
                return Route(f"youtube_download {qurl}", source="offline")
            return Route(f"download_file {qurl}", source="offline")

    file_size_subject = re.search(
        r"(?i)(?:"
        r"\b(?:find|search|list|show)\s+.*\bfiles?\b|"
        r"\b(?:find|search|list|show)\s+.*\bdownloads?\b|"
        r"\bfiles?\b.*\b(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b|"
        r"\bdownloads?\b.*\b(?:range\s+of|between|from|\d+\s*(?:kb|mb|gb))\b|"
        r"\bfiles?\s+in\s+(?:my\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b|"
        r"\blarge\s+files?\s+in\s+(?:my\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b|"
        r"\b(?:big|large|huge)\s+files?\b.*\b(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b"
        r")",
        clean,
    )
    file_size_threshold = re.search(
        r"(?i)(?:"
        r"(?:less|more|greater|larger|smaller|lesser|under|over|above|below|bigger)(?:\s+than)?|"
        r"\b(?:range\s+of|between|from)\b|"
        r"\d+\s*(?:kb|mb|gb)\b\s+(?:to|and|-)\s+\d+\s*(?:kb|mb|gb)\b|"
        r"\d+\s*(?:kb|mb|gb)\b"
        r")",
        clean,
    )
    if file_size_subject and (
        file_size_threshold or re.search(r"(?i)\b(?:large|big|huge)\s+files?\b", clean)
    ):
        return Route(f"find_files_by_size {cmd}", source="offline")

    if _is_knowledge_question(clean):
        return Route(f"web_answer {cmd}", source="offline")

    chat_route = _route_chat_intent(cmd)
    if chat_route:
        return chat_route

    competitions_route = _route_competitions(cmd)
    if competitions_route:
        return competitions_route

    if _is_investment_question(clean):
        topic = _strip_query_prefix(cmd)
        return Route(
            f"predictions --domain stocks --deep {shlex.quote(topic)}",
            source="offline",
        )

    try:
        from arka.routing.symbolic import (
            route_currency_convert,
            route_daily_brief,
            route_kaggle,
            route_kalshi,
            route_timezone_convert,
        )

        currency_route = route_currency_convert(cmd)
        if currency_route:
            return Route(currency_route, source="offline")
        timezone_route = route_timezone_convert(cmd)
        if timezone_route:
            return Route(timezone_route, source="offline")
        kalshi_route = route_kalshi(cmd)
        if kalshi_route:
            return Route(kalshi_route, source="offline")
        kaggle_route = route_kaggle(cmd)
        if kaggle_route:
            return Route(kaggle_route, source="offline")
        brief_route = route_daily_brief(cmd)
        if brief_route:
            return Route(brief_route, source="offline")
    except ImportError:
        pass

    if _is_council_request(clean):
        try:
            from arka.agent.council import nl_to_argv

            argv = nl_to_argv(clean)
            if argv:
                return Route(
                    "council " + " ".join(shlex.quote(a) for a in argv),
                    source="offline",
                )
        except ImportError:
            pass
        return Route(f"council {cmd}", source="offline")

    if _is_interesting_fact_request(clean):
        return Route(f"interesting_fact {cmd}", source="offline")

    if _is_platform_howto_question(clean):
        return Route(f"platform_howto {cmd}", source="offline")

    if _is_system_advice_question(clean):
        return Route(f"agent_ask {cmd}", source="offline")

    return None


def _match_third_party(cmd: str) -> str | None:
    try:
        import subprocess
        import sys

        from arka.paths import script_path

        path = script_path("arka_skills.py")
        if not path.is_file():
            return None
        proc = subprocess.run(
            [sys.executable, str(path), "match", cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        line = proc.stdout.strip()
        return line or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _route_chat_intent(cmd: str) -> Route | None:
    try:
        import subprocess
        import sys

        from arka.paths import script_path

        path = script_path("arka_chat.py")
        if not path.is_file():
            return None
        proc = subprocess.run(
            [sys.executable, str(path), "intent", cmd],
            capture_output=True,
            text=True,
            timeout=45,
        )
        line = proc.stdout.strip()
        if not line or "\t" not in line:
            return None
        action, _data = line.split("\t", 1)
        action = action.strip().upper()
        if action == "SEARCH":
            return Route(f"web_answer {cmd}", source="intent")
        if action == "CALC":
            return Route(f"calc {cmd}", source="intent")
        if action == "WEATHER":
            return Route(f"hyperlocal_weather {cmd}", source="intent")
        if action == "ERROR":
            return Route(f"error_helper {cmd}", source="intent")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _strip_query_prefix(cmd: str) -> str:
    stripped = re.sub(
        r"^(?i)(?:please\s+)?(?:tell|explain|describe)(?:\s+me)?(?:\s+about)?\s+",
        "",
        cmd.strip(),
    ).strip()
    return stripped or cmd.strip()


def _is_investment_question(clean: str) -> bool:
    return bool(
        re.search(
            r"(?i)(where\s+(to|should\s+i)\s+invest|how\s+(to|can\s+i)\s+invest|invest\s+\d|"
            r"make\s+(?:a\s+)?profit|best\s+(?:place|option|way|stock|fund)\s+to\s+(?:invest|put)|"
            r"\d+\s+for\s+\d+\s*(?:day|week|month)|\b(?:stock|market)\s+invest)",
            clean,
        )
    )


_SHOW_ME_IMAGE_HINT = re.compile(
    r"(?i)\b(?:image|photo|picture|pic|screenshot|snapshot|"
    r"\.png|\.jpe?g|\.webp|\.gif|\.bmp|\.svg|\.heic|\.tiff?)\b",
)


def _is_council_request(clean: str) -> bool:
    try:
        from arka.routing.council import is_council_request

        return is_council_request(clean)
    except ImportError:
        return False


def _is_interesting_fact_request(clean: str) -> bool:
    try:
        from arka.routing.interesting_fact import is_interesting_fact_request

        return is_interesting_fact_request(clean)
    except ImportError:
        return False


def _is_platform_howto_question(clean: str) -> bool:
    try:
        from arka.routing.platform_howto import is_platform_howto_question

        return is_platform_howto_question(clean)
    except ImportError:
        return False


def _is_system_advice_question(clean: str) -> bool:
    """Personal machine / upgrade opinion questions → agent_ask, not web_answer."""
    if re.search(
        r"(?i)\b(this\s+(pc|computer|system|machine|mac|macbook|laptop)|"
        r"my\s+(cpu|gpu|ram|disk|pc|computer|system|driver|terminal|shell|mac|macbook|machine|laptop))\b",
        clean,
    ):
        return True
    if re.search(r"(?i)\b(my|should\s+i|can\s+i|do\s+i|am\s+i)\b", clean) and re.search(
        r"(?i)\b(outdated|too\s+old|too\s+slow|good\s+enough|worth\s+upgrad|bottleneck|"
        r"malware|infected|hacked|compromised|specs?\s+for\s+my|upgrade|gaming|cpu|gpu|ram|disk|"
        r"system|pc|computer|mac|macbook|machine|laptop)\b",
        clean,
    ):
        return True
    return bool(
        re.search(
            r"(?i)(outdated|too\s+old|too\s+slow|good\s+enough|worth\s+upgrad|bottleneck|"
            r"malware|infected|hacked|compromised|specs?\s+for\s+my)",
            clean,
        )
    )


def _is_knowledge_question(clean: str) -> bool:
    try:
        from arka.routing.symbolic import route_daily_brief

        if route_daily_brief(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.price_sources import is_price_check_query

        if is_price_check_query(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.competitions import wants_competitions_search

        if wants_competitions_search(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.routing.learned import match_learned, wants_route_management

        if wants_route_management(clean) or match_learned(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.generate_data import wants_generate_data

        if wants_generate_data(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.view_data import wants_view_data

        if wants_view_data(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.github_resume import wants_github_resume

        if wants_github_resume(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.agent.data_ask import wants_data_ask

        if wants_data_ask(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.llm.model_advisor import is_model_select_query

        if is_model_select_query(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.llm.provider_select import is_preferred_model_set_query

        if is_preferred_model_set_query(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.integrations.fugu import wants_fugu

        if wants_fugu(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.integrations.gemini_cli import wants_gemini_cli

        if wants_gemini_cli(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.integrations.harvard_ark import wants_harvard_ark

        if wants_harvard_ark(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.integrations.kalshi import wants_kalshi

        if wants_kalshi(clean):
            return False
    except ImportError:
        pass
    try:
        from arka.integrations.kaggle import wants_kaggle

        if wants_kaggle(clean):
            return False
    except ImportError:
        pass
    if re.search(r"(?i)\b(life[- ]sciences?)\s+(list|install|info|doctor)\b", clean):
        return False
    if re.search(r"(?i)\b(life[- ]sciences?|biomedical research tools|bioinformatics tools)\b", clean):
        return False
    if _is_investment_question(clean):
        return False
    if re.search(r"[\w.+-]+@[\w.-]+\.\w+", clean) and re.search(
        r"(?i)\b(send|email|draft|compose|write)\b",
        clean,
    ):
        return False
    if re.search(
        r"(?i)\b(birthday|anniversary|wedding|valentine|christmas|holiday|gift|gifts|present|presents)\b",
        clean,
    ):
        return True
    if re.match(
        r"(?i)^what\s+to\s+(give|buy|get|choose|pick|wear|say|cook|make|bring|serve)\b",
        clean,
    ):
        return True
    if re.match(
        r"(?i)^what\s+(should|can|could)\s+i\s+(give|buy|get|choose|pick)\b",
        clean,
    ):
        return True
    if re.search(
        r"\b(my|this pc|my computer|my mac|my macbook|my machine)\b",
        clean,
    ) and re.search(
        r"(?i)\b(cpu|gpu|ram|disk|pc|computer|system|mac|macbook|machine|laptop|upgrade|outdated|gaming)\b",
        clean,
    ):
        return False
    if re.search(r"\bshould i\b", clean) and re.search(
        r"(?i)\b(my|this pc|cpu|gpu|ram|disk|upgrade|install|buy a new (?:pc|laptop|mac))\b",
        clean,
    ):
        return False
    if re.match(r"^show\s+me\s+", clean) and not _SHOW_ME_IMAGE_HINT.search(clean):
        return True
    if re.search(
        r"(?i)(\bvs\.?\b|\bversus\b|\bdifference\s+(between|of|in)\b|\bdifferences?\s+between\b|\bcompare\b|\bcomparison\b)",
        clean,
    ) and not re.search(
        r"(?i)\b(this\s+(pc|computer|system|machine|mac|macbook|laptop)|my\s+(cpu|gpu|ram|disk|pc|computer|system|driver|terminal|shell|mac|macbook|machine|laptop))\b",
        clean,
    ):
        return True
    return bool(
        re.match(
            r"^(why |where |when |who |what |tell me |explain |describe |how old |how many |how much )",
            clean,
        )
    )
