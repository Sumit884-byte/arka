#!/usr/bin/env python3
"""Copy runtime scripts into src/arka/bundled for pip wheels."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLED = ROOT / "src" / "arka" / "bundled"

NAMES = [
    "arka_agent.py",
    "arka_aie.py",
    "arka_batch_summarize.py",
    "arka_chat.py",
    "arka_compute.py",
    "arka_disk.py",
    "arka_generate_image.py",
    "arka_generate_video.py",
    "arka_hf_bridge.py",
    "arka_llm.py",
    "arka_macro_events.py",
    "arka_market_emotion.py",
    "arka_media.py",
    "arka_media_qa.py",
    "arka_password_vault.py",
    "arka_pdf_rag.py",
    "arka_phone.py",
    "arka_predictions.py",
    "arka_progress.py",
    "arka_remote_server.py",
    "arka_stt_map.py",
    "arka_stock_bridge.py",
    "arka_stock_context_worker.py",
    "arka_stock_fundamentals.py",
    "arka_competition_funding.py",
    "arka_summarize.py",
    "arka_talents.py",
    "arka_turboquant_install.py",
    "arka_turboquant_rag.py",
    "arka_usage.py",
    "arka_wake.py",
    "arka_whatsapp_inbox.py",
    "arka_youtube.py",
    "arka_youtube_bulk.py",
    "arka_youtube_research.py",
    "edge_speak.py",
    "indic_tts.py",
    "sarvam_speak.py",
    "sarvam_stt.py",
    "web_answer.py",
    ".env.example",
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
    print(f"Synced {n} files → {BUNDLED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
