"""Built-in lazy skill registrations for in-process dispatch."""

from __future__ import annotations

from arka.core.skill_registry import SkillRegistry

# (primary_name, module_path, aliases)
# First-wave adapter wrap: existing ``main`` functions, imported only on run.
_LAZY_SKILLS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("harness", "arka.integrations.harness_cli", ("harness_bench", "harness-bench")),
    ("trueforge", "arka.integrations.trueforge", ("true_forge", "true-forge")),
    ("n8n", "arka.integrations.n8n", ()),
    ("subagent", "arka.integrations.subagent", ()),
    ("service_autostart", "arka.integrations.service_autostart", ("service-autostart", "autostart_service", "autostart")),
    ("benchmark", "arka.integrations.benchmark_cli", ()),
    ("play", "arka.agent.play", ("game_benchmark", "game-benchmark")),
    ("docker", "arka.integrations.docker_status", ("docker_status", "docker-status")),
    ("social_code_lookup", "arka.agent.social_code_lookup", ("social-code-lookup", "social_code")),
    ("look_for_opensource", "arka.agent.look_for_opensource", ()),
    ("website_pages", "arka.agent.website_pages", ()),
    ("web_template", "arka.agent.web_templates", ("web_templates",)),
    ("podcast_inspiration", "arka.agent.podcast_inspiration", ()),
    ("daily_brief", "arka.agent.daily_brief", ("brief",)),
    ("self_repair", "arka.agent.self_repair", ("self-repair",)),
    ("survival_lang", "arka.agent.survival_lang", ()),
    ("qa", "arka.agent.qa_engineering", ("qa_engineering", "qa-engineering")),
    ("jsonkit", "arka.core.jsonkit", ("url-kit", "urlkit")),
    ("ocr_skill", "arka.agent.ocr_skill", ("arka_ocr",)),
    ("rag_skill", "arka.agent.rag_skill", ("arka_rag",)),
    ("prompt_coach", "arka.agent.prompt_coach", ("prompt-coach",)),
    ("nudge", "arka.agent.nudge", ()),
    ("safety_advice", "arka.agent.safety_advice", ("safety-advice",)),
    ("contextual_answer", "arka.agent.contextual_answer", ("contextual-answer",)),
    ("webhook", "arka.integrations.webhook", ()),
    ("media_transform", "arka.media.media_transform", ("media-transform",)),
    ("site_summary", "arka.integrations.site_summary", ("site-summary",)),
    ("select_model", "arka.llm.model_advisor", ("model_advisor", "best_model")),
    ("code_convert", "arka.agent.code_convert", ("code-convert",)),
    ("design_resources", "arka.agent.design_resources", ("design-resources",)),
    ("hybrid", "arka.llm.hybrid", ("model_hybrid",)),
    ("env_bridge", "arka.agent.env_bridge", ("env-bridge",)),
    ("md_doc", "arka.agent.md_doc", ("md-doc", "read_md")),
    ("markdown_style", "arka.core.markdown_style", ("markdown-style",)),
    ("project_docs", "arka.integrations.project_docs", ("project-docs",)),
    ("human_docs", "arka.agent.human_docs", ("human-docs",)),
    ("batch", "arka.agent.batch", ()),
    ("background", "arka.agent.background", ()),
    ("sandbox", "arka.agent.sandbox", ()),
    ("text", "arka.agent.text_edit", ("text_edit", "text-edit")),
    ("word_counter", "arka.agent.word_counter", ("word-counter",)),
    ("move_file", "arka.agent.move_file", ("move-file",)),
    ("surgical_edit", "arka.agent.surgical_edit", ("surgical-edit",)),
    ("ideate", "arka.agent.ideate", ()),
    ("cool_build", "arka.agent.cool_build", ("build_something_cool",)),
    ("hallmark", "arka.agent.hallmark", ()),
    ("coderabbit", "arka.agent.coderabbit_review", ("coderabbit_review",)),
    ("self_improve", "arka.agent.self_improve", ()),
    ("self_build", "arka.agent.self_build", ("self-build",)),
    ("exercise_dataset", "arka.agent.exercise_dataset", ("exercise-dataset",)),
    ("github_dataset", "arka.agent.github_dataset", ("github-dataset",)),
    ("github_resume", "arka.agent.github_resume", ("github-resume",)),
    ("search", "arka.agent.search_setup", ("search_setup",)),
    ("integration", "arka.agent.integration_setup", ("integrations", "connect")),
    ("share", "arka.llm.share", ()),
    ("provider", "arka.llm.provider_select", ()),
    ("personalize", "arka.core.personalize", ()),
    ("persona", "arka.agent.personas.cli", ()),
    ("browser_check", "arka.agent.browser_check", ("browser-check",)),
    ("play_website_game", "arka.agent.play_website_game", ("play-website-game",)),
    ("automate", "arka.agent.automation", ()),
    ("verify_web_interaction", "arka.agent.verify_web_interaction", ("verify-web-interaction",)),
    ("design", "arka.agent.design_flow", ("design_flow",)),
    ("noise_remove", "arka.media.noise_remove", ("noise-remove",)),
    ("create_video", "arka.media.create_video", ("create-video",)),
    ("edit_video", "arka.media.edit_video", ("edit-video",)),
    ("dub_video", "arka.media.dub_video", ("dub-video",)),
    ("fetch_lyrics", "arka.media.fetch_lyrics", ("fetch-lyrics",)),
    ("model_video", "arka.media.model_video", ("model-video",)),
    ("chart", "arka.charts.plot", ()),
    ("predict", "arka.predict.cli", ()),
    ("data_dashboard", "arka.agent.data_dashboard", ("data-dashboard",)),
    ("bi_dashboard", "arka.agent.bi_dashboard", ("bi-dashboard",)),
    ("observability", "arka.telemetry.observability_doctor", ("observability_doctor",)),
)


def _connector_main(argv: list[str]) -> int:
    from arka.integrations.cli_connector import main

    return main(argv or ["status"])


def register_all(reg: SkillRegistry) -> None:
    for name, module, aliases in _LAZY_SKILLS:
        reg.register_lazy(name, module, aliases=aliases)
    reg.register("connector", _connector_main)
