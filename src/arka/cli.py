"""Arka CLI — cross-platform entry point (macOS, Windows, Linux)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from arka import __version__
from arka.dispatch import run_fish_skill, run_script, run_skill
from arka.env import load_env
from arka.fish_bridge import delegate_fish_function, delegate_subcommand, delegate_to_fish
from arka.paths import (
    arka_home,
    bundled_dir,
    cache_dir,
    checkout_root,
    config_dir,
    ensure_layout,
    entry_script,
    env_file,
    fish_config,
    package_dir,
)
from arka.platform_info import fish_install_hint, has_full_fish_agent, skill_mode, system
from arka.router import route


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        return _cmd_help()

    if args[0] in ("-h", "--help", "help"):
        return _cmd_help()

    if args[0] in ("-V", "--version", "version"):
        print(f"arka {__version__} ({system()})")
        return 0

    if args[0] == "shell-init":
        return _cmd_shell_init(args[1:])

    if args[0] in ("download", "dl"):
        return _cmd_download(args[1:])

    if args[0] in ("summarize", "summary"):
        return _cmd_summarize(args[1:])

    if args[0] == "setup":
        return _cmd_setup(args[1:])

    if args[0] == "platform":
        return _cmd_platform(args[1:])

    if args[0] == "doctor":
        return _cmd_doctor()

    if args[0] == "personalize":
        from arka.core.personalize import main as personalize_main

        return personalize_main(args[1:])

    if args[0] == "persona":
        from arka.agent.personas.cli import main as persona_main

        return persona_main(args[1:])

    if args[0] == "config":
        from arka.core.config_backup import main as config_main

        return config_main(args[1:])

    if args[0] in ("refetch", "update", "sync"):
        return _cmd_refetch(args[1:])

    if args[0] in ("goal", "loop"):
        return _cmd_goal(args[1:])

    if args[0] in ("reload", "refresh") and has_full_fish_agent():
        code = delegate_subcommand(args[0], args[1:])
        return code if code is not None else 1

    if args[0] == "ai-skill-model":
        return _cmd_ai_skill_model(args[1:])

    if args[0] == "ai-models":
        return _cmd_ai_models()

    if args[0] in ("ai-pref", "ai-status") and has_full_fish_agent():
        code = delegate_fish_function(args[0], args[1:])
        return code if code is not None else 1

    if args[0] in ("ai-pref", "ai-status"):
        print(f"{args[0]} requires fish shell — install fish or use: arka ai-skill-model", file=sys.stderr)
        return 1

    if args[0] in ("youtube", "yt"):
        return _cmd_youtube(args[1:])

    if args[0] == "route":
        if len(args) >= 2 and args[1] in (
            "learn",
            "list",
            "delete",
            "test",
            "teach",
            "show",
            "from-trace",
        ):
            rest = args[2:]
            if args[1] == "teach":
                return run_script("arka_route_learn.py", ["learn", *rest])
            if args[1] == "from-trace":
                return run_script("arka_route_learn.py", ["learn", "--from-trace", *rest])
            return run_script("arka_route_learn.py", [args[1], *rest])
        text = " ".join(args[1:]).strip()
        if not text:
            print("Usage: arka route <request>", file=sys.stderr)
            return 1
        return _cmd_route_preview(text)

    if args[0] == "teach":
        if len(args) >= 2 and args[1] == "route":
            return run_script("arka_route_learn.py", ["learn", *args[2:]])
        print("Usage: arka teach route <phrase> <skill>", file=sys.stderr)
        return 1

    # Subcommands that map to Python scripts
    if args[0] == "chat":
        return run_script("arka_chat.py", args[1:])

    if args[0] == "password":
        from arka.skills import run_password

        return run_password(args[1:])

    if args[0] == "aie":
        return run_script("arka_aie.py", args[1:] or ["status"])

    if args[0] == "google":
        return run_script("arka_google.py", args[1:])

    if args[0] == "gemini":
        return run_script("arka_gemini.py", args[1:])

    if args[0] == "fugu":
        return run_script("arka_fugu.py", args[1:])

    if args[0] == "benchmark":
        return run_script("arka_benchmark.py", args[1:])

    if args[0] == "orchestrate":
        return _cmd_orchestrate(args[1:])

    if args[0] == "kaggle":
        return run_script("arka_kaggle.py", args[1:])

    if args[0] == "mcp":
        return run_script("arka_mcp.py", args[1:])

    if args[0] in ("agent_hub", "agent-hub", "hub"):
        return run_script("arka_agent_hub.py", args[1:])

    if args[0] in ("team", "teams"):
        return run_script("arka_teams.py", ["team", *args[1:]])

    if args[0] == "workflow":
        return run_script("arka_teams.py", ["workflow", *args[1:]])

    if args[0] == "memory":
        return run_script("arka_memory.py", args[1:])

    if args[0] == "remind":
        rest = args[1:]
        if not rest:
            return run_script("arka_remind.py", ["status"])
        return run_script("arka_remind.py", rest)

    if args[0] in ("ascii", "ascii_art"):
        return run_script("arka_ascii_art.py", args[1:])

    if args[0] in ("ask", "web"):
        q = " ".join(args[1:]).strip()
        if not q:
            print("Usage: arka ask <question>", file=sys.stderr)
            return 1
        from arka.skills import run_chat_ask

        return run_chat_ask(q, deep=args[0] == "web" and "--deep" in args)

    # Fish-only service subcommands (listen, start, serve, …)
    fish_subs = {
        "listen",
        "start",
        "stop",
        "status",
        "serve",
        "speak",
        "speak-lang",
        "speak-voice",
        "brief",
        "yt-bulk",
        "queue",
        "wifi",
        "usage",
        "voice",
        "tts-setup",
        "autostart",
        "phone-env",
    }
    if args[0] in fish_subs and has_full_fish_agent():
        code = delegate_subcommand(args[0], args[1:])
        return code if code is not None else 1

    # Natural language: full agent via bundled config.fish when fish is installed
    text = " ".join(args).strip()
    if has_full_fish_agent():
        code = delegate_to_fish(args)
        if code is not None:
            return code

    return _run_portable(text)


def _run_portable(text: str) -> int:
    try:
        from arka.telemetry import mark_error, mark_ok, request_span
    except ImportError:
        request_span = None  # type: ignore[assignment,misc]

    ctx = (
        request_span("arka ask", attributes={"arka.request.text": text[:500]})
        if request_span is not None
        else _cli_null_context()
    )
    with ctx as current:
        r = route(text)
        if r:
            if r.skill == "help":
                code = _cmd_help()
            elif r.kind == "shell":
                from arka.dispatch import run_shell

                print(f"→ {r.skill}")
                code = run_shell(r.skill)
            else:
                print(f"→ {r.skill}")
                code = run_skill(r.skill)
        else:
            from arka.skills import run_chat_ask

            print("→ ask")
            code = run_chat_ask(text)

        if request_span is not None:
            current.set_attribute("arka.exit_code", code)
            if code == 0:
                mark_ok(current)
            else:
                mark_error(current, f"exit {code}")
        return code


def _cli_null_context():
    from contextlib import nullcontext

    return nullcontext()


def _cmd_refetch(extra: list[str]) -> int:
    """Pull latest git + sync src/arka/bundled + optional pip reinstall."""
    pull = "--no-pull" not in extra
    do_install = "--install" in extra or "-i" in extra

    root = checkout_root()
    if root is None:
        print("Not inside an Arka git clone.", file=sys.stderr)
        print("Use: git clone https://github.com/Sumit884-byte/arka && cd arka && arka refetch --install", file=sys.stderr)
        return 1

    if pull and (root / ".git").is_dir():
        print("→ git pull")
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=root)
        if r.returncode != 0:
            print("git pull failed (fix conflicts or use: arka refetch --no-pull)", file=sys.stderr)
            return r.returncode

    sync = root / "scripts" / "sync_bundled.py"
    if sync.is_file():
        print("→ sync bundled scripts")
        r = subprocess.run([sys.executable, str(sync)], cwd=root)
        if r.returncode != 0:
            return r.returncode
    else:
        print(f"Missing {sync}", file=sys.stderr)
        return 1

    if do_install:
        print("→ pip install -e '.[chat]'")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", f"{root}[chat]"],
            cwd=root,
        )
        if r.returncode != 0:
            return r.returncode

    ensure_layout()
    print(f"✓ Refetch complete — bundle: {bundled_dir()}")
    print("  arka doctor")
    return 0


def _resolve_download_url(text: str) -> str | None:
    """Turn user input into a URL. Bare YouTube IDs avoid zsh ? glob issues."""
    text = (text or "").strip()
    url_match = re.search(r"https?://[^\s]+", text)
    if url_match:
        return url_match.group(0)

    token = text.split()[0] if text.split() else ""
    if re.fullmatch(r"PL[\w-]+", token, re.I):
        return f"https://www.youtube.com/playlist?list={token}"

    pl_match = re.search(r"(?i)\bplaylist\s+(PL[\w-]+)", text)
    if pl_match:
        return f"https://www.youtube.com/playlist?list={pl_match.group(1)}"

    if re.fullmatch(r"[\w-]{11}", token) and not token.upper().startswith("PL"):
        return f"https://www.youtube.com/watch?v={token}"

    channel_match = re.search(r"@[\w.-]+", text)
    if channel_match:
        return f"https://www.youtube.com/{channel_match.group(0)}"

    return None


def _split_download_argv(rest: list[str]) -> tuple[list[str], list[str]]:
    """Split positional target tokens from passthrough flags."""
    flags: list[str] = []
    positional: list[str] = []
    flag_with_value = {"--start", "--end", "--range", "--limit", "--quality", "-q"}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in ("--audio", "--wait", "--channel"):
            flags.append(tok)
            i += 1
        elif tok in flag_with_value and i + 1 < len(rest):
            flags.extend([tok, rest[i + 1]])
            i += 2
        elif tok.startswith("-"):
            flags.append(tok)
            i += 1
        else:
            positional.append(tok)
            i += 1
    return positional, flags


def _cmd_download(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka download <target> [options]\n"
            "       arka download this <target> [options]\n"
            "\n"
            "YouTube playlist  → bulk download (yt-dlp)\n"
            "YouTube video     → single download\n"
            "Other URL         → curl to current directory\n"
            "\n"
            "Playlist slice (1-based indices, inclusive):\n"
            "  arka download PLxxx --range 6-9\n"
            "  arka download PLxxx --start 6 --end 9\n"
            "\n"
            "No shell setup needed — use a playlist ID (no ? in the command):\n"
            "  arka download PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige\n"
            "  arka download dQw4w9WgXcQ\n"
            "\n"
            "Full URLs: quote them in zsh (only when the URL contains ? or &):\n"
            "  arka download 'https://youtube.com/playlist?list=PLxxx'"
        )
        return 0 if rest and rest[0] in ("-h", "--help", "help") else 1

    positional, passthrough = _split_download_argv(rest)
    text = " ".join(positional).strip()
    text = re.sub(r"^(this|the)\s+", "", text, flags=re.I).strip()
    url = _resolve_download_url(text)
    if not url:
        print("No download target found. Usage: arka download <url-or-id>", file=sys.stderr)
        print("  Example: arka download PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige", file=sys.stderr)
        return 1

    flags: list[str] = list(passthrough)
    if re.search(r"(?i)\b(audio|mp3)\b", text) and "--audio" not in flags:
        flags.append("--audio")

    if re.search(r"(?i)(playlist\?list=|/playlist)", url):
        return run_script("arka_youtube_bulk.py", ["download", url, "--wait", *flags])

    if re.search(r"(?i)(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", url):
        return run_script("arka_youtube.py", ["download", url, *flags])

    if re.search(r"(?i)youtube\.com/@", url):
        return run_script(
            "arka_youtube_bulk.py", ["download", url, "--wait", "--channel", *flags]
        )

    if has_full_fish_agent():
        code = delegate_to_fish(["download_file", url])
        if code is not None:
            return code

    return _curl_download(url)


def _curl_download(url: str) -> int:
    from urllib.parse import unquote, urlparse

    name = unquote(urlparse(url).path.rsplit("/", 1)[-1] or "download.bin")
    if "?" in name:
        name = name.split("?", 1)[0]
    print(f"Downloading → {name}")
    proc = subprocess.run(
        ["curl", "-fL", "--progress-bar", "-o", name, url],
        check=False,
    )
    return proc.returncode


def _is_email_summarize_request(rest: list[str]) -> bool:
    text = " ".join(rest).lower()
    return bool(re.search(r"\b(emails?|gmail|gmails|mail|inbox)\b", text))


def _cmd_gmail_summarize_nl(rest: list[str]) -> int:
    from arka.integrations.google_workspace import build_gmail_argv_from_nl

    text = " ".join(rest).strip()
    if not text:
        print("Usage: arka summarize unread emails [within N days]", file=sys.stderr)
        return 1
    try:
        return run_script("arka_google.py", build_gmail_argv_from_nl(text, summarize=True))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _cmd_summarize(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka summarize youtube <video-id|PLid|url>\n"
            "       arka summarize playlist --url <url> [--limit N]\n"
            "       arka summarize folder <directory>\n"
            "       arka summarize unread emails [within N days]\n"
            "       arka summarize all emails within 2 days\n"
            "\n"
            "YouTube: tries captions first. If missing, asks to download audio\n"
            "         and transcribe locally (unless --yes-transcribe / --no-transcribe).\n"
            "\n"
            "Gmail: requires arka google login. Uses calendar-day windows by default.\n"
            "\n"
            "Examples:\n"
            "  arka summarize youtube dQw4w9WgXcQ\n"
            "  arka summarize unread emails within 2 days\n"
            "  arka summarize all emails from last 3 days\n"
            "  arka google gmail --summarize --unread --days 2 --all"
        )
        return 0 if rest and rest[0] in ("-h", "--help", "help") else 1

    if _is_email_summarize_request(rest):
        return _cmd_gmail_summarize_nl(rest)

    head = rest[0].lower()
    if head in ("youtube", "yt", "video"):
        tail = rest[1:]
        if not tail:
            print("Usage: arka summarize youtube <video-id|PLid>", file=sys.stderr)
            return 1
        text = " ".join(tail).strip()
        text = re.sub(r"^(this|the)\s+", "", text, flags=re.I).strip()
        url = _resolve_download_url(text)
        if not url:
            print("Could not parse YouTube target.", file=sys.stderr)
            return 1
        argv = ["playlist", "--url", url]
        for flag in ("--limit", "-q", "--question", "--yes-transcribe", "--no-transcribe"):
            if flag in tail:
                idx = tail.index(flag)
                argv.append(flag)
                if flag in ("--limit", "-q", "--question") and idx + 1 < len(tail):
                    argv.append(tail[idx + 1])
        return run_script("arka_batch_summarize.py", argv)

    if head in ("playlist", "pl"):
        return run_script("arka_batch_summarize.py", ["playlist", *rest[1:]])

    if head in ("folder", "dir", "directory"):
        if len(rest) < 2:
            print("Usage: arka summarize folder <path>", file=sys.stderr)
            return 1
        return run_script("arka_batch_summarize.py", ["folder", *rest[1:]])

    if has_full_fish_agent():
        code = delegate_to_fish(["summarize", *rest])
        if code is not None:
            return code

    return run_script("arka_batch_summarize.py", ["folder", *rest])


def _cmd_shell_init(rest: list[str]) -> int:
    shell = rest[0] if rest else "zsh"
    if shell != "zsh":
        print(f"Unsupported shell: {shell}  (try: arka shell-init zsh)", file=sys.stderr)
        return 1
    print(
        """# Add to ~/.zshrc (Arka + zsh-safe URLs):
arka() {
  noglob command arka "$@"
}
goal() {
  command arka goal "$@"
}
loop() {
  command arka goal "$@"
}"""
    )
    return 0


def _cmd_goal(rest: list[str]) -> int:
    if rest and rest[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka goal [options] <goal description>\n"
            "       arka loop <goal>          (alias)\n"
            "\n"
            "Autonomous multi-step agent (works from zsh/bash — no fish required).\n"
            "\n"
            "Options:\n"
            "  -b, --butterfish   Butterfish Goal Mode (asks to install via brew/go)\n"
            "  -y, --yes          Auto-approve risky actions and installs\n"
            "  -n, --max N        Max steps (default 25)\n"
            "  -v, --verify       LLM verification when goal completes\n"
            "\n"
            "Examples:\n"
            "  arka goal debug my nginx setup\n"
            "  arka goal -b -y set up venv and run pytest\n"
            "  arka loop install requests and verify import\n"
            "\n"
            "Fish shell also has a native goal function (same behavior)."
        )
        return 0

    if has_full_fish_agent() and "--python" not in rest:
        code = delegate_fish_function("goal", rest)
        if code is not None:
            return code

    from arka.agent.goal import main as goal_main

    try:
        from arka.telemetry import mark_error, mark_ok, request_span
    except ImportError:
        request_span = None  # type: ignore[assignment,misc]

    goal_text = " ".join(rest).strip()
    ctx = (
        request_span("arka goal", attributes={"arka.request.text": goal_text[:500]})
        if request_span is not None
        else _cli_null_context()
    )
    with ctx as current:
        code = goal_main(argv=["goal", *rest])
        if request_span is not None:
            current.set_attribute("arka.exit_code", code)
            if code == 0:
                mark_ok(current)
            else:
                mark_error(current, f"exit {code}")
        return code


def _cmd_youtube(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka youtube research <query> [--limit N] [--focus Q] [--index]\n"
            "       arka research youtube <query>   (alias)\n"
            "Default: 2 videos. Example: arka youtube research react"
        )
        return 0 if rest and rest[0] in ("-h", "--help", "help") else 1

    sub = rest[0].lower()
    if sub in ("research", "yt-research", "search"):
        tail = rest[1:]
        if not tail:
            print("Usage: arka youtube research <query> [--limit N]", file=sys.stderr)
            return 1
        argv = ["search", *tail]
        if "--index" not in tail:
            argv.append("--index")
        return run_script("arka_youtube_research.py", argv)

    if has_full_fish_agent():
        code = delegate_subcommand("youtube", rest)
        if code is not None:
            return code

    print(f"Unknown youtube subcommand: {rest[0]}  (try: research)", file=sys.stderr)
    return 1


def _cmd_orchestrate(rest: list[str]) -> int:
    import os

    benchmark = "--benchmark" in rest
    filtered = [a for a in rest if a != "--benchmark"]
    if benchmark:
        os.environ["ARKA_BENCHMARK_ORCHESTRATE"] = "1"
    text = " ".join(filtered).strip()
    if not text:
        print("Usage: arka orchestrate [--benchmark] <request>", file=sys.stderr)
        print("  --benchmark  Prefer providers/models from benchmark-results.json", file=sys.stderr)
        return 1
    if benchmark:
        from arka.llm.benchmarks import benchmark_chain_entries, load_results

        if not (load_results().get("suites") or {}):
            print(
                "No benchmark results yet — run: arka benchmark run --dry-run (or live run)",
                file=sys.stderr,
            )
            return 1
        task = "default"
        winners = benchmark_chain_entries(task)
        if winners:
            label = ", ".join(f"{p}/{m}" for p, m in winners[:3])
            print(f"benchmark route ({task}): {label}")
    if has_full_fish_agent():
        code = delegate_to_fish(filtered)
        if code is not None:
            return code
    return _run_portable(text)


def _cmd_route_preview(text: str) -> int:
    r = route(text)
    if r:
        print(f"skill: {r.skill}")
        print(f"kind: {r.kind}")
        print(f"source: {r.source}")
        return 0
    print("skill: (none — would fall back to LLM chat)")
    if skill_mode() == "portable":
        print(f"hint: install fish for 70+ skills — {fish_install_hint()}", file=sys.stderr)
    return 0


def _cmd_setup(extra: list[str] | None = None) -> int:
    extra = extra or []
    skip_venv = "--no-venv" in extra or "--layout-only" in extra

    home = ensure_layout()
    from arka.platform_info import ensure_platform_cache
    from arka.setup_runtime import ensure_venv, resolve_venv_python, venv_dir, verify_chat_imports

    profile = ensure_platform_cache()
    print(f"Arka setup ({profile.get('platform', system())})")
    print(f"  Scripts: (package) {home}")
    print(f"  Config:  {config_dir()}")
    print(f"  Cache:   {cache_dir()}")
    print(f"  Env:     {env_file()}")

    if not skip_venv:
        print(f"\n→ Python venv: {venv_dir()}")
        try:
            ensure_venv(install_chat=True)
        except RuntimeError as exc:
            print(f"  ✗ {exc}", file=sys.stderr)
            return 1
        vpy = resolve_venv_python(require_agno=True)
        if not vpy:
            missing = verify_chat_imports(venv_dir() / "bin" / "python3")
            print(f"  ⚠ Missing modules in venv: {', '.join(missing) or 'agno'}", file=sys.stderr)
            print("  Retry: arka setup", file=sys.stderr)
            return 1
        print(f"  ✓ Chat deps installed → {vpy}")
        print("    (agno, ddgs, trafilatura, beautifulsoup4, …)")

    if not env_file().is_file():
        print("  Edit .env and add GEMINI_API_KEY or GROQ_API_KEY")
    if skill_mode() == "portable":
        print(f"\n  For all 70+ skills, install fish: {fish_install_hint()}")
    print("\n✓ Setup complete — try: arka brief   or   arka ask \"what is Python?\"")
    print("  Next: arka personalize wizard — get skill recommendations for your interests")
    return 0


def _cmd_platform(extra: list[str]) -> int:
    sub = extra[0] if extra else "show"
    script = entry_script("arka_platform.py")
    if not script.is_file():
        print(f"Missing {script}", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(script), sub, *extra[1:]]
    return subprocess.run(cmd).returncode


def _cmd_doctor() -> int:
    from arka.platform_info import ensure_platform_cache
    from arka.setup_runtime import resolve_venv_python, venv_dir, verify_chat_imports

    profile = ensure_platform_cache()
    plat = profile.get("platform", system())
    print(f"arka {__version__} — {plat}")
    if profile.get("detected_at"):
        print(f"  Platform cache: {config_dir() / 'platform.json'}")
        print(f"  Detected:       {profile.get('detected_at')}")
    bundled = bundled_dir()
    print(f"  Package bundle: {bundled}")
    print(f"  ARKA_HOME:      {arka_home()}")
    print(f"  Config:         {config_dir()}")
    print(f"  Cache:          {cache_dir()}")
    print(f"  config.fish:    {('ok' if (arka_home() / 'config.fish').is_file() else 'missing — run: python scripts/sync_bundled.py')}")
    vpy = resolve_venv_python(require_agno=False)
    print(f"  venv-arka:      {venv_dir()}{(' → ' + str(vpy) if vpy else ' (missing — run: arka setup)')}")
    if vpy:
        missing = verify_chat_imports(vpy)
        if missing:
            print(f"  chat modules:   missing {', '.join(missing)} — run: arka setup")
        else:
            print("  chat modules:   ok (agno, ddgs, trafilatura, …)")
    mode = skill_mode()
    if mode == "full":
        print(f"  Skills:         full (70+) via {fish_config()}")
    else:
        print("  Skills:         portable Python subset (chat, passwords, weather, calc, …)")
        print(f"  Install fish:   {fish_install_hint()}")
    return 0


def _cmd_ai_models() -> int:
    if has_full_fish_agent():
        code = delegate_fish_function("ai-models", [])
        if code is not None:
            return code
    return run_script("arka_llm.py", ["providers", "--models"])


def _cmd_ai_skill_model(rest: list[str]) -> int:
    script_args = ["skill-models"]
    if not rest:
        script_args.append("list")
    elif rest[0].lower() == "profiles":
        script_args.extend(["list", "--profiles-only"])
    elif rest[0].lower() == "show":
        if len(rest) < 2:
            print("Usage: arka ai-skill-model show <skill|profile>", file=sys.stderr)
            return 1
        script_args.extend(["show", rest[1]])
    elif rest[0].lower() == "clear":
        if len(rest) < 2:
            print("Usage: arka ai-skill-model clear <skill|profile>", file=sys.stderr)
            return 1
        script_args.extend(["clear", rest[1]])
    elif rest[0].lower() == "path":
        script_args.append("path")
    elif len(rest) >= 2:
        script_args.extend(["set", rest[0], rest[1]])
    else:
        print(
            "Usage: arka ai-skill-model [profiles|show <name>|clear <name>|<skill> <model>]",
            file=sys.stderr,
        )
        return 1
    return run_script("arka_llm.py", script_args)


def _cmd_help() -> int:
    print(
        """Arka — cross-platform AI agent

Install:
  pip install arka-agent          # core
  pip install 'arka-agent[chat]'  # web answers, calc, weather
  arka setup                      # config dirs + venv-arka + chat deps (ddgs, agno, …)
  arka platform [detect|show]     # cache OS profile on first run (~/.config/arka/platform.json)
  arka refetch [--install]        # git pull + sync bundled (after clone or on another PC)
  arka reload [--listen] [--dev]  # re-source config in this shell (fish); --listen restarts mic
  arka youtube research <query>   # YouTube search + transcript digest (default 2 videos)
  arka download <id-or-url>       # YouTube playlist ID, video ID, or quoted URL
  arka summarize youtube <id>     # Summarize video/playlist (captions → optional STT)
  arka remind in 30m stretch      # Reminder at time; again when you're back if idle/off

Usage:
  arka <request>                  # natural language (routes to best skill)
  arka ask <question>             # web + AI answer
  arka goal <goal>                # autonomous multi-step agent (zsh/bash/fish)
  arka goal -b <goal>             # Butterfish Goal Mode (install on confirm)
  arka loop <goal>                # alias for arka goal
  arka password save wifi         # generate + store password
  arka password set wifi <secret> # store your own password
  arka password get wifi          # retrieve stored password
  arka google setup               # Google Calendar + Gmail OAuth setup
  arka google login               # sign in via browser URL
  arka google gmail --unread      # list unread mail
  arka google gmail --draft --to you@example.com --about "topic"
  arka google calendar --today    # today's events
  arka gemini <prompt>            # Google Gemini CLI (npm @google/gemini-cli)
  arka gemini status              # check Gemini CLI install
  arka fugu <prompt>              # Sakana Fugu multi-agent orchestrator
  arka fugu ultra <prompt>        # Fugu Ultra (deeper orchestration)
  arka fugu status                # check Sakana API key + provider
  arka benchmark run [--dry-run]  # compare models/providers on sample tasks
  arka benchmark show             # view benchmark rankings by task profile
  arka benchmark apply            # write winners to llm-skill-models.json
  arka orchestrate --benchmark <request>  # route using benchmark winners
  arka chat calc integrate sin(x) # SymPy
  arka ascii "HELLO"              # ASCII banner (figlet / pyfiglet)
  arka ascii --from-image cat.jpg # image → ASCII art
  arka route <request>            # preview routing (no run)
  arka route learn "phrase" "skill"  # teach NL → CLI mapping
  arka route list                 # show learned routes
  arka teach route "phrase" "skill"  # alias for route learn
  arka ai-models                  # list LLM providers and models
  arka ai-skill-model profiles    # per-skill model choices by profile
  arka ai-skill-model web_answer groq/llama-3.3-70b-versatile
  arka doctor                     # install diagnostics

Platforms:
  All platforms   70+ skills when fish is installed (bundled config.fish in pip package)
  Without fish    Portable Python skills (chat, passwords, web, calc, weather, sports)
  Install fish:   macOS brew install fish | Linux apt install fish | Windows scoop install fish

Docs: README.md in ARKA_HOME"""
    )
    return 0
