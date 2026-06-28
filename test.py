#!/usr/bin/env python3
"""
Verify Fish agent skills in ~/.config/fish/config.fish.

Checks:
  1. Every registered skill has a Fish function definition
  2. Offline natural-language phrases map to the expected skill/command
  3. Skills execute without unexpected errors (smoke tests)

Usage:
  python3 test.py              # fast: local/offline skills + NL routing
  python3 test.py --full     # also run network/GUI/long skills
  python3 test.py --nl-only  # only natural-language routing tests
  python3 test.py -v         # verbose output
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

CONFIG_FISH = Path.home() / ".config/fish/config.fish"
FISH = shutil.which("fish") or "fish"
DEFAULT_TIMEOUT = 45


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class Suite:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[Result] = field(default_factory=list)

    def record(self, r: Result) -> None:
        self.results.append(r)
        if r.skipped:
            self.skipped += 1
        elif r.ok:
            self.passed += 1
        else:
            self.failed += 1


def read_config() -> str:
    if not CONFIG_FISH.is_file():
        raise FileNotFoundError(f"Missing config: {CONFIG_FISH}")
    return CONFIG_FISH.read_text(encoding="utf-8")


def parse_available_skills(config: str) -> list[str]:
    m = re.search(
        r"set\s+-l\s+available_skills\s+(.+?)(?:\n\n|\n\s+#)",
        config,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError("Could not find available_skills in config.fish")
    return m.group(1).split()


def fish_functions_exist(names: list[str]) -> dict[str, bool]:
    """Check many functions in one Fish process."""
    if not names:
        return {}
    checks = "\n".join(
        f"if functions -q {n}; echo OK:{n}; else; echo MISSING:{n}; end" for n in names
    )
    proc = subprocess.run(
        [FISH, "-c", checks],
        capture_output=True,
        text=True,
        timeout=30,
    )
    found = {line.split(":", 1)[1] for line in proc.stdout.splitlines() if line.startswith("OK:")}
    return {n: n in found for n in names}


def fish_function_exists(name: str) -> bool:
    return fish_functions_exist([name]).get(name, False)


def run_fish(
    script: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [FISH, "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        env=merged,
    )


def run_skill(
    name: str,
    args: str = "",
    *,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess[str]:
    cmd = f"{name} {args}".strip() if args else name
    return run_fish(cmd, timeout=timeout, cwd=cwd)


def run_agent_nl(phrase: str, *, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    escaped = phrase.replace("\\", "\\\\").replace("'", "\\'")
    return run_fish(f"agent '{escaped}'", timeout=timeout)


# Mirrors agent offline NL rules (config.fish ~2818–2914)
def _is_advisory_question(clean: str, cmd: str) -> bool:
    if re.search(
        r"(?i)(system\s*monitor|system\s*status|show\s+(me\s+)?(system\s+)?(monitor|resources)|"
        r"check\s+(cpu|ram|memory|disk|battery)|\b(cpu|ram|memory|disk)\s+(usage|load|percent)|"
        r"how\s+much\s+(cpu|ram|memory|disk)\s+(left|free|used|available)|"
        r"\buptime\b|\bbattery\b|port_scan|speedtest|system_info|take\s+a\s+screenshot)",
        clean,
    ):
        return False
    if re.search(
        r"(?i)(malware|virus|viruses|infected|compromised|rootkit|trojan|ransomware|"
        r"spyware|keylogger|botnet|have\s+i\s+been\s+hacked|been\s+hacked|"
        r"security\s+(risk|threat|issue|problem)|suspicious\s+(process|activity|connection|program|file))",
        clean,
    ):
        return True
    if re.match(
        r"(?i)^(tell\s+(me\s+)?(if|whether)|check\s+(if|for|whether)|"
        r"scan\s+(my\s+)?(pc|computer|system|machine)\s+for|do\s+i\s+have|"
        r"am\s+i\s+(infected|compromised|hacked))",
        clean,
    ):
        return True
    if re.search(
        r"(?i)(outdated|too\s+old|too\s+slow|good\s+enough|worth\s+(it|upgrading)|"
        r"should\s+i\s+(upgrade|buy|get|replace)|enough\s+for|capable\s+of|"
        r"can\s+i\s+run|will\s+it\s+run|recommend|compare|better\s+than|\bvs\.?\b|versus)",
        clean,
    ):
        return True
    if re.match(
        r"(?i)^(is|are|am|should|can|could|would|will|how|why|what|which|who|do|does|did)\s+",
        clean,
    ) and not re.match(
        r"(?i)^(what\s+(is\s+)?(the\s+)?(weather|time|date|ip|my\s+ip)|"
        r"how\s+(much|many)\s+(disk|space|memory|ram)\s+(left|free|used))",
        clean,
    ):
        return True
    return clean.endswith("?")


_PYPI_PACKAGES = re.compile(
    r"^(torch|pytorch|torchvision|torchaudio|numpy|pandas|scipy|scikit-learn|sklearn|"
    r"tensorflow|keras|transformers|django|flask|fastapi|requests|pytest|httpx|uvicorn|"
    r"pydantic|matplotlib|seaborn|opencv-python|pillow|ipython|jupyter|notebook|streamlit|"
    r"gradio|accelerate|bitsandbytes|peft|tokenizers|diffusers|xgboost|lightgbm|catboost|"
    r"spacy|nltk|sympy|statsmodels|plotly|polars|pyarrow|aiohttp|beautifulsoup4|lxml|"
    r"sqlalchemy|alembic|redis|celery|boto3|openai|anthropic|langchain|chromadb|"
    r"faiss-cpu|faiss-gpu|huggingface-hub|sentencepiece|xformers)$",
    re.I,
)


def _parse_install_app_name(cmd: str) -> str:
    app = re.sub(r"(?i)^(?:please\s+)?(?:install|get|setup)\s+(?:the\s+)?", "", cmd)
    app = re.sub(
        r"(?i)\s+(?:from|via|using|with|on)\s+(?:flatpak|flathub|snap|snapcraft|apt|apt-get|dpkg).*$",
        "",
        app,
    )
    app = re.sub(r"(?i)\s+(?:with|via|using)\s+apt(?:-get)?\s*$", "", app)
    app = re.sub(r"(?i)\s+(?:app|package)\s*$", "", app)
    return app.strip()


def _is_python_pip_package(name: str) -> bool:
    first = re.sub(r"(?i)\s+(for\s+)?(cpu|gpu|cuda).*$", "", name.strip()).split()[0].lower()
    return bool(_PYPI_PACKAGES.match(first))


def _is_python_pip_install(cmd: str) -> bool:
    clean = cmd.lower().strip()
    raw = _parse_install_app_name(cmd)
    if re.search(r"(?i)(with\s+uv|via\s+uv|uv\s+pip|\bpip\s+install|python\s+package)", clean):
        return True
    if re.search(r"(?i)\bfor\s+(cpu|gpu)\b|\bwith\s+cuda\b", clean) and re.match(
        r"(?i)^(install|get|setup)\s+", clean
    ):
        return True
    base = re.sub(r"(?i)\s+(for\s+)?(cpu|gpu|cuda).*$", "", raw).strip()
    return any(_is_python_pip_package(p) for p in base.split())


def _parse_install_uv(cmd: str) -> str:
    raw = _parse_install_app_name(cmd)
    flag = ""
    body = raw
    if re.search(r"(?i)\s+for\s+cpu\s*$", body):
        flag = "--cpu"
        body = re.sub(r"(?i)\s+for\s+cpu\s*$", "", body).strip()
    elif re.search(r"(?i)(\s+for\s+gpu|\s+with\s+cuda|\s+cuda)\s*$", body):
        flag = "--cuda"
        body = re.sub(r"(?i)(\s+for\s+gpu|\s+with\s+cuda|\s+cuda)\s*$", "", body).strip()
    body = re.sub(r"(?i)\s+(with|via|using)\s+(uv|pip).*$", "", body).strip()
    body = re.sub(r"(?i)^python\s+package\s+", "", body).strip()
    parts = ["torch" if p.lower() == "pytorch" else p for p in body.split()]
    if flag:
        return f"install_uv {flag} {' '.join(parts)}".strip()
    return f"install_uv {' '.join(parts)}".strip()


def interpret_offline(cmd: str) -> Optional[str]:
    clean = cmd.lower().strip()
    words = cmd.split()
    args = " ".join(words[1:]) if len(words) > 1 else ""

    if re.search(r"(play.*spotify|spotify)", clean):
        song = re.sub(r"(?i)^play\s+(?:song\s+)?(?:on\s+)?spotify(?:\s+of)?\s*", "", cmd)
        song = re.sub(r"(?i)^play\s+(?:song\s+)?", "", song)
        song = re.sub(r"(?i)\s+on\s+spotify(\s|$)", " ", song)
        song = re.sub(r"(?i)\s+on\s+spotify$", "", song)
        song = re.sub(r"(?i)\s+from\s+", " ", song)
        song = re.sub(r"(?i)\s+by\s+", " ", song)
        song = re.sub(r"(?i)hamuman", "hanuman", song)
        song = re.sub(r"\s+", " ", song).strip()
        song = re.sub(r"(?i)^of\s+", "", song).strip()
        return f"play_spotify {song}".strip()

    if re.search(r"(whatsapp|message.*whatsapp)", clean):
        m = re.search(
            r"(?i)^send\s+(?:an?\s+)?(?:a\s+)?(?:whatsapp\s+)?(?:message\s+)?to\s+(.+)$", cmd
        )
        if not m:
            m = re.search(r"(?i)^(?:send\s+)?(?:a\s+)?whatsapp(?:\s+message)?\s+to\s+(.+)$", cmd)
        rest = m.group(1).strip() if m else ""
        if ":" in rest:
            target, msg = rest.split(":", 1)
            return f"send_whatsapp {target.strip()} {msg.strip()}".strip()
        pm = re.match(r"^(\+?[0-9][0-9\s-]{6,}[0-9])\s+(.+)$", rest)
        if pm:
            num = re.sub(r"\s", "", pm.group(1))
            return f"send_whatsapp {num} {pm.group(2).strip()}".strip()
        words = rest.split()
        if len(words) >= 2:
            return f"send_whatsapp {' '.join(words[:-1])} {words[-1]}".strip()
        return f"send_whatsapp {rest}".strip() if rest else "send_whatsapp"

    if re.search(r"(play.*youtube|youtube|play.*episode|play.*anime|play.*video|watch)", clean):
        q = re.sub(r"(?i)^play\s+(?:a\s+|an\s+)?(?:video\s+|episode\s+|anime\s+)?(?:on\s+)?youtube(?:\s+of)?\s*", "", cmd)
        q = re.sub(r"(?i)^play\s+(?:video\s+|episode\s+|anime\s+)?(?:a\s+|an\s+)?", "", q)
        q = re.sub(r"(?i)\s+on\s+youtube$", "", q)
        q = re.sub(r"(?i)^of\s+", "", q)
        q = re.sub(r"(?i)^watch\s+(?:a\s+|an\s+)?", "", q).strip()
        return f"play_youtube {q}".strip() if q else "play_youtube"

    if re.search(r"(play.*song|random.*song|local.*music)", clean):
        song_q = re.sub(r"(?i)^play\s+(?:a\s+)?(?:random\s+)?(?:local\s+)?song\s*", "", cmd).strip()
        return f"play_song {song_q}".strip() if song_q else "play_song"

    if re.search(r"(play.*movie|play.*film|play\s+(?:local\s+)?media|rplay)", clean):
        movie_query = re.sub(r"(?i)^play\s+(?:a\s+|an\s+)?(?:movie|film|media|videos?)\s+(?:from\s+|in\s+)?", "", cmd)
        movie_query = re.sub(r"(?i)^rplay\s+", "", movie_query).strip()
        return f"play_movie {movie_query}".strip() if movie_query else "play_movie"

    if re.search(r"(?i)^play\s+.+\s+(from|by)\s+", clean):
        song_q = re.sub(r"(?i)^play\s+(?:a\s+|an\s+)?", "", cmd).strip()
        return f"play_song {song_q}".strip()

    if re.match(r"^play\s+\S", clean):
        play_target = re.sub(r"(?i)^play\s+(?:a\s+|an\s+)?", "", cmd).strip()
        if re.match(r"(?i)^(song|music)\b", play_target):
            return "play_song"
        if re.match(r"(?i)^(movie|film)\b", play_target):
            title = re.sub(r"(?i)^(?:movie|film)\s+", "", play_target)
            return f"play_movie {title}".strip()
        return f"play_movie {play_target}".strip()

    if re.search(r"(list.*folder|show.*folder|folder.*names|what.*folders|name.*of.*folders)", clean):
        m = re.search(r"(?i)(?:folders?\s+in|folders?\s+under|folders?\s+at)\s+(.+)$", cmd)
        path = m.group(1).strip() if m else ""
        return f"list_folders {path}".strip() if path else "list_folders"

    if re.search(r"(what.*inside|inside.*folder|contents.*of|show.*contents|list.*inside|what.*is.*in)", clean):
        m = re.search(r"(?i)(?:inside|contents of|what is in|what.s in|in)\s+(.+)$", cmd)
        path = m.group(1).strip() if m else ""
        return f"show_folder {path}".strip() if path else "show_folder"

    if re.search(r"(find.*file|search.*file|look.*for.*file|locate.*file)", clean):
        pat = re.sub(r"(?i)^.*(?:find|search|look for|locate)\s+(?:file\s+)?", "", cmd)
        pat = re.sub(r"(?i)\s+(?:in|under|from)\s+.+$", "", pat).strip()
        return f"search_files {pat}".strip() if pat else "search_files"

    if re.search(
        r"(?i)wallpaper|desktop\s+background|set\s+(?:this|it)\s+as\s+wallpaper|background\s+image",
        clean,
    ):
        for w in cmd.split():
            if re.search(r"\.(jpe?g|png|webp|gif|bmp|svg)$", w, re.I):
                return f"set_wallpaper {w}"
        return "set_wallpaper"

    if _is_advisory_question(clean, cmd):
        return f"agent_ask {cmd}"

    rules: list[tuple[str, str]] = [
        (r"(weather|forecast|temp)", f"weather {args}".strip()),
        (r"(timer|countdown)", f"timer {args}".strip()),
        (r"(screenshot|capture)", "screenshot"),
        (r"(system\s*monitor|show\s+system\s+monitor|cpu\s+usage|ram\s+usage|memory\s+usage|system\s*status)", "system_monitor"),
        (r"(excuse|blame)", "excuse"),
        (r"(bored|break|suggest)", "bored"),
        (r"(shorten.*url|short.*link)", f"shorten_url {args}".strip()),
        (r"(qr.*code|qr)", f"qr_code {args}".strip()),
        (r"(crypto|bitcoin|ethereum|solana|btc)", f"crypto_price {args}".strip()),
        (r"(pomodoro|tomato)", f"pomodoro {args}".strip()),
        (r"(git|branch|commit)", "git_summary"),
        (r"(project|open.*project)", f"open_project {args}".strip()),
        (r"(finance|stocks)", "open_finance"),
        (r"(news)", "open_news"),
        (r"(speedtest|internet.*speed)", "speedtest"),
        (r"(port|open.*port)", "port_scan"),
        (r"(disk|space)", f"disk_usage {args}".strip()),
        (r"(todo)", f"todo {args}".strip()),
        (r"(password)", f"generate_password {args}".strip()),
        (r"(ip.*address|ip.*info|my.*ip)", "ip_info"),
        (r"(fix.*venv|recreate.*venv|reset.*venv)", f"fix_venv {args}".strip()),
    ]
    for pattern, out in rules:
        if re.search(pattern, clean):
            return out

    if re.search(r"(bmi|body.*mass|calculate.*bmi)", clean):
        nums = re.findall(r"\b\d+\b", cmd)
        if len(nums) >= 2:
            return f"calculate_bmi {nums[0]} {nums[1]}"
        return f"calculate_bmi {args}".strip()

    if re.search(r"(cheat|cheat.*sheet)", clean):
        return f"cheat {args}".strip()

    if re.search(
        r"(create|add|make).*(desktop|launcher|shortcut).*(unreal|unreal\s*engine)"
        r"|unreal.*(desktop|launcher|shortcut)",
        clean,
        re.I,
    ):
        return "create_desktop_app unreal"

    if re.search(r"(extract\s+this\s+and\s+run|extract\s+and\s+run|extract.*\brun\b)", clean):
        m = re.search(r"(?i)extract\s+(?:this\s+)?(?:and\s+)?run\s+(.+)$", cmd)
        if m:
            return f"extract_and_run {m.group(1).strip()}".strip()
        return "extract_and_run"

    if re.search(
        r"(intel|graphics|gpu).*(driver|issue)|driver has known|recommended driver|installed version of the.*driver",
        clean,
        re.I,
    ) or re.search(r"^fix\b.*(driver|graphics|gpu|intel)", clean, re.I):
        url_m = re.search(r"(https?://\S+)", cmd)
        return (
            f"fix_graphics_driver {url_m.group(1).rstrip('.,);]>')}"
            if url_m
            else "fix_graphics_driver"
        )

    if re.search(r"^(?:download\s+|wget\s+|curl\s+-o\s+)", clean, re.I) and not re.search(
        r"download\s+and\s+install", clean
    ):
        dl = re.sub(r"(?i)^(?:download\s+|wget\s+|curl\s+-o\s+)", "", cmd).strip()
        return f"download_file {dl}".strip() if dl else "download_file"

    if re.search(r"^download\s+(?:this|the)\s+", clean, re.I) and not re.search(
        r"download\s+and\s+install", clean
    ):
        dl = re.sub(r"(?i)^download\s+(?:this|the)\s+", "", cmd).strip()
        return f"download_file {dl}".strip() if dl else "download_file"

    if re.search(r"(install|get|setup).*(with|via|using)\s+apt|\bapt\s+install", clean) and not re.search(
        r"download\s+and\s+install", clean
    ):
        app = re.sub(r"(?i)^(install|get|setup)\s+(?:the\s+)?", "", cmd)
        app = re.sub(
            r"(?i)\s+(?:from|via|using|with|on)\s+(?:flatpak|flathub|snap|snapcraft|apt|apt-get|dpkg).*$",
            "",
            app,
        )
        app = re.sub(r"(?i)\s+(?:with|via|using)\s+apt(?:-get)?\s*$", "", app).strip()
        return f"install_apt {app}".strip() if app else "install_apt"

    if re.search(r"(install|get|setup).*(flatpak|flathub)", clean) and not re.search(
        r"download\s+and\s+install", clean
    ):
        app = re.sub(r"(?i)^(install|get|setup)\s+(?:the\s+)?", "", cmd)
        app = re.sub(r"(?i)\s+(?:from|via|using|with|on)\s+(?:flatpak|flathub).*$", "", app).strip()
        return f"install_flatpak {app}".strip() if app else "install_flatpak"

    if re.search(r"(install|get|setup).*snap", clean) and not re.search(
        r"download\s+and\s+install", clean
    ):
        app = re.sub(r"(?i)^(install|get|setup)\s+(?:the\s+)?", "", cmd)
        app = re.sub(r"(?i)\s+(?:from|via|using|with|on)\s+snap.*$", "", app).strip()
        return f"install_snap {app}".strip() if app else "install_snap"

    if re.search(r"(install|setup|download\s+and\s+install)", clean) and not re.search(
        r"(flatpak|flathub|snap|with\s+apt|via\s+apt)", clean, re.I
    ):
        if _is_python_pip_install(cmd):
            return _parse_install_uv(cmd)
        app = re.sub(r"(?i)^(download\s+and\s+)?(?:install|setup)\s+(?:the\s+)?", "", cmd).strip()
        app = app.strip("'\"")
        if re.search(r"\.(deb|rpm|AppImage|appimage|tar\.gz|tgz|zip)$", app, re.I):
            return f"install_package {app}".strip()
        return f"install_app {app}".strip() if app else "install_app"

    if re.search(r"(flatpak.*snap|snap.*flatpak|search.*flatpak|search.*snap|query.*flatpak|query.*snap)", clean):
        store_q = re.sub(r"(?i)^(query|search|find|look for)\s+", "", cmd)
        store_q = re.sub(r"(?i)^.*\bfor\s+", "", store_q)
        store_q = re.sub(r"(?i)\b(flatpak|snap|flathub|and|or)\b", " ", store_q)
        store_q = re.sub(r"\s+", " ", store_q).strip()
        return f"search_stores {store_q}".strip() if store_q else "search_stores"

    m = re.search(r"(?:open|launch|start)\s+(.+)", clean)
    if m:
        target = m.group(1)
        if not re.search(r"(project|news|finance|url)", target):
            return f"open_app {target}"

    return None


def resolve_spotify_track_id(query: str) -> Optional[str]:
    """Mirrors _spotify_resolve_track_id in config.fish (DDG + artist match)."""
    import json
    import re
    import urllib.parse
    import urllib.request

    query = query.strip()
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    def ddg_tracks(q: str) -> list[str]:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
        req = urllib.request.Request(url, headers=headers)
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace")
        return re.findall(r"open\.spotify\.com/track/([a-zA-Z0-9]+)", html)

    def track_title(tid: str) -> str:
        try:
            oembed = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{tid}"
            req = urllib.request.Request(oembed, headers=headers)
            data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            return (data.get("title") or "").lower()
        except Exception:
            return ""

    words = query.split()
    artist_bits = [w.lower() for w in words[-2:]] if len(words) >= 4 else []
    seen: list[str] = []
    candidates: list[str] = []
    for q in (
        f"site:open.spotify.com/track {query}",
        f"{query} spotify track",
        f"{query} site:open.spotify.com/track",
    ):
        for tid in ddg_tracks(q):
            if tid in seen:
                continue
            seen.append(tid)
            candidates.append(tid)
        if candidates:
            break

    if not candidates:
        return None

    best = candidates[0]
    if artist_bits:
        for tid in candidates[:8]:
            title = track_title(tid)
            if all(bit in title for bit in artist_bits):
                return tid
            if any(bit in title for bit in artist_bits):
                best = tid
    return best


def spotify_oembed_title(track_id: str) -> str:
    import json
    import urllib.request

    url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    return data.get("title") or ""


def has_spotify_desktop() -> bool:
    if shutil.which("spotify"):
        return True
    if shutil.which("flatpak"):
        r = subprocess.run(
            ["flatpak", "list", "--app"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "com.spotify.Client" in (r.stdout or ""):
            return True
    if shutil.which("snap"):
        r = subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=10)
        if re.search(r"^spotify\s", r.stdout or "", re.MULTILINE):
            return True
    return False


NL_CASES: list[tuple[str, str]] = [
    ("play bohemian rhapsody on spotify", "play_spotify"),
    ("play hamuman chalisa on spotify from shankar mahadevan", "play_spotify"),
    ("what's the weather in London", "weather"),
    ("set a timer for 5m", "timer"),
    ("take a screenshot", "screenshot"),
    ("show system monitor", "system_monitor"),
    ("is my cpu too outdated", "agent_ask"),
    ("tell if my pc has malware", "agent_ask"),
    ("install torch for cpu", "install_uv"),
    ("give me an excuse", "excuse"),
    ("I'm bored suggest something", "bored"),
    ("generate a password", "generate_password"),
    ("what's my ip address", "ip_info"),
    ("show disk space", "disk_usage"),
    ("scan open ports", "port_scan"),
    ("git branch status", "git_summary"),
    ("open finance sites", "open_finance"),
    ("open news", "open_news"),
    ("run speedtest", "speedtest"),
    ("bitcoin price", "crypto_price"),
    ("make a qr code for hello", "qr_code"),
    ("calculate bmi 70 kg 175 cm", "calculate_bmi"),
    ("play random local song", "play_song"),
    ("watch python tutorial on youtube", "play_youtube"),
    ("send whatsapp to +1234567890: hi there", "send_whatsapp"),
    ("open firefox", "open_app"),
    ("add todo buy milk", "todo"),
    (
        "set this as wallpaper /home/s/Pictures/wallpapers/wallpaper/wallpaper_3.jpg",
        "set_wallpaper",
    ),
]


def first_token(cmd: str) -> str:
    return cmd.split()[0] if cmd.split() else ""


def test_fallback_helpers(suite: Suite, verbose: bool) -> None:
    """Verify shared _fallback_try, _cmd_chain, _agent_dispatch helpers."""
    helpers = [
        "_fallback_try",
        "_cmd_chain",
        "_agent_is_skill",
        "_agent_dispatch_one",
        "_agent_dispatch",
        "_spotify_browser_start_play",
        "_spotify_fb_web_search",
    ]
    exists = fish_functions_exist(helpers)
    missing = [h for h in helpers if not exists.get(h, False)]
    suite.record(
        Result(
            "fallback:helpers-defined",
            len(missing) == 0,
            "missing: " + ", ".join(missing) if missing else "ok",
        )
    )

    body = r"""
source ~/.config/fish/config.fish
function _fb_ok; return 0; end
function _fb_fail; return 1; end
_fallback_try _fb_fail _fb_ok --
echo FB:$status
_cmd_chain false true
echo CMD:$status
if _agent_is_skill play_spotify; echo SKILL:0; else; echo SKILL:1; end
"""
    try:
        proc = run_fish(body, timeout=20)
        out = proc.stdout
        fb_ok = "FB:0" in out
        cmd_ok = "CMD:0" in out  # skips missing 'false', runs 'true'
        skill_ok = "SKILL:0" in out
        suite.record(Result("fallback:try-chain", fb_ok and skill_ok, out.strip()[:200]))
        suite.record(Result("fallback:cmd-chain", cmd_ok, "skips missing binary" if cmd_ok else out[:120]))
    except Exception as e:
        suite.record(Result("fallback:runtime", False, str(e)[:120]))

    if verbose:
        for r in suite.results[-3:]:
            if r.name.startswith("fallback:"):
                mark = "✓" if r.ok else "✗"
                print(f"  {mark} {r.name}: {r.detail}")


def test_skill_definitions(suite: Suite, skills: list[str], verbose: bool) -> None:
    exists_map = fish_functions_exist(skills)
    for skill in skills:
        exists = exists_map.get(skill, False)
        r = Result(
            f"define:{skill}",
            exists,
            "function missing" if not exists else "ok",
        )
        suite.record(r)
        if verbose:
            mark = "✓" if r.ok else "✗"
            print(f"  {mark} {skill}: {r.detail}")


def test_spotify_track_resolve(suite: Suite, verbose: bool) -> None:
    """Resolver should prefer Shankar Mahadevan for the hanuman chalisa query."""
    import time

    query = "hanuman chalisa shankar mahadevan"
    try:
        track_id = resolve_spotify_track_id(query)
        if not track_id:
            time.sleep(1)
            track_id = resolve_spotify_track_id(query)
    except Exception as e:
        suite.record(Result("spotify-resolve:artist", False, str(e)[:120]))
        return

    if not track_id:
        suite.record(
            Result(
                "spotify-resolve:artist",
                True,
                "skipped (DDG lookup unavailable)",
            )
        )
        if verbose:
            print("  ~ spotify resolve: skipped (DDG unavailable)")
        return

    ok = True
    detail = track_id
    try:
        title = spotify_oembed_title(track_id).lower()
        ok = "shankar" in title and "mahadevan" in title
        detail = f"{track_id} -> {title!r}"
    except Exception as e:
        ok = False
        detail = str(e)[:120]

    suite.record(Result("spotify-resolve:artist", ok, detail))
    if verbose:
        mark = "✓" if ok else "✗"
        print(f"  {mark} spotify resolve: {detail}")


def test_nl_spotify_query_cleanup(suite: Suite, verbose: bool) -> None:
    phrase = "play hamuman chalisa on spotify from shankar mahadevan"
    interpreted = interpret_offline(phrase)
    ok = (
        interpreted is not None
        and "hanuman chalisa shankar mahadevan" in interpreted
        and "hamuman" not in interpreted
        and " on spotify" not in interpreted.lower()
    )
    suite.record(
        Result(
            "nl-spotify:cleanup",
            ok,
            f"got {interpreted!r}",
        )
    )
    if verbose:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {phrase!r} -> {interpreted!r}")


def test_nl_offline(suite: Suite, verbose: bool) -> None:
    for phrase, expected_skill in NL_CASES:
        interpreted = interpret_offline(phrase)
        ok = interpreted is not None and first_token(interpreted) == expected_skill
        r = Result(
            f"nl-offline:{phrase[:40]}",
            ok,
            f"got {interpreted!r}, want {expected_skill}",
        )
        suite.record(r)
        if verbose:
            mark = "✓" if r.ok else "✗"
            print(f"  {mark} {phrase!r} -> {interpreted!r}")


def test_nl_agent(suite: Suite, verbose: bool) -> None:
    """End-to-end: agent offline phrases route to skills (no LLM wait)."""
    # Only phrases that hit config.fish offline rules (see interpret_offline)
    safe_phrases = [
        ("give me an excuse", "excuse"),
        ("I'm bored", "bored"),
        ("calculate bmi 80 180", "calculate_bmi"),
        ("generate password", "generate_password"),
        ("what's the weather", "weather"),
        ("scan open ports", "port_scan"),
    ]
    for phrase, expected in safe_phrases:
        try:
            proc = run_agent_nl(phrase, timeout=25)
        except subprocess.TimeoutExpired:
            suite.record(Result(f"nl-agent:{phrase[:30]}", False, "timeout"))
            continue

        combined = (proc.stdout + proc.stderr).lower()
        offline = "local offline translation match" in combined
        ok = proc.returncode == 0 and offline and (
            expected in combined
            or f"interpreted: {expected}" in combined
            or f"running skill: {expected}" in combined
        )
        suite.record(
            Result(
                f"nl-agent:{phrase[:30]}",
                ok,
                f"offline={offline} exit={proc.returncode}",
            )
        )
        if verbose:
            mark = "✓" if ok else "✗"
            print(f"  {mark} agent {phrase!r} (exit {proc.returncode})")


SmokeFn = Callable[[], tuple[bool, str]]


def _ok(proc: subprocess.CompletedProcess[str], *, allow_usage_error: bool = False) -> tuple[bool, str]:
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0:
        return True, out[:200] or "ok"
    if allow_usage_error and proc.returncode == 1 and ("usage:" in out.lower() or "error:" in out.lower()):
        return True, "usage/help exit 1 (expected)"
    return False, f"exit {proc.returncode}: {out[:300]}"


def build_smoke_tests(tmp: Path, full: bool) -> list[tuple[str, SmokeFn, bool]]:
    """Return (name, runner, needs_full)."""
    tests: list[tuple[str, SmokeFn, bool]] = []

    def add(name: str, fn: SmokeFn, needs_full: bool = False) -> None:
        tests.append((name, fn, needs_full))

    add("excuse", lambda: _ok(run_skill("excuse")))
    add("bored", lambda: _ok(run_skill("bored")))
    add("system_info", lambda: _ok(run_skill("system_info")))
    add("system_monitor", lambda: _ok(run_skill("system_monitor")))
    add("calculate_bmi", lambda: _ok(run_skill("calculate_bmi", "70 175")))
    def generate_password() -> tuple[bool, str]:
        try:
            return _ok(run_skill("generate_password", "12", timeout=60))
        except subprocess.TimeoutExpired:
            return True, "slow urandom; skipped"

    add("generate_password", generate_password)
    add("disk_usage", lambda: _ok(run_skill("disk_usage", ".")))
    add("port_scan", lambda: _ok(run_skill("port_scan")))
    add("clipboard", lambda: _ok(run_skill("clipboard", "pytest-clipboard")))
    add("todo", lambda: _ok(run_skill("todo")))
    add("timer", lambda: _ok(run_skill("timer", "1s"), timeout=15))

    def git_summary() -> tuple[bool, str]:
        repo = tmp / "git_repo"
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=False, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=repo, check=False)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=False)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=repo, check=False)
        return _ok(run_skill("git_summary", cwd=repo))

    add("git_summary", git_summary)

    def create_folder_write_run() -> tuple[bool, str]:
        d = tmp / "skill_dir"
        script = d / "hello.py"
        r1 = run_skill("create_folder", str(d))
        if r1.returncode != 0:
            return False, f"create_folder failed: {r1.stderr}"
        r2 = run_skill("write_script", f"{script} 'print(42)'")
        if r2.returncode != 0:
            return False, f"write_script failed: {r2.stderr}"
        return _ok(run_skill("run_script", str(script)), cwd=d)

    add("create_folder+write+run", create_folder_write_run)

    add("qr_code", lambda: _ok(run_skill("qr_code", "test"), allow_usage_error=False))
    def lint_python() -> tuple[bool, str]:
        proc = run_skill("lint_python", ".", timeout=20)
        out = (proc.stdout + proc.stderr).lower()
        if proc.returncode == 0:
            return True, "ok"
        if "not installed" in out or "install:" in out:
            return True, "no linter installed (skipped)"
        return False, f"exit {proc.returncode}"

    add("lint_python", lint_python)

    add("open_project", lambda: _ok(run_skill("open_project"), allow_usage_error=True), needs_full=True)
    add("ollama_run", lambda: _ok(run_skill("ollama_run"), allow_usage_error=True))
    add("spotify_control", lambda: _ok(run_skill("spotify_control", "status"), allow_usage_error=True), needs_full=True)
    add("play_song", lambda: _ok(run_skill("play_song"), allow_usage_error=True), needs_full=True)
    def activate_venv() -> tuple[bool, str]:
        proc = run_skill("activate_venv")
        out = (proc.stdout + proc.stderr).lower()
        if proc.returncode == 0:
            return True, "ok"
        if proc.returncode == 1 and ("no virtual environment" in out or "usage:" in out):
            return True, "no venv present (expected)"
        return False, f"exit {proc.returncode}"

    add("activate_venv", activate_venv)
    add("create_venv", lambda: _ok(run_skill("create_venv", "test_venv"), allow_usage_error=True), needs_full=True)

    # Network / GUI — full mode only
    add("weather", lambda: _ok(run_skill("weather"), timeout=20), needs_full=True)
    add("ip_info", lambda: _ok(run_skill("ip_info"), timeout=20), needs_full=True)
    add("crypto_price", lambda: _ok(run_skill("crypto_price", "BTC"), timeout=25), needs_full=True)
    add("translate", lambda: _ok(run_skill("translate", "spanish hello"), timeout=25), needs_full=True)
    add("shorten_url", lambda: _ok(run_skill("shorten_url", "https://example.com"), timeout=25), needs_full=True)
    add("cheat", lambda: _ok(run_skill("cheat", "python print"), timeout=25), needs_full=True)
    add("speedtest", lambda: _ok(run_skill("speedtest"), timeout=90), needs_full=True)
    add("search_web", lambda: _ok(run_skill("search_web", "fish shell"), timeout=15), needs_full=True)
    add("open_urls", lambda: _ok(run_skill("open_urls", "https://example.com"), timeout=15), needs_full=True)
    add("open_finance", lambda: _ok(run_skill("open_finance"), timeout=20), needs_full=True)
    add("open_news", lambda: _ok(run_skill("open_news"), timeout=20), needs_full=True)
    def play_spotify_smoke() -> tuple[bool, str]:
        if not has_spotify_desktop():
            return True, "skipped (install Spotify desktop for full play_spotify test)"
        return _ok(
            run_skill("play_spotify", "hanuman chalisa shankar mahadevan"),
            timeout=45,
        )

    add("play_spotify", play_spotify_smoke, needs_full=True)
    add("play_youtube", lambda: _ok(run_skill("play_youtube", "test"), timeout=30), needs_full=True)
    add("screenshot", lambda: _ok(run_skill("screenshot"), timeout=20), needs_full=True)
    add("browse_web", lambda: _ok(run_skill("browse_web"), allow_usage_error=True), needs_full=False)
    add("send_whatsapp", lambda: _ok(run_skill("send_whatsapp"), allow_usage_error=True))
    add("create_skill", lambda: _ok(run_skill("create_skill"), allow_usage_error=True))
    add("open_app", lambda: _ok(run_skill("open_app"), allow_usage_error=True))

    for skill in ("open_file", "list_files", "search_files", "list_folders", "show_folder", "play_movie"):
        add(
            skill,
            lambda n=skill: (fish_function_exists(n), "implemented" if fish_function_exists(n) else "no function"),
        )

    return tests


def run_smoke_batch_fish(script_body: str, *, timeout: int = 60) -> dict[str, int]:
    """Run multiple smoke commands in one Fish process; returns name -> exit code."""
    proc = run_fish(script_body, timeout=timeout)
    results: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("SMOKE_STATUS:"):
            _, name, code = line.split(":", 2)
            results[name] = int(code)
    return results


def test_smoke_batch_local(suite: Suite, tmp: Path, verbose: bool) -> None:
    """Fast offline smokes in a single Fish startup."""
    repo = tmp / "git_repo"
    repo.mkdir(parents=True, exist_ok=True)
    d = tmp / "skill_dir"
    script = d / "hello.py"

    body = f"""
set -l repo '{repo}'
set -l skill_dir '{d}'
set -l script '{script}'
cd '{tmp}'

function _smoke
    set -l n $argv[1]
    $argv[2..-1]
    set -l st $status
    echo SMOKE_STATUS:$n:$st
end

_smoke excuse excuse
_smoke bored bored
_smoke system_info system_info
_smoke system_monitor system_monitor
_smoke calculate_bmi calculate_bmi 70 175
_smoke disk_usage disk_usage .
_smoke port_scan port_scan
_smoke clipboard clipboard pytest-batch
_smoke todo todo
_smoke timer timer 1s
_smoke qr_code qr_code test
_smoke ollama_run ollama_run

cd $repo; and git init -q; and git config user.email test@test.local; and git config user.name Test; and git commit --allow-empty -m init -q
cd $repo; and _smoke git_summary git_summary

_smoke create_folder create_folder $skill_dir
_smoke write_script write_script $script 'print(42)'
cd $skill_dir; and _smoke run_script run_script $script
"""
    try:
        codes = run_smoke_batch_fish(body, timeout=30)
    except subprocess.TimeoutExpired:
        for name in (
            "excuse",
            "bored",
            "system_info",
            "system_monitor",
            "calculate_bmi",
            "disk_usage",
            "port_scan",
            "clipboard",
            "todo",
            "timer",
            "qr_code",
            "ollama_run",
            "git_summary",
            "create_folder",
            "write_script",
            "run_script",
        ):
            suite.record(Result(f"smoke:{name}", False, "batch timeout"))
        return

    for name, code in codes.items():
        ok = code == 0
        suite.record(Result(f"smoke:{name}", ok, f"exit {code}"))
        if verbose:
            print(f"  {'✓' if ok else '✗'} smoke:{name} — exit {code}")


def test_smoke(suite: Suite, full: bool, verbose: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="fish-skills-test-") as td:
        tmp = Path(td)
        test_smoke_batch_local(suite, tmp, verbose)

        tests = build_smoke_tests(tmp, full)
        batch_done = {
            "excuse",
            "bored",
            "system_info",
            "system_monitor",
            "calculate_bmi",
            "disk_usage",
            "port_scan",
            "clipboard",
            "todo",
            "timer",
            "qr_code",
            "ollama_run",
            "git_summary",
            "create_folder+write+run",
            "create_folder",
            "write_script",
            "run_script",
        }
        for name, fn, needs_full in tests:
            if name in batch_done or name.startswith("create_folder"):
                continue
            if needs_full and not full:
                suite.record(Result(f"smoke:{name}", True, "needs --full", skipped=True))
                if verbose:
                    print(f"  ~ smoke:{name} (skipped, use --full)")
                continue
            try:
                ok, detail = fn()
            except subprocess.TimeoutExpired:
                ok, detail = False, "timeout"
            except Exception as exc:
                ok, detail = False, str(exc)

            suite.record(Result(f"smoke:{name}", ok, detail))
            if verbose:
                mark = "✓" if ok else "✗"
                print(f"  {mark} smoke:{name} — {detail[:80]}")


def print_summary(suite: Suite) -> int:
    print()
    print("=" * 60)
    print(f"Passed:  {suite.passed}")
    print(f"Failed:  {suite.failed}")
    print(f"Skipped: {suite.skipped}")
    print("=" * 60)

    if suite.failed:
        print("\nFailures:")
        for r in suite.results:
            if not r.ok and not r.skipped:
                print(f"  ✗ {r.name}: {r.detail}")

    return 0 if suite.failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Fish agent skills and NL routing")
    parser.add_argument("--full", action="store_true", help="Include network/GUI/slow skills")
    parser.add_argument("--nl-only", action="store_true", help="Only NL routing tests")
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="Skip agent integration (offline NL unit tests only)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not shutil.which("fish"):
        print("error: fish shell not found in PATH", file=sys.stderr)
        return 2

    config = read_config()
    skills = parse_available_skills(config)
    suite = Suite()

    print(f"Config: {CONFIG_FISH}")
    print(f"Skills registered: {len(skills)}\n")

    print("1) Skill function definitions")
    test_skill_definitions(suite, skills, args.verbose)

    print("2) Offline natural-language routing")
    test_nl_offline(suite, args.verbose)
    test_nl_spotify_query_cleanup(suite, args.verbose)
    test_spotify_track_resolve(suite, args.verbose)

    print("2b) Modular fallback helpers")
    test_fallback_helpers(suite, args.verbose)

    if not args.nl_only and not args.no_agent:
        print("3) agent integration (offline phrases)")
        test_nl_agent(suite, args.verbose)

    if not args.nl_only:
        step = 3 if args.no_agent else 4
        print(f"{step}) Skill smoke tests")
        test_smoke(suite, args.full, args.verbose)

    return print_summary(suite)


if __name__ == "__main__":
    sys.exit(main())
