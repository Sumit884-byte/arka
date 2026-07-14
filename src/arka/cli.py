"""Arka CLI — cross-platform entry point (macOS, Windows, Linux)."""

from __future__ import annotations

import re
import subprocess
import sys

from arka import __version__
from arka.dispatch import run_script, run_skill
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
)
from arka.platform_info import fish_install_hint, has_full_fish_agent, skill_mode, system
from arka.router import route


def main(argv: list[str] | None = None) -> int:
    load_env()
    from arka.core.mode import load_mode

    load_mode()
    args = argv if argv is not None else sys.argv[1:]

    _SKIP_AUTO_REFETCH = frozenset(
        {
            "refetch",
            "update",
            "sync",
            "reload",
            "refresh",
            "shell-init",
            "setup",
            "-h",
            "--help",
            "help",
            "-V",
            "--version",
            "version",
        }
    )
    if args and args[0] not in _SKIP_AUTO_REFETCH:
        try:
            from arka.core.auto_refetch import maybe_auto_refetch

            maybe_auto_refetch(quiet=True)
        except ImportError:
            pass

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

    if args[0] == "mode":
        from arka.core.mode import main as mode_main

        return mode_main(["mode", *args[1:]])

    if args[0] == "provider":
        from arka.llm.provider_select import main as provider_main

        return provider_main(args[1:] or None)

    if args[0] == "code":
        from arka.core.code_project import main as code_main

        return code_main(["code", *args[1:]])

    if args[0] == "self":
        from arka.agent.self_improve import main as self_main

        return self_main(args[1:])

    if args[0] == "repo":
        from arka.agent.repo_context import main as repo_context_main

        return repo_context_main(["repo", *args[1:]])

    if args[0] == "ci":
        from arka.agent.dev_tools import main as dev_tools_main

        return dev_tools_main(["ci", *args[1:]])

    if args[0] in ("review", "route-audit", "route_audit", "skill"):
        from arka.agent.dev_tools import main as dev_tools_main

        if args[0] == "route-audit" or args[0] == "route_audit":
            return dev_tools_main(["route-audit", *args[1:]])
        return dev_tools_main([args[0], *args[1:]])

    if args[0] in ("design_from_screenshot", "design-screenshot", "designshot"):
        from arka.agent.design_from_screenshot import main as design_main

        return design_main([args[0].replace("-", "_"), *args[1:]])

    if args[0] in ("urlkit", "url-kit"):
        from arka.core.urlkit import main as urlkit_main

        return urlkit_main(args[1:])

    if args[0] in ("lint_project", "lint-project", "lint_all"):
        from arka.agent.lint_project import main as lint_main

        return lint_main([args[0].replace("-", "_"), *args[1:]])

    if args[0] == "llm":
        from arka.agent.repo_context import main as repo_context_main

        return repo_context_main(["llm", *args[1:]])

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
        return _cmd_ai_models(args[1:])

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

    if args[0] in ("harvard-ark", "harvard_ark", "harvardark"):
        return run_script("arka_harvard_ark.py", args[1:])

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

    if args[0] == "flow":
        return run_script("arka_flow.py", args[1:])

    if args[0] in ("fact_check", "fact-check", "factcheck", "factchecker"):
        return run_script("arka_fact_check.py", args[1:])

    if args[0] in ("quiz", "quiz_practice", "quiz-practice"):
        return run_script("arka_quiz_practice.py", args[1:])

    if args[0] == "council":
        return run_script("arka_council.py", args[1:])

    if args[0] == "convert":
        return _run_convert(args[1:])

    if args[0] in ("currency_convert", "currency"):
        return run_script("arka_currency.py", ["convert", *args[1:]])

    if args[0] in ("timezone_convert", "tz_convert", "timezone"):
        return run_script("arka_timezone_convert.py", ["convert", *args[1:]])

    if args[0] in ("open_url", "open", "browse"):
        return run_script("arka_open_url.py", args)

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
    mode_hit = _try_mode_nl(text)
    if mode_hit is not None:
        return mode_hit
    provider_hit = _try_provider_nl(text)
    if provider_hit is not None:
        return provider_hit
    code_hit = _try_code_nl(text)
    if code_hit is not None:
        return code_hit
    # Plan/ask modes use the Python router so structured plans and read-only
    # guards apply; fish delegation would skip print_plan output.
    from arka.core.mode import get_mode

    if get_mode() in ("plan", "ask"):
        return _run_portable(text)
    if has_full_fish_agent():
        code = delegate_to_fish(args)
        if code is not None:
            return code

    return _run_portable(text)


def _run_convert(rest: list[str]) -> int:
    """Route ambiguous `convert` to timezone or currency based on NL."""
    from arka.routing.symbolic import is_timezone_convert_request

    text = " ".join(rest).strip()
    if text and is_timezone_convert_request(text):
        return run_script("arka_timezone_convert.py", ["convert", *rest])
    return run_script("arka_currency.py", ["convert", *rest])


def _try_code_nl(text: str) -> int | None:
    from arka.core.code_project import main as code_main, route_code_nl

    hit = route_code_nl(text)
    if not hit:
        return None
    parts = hit.split(maxsplit=1)
    rest = parts[1].split() if len(parts) > 1 else []
    if parts[0] == "code":
        return code_main(["code", *rest])
    return None


def _try_provider_nl(text: str) -> int | None:
    from arka.llm.provider_select import is_provider_select_query, main as provider_main, nl_to_argv

    if not is_provider_select_query(text):
        return None
    argv = nl_to_argv(text)
    if not argv:
        from arka.llm.provider_select import cmd_show
        import argparse

        return cmd_show(argparse.Namespace())
    return provider_main(argv)


def _try_mode_nl(text: str) -> int | None:
    from arka.core.mode import main as mode_main, route_mode_nl

    hit = route_mode_nl(text)
    if not hit:
        return None
    parts = hit.split()
    if len(parts) == 1:
        from arka.core.mode import cmd_show

        return cmd_show()
    return mode_main(["mode", *parts[1:]])


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
        code = _execute_request(text)
        if request_span is not None:
            current.set_attribute("arka.exit_code", code)
            if code == 0:
                mark_ok(current)
            else:
                mark_error(current, f"exit {code}")
        return code


def _execute_request(text: str) -> int:
    from arka.core.mode import (
        ask_mode_skill,
        get_mode,
        mode_allows_execution,
        print_debug_route,
        print_plan,
        try_multitask_delegate,
    )
    from arka.dispatch import run_shell

    r = route(text)
    if get_mode() == "debug":
        print_debug_route(text, r)

    multitask_code = try_multitask_delegate(text, r)
    if multitask_code is not None:
        return multitask_code

    if get_mode() == "plan":
        print_plan(text, r)
        return 0

    if r:
        if r.skill.split(maxsplit=1)[0] == "mode":
            return _try_mode_nl(r.skill) or 0
        if r.skill.split(maxsplit=1)[0] == "code":
            return _try_code_nl(r.skill) or 0
        if r.skill == "help":
            return _cmd_help()
        skill_line = r.skill
        if get_mode() == "ask":
            skill_line = ask_mode_skill(r.skill, text)
        allowed, reason = mode_allows_execution(skill_line, kind=r.kind)
        if not allowed:
            if get_mode() == "ask":
                from arka.skills import run_chat_ask

                print(f"→ ask ({reason})")
                return run_chat_ask(text)
            print(reason, file=sys.stderr)
            return 1
        if r.kind == "shell":
            print(f"→ {r.skill}")
            return run_shell(r.skill)
        print(f"→ {skill_line}")
        return run_skill(skill_line)

    from arka.skills import run_chat_ask

    print("→ ask")
    return run_chat_ask(text)


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
    try:
        from arka.agent.repo_context import sync_index

        idx = sync_index(root, quiet=True)
        if idx.get("ok") and not idx.get("skipped"):
            print(f"→ llm.txt changelog: {idx.get('changed', 0)} file(s)")
    except ImportError:
        pass
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
        from arka.llm.skill_profiles import skill_task_profile
        from arka.router import route

        routed = route(text)
        task = skill_task_profile(routed.skill.split(maxsplit=1)[0] if routed else "")
        if task == "default":
            task = "chat"

        if not (load_results().get("suites") or {}):
            print(
                "No benchmark results yet — run: arka benchmark run --dry-run (or live run)",
                file=sys.stderr,
            )
            return 1
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
    from arka.core.mode import get_mode, print_debug_route

    r = route(text)
    if get_mode() == "debug":
        print_debug_route(text, r)
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

    from arka.integrations.context7_mcp import setup_context7
    from arka.integrations.mcp_server import ensure_arka_self_in_config

    print("\n→ Context7 (library docs MCP)")
    skip_context7 = "--no-context7" in extra
    setup_context7(skip_cli=skip_context7)
    if ensure_arka_self_in_config():
        print("  ✓ Arka self-MCP added to ~/.config/arka/mcp.json")

    try:
        from arka.agent.repo_context import sync_index

        idx = sync_index(quiet=True)
        if idx.get("ok") and not idx.get("skipped"):
            print(f"\n→ llm.txt changelog: {idx.get('changed', 0)} file(s) indexed")
    except ImportError:
        pass

    if not env_file().is_file():
        print("  Edit .env and add GEMINI_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY")
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
    from arka.integrations.context7_mcp import format_doctor_lines
    from arka.llm.fallback import llm_doctor_lines

    for line in llm_doctor_lines():
        print(line)
    for line in format_doctor_lines():
        print(line)
    return 0


def _cmd_ai_models(rest: list[str] | None = None) -> int:
    script_args = ["providers", "--models"]
    if rest and "--all" in rest:
        script_args.append("--all")
    if has_full_fish_agent() and not rest:
        code = delegate_fish_function("ai-models", [])
        if code is not None:
            return code
    return run_script("arka_llm.py", script_args)


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
  arka setup                      # config dirs + venv-arka + chat deps + Context7 MCP
  arka platform [detect|show]     # cache OS profile on first run (~/.config/arka/platform.json)
  arka refetch [--install]        # git pull + sync bundled (after clone or on another PC)
  arka repo index                 # append git file deltas to llm.txt changelog
  arka llm sync                   # alias for arka repo index
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
  arka harvard-ark install        # Harvard ARK KG CLI (PrimeKG — external, not Arka itself)
  arka harvard-ark chat           # interactive biomedical knowledge graph chat
  arka harvard-ark list           # list PrimeKG / AfriMedKG / OptimusKG graphs
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
  arka council "should I learn Rust?"  # multi-persona deliberation chamber
  arka council list               # past council questions
  arka mode [ask|plan|agent|debug|multitask]  # operation mode (default: agent)
  arka code init <folder>         # initialize scoped coding workspace
  arka code write <goal>          # write code only inside project folder
  arka code status                # show active code project
  arka self improve [target] [--apply]  # analyze + plan; --apply runs goal agent
  arka route <request>            # preview routing (no run)
  arka route learn "phrase" "skill"  # teach NL → CLI mapping
  arka route list                 # show learned routes
  arka teach route "phrase" "skill"  # alias for route learn
  arka ai-models                  # list LLM providers and models
  arka provider list              # providers with keys configured
  arka provider set openrouter    # set preferred provider + autodetect model
  arka provider models            # list live models for preferred provider
  arka provider show              # show current preference
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
