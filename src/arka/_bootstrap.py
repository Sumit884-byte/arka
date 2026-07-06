"""Bootstrap legacy flat imports and dev checkout paths."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

_SRC = Path(__file__).resolve().parent.parent
_ROOT = _SRC.parent.parent

LEGACY_MODULES: dict[str, str] = {
    "arka_paths": "arka.paths",
    "arka_platform": "arka.core.platform",
    "arka_progress": "arka.core.progress",
    "arka_compute": "arka.core.compute",
    "arka_disk": "arka.core.disk",
    "arka_security": "arka.core.security",
    "arka_usage": "arka.core.usage",
    "arka_memory_detect": "arka.core.memory_detect",
    "arka_llm": "arka.llm.cli",
    "arka_llm_fallback": "arka.llm.fallback",
    "arka_llm_servers": "arka.llm.servers",
    "arka_youtube": "arka.youtube.transcript",
    "arka_youtube_research": "arka.youtube.research",
    "arka_youtube_bulk": "arka.youtube.bulk",
    "arka_ytdlp_progress": "arka.youtube.ytdlp_progress",
    "arka_batch_summarize": "arka.media.batch",
    "arka_media": "arka.media.transcript",
    "arka_media_qa": "arka.media.qa",
    "arka_summarize": "arka.media.summarize",
    "arka_stock_bridge": "arka.stock.bridge",
    "arka_stock_fundamentals": "arka.stock.fundamentals",
    "arka_stock_ui": "arka.stock.ui",
    "arka_stock_context_worker": "arka.stock.context_worker",
    "arka_macro_events": "arka.stock.macro_events",
    "arka_market_emotion": "arka.stock.emotion",
    "arka_competition_funding": "arka.stock.competition_funding",
    "arka_predictions": "arka.stock.predictions",
    "arka_turboquant_install": "arka.stock.turboquant_install",
    "arka_turboquant_rag": "arka.stock.turboquant_rag",
    "arka_agent": "arka.agent.core",
    "arka_professions": "arka.agent.professions",
    "arka_profession_plugins": "arka.agent.profession_plugins",
    "arka_profession_projects": "arka.agent.profession_projects",
    "arka_chat": "arka.agent.chat",
    "arka_survival_lang": "arka.agent.survival_lang",
    "arka_pr_check": "arka.agent.pr_check",
    "arka_skills": "arka.agent.skills",
    "arka_talents": "arka.agent.talents",
    "arka_wake": "arka.agent.wake",
    "arka_voice": "arka.agent.voice",
    "arka_stt_map": "arka.agent.stt_map",
    "arka_assemblyai_stt": "arka.agent.assemblyai_stt",
    "arka_supermemory": "arka.integrations.supermemory",
    "arka_spotify": "arka.integrations.spotify",
    "arka_whatsapp_inbox": "arka.integrations.whatsapp_inbox",
    "arka_hf_bridge": "arka.integrations.hf_bridge",
    "arka_remote_server": "arka.integrations.remote_server",
    "arka_phone": "arka.integrations.phone",
    "arka_remind": "arka.integrations.remind",
    "arka_routines": "arka.integrations.routines",
    "arka_sports": "arka.integrations.sports",
    "arka_password_vault": "arka.integrations.password_vault",
    "arka_google": "arka.integrations.google_workspace",
    "arka_qr": "arka.integrations.qr_code",
    "arka_mac_mic": "arka.integrations.mac_mic",
    "arka_pdf_rag": "arka.pdf.rag",
    "arka_generate_image": "arka.generate.image",
    "arka_generate_video": "arka.generate.video",
    "arka_chart": "arka.charts.plot",
    "arka_aie": "arka.aie.cli",
    "web_answer": "arka.agent.web_answer",
    "edge_speak": "arka.voice.edge_speak",
    "indic_tts": "arka.voice.indic_tts",
    "sarvam_speak": "arka.voice.sarvam_speak",
    "sarvam_stt": "arka.voice.sarvam_stt",
    "spotify_dom": "arka.integrations.spotify_dom",
}

_bootstrapped = False


def _ensure_src_on_path() -> None:
    src_root = str(_ROOT / "src")
    if src_root not in sys.path:
        sys.path.insert(0, src_root)


def install_legacy_aliases() -> None:
    for legacy, qualname in LEGACY_MODULES.items():
        if legacy in sys.modules:
            continue
        try:
            sys.modules[legacy] = importlib.import_module(qualname)
        except ImportError:
            continue


def bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    _ensure_src_on_path()
    _bootstrapped = True


def run_legacy_module(qualname: str) -> int:
    """Run a package module's ``main()`` or ``__main__`` block."""
    bootstrap()
    mod = importlib.import_module(qualname)
    main = getattr(mod, "main", None)
    if callable(main):
        return int(main() or 0)
    import runpy

    runpy.run_module(qualname, run_name="__main__", alter_sys=True)
    return 0


def legacy_shim(qualname: str) -> ModuleType:
    bootstrap()
    return importlib.import_module(qualname)
