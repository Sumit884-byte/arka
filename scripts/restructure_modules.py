#!/usr/bin/env python3
"""Migrate flat arka_*.py modules into src/arka/<domain>/."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "arka"

LAYOUT: dict[str, tuple[str, str]] = {
    "arka_platform": ("core", "platform.py"),
    "arka_progress": ("core", "progress.py"),
    "arka_compute": ("core", "compute.py"),
    "arka_disk": ("core", "disk.py"),
    "arka_security": ("core", "security.py"),
    "arka_usage": ("core", "usage.py"),
    "arka_memory_detect": ("core", "memory_detect.py"),
    "arka_llm": ("llm", "cli.py"),
    "arka_llm_fallback": ("llm", "fallback.py"),
    "arka_llm_servers": ("llm", "servers.py"),
    "arka_youtube": ("youtube", "transcript.py"),
    "arka_youtube_research": ("youtube", "research.py"),
    "arka_youtube_bulk": ("youtube", "bulk.py"),
    "arka_ytdlp_progress": ("youtube", "ytdlp_progress.py"),
    "arka_batch_summarize": ("media", "batch.py"),
    "arka_media": ("media", "transcript.py"),
    "arka_media_qa": ("media", "qa.py"),
    "arka_summarize": ("media", "summarize.py"),
    "arka_stock_bridge": ("stock", "bridge.py"),
    "arka_stock_fundamentals": ("stock", "fundamentals.py"),
    "arka_stock_ui": ("stock", "ui.py"),
    "arka_stock_context_worker": ("stock", "context_worker.py"),
    "arka_macro_events": ("stock", "macro_events.py"),
    "arka_market_emotion": ("stock", "emotion.py"),
    "arka_competition_funding": ("stock", "competition_funding.py"),
    "arka_predictions": ("stock", "predictions.py"),
    "arka_turboquant_install": ("stock", "turboquant_install.py"),
    "arka_turboquant_rag": ("stock", "turboquant_rag.py"),
    "arka_agent": ("agent", "core.py"),
    "arka_chat": ("agent", "chat.py"),
    "arka_skills": ("agent", "skills.py"),
    "arka_talents": ("agent", "talents.py"),
    "arka_wake": ("agent", "wake.py"),
    "arka_voice": ("agent", "voice.py"),
    "arka_stt_map": ("agent", "stt_map.py"),
    "arka_assemblyai_stt": ("agent", "assemblyai_stt.py"),
    "arka_supermemory": ("integrations", "supermemory.py"),
    "arka_spotify": ("integrations", "spotify.py"),
    "arka_whatsapp_inbox": ("integrations", "whatsapp_inbox.py"),
    "arka_hf_bridge": ("integrations", "hf_bridge.py"),
    "arka_remote_server": ("integrations", "remote_server.py"),
    "arka_phone": ("integrations", "phone.py"),
    "arka_remind": ("integrations", "remind.py"),
    "arka_sports": ("integrations", "sports.py"),
    "arka_password_vault": ("integrations", "password_vault.py"),
    "arka_mac_mic": ("integrations", "mac_mic.py"),
    "arka_pdf_rag": ("pdf", "rag.py"),
    "arka_generate_image": ("generate", "image.py"),
    "arka_generate_video": ("generate", "video.py"),
    "arka_aie": ("aie", "cli.py"),
    "web_answer": ("agent", "web_answer.py"),
    "edge_speak": ("voice", "edge_speak.py"),
    "indic_tts": ("voice", "indic_tts.py"),
    "sarvam_speak": ("voice", "sarvam_speak.py"),
    "sarvam_stt": ("voice", "sarvam_stt.py"),
    "spotify_dom": ("integrations", "spotify_dom.py"),
}

LEGACY_TO_QUALNAME = {k: f"arka.{p}.{f[:-3]}" for k, (p, f) in LAYOUT.items()}
LEGACY_TO_QUALNAME["arka_paths"] = "arka.paths"

IMPORT_RE = re.compile(
    r"^(\s*)(from|import)\s+(arka_[a-z_]+|web_answer|edge_speak|indic_tts|sarvam_speak|sarvam_stt|spotify_dom)\b",
    re.M,
)

SHIM = '''\
#!/usr/bin/env python3
"""Legacy entrypoint — prefer the ``arka`` package module."""
from arka._bootstrap import run_legacy_module

if __name__ == "__main__":
    raise SystemExit(run_legacy_module("{qualname}"))
'''


def rewrite_imports(text: str) -> str:
    def repl(line: str) -> str:
        m = IMPORT_RE.match(line)
        if not m:
            return line
        indent, kw, legacy = m.group(1), m.group(2), m.group(3)
        qual = LEGACY_TO_QUALNAME.get(legacy, legacy)
        rest = line[m.end() :]
        if kw == "from":
            return f"{indent}from {qual}{rest}"
        if " as " in rest:
            return f"{indent}import {qual}{rest}"
        return f"{indent}import {qual}{rest}"

    return "\n".join(repl(line) for line in text.splitlines()) + ("\n" if text.endswith("\n") else "")


def merge_paths() -> None:
    legacy = (ROOT / "arka_paths.py").read_text(encoding="utf-8")
    dest = SRC / "paths.py"
    body = dest.read_text(encoding="utf-8")
    if "def load_env_file" not in body:
        chunk = legacy.split("def stock_project_dir", 1)[1]
        body = body.rstrip() + "\n\n\ndef stock_project_dir" + chunk
        dest.write_text(body, encoding="utf-8")
    body = dest.read_text(encoding="utf-8")
    body = body.replace('(bundled / "arka_chat.py")', '(bundled / "config.fish")')
    body = body.replace('(root / "arka_chat.py")', '(root / "pyproject.toml")')
    dest.write_text(body, encoding="utf-8")


def write_shim(name: str, qualname: str) -> None:
    path = ROOT / f"{name}.py"
    path.write_text(SHIM.format(qualname=qualname), encoding="utf-8")
    path.chmod(0o755)


def rewrite_tree(directory: Path) -> None:
    for path in directory.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        new = rewrite_imports(text)
        if new != text:
            path.write_text(new, encoding="utf-8")


def main() -> int:
    packages = {p for p, _ in LAYOUT.values()} | {"core", "llm", "youtube", "media", "stock", "agent", "integrations", "pdf", "generate", "voice", "aie"}
    for pkg in sorted(packages):
        d = SRC / pkg
        d.mkdir(parents=True, exist_ok=True)
        init = d / "__init__.py"
        if not init.exists():
            init.write_text(f'"""Arka {pkg}."""\n', encoding="utf-8")

    moved = 0
    for legacy, (pkg, fname) in LAYOUT.items():
        src = ROOT / f"{legacy}.py"
        if not src.is_file():
            continue
        dest = SRC / pkg / fname
        shutil.copy2(src, dest)
        dest.write_text(rewrite_imports(dest.read_text(encoding="utf-8")), encoding="utf-8")
        moved += 1

    merge_paths()
    rewrite_tree(SRC)

    write_shim("arka_paths", "arka.paths")
    for legacy in LAYOUT:
        write_shim(legacy, LEGACY_TO_QUALNAME[legacy])

    bundled = SRC / "bundled"
    for old in bundled.glob("arka_*.py"):
        old.unlink()

    print(f"Moved {moved} modules; wrote shims at repo root")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
