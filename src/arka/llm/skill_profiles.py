#!/usr/bin/env python3
"""Per-skill LLM task profiles and default model suggestions."""

from __future__ import annotations

# Task profile → description + suggested default model (provider/model or bare model id)
TASK_PROFILES: dict[str, dict[str, str]] = {
    "route": {
        "description": "NL routing — pick skill or shell command",
        "default_model": "groq/llama-3.1-8b-instant",
    },
    "chat": {
        "description": "Q&A, talk, web answers, advisory agent_ask",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "summarize": {
        "description": "Transcripts, URLs, media, Gmail, folder digests",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "research": {
        "description": "Deep web/YouTube research, speak_research",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "agent": {
        "description": "Goal agent, code agent, professions, PR check, vision Q&A",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "pdf": {
        "description": "PDF/doc RAG Q&A and summarization",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "predictions": {
        "description": "Stock/opportunity predictions and analysis",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "compose_video": {
        "description": "Info/video script generation for compose_video",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "compose_slides": {
        "description": "Presentation deck script generation for compose_slides",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "flow": {
        "description": "Structured multi-block step-by-step flow answers",
        "default_model": "gemini/gemini-2.5-flash",
    },
    "default": {
        "description": "General LLM completions",
        "default_model": "gemini/gemini-2.0-flash",
    },
}

# Built-in skill name → task profile (extend via llm-skill-models.json "_profiles" overrides)
SKILL_TASK_MAP: dict[str, str] = {
    # Routing (set explicitly when calling route)
    "route": "route",
    # Chat / Q&A
    "platform_howto": "chat",
    "interesting_fact": "chat",
    "flow": "flow",
    "elon": "chat",
    "talk_to_elon": "chat",
    "elon_chat": "chat",
    "persona": "chat",
    "web_answer": "chat",
    "deep_web_answer": "research",
    "web_essay": "chat",
    "agent_ask": "chat",
    "arka_ask": "chat",
    "talk": "chat",
    "ask": "chat",
    "translate": "chat",
    "error_helper": "chat",
    "product_reviewer": "chat",
    "price_check": "chat",
    "fact_check": "research",
    "quiz_practice": "chat",
    "council": "chat",
    "calc": "chat",
    # Summarize
    "youtube_transcript": "summarize",
    "yt_download": "summarize",
    "youtube_download": "summarize",
    "media_transcript": "summarize",
    "transcribe_media": "summarize",
    "summarize_url": "summarize",
    "post_x": "summarize",
    "folder_summarize": "summarize",
    "playlist_summarize": "summarize",
    "transcript_ask": "summarize",
    "media_ask": "summarize",
    "google": "summarize",
    "daily_brief": "summarize",
    # Research
    "youtube_research": "research",
    "yt_research": "research",
    "speak_research": "research",
    "agent_research": "research",
    "deep_queue": "research",
    # Agent / multi-step
    "agent_code": "agent",
    "agent_handoff": "agent",
    "agent_fanout": "agent",
    "agent_plan": "agent",
    "goal": "agent",
    "self_improve": "agent",
    "meeting_agent": "agent",
    "study_agent": "agent",
    "inbox_agent": "agent",
    "compare_agent": "agent",
    "profession": "agent",
    "pr_check": "agent",
    "drawing_ask": "agent",
    "describe_image": "agent",
    "describe_screen": "agent",
    "describe_video": "agent",
    "codebase_ingest": "agent",
    "semantic_memory": "agent",
    "github_repo": "agent",
    "repo_map": "agent",
    "repo_context": "agent",
    # PDF / RAG
    "pdf_ask": "pdf",
    "doc_ask": "pdf",
    "data_ask": "chat",
    "ask_data": "chat",
    "query_data": "chat",
    "analyze_data": "chat",
    "pdf_ingest": "pdf",
    "doc_ingest": "pdf",
    # Predictions / stocks
    "predictions": "predictions",
    "stock": "predictions",
    "stock_analysis": "predictions",
    "macro": "predictions",
    "emotion": "predictions",
    # Video compose
    "compose_video": "compose_video",
    "compose_slides": "compose_slides",
    # Meta / setup
    "select_model": "chat",
    "model_select": "chat",
    "best_model": "chat",
    "model_advisor": "chat",
}


def normalize_skill_name(skill: str | None) -> str:
    raw = (skill or "").strip().lower()
    if not raw:
        return ""
    return raw.replace("-", "_")


def skill_task_profile(skill: str | None) -> str:
    """Map a skill name to its LLM task profile."""
    key = normalize_skill_name(skill)
    if not key:
        return "default"
    return SKILL_TASK_MAP.get(key, "default")


def task_profile_info(profile: str) -> dict[str, str]:
    return dict(TASK_PROFILES.get(profile, TASK_PROFILES["default"]))


def known_skill_names() -> list[str]:
    return sorted(SKILL_TASK_MAP.keys())


def known_task_profiles() -> list[str]:
    return list(TASK_PROFILES.keys())


def default_model_for_skill(skill: str | None) -> str:
    profile = skill_task_profile(skill)
    return task_profile_info(profile).get("default_model", "")


def default_model_for_profile(profile: str) -> str:
    return task_profile_info(profile).get("default_model", "")
