"""Static catalog of Python-native skills — names only, no heavy imports.

CapabilityRouter uses this list so bash/zsh/PowerShell users see the same
in-process skills that ``dispatch.run_skill`` already handles, without
requiring fish or importing skill modules at catalog time.
"""

from __future__ import annotations


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_")


# Primary names handled in-process by arka.dispatch / the skill registry.
# Keep this list name-only so importing this module stays cheap.
PYTHON_NATIVE_SKILLS: frozenset[str] = frozenset(
    {
        "alert",
        "arka_ocr",
        "arka_rag",
        "automate",
        "background",
        "background_remove",
        "batch",
        "benchmark",
        "bi_dashboard",
        "blocks",
        "browser_check",
        "calc",
        "capabilities",
        "chart",
        "chart_from_pdf",
        "code",
        "code_convert",
        "coderabbit",
        "coding_tui",
        "coding_workflow",
        "connector",
        "contextual_answer",
        "cool_build",
        "council",
        "create_video",
        "currency",
        "daily_brief",
        "daily_reading",
        "dashboard",
        "data_dashboard",
        "day_research",
        "deploy",
        "describe_video",
        "design",
        "design_from_screenshot",
        "design_resources",
        "dev",
        "dev_tools",
        "docker",
        "dub_video",
        "duplicate_text",
        "edit_video",
        "elon",
        "env_bridge",
        "env_setup",
        "exercise_dataset",
        "fact_check",
        "fetch_lyrics",
        "finetune_model",
        "free_credits",
        "free_models",
        "frontend",
        "frontend_loop",
        "game",
        "geo_seo",
        "github_dataset",
        "github_resume",
        "graphify",
        "greeting",
        "guardrails",
        "hallmark",
        "harness",
        "health_reading",
        "help",
        "human_docs",
        "hybrid",
        "ideate",
        "integration",
        "iterate",
        "joke",
        "jsonkit",
        "jules",
        "local_llm",
        "look_for_opensource",
        "loop_engineering",
        "markdown_style",
        "mcp_auto",
        "md_doc",
        "media_transform",
        "model_optimizer",
        "model_to_image",
        "model_video",
        "move_file",
        "n8n",
        "noise_remove",
        "nudge",
        "observability",
        "ocr_skill",
        "open_url",
        "optimize",
        "output",
        "persona",
        "personalize",
        "play",
        "play_website_game",
        "podcast_inspiration",
        "predict",
        "price_check",
        "project_docs",
        "prompt_coach",
        "prompt_optimize",
        "provider",
        "qa",
        "quiz",
        "rag_skill",
        "repo_graph",
        "repo_reverse",
        "research_math",
        "safety_advice",
        "sandbox",
        "search",
        "select_model",
        "self_build",
        "self_improve",
        "self_repair",
        "service_autostart",
        "share",
        "signoz_publish",
        "site_summary",
        "social_code_lookup",
        "society",
        "spreadsheet",
        "stock_analyze",
        "structure",
        "subagent",
        "surgical_edit",
        "survival_lang",
        "teammate_review",
        "telemetry_connect",
        "template",
        "terminal_video",
        "text",
        "thinking",
        "timezone_convert",
        "train_plan",
        "treemap",
        "trueforge",
        "ultra_fast",
        "url_app",
        "usage",
        "verify_web_interaction",
        "video_evidence",
        "vision_evidence",
        "weather",
        "web_template",
        "webhook",
        "website_pages",
        "word_counter",
        "workspace",
    }
)

# Explicit CLI heads that still require the fish agent (mic/TTS/service loops).
FISH_ONLY_SKILLS: frozenset[str] = frozenset(
    {
        "ai_pref",
        "ai_status",
        "listen",
        "phone_env",
        "queue",
        "refresh",
        "reload",
        "serve",
        "speak",
        "speak_lang",
        "speak_voice",
        "start",
        "stop",
        "tts_setup",
        "wifi",
        "yt_bulk",
    }
)

# Fish subcommand names that already have a Python-native implementation.
FISH_SUB_PYTHON_ALIASES: dict[str, str] = {
    "autostart": "service_autostart",
    "brief": "daily_brief",
    "usage": "usage",
}


def is_python_native(name: str) -> bool:
    key = _norm(name)
    if key in PYTHON_NATIVE_SKILLS:
        return True
    return FISH_SUB_PYTHON_ALIASES.get(key, "") in PYTHON_NATIVE_SKILLS


def is_fish_only(name: str) -> bool:
    return _norm(name) in FISH_ONLY_SKILLS


def resolve_python_name(name: str) -> str:
    key = _norm(name)
    return FISH_SUB_PYTHON_ALIASES.get(key, key)
