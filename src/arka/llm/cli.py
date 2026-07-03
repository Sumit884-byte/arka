#!/usr/bin/env python3
"""Model-agnostic LLM completions for Arka via Agno."""

from __future__ import annotations

import argparse
import sys

from arka.llm.fallback import (
    env,
    fetch_gemini_models_live,
    gemini_model_ids,
    llm_complete as _fallback_complete,
    llm_last_error,
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
    return _fallback_complete(system, user, temperature, task=task)


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
    if not aliases_list:
        aliases_list = env("ARKA_ROUTE_ALIASES")
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
        "Daily brief -> daily_brief. Wi-Fi info -> wifi_info. "
        "Simple queries: shell commands (date, df)."
    )
    return llm_complete(system, user, temperature=0.1, task="route")


def cmd_active_model(_args: argparse.Namespace) -> int:
    label = model_label()
    if label:
        print(label)
    return 0 if label else 1


def cmd_complete(args: argparse.Namespace) -> int:
    text = llm_complete(args.system, args.user, args.temperature, task=args.task or None)
    if not text:
        err = llm_last_error()
        if err:
            print(err, file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    if args.gemini_live:
        live = fetch_gemini_models_live(force=args.refresh)
        if not live:
            print("No live Gemini models (check GEMINI_API_KEY / ARKA_GEMINI_LIST).", file=sys.stderr)
            return 1
        for model_id in live:
            print(f"gemini\t{model_id}\tlive")
        return 0
    for provider, model_id in ordered_model_candidates(task=args.task or None):
        ok = provider_available(provider)
        mark = "ok" if ok else "skip"
        ex = "exhausted" if _model_exhausted(provider, model_id) else "ready"
        print(f"{provider}\t{model_id}\t{mark}\t{ex}")
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    reset_llm_exhaustion()
    print("LLM exhaustion cache cleared.")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    text = llm_route(args.cmd, args.skills, env("ARKA_ROUTE_ALIASES"))
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
    p_complete.set_defaults(func=cmd_complete)

    p_route = sub.add_parser("route", help="NL command -> skill/shell (agent routing)")
    p_route.add_argument("cmd")
    p_route.add_argument("--skills", required=True)
    p_route.set_defaults(func=cmd_route)

    p_models = sub.add_parser("models", help="List provider/model fallback chain")
    p_models.add_argument("--task", help="Task profile for chain")
    p_models.add_argument(
        "--gemini-live",
        action="store_true",
        help="List Gemini generateContent models from API (ListModels)",
    )
    p_models.add_argument("--refresh", action="store_true", help="Bypass Gemini list cache")
    p_models.set_defaults(func=cmd_models)

    p_active = sub.add_parser("active-model", help="Show last-used or preferred LLM model")
    p_active.set_defaults(func=cmd_active_model)

    p_reset = sub.add_parser("reset-exhaustion", help="Clear session provider/model exhaustion cache")
    p_reset.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
