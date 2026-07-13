#!/usr/bin/env python3
"""Model-agnostic LLM completions for Arka via Agno."""

from __future__ import annotations

import argparse
import sys

from arka.llm.fallback import (
    env,
    fetch_gemini_models_live,
    fetch_groq_models_live,
    fetch_ollama_models_live,
    llm_complete as _fallback_complete,
    llm_last_error,
    llm_stream_complete as _fallback_stream,
    model_label,
    ordered_model_candidates,
    provider_available,
    reset_llm_exhaustion,
)
from arka.llm.fallback import EXHAUSTION


def _load_fish_env() -> None:
    try:
        import arka.paths as arka_paths

        arka_paths.load_env_file()
        return
    except ImportError:
        pass
    env_file = __import__("pathlib").Path.home() / ".config" / "fish" / ".env"
    if not env_file.is_file():
        return
    import re

    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if key and not __import__("os").environ.get(key, "").strip():
            __import__("os").environ[key] = val


def _model_exhausted(provider: str, model_id: str) -> bool:
    return EXHAUSTION.exhausted(provider, model_id)


def llm_complete(
    system: str,
    user: str,
    temperature: float = 0.2,
    *,
    task: str | None = None,
    skill: str | None = None,
    skip_security: bool = False,
) -> str:
    if not skip_security:
        try:
            from arka.core.security import apply_llm_security

            blocked, system, user = apply_llm_security(system, user, task=task)
            if blocked:
                return blocked
        except ImportError:
            pass
    try:
        from arka.telemetry import (
            llm_http_span_attributes,
            mark_error,
            mark_ok,
            parse_http_status_code,
            set_http_span_attributes,
            span,
        )
    except ImportError:
        return _fallback_complete(system, user, temperature, task=task, skill=skill)

    attrs = {
        "gen_ai.system": "arka",
        "arka.task": task or "default",
        "gen_ai.request.temperature": temperature,
        "arka.llm.prompt_chars": len(system) + len(user),
    }
    if skill:
        attrs["arka.skill"] = skill
    with span("arka.llm.complete", attributes=attrs) as current:
        try:
            text = _fallback_complete(system, user, temperature, task=task, skill=skill)
        except Exception as exc:
            code = parse_http_status_code(exc)
            if code is not None:
                set_http_span_attributes(current, method="POST", status_code=code)
            mark_error(current, str(exc), exc=exc)
            raise
        if text.startswith("[LLM error:"):
            code = parse_http_status_code(text)
            if code is not None:
                set_http_span_attributes(current, method="POST", status_code=code)
            mark_error(current, text[:200])
        else:
            current.set_attribute("arka.llm.completion_chars", len(text))
            try:
                from arka.llm.fallback import llm_last_model

                last = llm_last_model()
                if last:
                    current.set_attribute("gen_ai.provider.name", last[0])
                    current.set_attribute("gen_ai.request.model", last[1])
                    set_http_span_attributes(
                        current,
                        method="POST",
                        url=llm_http_span_attributes(last[0])["http.url"],
                        status_code=200,
                    )
            except ImportError:
                set_http_span_attributes(current, method="POST", status_code=200)
            mark_ok(current)
        return text


def _host_platform() -> str:
    try:
        from arka.core.platform import cached_platform

        plat = cached_platform()
        if plat:
            return plat
    except ImportError:
        pass
    import platform as _platform

    sysname = _platform.system()
    if sysname == "Darwin":
        return "macos"
    if sysname.startswith("Linux"):
        return "linux"
    if sysname == "Windows":
        return "windows"
    return sysname.lower()


def _platform_hint(plat: str) -> str:
    if plat == "macos":
        return (
            "Host: macOS. Use sw_vers, sysctl, vm_stat, df -h, system_profiler, ipconfig, ps aux, open, brew. "
            "Do NOT use lscpu, free, lspci, lsb_release, apt, /proc, or systemctl."
        )
    if plat == "linux":
        return (
            "Host: Linux. Use lscpu, free -h, df -h, lspci, uname, /proc/cpuinfo, apt/dnf/pacman, ss, systemctl."
        )
    if plat == "windows":
        return "Host: Windows. Prefer portable commands or PowerShell where needed."
    return "Host: unknown. Prefer portable commands: uname, df, ps, python3."


def llm_route(cmd: str, available_skills: str, aliases_list: str) -> str:
    """Interpret natural language into a skill name or shell command."""
    try:
        from arka.core.security import verify_user_prompt

        gate = verify_user_prompt(cmd)
        if gate.status == "block":
            return "impossible"
    except ImportError:
        pass
    try:
        from arka.telemetry import mark_error, mark_ok, span
    except ImportError:
        span = None  # type: ignore[assignment,misc]

    ctx = (
        span(
            "arka.route.llm",
            attributes={"arka.task": "route", "arka.route.input_chars": len(cmd)},
        )
        if span is not None
        else _null_context()
    )
    with ctx as current:
        if not aliases_list:
            aliases_list = env("ROUTE_ALIASES")
        learned_hint = ""
        try:
            from arka.routing.learned import prompt_summary

            learned_hint = prompt_summary()
            if learned_hint:
                learned_hint = learned_hint + "\n"
        except ImportError:
            pass
        plat = _host_platform()
        plat_hint = _platform_hint(plat)
        system = (
            f"You are a cross-platform shell expert on {plat} (fish shell). "
            "Respond with ONLY the command(s) or skill name(s). "
            "No markdown. No explanations. If no command is safe or possible, respond 'impossible'.\n"
            f"{plat_hint}\n"
            "If the user's request is a question, math calculation, or query that can be answered by "
            "running a standard shell command (e.g. date, date +%Y, python3 -c \"print(...)\"), "
            "output that exact shell command.\n"
            "Do NOT map a request to one of the custom skills unless it is a very direct and clear match. "
            "Unrelated or loose matches must not be mapped to skills "
            "(e.g., do NOT map 'tell me year' to 'system_info', use date or date +%Y instead).\n"
            f"Available Shell Aliases:\n{aliases_list}\n"
            f"{learned_hint}"
            "Use symbolic reasoning to match and use the most appropriate shell alias if one exists.\n"
            "CRITICAL NOTE ON ALIASES:\n"
            "- ls is aliased to eza. eza does NOT support standard ls sorting flags like -t, -ltr, or -lt. "
            "To sort by newest/recency, use eza --sort newest. To sort by oldest, use eza --sort oldest. "
            "Alternatively bypass the alias via command ls -lt.\n"
            "- cat is aliased to batcat."
        )
        user = (
            f"Convert to safe shell command(s) or skill(s): '{cmd}'. "
            f"Available skills: {available_skills}. "
            "IMPORTANT: For multiple tasks, use '&&' between commands. "
            "ROUTING RULES: Multi-step goals that need try/fix/retry -> goal <goal> (or loop <goal>). "
            "'install APP' (no store named) -> install_app APP. "
            "Python/PyPI packages -> install_uv [--cpu|--cuda] PACKAGE. "
            "Intel/GPU driver warnings (Linux) -> fix_graphics_driver. "
            "'install APP with apt' -> install_apt APP. "
            "Local machine specs (specs of my pc/mac, tell me about my mac, tell me my gpu/cpu/ram) -> system_info or system_info gpu|cpu|ram|disk. "
            "Opinion/advice questions (is my cpu good enough, should I upgrade) -> agent_ask <full question>. "
            "Factual general-knowledge questions -> web_answer <full question> (NOT search_web). "
            "Live CPU/RAM usage meters -> system_monitor (NOT for specs dumps). "
            "'play <title>' -> play_movie. "
            "Ambiguous play/media (film + music, song on spotify, etc.): pick the skill that matches user intent — "
            "film/movie/video -> play_movie; song/soundtrack only -> play_song; spotify -> play_spotify; youtube -> play_youtube. "
            "Example: 'play a film that has X music' -> play_movie <title> (user wants the movie, not just the track). "
            "'generate image of X' -> generate_image X. "
            "'generate password' -> generate_password [len]. "
            "'save password for wifi' / generate_password save <name> -> encrypted vault. "
            "'get password wifi' -> generate_password get <name>. "
            "'generate video of X' -> generate_video X. "
            "'predict opportunities in antiques/stocks/strategy' -> predictions <topic>. "
            "'where to invest 3000 for 1 month' / 'make profit' -> predictions --domain stocks --deep <question>. "
            "'stock invest <question>' — same as above. "
            "'stock macro' / disaster/geopolitics questions → macro event stock impact + hold duration. "
            "'stock funding' / 'stock competition TICKER' → recent VC/IPO deals + peer scoreboard. "
            "'stock fundamentals TICKER' → debt/equity, ROE, P/E, margins. "
            "'stock emotion' → net news sentiment sum + crowd behavior forecast. "
            "'stock news/prices/analyze TICKER/dashboard' -> stock <subcommand>. "
            "Profession NL — explicit only: 'as a nutritionist …' → profession ask nutrition …. "
            "Professions are curated source lists (RSS, web, local repos) — not role prompts; answers cite sources. "
            "'profession sources nutrition' lists feeds and indexes for a domain. "
            "'I'm a doctor' is remembered; later health questions use your saved domain. "
            "Domains: health, nutrition, startup, investor, teacher, legal, engineer, journalism, marketing, finance, counselor, chef. "
            "'profession setup' clones and indexes investor/nutrition/startup/engineer repos for source-backed answers. "
            "Document RAG: ingest -> doc_ingest|pdf_ingest <path> (PDF, docx, pptx, xlsx, txt, md, html, code, …). "
            "Q&A/summarize -> doc_ask|pdf_ask [--doc NAME] <question>. "
            "List docs -> doc_list|pdf_list. Supported formats: arka pdf formats. "
            "ARCHIVES: extract and run FILE.zip -> extract_and_run. "
            "Artificial Internet Enhancements (AIE): start/stop/status/cleanup -> internet_enhance [start|stop|status|cleanup] [all|click|copy|zip|classify]. "
            "YouTube transcript -> youtube_transcript <url> [--summarize]. "
            "Single YouTube video download -> youtube_download <url> [--audio] [--quality 1080|720|480]. "
            "YouTube bulk download playlist/channel -> youtube_bulk download <url> [--channel] [--audio] [--wait]; "
            "youtube_bulk start|stop|open|library|status. "
            "Local mp3/mp4/audio -> media_transcript <path> [--summarize] [-q \"your instructions\"] (Groq/Sarvam STT + ffmpeg). "
            "Or: arka summarize [for N words] [focus on X] <file> — default covers the entire video concisely. "
            "Folder of media -> folder_summarize <dir> [-r] [--limit N]. "
            "YouTube/local playlist digest -> playlist_summarize --url URL | --folder DIR. "
            "Codebase Q&A -> codebase_ingest <project-dir> [-n name]; then doc_ask --doc codebase-NAME <question>. "
            "Summarize web page -> summarize_url <url>. "
            "Daily/tech brief -> daily_brief. Wi-Fi info -> wifi_info. "
            "Simple queries: shell commands (date, df)."
        )
        result = llm_complete(system, user, temperature=0.1, task="route")
        if span is not None:
            current.set_attribute("arka.route.result", result[:500])
            if result == "impossible":
                mark_error(current, "impossible")
            else:
                mark_ok(current)
        return result


def _null_context():
    from contextlib import nullcontext

    return nullcontext()


def cmd_active_model(_args: argparse.Namespace) -> int:
    label = model_label()
    if label:
        print(label)
    return 0 if label else 1


def cmd_complete(args: argparse.Namespace) -> int:
    text = llm_complete(
        args.system,
        args.user,
        args.temperature,
        task=args.task or None,
        skill=getattr(args, "skill", None) or None,
    )
    if not text:
        err = llm_last_error()
        if err:
            print(err, file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_stream(args: argparse.Namespace) -> int:
    if not args.skip_security:
        try:
            from arka.core.security import apply_llm_security

            blocked, system, user = apply_llm_security(args.system, args.user, task=args.task)
            if blocked:
                print(blocked, end="", flush=True)
                return 0
            args.system, args.user = system, user
        except ImportError:
            pass
    got = False
    for delta in _fallback_stream(
        args.system,
        args.user,
        args.temperature,
        task=args.task or None,
        skill=getattr(args, "skill", None) or None,
    ):
        got = True
        print(delta, end="", flush=True)
    if not got:
        err = llm_last_error()
        if err:
            print(err, file=sys.stderr)
        return 1
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    if args.gemini_live:
        live = fetch_gemini_models_live(force=args.refresh)
        if not live:
            print("No live Gemini models (check GEMINI_API_KEY / GEMINI_LIST).", file=sys.stderr)
            return 1
        for model_id in live:
            print(f"gemini\t{model_id}\tlive")
        return 0
    if getattr(args, "groq_live", False):
        live = fetch_groq_models_live(force=args.refresh)
        if not live:
            print("No live Groq models (check GROQ_API_KEY / GROQ_LIST).", file=sys.stderr)
            return 1
        for model_id in live:
            print(f"groq\t{model_id}\tlive")
        return 0
    if getattr(args, "ollama_live", False):
        live = fetch_ollama_models_live(force=args.refresh)
        if not live:
            print("No live Ollama models (check OLLAMA_HOST / ollama serve / OLLAMA_LIST).", file=sys.stderr)
            return 1
        for model_id in live:
            print(f"ollama\t{model_id}\tlive")
        return 0
    include_all = bool(getattr(args, "all", False))
    for provider, model_id in ordered_model_candidates(
        task=args.task or None,
        skill=getattr(args, "skill", None) or None,
    ):
        if not include_all:
            if not provider_available(provider):
                continue
            if _model_exhausted(provider, model_id):
                continue
        ok = provider_available(provider)
        mark = "ok" if ok else "skip"
        ex = "exhausted" if _model_exhausted(provider, model_id) else "ready"
        print(f"{provider}\t{model_id}\t{mark}\t{ex}")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    from arka.llm.provider_select import detect_provider_models
    from arka.llm.providers import provider_catalog_models, provider_specs

    show_models = getattr(args, "models", False)
    include_all = bool(getattr(args, "all", False))
    if show_models:
        print("slug\tdisplay_name\tconfigured\tkind\tdefault_model\tmodels\tsource")
        for spec in provider_specs():
            ok = "yes" if provider_available(spec.slug) else "no"
            if include_all or not provider_available(spec.slug):
                models = provider_catalog_models(spec)
                source = "catalog"
            else:
                models, source = detect_provider_models(
                    spec.slug,
                    include_live=True,
                    include_all=include_all,
                )
                if not models:
                    models = provider_catalog_models(spec)
                    source = "catalog"
            model_text = ",".join(models)
            print(
                f"{spec.slug}\t{spec.display_name}\t{ok}\t{spec.kind}\t"
                f"{spec.default_model}\t{model_text}\t{source}"
            )
        return 0

    print("slug\tdisplay_name\tconfigured\tdefault_model\tenv_keys")
    for spec in provider_specs():
        ok = "yes" if provider_available(spec.slug) else "no"
        keys = ",".join(spec.env_keys[:3])
        print(f"{spec.slug}\t{spec.display_name}\t{ok}\t{spec.default_model}\t{keys}")
    return 0


def cmd_trace_status(_args: argparse.Namespace) -> int:
    try:
        from arka.telemetry import spans_enabled, trace_status
    except ImportError:
        print("enabled\tfalse")
        print("configured\tfalse")
        print("packages\tmissing")
        return 0
    status = trace_status()
    for key, value in status.items():
        print(f"{key}\t{value}")
    if spans_enabled() and status.get("configured") != "true":
        print("hint\tpip install 'arka-agent[observability]'")
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    reset_llm_exhaustion()
    print("LLM exhaustion cache cleared.")
    return 0


def cmd_vllm_status(_args: argparse.Namespace) -> int:
    from arka.llm.providers import get_provider, provider_base_url, vllm_cloud_configured
    from arka.llm.servers import (
        _vllm_health_url,
        apply_vllm_defaults,
        is_reachable,
        provider_available_with_servers,
        vllm_explicitly_configured,
    )

    explicit = vllm_explicitly_configured()
    apply_vllm_defaults()
    local_reachable = is_reachable("vllm")
    local_configured = provider_available_with_servers("vllm")
    host = __import__("os").environ.get("VLLM_HOST", "127.0.0.1:8000")
    model = __import__("os").environ.get("VLLM_MODEL", "default")
    start_cmd = __import__("os").environ.get("VLLM_START_CMD", "")

    print("backend\tvllm")
    print(f"explicit_config\t{str(explicit).lower()}")
    print(f"reachable\t{local_reachable}")
    print(f"configured\t{local_configured}")
    print(f"host\t{host}")
    print(f"health_url\t{_vllm_health_url()}")
    print(f"model\t{model}")
    print(f"start_cmd\t{start_cmd or '(unset)'}")

    cloud_configured = vllm_cloud_configured()
    cloud_reachable = is_reachable("vllm-cloud") if cloud_configured else False
    print("")
    print("backend\tvllm-cloud")
    print(f"configured\t{str(cloud_configured).lower()}")
    print(f"reachable\t{cloud_reachable}")
    if cloud_configured:
        spec = get_provider("vllm-cloud")
        print(f"url\t{provider_base_url(spec) if spec else ''}")
        print(f"model\t{__import__('os').environ.get('VLLM_CLOUD_MODEL', 'default')}")

    if not local_reachable and not local_configured and not cloud_configured:
        return 1
    return 0


def cmd_skill_models(args: argparse.Namespace) -> int:
    from arka.llm.skill_models import (
        clear_skill_model,
        effective_model_for_skill,
        list_skill_model_rows,
        set_skill_model,
        skill_models_path,
    )

    if args.skill_models_cmd == "path":
        print(skill_models_path())
        return 0

    if args.skill_models_cmd == "set":
        if not args.target or not args.model:
            print("Usage: skill-models set <skill|profile> <provider/model>", file=sys.stderr)
            return 1
        try:
            path = set_skill_model(args.target, args.model)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Saved {args.target} → {args.model} in {path}")
        return 0

    if args.skill_models_cmd == "clear":
        if not args.target:
            print("Usage: skill-models clear <skill|profile>", file=sys.stderr)
            return 1
        path = clear_skill_model(args.target)
        print(f"Cleared {args.target} in {path}")
        return 0

    if args.skill_models_cmd == "show":
        if not args.target:
            print("Usage: skill-models show <skill|profile>", file=sys.stderr)
            return 1
        model = effective_model_for_skill(args.target)
        if model:
            print(model)
            return 0
        print(f"No model configured for {args.target}", file=sys.stderr)
        return 1

    print(f"path\t{skill_models_path()}")
    print("kind\tname\tprofile\tconfigured\tsuggested\tdescription")
    for row in list_skill_model_rows():
        if args.profile and row["kind"] != "profile":
            continue
        if args.skill_only and row["kind"] != "skill":
            continue
        print(
            f"{row['kind']}\t{row['name']}\t{row['profile']}\t{row['configured']}\t"
            f"{row['suggested']}\t{row['description']}"
        )
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    text = llm_route(args.cmd, args.skills, env("ROUTE_ALIASES"))
    if not text:
        return 1
    print(text)
    return 0


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="Arka model-agnostic LLM (Agno)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_complete = sub.add_parser("complete", help="System + user completion with auto-fallback")
    p_complete.add_argument("--system", "-s", required=True)
    p_complete.add_argument("--user", "-u", required=True)
    p_complete.add_argument("--temperature", "-t", type=float, default=0.2)
    p_complete.add_argument("--task", help="Task profile: summarize|route|chat|research|agent|pdf|predictions")
    p_complete.add_argument("--skill", help="Skill name for per-skill model selection (e.g. web_answer)")
    p_complete.set_defaults(func=cmd_complete)

    p_stream = sub.add_parser("stream", help="Stream system + user completion (stdout deltas)")
    p_stream.add_argument("--system", "-s", required=True)
    p_stream.add_argument("--user", "-u", required=True)
    p_stream.add_argument("--temperature", "-t", type=float, default=0.2)
    p_stream.add_argument("--task", help="Task profile: summarize|route|chat|research|agent|pdf|predictions")
    p_stream.add_argument("--skill", help="Skill name for per-skill model selection")
    p_stream.add_argument("--skip-security", action="store_true", help=argparse.SUPPRESS)
    p_stream.set_defaults(func=cmd_stream, skip_security=False)

    p_route = sub.add_parser("route", help="NL command -> skill/shell (agent routing)")
    p_route.add_argument("cmd")
    p_route.add_argument("--skills", required=True)
    p_route.set_defaults(func=cmd_route)

    p_models = sub.add_parser("models", help="List provider/model fallback chain")
    p_models.add_argument("--task", help="Task profile for chain")
    p_models.add_argument("--skill", help="Skill name for per-skill chain")
    p_models.add_argument(
        "--gemini-live",
        action="store_true",
        help="List Gemini generateContent models from API (ListModels)",
    )
    p_models.add_argument(
        "--groq-live",
        action="store_true",
        help="List Groq chat models from API",
    )
    p_models.add_argument(
        "--ollama-live",
        action="store_true",
        help="List installed Ollama models from /api/tags",
    )
    p_models.add_argument("--refresh", action="store_true", help="Bypass live model list cache")
    p_models.add_argument(
        "--all",
        action="store_true",
        help="Include unavailable providers and exhausted models in fallback chain",
    )
    p_models.set_defaults(func=cmd_models)

    p_active = sub.add_parser("active-model", help="Show last-used or preferred LLM model")
    p_active.set_defaults(func=cmd_active_model)

    p_reset = sub.add_parser("reset-exhaustion", help="Clear session provider/model exhaustion cache")
    p_reset.set_defaults(func=cmd_reset)

    p_providers = sub.add_parser("providers", help="List supported LLM providers and env keys")
    p_providers.add_argument(
        "--models",
        action="store_true",
        help="Include detected model list per provider",
    )
    p_providers.add_argument(
        "--all",
        action="store_true",
        help="Include static catalog models not in live lists",
    )
    p_providers.set_defaults(func=cmd_providers)

    p_skill_models = sub.add_parser("skill-models", help="Per-skill / per-profile model choices")
    p_skill_models_sub = p_skill_models.add_subparsers(dest="skill_models_cmd")
    p_skill_models_list = p_skill_models_sub.add_parser("list", help="List skill/profile model map")
    p_skill_models_list.add_argument("--profiles-only", dest="profile", action="store_true")
    p_skill_models_list.add_argument("--skills-only", dest="skill_only", action="store_true")
    p_skill_models_list.set_defaults(func=cmd_skill_models, skill_models_cmd="list", target="", model="")
    p_skill_models_show = p_skill_models_sub.add_parser("show", help="Effective model for one skill/profile")
    p_skill_models_show.add_argument("target")
    p_skill_models_show.set_defaults(func=cmd_skill_models, skill_models_cmd="show", model="")
    p_skill_models_set = p_skill_models_sub.add_parser("set", help="Set model for skill or profile")
    p_skill_models_set.add_argument("target")
    p_skill_models_set.add_argument("model")
    p_skill_models_set.set_defaults(func=cmd_skill_models, skill_models_cmd="set")
    p_skill_models_clear = p_skill_models_sub.add_parser("clear", help="Remove skill/profile override")
    p_skill_models_clear.add_argument("target")
    p_skill_models_clear.set_defaults(func=cmd_skill_models, skill_models_cmd="clear", model="")
    p_skill_models_path = p_skill_models_sub.add_parser("path", help="Show config file path")
    p_skill_models_path.set_defaults(func=cmd_skill_models, skill_models_cmd="path", target="", model="")
    p_skill_models.set_defaults(func=cmd_skill_models, skill_models_cmd="list", target="", model="", profile=False, skill_only=False)

    p_vllm = sub.add_parser("vllm", help="Local vLLM status (reachability, env, fallback chain)")
    p_vllm_sub = p_vllm.add_subparsers(dest="vllm_cmd")
    p_vllm_status = p_vllm_sub.add_parser("status", help="Show vLLM / vLLM Cloud configuration")
    p_vllm_status.set_defaults(func=cmd_vllm_status)
    p_vllm.set_defaults(func=cmd_vllm_status, vllm_cmd="status")

    p_trace = sub.add_parser("trace-status", help="Show OpenTelemetry / SigNoz tracing status")
    p_trace.set_defaults(func=cmd_trace_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
