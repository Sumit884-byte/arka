#!/usr/bin/env python3
"""Copy runtime files into src/arka/bundled for pip wheels (run before build)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLED = ROOT / "src" / "arka" / "bundled"

# All runtime assets shipped inside the package (no external folder copy needed)
NAMES = [
    "arka_paths.py",
    "arka_agent.py",
    "arka_memory_detect.py",
    "arka_security.py",
    "arka_aie.py",
    "arka_batch_summarize.py",
    "arka_chat.py",
    "arka_compute.py",
    "arka_disk.py",
    "arka_generate_image.py",
    "arka_generate_video.py",
    "arka_hf_bridge.py",
    "arka_llm.py",
    "arka_llm_fallback.py",
    "arka_llm_servers.py",
    "arka_macro_events.py",
    "arka_market_emotion.py",
    "arka_media.py",
    "arka_media_qa.py",
    "arka_password_vault.py",
    "arka_platform.py",
    "arka_pdf_rag.py",
    "arka_phone.py",
    "arka_predictions.py",
    "arka_progress.py",
    "arka_remote_server.py",
    "arka_stt_map.py",
    "arka_assemblyai_stt.py",
    "arka_sports.py",
    "arka_spotify.py",
    "arka_supermemory.py",
    "arka_skills.py",
    "arka_stock_bridge.py",
    "arka_stock_context_worker.py",
    "arka_stock_fundamentals.py",
    "arka_competition_funding.py",
    "arka_summarize.py",
    "arka_talents.py",
    "arka_voice.py",
    "arka_turboquant_install.py",
    "arka_turboquant_rag.py",
    "arka_usage.py",
    "arka_wake.py",
    "arka_mac_mic.py",
    "arka_whatsapp_inbox.py",
    "arka_youtube.py",
    "arka_youtube_bulk.py",
    "arka_ytdlp_progress.py",
    "arka_youtube_research.py",
    "arka_remind.py",
    "edge_speak.py",
    "indic_tts.py",
    "sarvam_speak.py",
    "sarvam_stt.py",
    "web_answer.py",
    "spotify_dom.py",
    "config.fish",
    "arka_boot.sh",
    "arka_voice_hf.sh",
    "termux-boot-arka.sh",
    "arka_chat_requirements.txt",
    "arka_turboquant_requirements.txt",
    ".env.example",
]

OPTIONAL_DIRS = [
    ("privategpt", "settings.override.yaml"),
]


def main() -> int:
    BUNDLED.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in NAMES:
        src = ROOT / name
        if not src.is_file():
            continue
        shutil.copy2(src, BUNDLED / name)
        n += 1
    for subdir, fname in OPTIONAL_DIRS:
        src = ROOT / subdir / fname
        if src.is_file():
            dst_dir = BUNDLED / subdir
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst_dir / fname)
            n += 1
    # Copy entire aie/ tree when present
    aie_src = ROOT / "aie"
    if aie_src.is_dir():
        aie_dst = BUNDLED / "aie"
        if aie_dst.exists():
            shutil.rmtree(aie_dst)
        shutil.copytree(aie_src, aie_dst)
        n += len(list(aie_dst.rglob("*")))
    wa_src = ROOT / "whatsapp"
    if wa_src.is_dir():
        wa_dst = BUNDLED / "whatsapp"
        if wa_dst.exists():
            shutil.rmtree(wa_dst)
        shutil.copytree(wa_src, wa_dst)
        n += len(list(wa_dst.rglob("*")))
    print(f"Synced {n} files → {BUNDLED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
