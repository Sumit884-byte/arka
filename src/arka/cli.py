"""Arka CLI — cross-platform entry point (macOS, Windows, Linux)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from arka import __version__
from arka.dispatch import run_fish_skill, run_script, run_skill
from arka.env import load_env
from arka.fish_bridge import delegate_subcommand, delegate_to_fish
from arka.paths import (
    arka_home,
    bundled_dir,
    cache_dir,
    checkout_root,
    config_dir,
    ensure_layout,
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
        return _cmd_setup()

    if args[0] == "platform":
        return _cmd_platform(args[1:])

    if args[0] == "doctor":
        return _cmd_doctor()

    if args[0] in ("refetch", "update", "sync"):
        return _cmd_refetch(args[1:])

    if args[0] in ("reload", "refresh") and has_full_fish_agent():
        code = delegate_subcommand(args[0], args[1:])
        return code if code is not None else 1

    if args[0] in ("youtube", "yt"):
        return _cmd_youtube(args[1:])

    if args[0] == "route":
        text = " ".join(args[1:]).strip()
        if not text:
            print("Usage: arka route <request>", file=sys.stderr)
            return 1
        return _cmd_route_preview(text)

    # Subcommands that map to Python scripts
    if args[0] == "chat":
        return run_script("arka_chat.py", args[1:])

    if args[0] == "password":
        from arka.skills import run_password

        return run_password(args[1:])

    if args[0] == "aie":
        return run_script("arka_aie.py", args[1:] or ["status"])

    if args[0] == "remind":
        return run_script("arka_remind.py", args[1:])

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
    r = route(text)
    if r:
        if r.skill == "help":
            return _cmd_help()
        print(f"→ {r.skill}")
        if r.kind == "shell":
            from arka.dispatch import run_shell

            return run_shell(r.skill)
        return run_skill(r.skill)

    from arka.skills import run_chat_ask

    print("→ ask")
    return run_chat_ask(text)


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


def _cmd_summarize(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka summarize youtube <video-id|PLid|url>\n"
            "       arka summarize playlist --url <url> [--limit N]\n"
            "       arka summarize folder <directory>\n"
            "\n"
            "YouTube: tries captions first. If missing, asks to download audio\n"
            "         and transcribe locally (unless --yes-transcribe / --no-transcribe).\n"
            "\n"
            "Examples:\n"
            "  arka summarize youtube dQw4w9WgXcQ\n"
            "  arka summarize youtube PLu71SKxNbfoDqgPchmvIsL4hTnJIrtige --limit 5\n"
            "  arka summarize youtube PLxxx --yes-transcribe"
        )
        return 0 if rest and rest[0] in ("-h", "--help", "help") else 1

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
        """# Add to ~/.zshrc so URLs with ? are not glob-expanded:
arka() {
  noglob command arka "$@"
}"""
    )
    return 0


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


def _cmd_setup() -> int:
    home = ensure_layout()
    from arka.platform_info import ensure_platform_cache

    profile = ensure_platform_cache()
    print(f"Arka setup complete ({profile.get('platform', system())})")
    print(f"  Scripts: (package) {home}")
    print(f"  Config:  {config_dir()}")
    print(f"  Cache:   {cache_dir()}")
    print(f"  Env:     {env_file()}")
    if not env_file().is_file():
        print("  Edit .env and add GEMINI_API_KEY or GROQ_API_KEY")
    if skill_mode() == "portable":
        print(f"\n  For all 70+ skills, install fish: {fish_install_hint()}")
    print("\nNext: pip install 'arka-agent[chat]'  then  arka ask \"what is Python?\"")
    return 0


def _cmd_platform(extra: list[str]) -> int:
    sub = extra[0] if extra else "show"
    script = arka_home() / "arka_platform.py"
    if not script.is_file():
        print(f"Missing {script}", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(script), sub, *extra[1:]]
    return subprocess.run(cmd).returncode


def _cmd_doctor() -> int:
    from arka.platform_info import ensure_platform_cache

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
    print(f"  arka_chat.py:   {('ok' if (arka_home() / 'arka_chat.py').is_file() else 'missing — run: python scripts/sync_bundled.py')}")
    mode = skill_mode()
    if mode == "full":
        print(f"  Skills:         full (70+) via {fish_config()}")
    else:
        print("  Skills:         portable Python subset (chat, passwords, weather, calc, …)")
        print(f"  Install fish:   {fish_install_hint()}")
    return 0


def _cmd_help() -> int:
    print(
        """Arka — cross-platform AI agent

Install:
  pip install arka-agent          # core
  pip install 'arka-agent[chat]'  # web answers, calc, weather
  arka setup                      # create ~/.config/arka + .env (scripts live in package)
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
  arka password save wifi         # generate + store password
  arka password set wifi <secret> # store your own password
  arka password get wifi          # retrieve stored password
  arka chat calc integrate sin(x) # SymPy
  arka route <request>            # preview routing (no run)
  arka doctor                     # install diagnostics

Platforms:
  All platforms   70+ skills when fish is installed (bundled config.fish in pip package)
  Without fish    Portable Python skills (chat, passwords, web, calc, weather, sports)
  Install fish:   macOS brew install fish | Linux apt install fish | Windows scoop install fish

Docs: README.md in ARKA_HOME"""
    )
    return 0
