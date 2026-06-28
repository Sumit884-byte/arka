#!/usr/bin/env python3
"""Model-agnostic LLM completions for Arka via Agno."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
from contextlib import contextmanager
from typing import Any

DEFAULT_MODELS: list[tuple[str, str]] = [
    ("gemini", "gemini-2.0-flash"),
    ("gemini", "gemini-1.5-flash"),
    ("groq", "llama-3.3-70b-versatile"),
    ("groq", "llama3-8b-8192"),
    ("ollama", "minimax-m2.5:cloud"),
    ("ollama", "minimax-m2:cloud"),
    ("ollama", "qwen3:8b"),
    ("ollama", "llama3.2:1b"),
]

KNOWN_GEMINI = {
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-3.5-flash",
}

_EXHAUSTED_MODELS: set[tuple[str, str]] = set()
_EXHAUSTED_LOCK = threading.Lock()


@contextmanager
def _quiet_llm_logs():
    """Suppress Agno/Gemini/Groq library noise on stderr (keep progress bars visible)."""
    if env("ARKA_LLM_VERBOSE") in {"1", "true", "yes"}:
        yield
        return
    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    agno_levels: list[tuple[Any, int]] = []
    try:
        from agno.utils import log as agno_log

        for lg in (agno_log.logger, agno_log.agent_logger, agno_log.team_logger, agno_log.workflow_logger):
            agno_levels.append((lg, lg.level))
            lg.setLevel(logging.CRITICAL + 1)
    except ImportError:
        pass
    try:
        yield
    finally:
        logging.disable(prev_disable)
        for lg, level in agno_levels:
            lg.setLevel(level)


def _mark_model_exhausted(provider: str, model_id: str, exc: Exception) -> None:
    msg = str(exc).lower()
    if not any(x in msg for x in ("429", "resource_exhausted", "quota exceeded", "rate limit", "invalid api key")):
        return
    with _EXHAUSTED_LOCK:
        _EXHAUSTED_MODELS.add((provider, model_id))
        if provider == "gemini" and any(x in msg for x in ("free_tier", "quota exceeded", "resource_exhausted")):
            for mid in _gemini_model_ids():
                _EXHAUSTED_MODELS.add(("gemini", mid))
        if provider == "groq" and "invalid api key" in msg:
            for mid in _groq_model_ids():
                _EXHAUSTED_MODELS.add(("groq", mid))


def _model_exhausted(provider: str, model_id: str) -> bool:
    with _EXHAUSTED_LOCK:
        return (provider, model_id) in _EXHAUSTED_MODELS


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _load_fish_env() -> None:
    try:
        import arka_paths

        arka_paths.load_env_file()
        return
    except ImportError:
        pass
    env_file = __import__("pathlib").Path.home() / ".config" / "fish" / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if key and not os.environ.get(key, "").strip():
            os.environ[key] = val


def _ensure_google_key() -> str:
    key = env("GEMINI_API_KEY") or env("GOOGLE_API_KEY")
    if key and not env("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = key
    return key


def _gemini_model_ids() -> list[str]:
    raw = [
        env("ARKA_CHAT_MODEL"),
        env("AI_PREFERRED_MODEL"),
        env("ARKA_LLM_MODEL"),
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    out: list[str] = []
    for model in raw:
        if not model or not model.startswith("gemini-"):
            continue
        if model not in KNOWN_GEMINI and "gemini-" not in model:
            continue
        if model not in out:
            out.append(model)
    if not out:
        out = ["gemini-2.0-flash", "gemini-1.5-flash"]
    return out


def _groq_model_ids() -> list[str]:
    raw = [
        env("GROQ_MODEL"),
        "llama-3.3-70b-versatile",
        "llama3-8b-8192",
    ]
    out: list[str] = []
    for model in raw:
        if model and model not in out:
            out.append(model)
    return out


def _ollama_model_ids() -> list[str]:
    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("ARKA_LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("ARKA_LLM_MODEL")
    raw = [
        env("OLLAMA_CHAT_MODEL"),
        pref_model if pref_provider == "ollama" else "",
        env("ARKA_LLM_MODEL") if pref_provider == "ollama" else "",
        "minimax-m2.5:cloud",
        "minimax-m2:cloud",
        "qwen3:8b",
        "llama3.2:1b",
    ]
    out: list[str] = []
    for model in raw:
        if model and model not in out:
            out.append(model)
    return out


def _ollama_host() -> str:
    host = env("OLLAMA_HOST", "127.0.0.1:11434").replace("0.0.0.0", "127.0.0.1")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


def ordered_model_candidates() -> list[tuple[str, str]]:
    pref_provider = (env("AI_PREFERRED_PROVIDER") or env("ARKA_LLM_PROVIDER")).lower()
    pref_model = env("AI_PREFERRED_MODEL") or env("ARKA_LLM_MODEL")

    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []

    def add(provider: str, model_id: str) -> None:
        key = (provider.lower(), model_id)
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    if pref_provider and pref_model:
        add(pref_provider, pref_model)

    if env("VLLM_HOST") or env("VLLM_API_URL"):
        add("vllm", env("VLLM_MODEL") or "default")

    if pref_provider == "gemini" or not pref_provider:
        for model_id in _gemini_model_ids():
            add("gemini", model_id)

    if env("GROQ_API_KEY"):
        for model_id in _groq_model_ids():
            add("groq", model_id)

    for model_id in _ollama_model_ids():
        add("ollama", model_id)

    for provider, model_id in DEFAULT_MODELS:
        add(provider, model_id)

    if pref_provider:
        pref_first = [x for x in ordered if x[0] == pref_provider]
        pref_rest = [x for x in ordered if x[0] != pref_provider]
        ordered = pref_first + pref_rest

    return ordered


def _provider_available(provider: str) -> bool:
    if provider == "gemini":
        return bool(_ensure_google_key())
    if provider == "groq":
        return bool(env("GROQ_API_KEY"))
    if provider == "ollama":
        return _ollama_reachable()
    if provider == "openai":
        return bool(env("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(env("ANTHROPIC_API_KEY"))
    if provider == "vllm":
        return bool(env("VLLM_HOST") or env("VLLM_API_URL"))
    return False


def _ollama_reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(f"{_ollama_host()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _vllm_base_url() -> str:
    base = env("VLLM_API_URL")
    if not base:
        host = env("VLLM_HOST", "127.0.0.1:8000")
        base = f"http://{host}"
    if not base.startswith("http"):
        base = f"http://{base}"
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def build_model(provider: str, model_id: str, temperature: float) -> Any | None:
    provider = provider.lower()
    if not _provider_available(provider):
        return None

    if provider == "gemini":
        from agno.models.google import Gemini

        _ensure_google_key()
        return Gemini(id=model_id, temperature=temperature)

    if provider == "groq":
        from agno.models.groq import Groq

        mid = env("GROQ_MODEL") or model_id
        return Groq(id=mid, temperature=temperature)

    if provider == "ollama":
        from agno.models.ollama import Ollama

        mid = model_id or env("OLLAMA_CHAT_MODEL") or "minimax-m2.5:cloud"
        if mid.startswith("gemini-"):
            mid = model_id or "minimax-m2.5:cloud"
        api_key = env("OLLAMA_API_KEY") or None
        return Ollama(
            id=mid,
            host=_ollama_host(),
            api_key=api_key,
            options={"temperature": temperature},
        )

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id, temperature=temperature)

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id, temperature=temperature)

    if provider == "vllm":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(
            id=model_id or "default",
            base_url=_vllm_base_url(),
            api_key=env("VLLM_API_KEY") or "EMPTY",
            temperature=temperature,
        )

    return None


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\n*", "", text)
    text = re.sub(r"\n*```$", "", text)
    return text.strip()


def _looks_like_error(text: str) -> bool:
    if not text:
        return True
    stripped = text.strip()
    if stripped.startswith("{") and '"error"' in stripped:
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "error" in data:
                return True
        except json.JSONDecodeError:
            pass
    low = stripped.lower()
    if "could not generate" in low or "resource_exhausted" in low:
        return True
    return False


def _run_text(system: str, user: str, temperature: float) -> str:
    from agno.agent import Agent

    last_error = ""
    verbose = env("ARKA_LLM_VERBOSE") in {"1", "true", "yes"}
    with _quiet_llm_logs():
        for provider, model_id in ordered_model_candidates():
            if _model_exhausted(provider, model_id):
                continue
            model = build_model(provider, model_id, temperature)
            if model is None:
                continue
            try:
                if verbose:
                    print(f"arka_llm: trying {provider}/{model_id}", file=sys.stderr)
                agent = Agent(model=model, instructions=system, markdown=False)
                run = agent.run(user)
                text = getattr(run, "content", None)
                if text is None:
                    text = str(run)
                text = _strip_fences(str(text).strip())
                if text and not _looks_like_error(text):
                    if verbose:
                        print(f"arka_llm: ok {provider}/{model_id}", file=sys.stderr)
                    return text
            except Exception as exc:
                last_error = str(exc)
                _mark_model_exhausted(provider, model_id, exc)
                if verbose:
                    print(f"arka_llm: fail {provider}/{model_id}: {exc}", file=sys.stderr)
                continue
    if last_error and verbose:
        print(f"arka_llm: all providers failed ({last_error})", file=sys.stderr)
    return ""


def llm_route(cmd: str, available_skills: str, aliases_list: str) -> str:
    """Interpret natural language into a skill name or shell command."""
    if not aliases_list:
        aliases_list = env("ARKA_ROUTE_ALIASES")
    system = (
        "You are a Linux shell expert. Respond with ONLY the command(s) or skill name(s). "
        "No markdown. No explanations. If no command is safe or possible, respond 'impossible'.\n"
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
        "ROUTING RULES: Multi-step goals that need try/fix/retry -> agent_loop <goal>. "
        "'install APP' (no store named) -> install_app APP. "
        "Python/PyPI packages -> install_uv [--cpu|--cuda] PACKAGE. "
        "Intel/GPU driver warnings -> fix_graphics_driver. "
        "'install APP with apt' -> install_apt APP. "
        "Opinion/advice questions -> agent_ask <full question> (NOT system_monitor). "
        "Factual questions -> web_answer <full question> (NOT search_web). "
        "Opinion/advice about YOUR PC -> system_monitor. "
        "'play <title>' -> play_movie. "
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
    return llm_complete(system, user, temperature=0.1)


def llm_complete(system: str, user: str, temperature: float = 0.2) -> str:
    return _run_text(system, user, temperature)


def cmd_complete(args: argparse.Namespace) -> int:
    text = llm_complete(args.system, args.user, args.temperature)
    if not text:
        return 1
    print(text)
    return 0


def cmd_models(_args: argparse.Namespace) -> int:
    for provider, model_id in ordered_model_candidates():
        ok = _provider_available(provider)
        mark = "ok" if ok else "skip"
        print(f"{provider}\t{model_id}\t{mark}")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    aliases = env("ARKA_ROUTE_ALIASES")
    text = llm_route(args.cmd, args.skills, aliases)
    if not text:
        return 1
    print(text)
    return 0


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="Arka model-agnostic LLM (Agno)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_complete = sub.add_parser("complete", help="System + user completion")
    p_complete.add_argument("--system", "-s", required=True)
    p_complete.add_argument("--user", "-u", required=True)
    p_complete.add_argument("--temperature", "-t", type=float, default=0.2)
    p_complete.set_defaults(func=cmd_complete)

    p_route = sub.add_parser("route", help="NL command -> skill/shell (agent routing)")
    p_route.add_argument("cmd")
    p_route.add_argument("--skills", required=True)
    p_route.set_defaults(func=cmd_route)

    p_models = sub.add_parser("models", help="List provider/model fallback chain")
    p_models.set_defaults(func=cmd_models)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
