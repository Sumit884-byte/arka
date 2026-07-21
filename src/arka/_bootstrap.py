"""Bootstrap legacy flat imports and dev checkout paths."""

from __future__ import annotations

import importlib
import inspect
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
    "arka_jsonkit": "arka.core.jsonkit",
    "arka_timekit": "arka.core.timekit",
    "arka_urlkit": "arka.core.urlkit",
    "arka_textkit": "arka.core.textkit",
    "arka_security": "arka.core.security",
    "arka_usage": "arka.core.usage",
    "arka_memory_detect": "arka.core.memory_detect",
    "arka_session_memory": "arka.core.session_memory",
    "arka_unified_memory": "arka.core.unified_memory",
    "arka_memory": "arka.integrations.memory_cli",
    "arka_personalize": "arka.core.personalize",
    "arka_config": "arka.core.config_backup",
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
    "arka_github_repo": "arka.agent.github_repo",
    "arka_competitions": "arka.agent.competitions",
    "arka_bookmarks": "arka.agent.bookmarks",
    "arka_repo_health": "arka.agent.repo_health",
    "arka_free_credits": "arka.agent.free_credits",
    "arka_repo_map": "arka.agent.repo_map",
    "arka_repo_context": "arka.agent.repo_context",
    "arka_self_improve": "arka.agent.self_improve",
    "arka_self_build": "arka.agent.self_build",
    "arka_jules": "arka.agent.jules",
    "arka_generate_data": "arka.agent.generate_data",
    "arka_data_ask": "arka.agent.data_ask",
    "arka_view_data": "arka.agent.view_data",
    "arka_docker_status": "arka.integrations.docker_status",
    "arka_clipboard_history": "arka.integrations.clipboard_history",
    "arka_route_learn": "arka.agent.route_learn",
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
    "arka_heartbeat": "arka.integrations.heartbeat",
    "arka_message_sessions": "arka.integrations.message_sessions",
    "arka_subagent": "arka.integrations.subagent",
    "arka_teams": "arka.integrations.teams_cli",
    "arka_webhook": "arka.integrations.webhook",
    "arka_sports": "arka.integrations.sports",
    "arka_currency": "arka.integrations.currency",
    "arka_open_url": "arka.integrations.open_url",
    "arka_kalshi": "arka.integrations.kalshi",
    "arka_kaggle": "arka.integrations.kaggle",
    "arka_password_vault": "arka.integrations.password_vault",
    "arka_google": "arka.integrations.google_workspace",
    "arka_gemini": "arka.integrations.gemini_cli",
    "arka_harvard_ark": "arka.integrations.harvard_ark",
    "arka_fugu": "arka.integrations.fugu",
    "arka_benchmark": "arka.integrations.benchmark_cli",
    "arka_qr": "arka.integrations.qr_code",
    "arka_mac_mic": "arka.integrations.mac_mic",
    "arka_pdf_rag": "arka.pdf.rag",
    "arka_pdf_tools": "arka.pdf.tools",
    "arka_generate_image": "arka.generate.image",
    "arka_generate_video": "arka.generate.video",
    "arka_compose_slides": "arka.media.compose_slides",
    "arka_compose_3d": "arka.media.compose_3d",
    "arka_terminal_video": "arka.media.terminal_video",
    "arka_text_to_3d": "arka.agent.text_to_3d",
    "arka_convert_media": "arka.media.convert_media",
    "arka_chart": "arka.charts.plot",
    "arka_chart_from_pdf": "arka.charts.chart_from_pdf",
    "arka_treemap": "arka.charts.treemap",
    "arka_ascii_art": "arka.agent.ascii_art",
    "arka_flow": "arka.agent.flow",
    "arka_fact_check": "arka.agent.fact_check",
    "arka_astronomy": "arka.agent.astronomy",
    "arka_metallurgy": "arka.agent.metallurgy",
    "arka_three_d": "arka.media.compose_3d",
    "arka_elon": "arka.agent.personas.elon",
    "arka_persona": "arka.agent.personas.cli",
    "arka_drawing": "arka.documents.drawing",
    "arka_describe_image": "arka.vision.describe",
    "arka_describe_video": "arka.vision.video",
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
        try:
            params = list(inspect.signature(main).parameters)
        except (TypeError, ValueError):
            params = []
        if params and params[0] in ("argv", "args"):
            return int(main(sys.argv[1:]) or 0)
        return int(main() or 0)
    import runpy

    runpy.run_module(qualname, run_name="__main__", alter_sys=True)
    return 0


def legacy_shim(qualname: str) -> ModuleType:
    bootstrap()
    return importlib.import_module(qualname)
