"""Run arka_*.py scripts with correct paths."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from arka.paths import arka_home, bundled_dir, cache_dir, config_dir, python_executable, script_path


def apply_env() -> None:
    bundled = bundled_dir()
    home = bundled if (bundled / "config.fish").is_file() else arka_home()
    os.environ["INSTALL_HOME"] = str(home)
    os.environ.setdefault("CONFIG_DIR", str(config_dir()))
    os.environ.setdefault("CACHE_DIR", str(cache_dir()))


def run_script(script: str, args: list[str] | None = None) -> int:
    apply_env()
    path = script_path(script)
    if not path.is_file():
        print(f"Missing script: {path}", file=sys.stderr)
        print("Reinstall arka-agent or run: python scripts/sync_bundled.py", file=sys.stderr)
        return 1
    cmd = [python_executable(), str(path), *(args or [])]
    if os.environ.get("ARKA_CAPTURE_STDIO", "").lower() in ("1", "true", "yes", "on"):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    return subprocess.call(cmd)


def run_skill(skill_line: str) -> int:
    """Execute a skill command line like 'generate_password set wifi secret'."""
    from arka.core.mode import get_mode, mode_allows_execution
    from arka.skills import run_chat_ask, run_chat_calc, run_chat_weather, run_password

    apply_env()
    parts = _split_skill_line(skill_line)
    if not parts:
        return 1
    head = parts[0]
    if head not in {"skills", "skill_settings"}:
        try:
            from arka.core.skill_settings import is_disabled
            if is_disabled(head):
                from arka.core.skill_settings import profile_disabled
                if head in profile_disabled():
                    print(f"Skill unavailable in hosted mode: {head}. Set ARKA_HOSTED_MODE=0 or run: arka skills enable {head}", file=sys.stderr)
                else:
                    print(f"Skill disabled: {head}. Enable it with: arka skills enable {head}", file=sys.stderr)
                return 1
        except ImportError:
            pass
    started = time.perf_counter()
    rest = parts[1:]

    if head == "mode":
        from arka.core.mode import cmd_show, main as mode_main

        if not rest:
            return cmd_show()
        return mode_main(["mode", *rest])
    if head in ("skills", "skill_settings"):
        from arka.core.skill_settings import main as skill_settings_main
        return skill_settings_main(rest)
    if head in ("plugin", "plugins"):
        from arka.agent.skills import main as plugins_main

        # `plugin` is the universal-plugin lifecycle namespace; retain
        # `skills` for the existing enable/disable settings commands.
        return plugins_main(rest)

    allowed, reason = mode_allows_execution(skill_line)
    if not allowed:
        if get_mode() == "plan":
            from arka.core.mode import print_plan
            from arka.router import route

            print_plan(skill_line, route(skill_line))
            return 0
        print(reason, file=sys.stderr)
        return 1

    head = parts[0]
    try:
        from arka.core.code_project import (
            CODE_WRITE_SKILLS,
            apply_env as apply_code_env,
            gate_code_write,
            gate_write_script_args,
        )

        code_ok, code_reason = gate_code_write(skill_line)
        if not code_ok:
            print(code_reason, file=sys.stderr)
            return 1
        if head == "write_script":
            ws_ok, ws_reason = gate_write_script_args(rest)
            if not ws_ok:
                print(ws_reason, file=sys.stderr)
                return 1
        if head in CODE_WRITE_SKILLS:
            apply_code_env()
    except ImportError:
        pass

    try:
        from arka.telemetry import mark_error, mark_ok, span
    except ImportError:
        span = None  # type: ignore[assignment,misc]
    from contextlib import nullcontext

    skill_ctx = (
        span(
            f"arka.skill.{head}",
            attributes={"arka.skill.name": head, "arka.skill.line": skill_line[:500]},
        )
        if span is not None
        else nullcontext()
    )
    with skill_ctx as current:
        if head in ("generate_password", "password", "pass"):
            code = run_password(rest)
        elif head == "config":
            from arka.core.default_config import main as config_main

            code = config_main(rest)
        elif head == "platform_howto":
            from arka.agent.platform_howto import answer_platform_howto

            answer = answer_platform_howto(" ".join(rest))
            if answer:
                print(answer)
                code = 0
            else:
                print("Could not get an answer (check LLM API keys)", file=sys.stderr)
                code = 1
        elif head in ("interesting_fact", "trivia", "fun_fact"):
            from arka.agent.interesting_fact import answer_interesting_fact

            answer = answer_interesting_fact(" ".join(rest))
            if answer:
                print(answer)
                code = 0
            else:
                print("Could not get a fact (check LLM API keys)", file=sys.stderr)
                code = 1
        elif head == "web_answer":
            code = run_chat_ask(" ".join(rest))
        elif head == "deep_web_answer":
            code = run_chat_ask(" ".join(rest), deep=True)
        elif head == "calc":
            code = run_chat_calc(" ".join(rest))
        elif head in ("observability", "observability_doctor", "signoz_doctor"):
            from arka.telemetry.observability_doctor import main as observability_main

            code = observability_main(rest)
        elif head in ("telemetry_connect", "telemetry-connect", "production_telemetry"):
            from arka.telemetry.codebase_connectors import main as connector_main
            code = connector_main(rest)
        elif head in ("hyperlocal_weather", "weather"):
            code = run_chat_weather(" ".join(rest))
        elif head == "price_check":
            from arka.agent.core import price_check

            price_check(" ".join(rest))
            code = 0
        elif head in ("fact_check", "fact-check", "factcheck", "factchecker"):
            from arka.agent.fact_check import fact_check

            code = fact_check(" ".join(rest))
        elif head in ("quiz_practice", "quiz-practice", "quiz"):
            code = run_script("arka_quiz_practice.py", rest)
        elif head == "council":
            code = run_script("arka_council.py", rest)
        elif head == "convert":
            from arka.routing.symbolic import is_timezone_convert_request

            text = " ".join(rest).strip()
            if text and is_timezone_convert_request(text):
                code = run_script("arka_timezone_convert.py", ["convert", *rest])
            else:
                code = run_script("arka_currency.py", ["convert", *rest])
        elif head in ("media_transform", "media-transform", "transform_media"):
            from arka.media.media_transform import main as transform_main
            code = transform_main(rest)
        elif head in ("currency_convert", "currency"):
            code = run_script("arka_currency.py", ["convert", *rest])
        elif head in ("timezone_convert", "tz_convert", "timezone"):
            code = run_script("arka_timezone_convert.py", ["convert", *rest])
        elif head in ("open_url", "open", "browse"):
            # Coding sessions should not unexpectedly launch GUI/browser
            # windows. Explicitly opt in when a workflow needs a headed tab.
            if os.environ.get("ARKA_CODING_SESSION") == "1" and os.environ.get("ARKA_CODING_AUTO_BROWSER", "0") not in {"1", "true", "yes"}:
                print("Browser opening disabled during coding session (set ARKA_CODING_AUTO_BROWSER=1 to enable).")
                code = 0
            else:
                code = run_script("arka_open_url.py", rest)
        elif head in ("select_model", "model_select", "best_model", "model_advisor"):
            from arka.llm.model_advisor import main as model_advisor_main

            code = model_advisor_main(rest or None)
        elif head in ("model", "model_host", "model-host") and rest and rest[0] in {"setup", "doctor", "list"}:
            from arka.llm.model_host_setup import main as model_setup_main
            code = model_setup_main(rest)
        elif head in ("model_optimizer", "model-optimizer") or (head == "model" and rest and rest[0] in {"recommend", "switch"}):
            from arka.llm.model_optimizer import main as optimizer_main
            code = optimizer_main(rest if head != "model" else rest)
        elif head in ("train_plan", "train-plan", "model_train") or (head == "model" and rest and rest[0] in {"train-plan", "train_plan"}):
            from arka.llm.train_plan import main as train_plan_main
            code = train_plan_main(rest[1:] if head == "model" else rest)
        elif head in ("stock_analyze", "stock-analyze", "market_analyze"):
            from arka.stock.analyzer import main as stock_main
            code = stock_main(rest)
        elif head in ("code_convert", "code-convert", "language_convert"):
            from arka.agent.code_convert import main as code_convert_main
            code = code_convert_main(rest)
        elif head in ("design_resources", "design-resources"):
            from arka.agent.design_resources import main as design_resources_main
            code = design_resources_main(rest)
        elif head in ("edge", "edge_mode", "edge-mode"):
            from arka.llm.edge import main as edge_main
            code = edge_main(rest)
        elif head in ("judge_demo", "judge-demo", "demo_pack"):
            from arka.agent.judge_demo import main as judge_demo_main
            code = judge_demo_main(rest)
        elif head in ("free_models", "free-models", "free_models_list"):
            from arka.llm.free_models import main as free_models_main
            code = free_models_main(rest)
        elif head in ("hybrid", "model_hybrid", "hybrid_model"):
            from arka.llm.hybrid import main as hybrid_main

            code = hybrid_main(rest or ["status"])
        elif head in ("local_llm", "local-llm", "run_only_local_llm", "run-only-local-llm"):
            from arka.llm.hybrid import main as hybrid_main
            code = hybrid_main(["run", "--local-only", *rest]) if rest else hybrid_main(["status", "--policy", "local-only"])
        elif head in ("guardrails", "llm_guardrails", "cost_guardrails"):
            from arka.llm.guardrails import main as guardrails_main
            code = guardrails_main(rest)
        elif head in ("grounding", "grounded", "anti_hallucination"):
            from arka.llm.grounding import enabled
            print(f"grounded_mode\t{'on' if enabled() else 'off'}")
            code = 0
        elif head in ("quantize", "quantise", "model_quantize"):
            from arka.llm.quantize import main as quantize_main
            code = quantize_main(rest)
        elif head in ("speculative", "speculative_decode", "mtp"):
            from arka.llm.speculative import main as speculative_main
            code = speculative_main(rest)
        elif head in ("backend", "inference_backend", "multi_gpu"):
            from arka.llm.backend import main as backend_main
            code = backend_main(rest)
        elif head in ("env_bridge", "env-bridge", "project_env"):
            from arka.agent.env_bridge import main as env_bridge_main
            code = env_bridge_main(rest)
        elif head in ("coding_workflow", "coding-workflow", "workflow"):
            from arka.agent.coding_workflows import main as workflow_main
            code = workflow_main(rest)
        elif head in ("mcp_auto", "mcp-auto", "mcp_autoconfig"):
            from arka.integrations.mcp_autoconfig import main as mcp_auto_main
            code = mcp_auto_main(rest)
        elif head in ("thinking", "thinking_level", "thinking-level"):
            from arka.llm.thinking import get, set_level
            if not rest:
                print(f"Thinking level: {get()}")
                code = 0
            else:
                try:
                    print(f"Thinking level set: {set_level(rest[0])}")
                    code = 0
                except ValueError as exc:
                    print(exc)
                    code = 2
        elif head in ("free_credits", "free-credits", "max_credits", "ai_credits"):
            from arka.agent.free_credits import run_guide

            code = run_guide()
        elif head == "provider":
            from arka.llm.provider_select import main as provider_main

            code = provider_main(rest or None)
        elif head == "personalize":
            from arka.core.personalize import main as personalize_main

            code = personalize_main(rest)
        elif head == "persona":
            from arka.agent.personas.cli import main as persona_main

            code = persona_main(rest)
        elif head in ("elon", "talk_to_elon", "elon_chat", "talk_elon"):
            from arka.agent.personas.elon import main as elon_main

            code = elon_main(rest)
        elif head == "google":
            code = run_script("arka_google.py", rest)
        elif head == "code":
            from arka.core.code_project import main as code_main

            code = code_main(["code", *rest])
        elif head in ("data", "data_collect", "collect_data", "data-collect") and rest and rest[0] in {"collect", "catalog"}:
            from arka.agent.data_collect import main as collect_main
            code = collect_main([*rest[1:], "--catalog"] if rest[0] == "catalog" else rest[1:])
        elif head in ("exercise_dataset", "exercise-dataset", "exercises", "fitness_dataset"):
            from arka.agent.exercise_dataset import main as exercise_main

            code = exercise_main(rest)
        elif head in ("github_dataset", "github-dataset", "dataset_repo", "dataset-repo"):
            from arka.agent.github_dataset import main as github_dataset_main

            code = github_dataset_main(rest)
        elif head in ("search", "search_setup", "search-setup"):
            from arka.agent.search_setup import main as search_setup_main
            code = search_setup_main(rest)
        elif head in ("integration", "integrations", "setup-integration", "connect"):
            from arka.agent.integration_setup import main as integration_main
            code = integration_main(rest)
        elif head == "agent_code":
            from arka.agent.core import code_agent

            code = code_agent(" ".join(rest))
        elif head == "batch":
            from arka.agent.batch import main as batch_main

            code = batch_main(rest)
        elif head in ("background", "background_processes", "background-processes"):
            from arka.agent.background import main as background_main

            code = background_main(rest or ["processes"])
        elif head in ("sandbox", "sandboxes"):
            from arka.agent.sandbox import main as sandbox_main

            code = sandbox_main(rest)
        elif head in ("background_remove", "background-removal", "remove_background"):
            from arka.agent.background_remove import main as remove_main
            code = remove_main(rest)
        elif head in ("model_to_image", "model-to-image", "render_3d"):
            from arka.agent.model_to_image import main as model_image_main
            code = model_image_main(rest)
        elif head in ("text", "text_edit", "text-edit"):
            from arka.agent.text_edit import main as text_main
            code = text_main(rest)
        elif head in ("word_counter", "word-counter", "wordcount", "word_count"):
            from arka.agent.word_counter import main as word_counter_main
            code = word_counter_main(rest)
        elif head in ("move_file", "move-file", "move"):
            from arka.agent.move_file import main as move_main
            code = move_main(rest)
        elif head in ("surgical_edit", "surgical-edit", "surgical"):
            from arka.agent.surgical_edit import main as surgical_main
            code = surgical_main(rest)
        elif head in ("ideate", "arka_ideate", "open_source_ideate"):
            from arka.agent.ideate import main as ideate_main
            code = ideate_main(rest)
        elif head in ("build_something_cool", "build-something-cool", "build_cool_feature", "build-cool-feature", "cool_build"):
            from arka.agent.cool_build import main as cool_main
            code = cool_main(rest)
        elif head in ("game", "game_studio", "game-studio"):
            if rest and rest[0] == "check":
                from arka.agent.game_control import main as game_check_main
                code = game_check_main(rest[1:])
            else:
                from arka.agent.game_studio import main as game_main
                code = game_main(rest)
        elif head in ("play", "game_benchmark", "game-benchmark"):
            from arka.agent.play import main as play_main
            code = play_main(rest)
        elif head in ("hallmark", "hallmark-design"):
            from arka.agent.hallmark import main as hallmark_main
            code = hallmark_main(rest)
        elif head in ("vision_evidence", "vision-evidence", "ocr_compare"):
            from arka.agent.vision_evidence import main as evidence_main
            code = evidence_main(rest)
        elif head in ("describe_video", "describe-video", "video_describe", "video-description"):
            from arka.vision.video import main as video_main
            code = video_main(rest)
        elif head in ("url_app", "url-app", "app_design_review"):
            from arka.agent.url_app_analyzer import main as url_app_main
            code = url_app_main(rest)
        elif head in ("coding_tui", "coding-tui", "code_tui"):
            from arka.agent.coding_tui import main as coding_tui_main
            code = coding_tui_main(rest)
        elif head in ("iterate", "loop"):
            from arka.agent.iterate import main as iterate_main
            code = iterate_main([head, *rest])
        elif head in ("loop_engineering", "loop-engineering", "engineer-loop"):
            from arka.agent.loop_engineering import main as loop_engineering_main
            code = loop_engineering_main(rest)
        elif head in ("ultra_fast", "ultra-fast", "fast_dev", "fast-dev"):
            from arka.agent.ultra_fast import main as ultra_main
            code = ultra_main(rest)
        elif head in ("env_setup", "env-setup", "create_env"):
            from arka.agent.env_setup import main as env_main
            code = env_main(rest)
        elif head in ("research_math", "math_script", "math-script"):
            from arka.agent.research_math import main as math_main
            code = math_main(rest)
        elif head in ("prompt_optimize", "prompt-optimizer", "optimize_prompt"):
            from arka.agent.prompt_optimize import main as prompt_main
            code = prompt_main(rest)
        elif head in ("deploy", "deployment"):
            from arka.agent.deploy import main as deploy_main
            code = deploy_main(rest)
        elif head in ("geo_seo", "geo-seo", "seo_audit"):
            from arka.agent.geo_seo import main as geo_main
            code = geo_main(rest)
        elif head in ("template", "templates", "workflow_template"):
            from arka.agent.workflow_templates import main as template_main
            code = template_main(rest)
        elif head in ("blocks", "block", "app_blocks", "app-blocks"):
            from arka.agent.blocks import main as blocks_main
            code = blocks_main(rest)
        elif head in ("hackathon", "hackathons"):
            from arka.agent.hackathon import main as hackathon_main
            code = hackathon_main(rest)
        elif head in ("optimize", "optimize_params", "evolve"):
            from arka.agent.optimize import main as optimize_main
            code = optimize_main(rest)
        elif head in ("repo_reverse", "repo-reverse", "reverse_repo"):
            from arka.agent.repo_reverse import main as reverse_main
            code = reverse_main(rest)
        elif head in ("repo_graph", "repo-graph", "repository_graph"):
            from arka.agent.repo_graph import main as graph_main
            code = graph_main(rest)
        elif head in ("workspace", "workspace_map", "workspace-map"):
            from arka.agent.workspace import main as workspace_main
            code = workspace_main(rest)
        elif head in ("structure", "structure_audit", "structure-audit"):
            from arka.agent.structure import main as structure_main
            code = structure_main(rest)
        elif head in ("dev_workflow", "dev-workflow", "devtool"):
            from arka.agent.dev_workflows import main as dev_workflow_main
            code = dev_workflow_main(rest)
        elif head in ("graphify", "graphify_repo", "graphify-repo"):
            from arka.agent.graphify import main as graphify_main
            code = graphify_main(rest)
        elif head in ("spreadsheet", "spreadsheet_create", "create_spreadsheet"):
            from arka.agent.generate_data import main as generate_data_main
            code = generate_data_main([*rest, "--format", "xlsx"] if "--format" not in rest else rest)
        elif head in ("teammate_review", "teammate-review", "ai_teammate"):
            from arka.agent.teammate_review import main as teammate_main
            code = teammate_main(rest)
        elif head in ("society", "ai_society", "ai-society"):
            from arka.agent.society import main as society_main
            code = society_main(rest)
        elif head in ("browser_check", "browser-check", "ui_check"):
            from arka.agent.browser_check import main as browser_main
            code = browser_main(rest)
        elif head in ("automate", "app_automate", "app-automate"):
            from arka.agent.automation import main as automation_main
            code = automation_main(rest)
        elif head in ("usage", "skill_usage"):
            if rest and rest[0] in ("dashboard", "dash"):
                from arka.agent.usage_dashboard import main as usage_dashboard_main
                code = usage_dashboard_main(rest[1:])
            else:
                from arka.core.skill_usage import report
                payload = report()
                print(f"Arka usage: {payload['total']} skill invocations")
                for skill, count in payload["skills"][:20]:
                    print(f"  {skill}: {count}")
                code = 0
        elif head in ("design", "design_flow"):
            from arka.agent.design_flow import main as design_main
            code = design_main(rest)
        elif head in ("session", "sessions", "message_session", "message-sessions"):
            from arka.integrations.message_sessions import main as sessions_main

            code = sessions_main(rest or ["status"])
        elif head in ("supermemory", "super-memory"):
            from arka.integrations.supermemory import main as supermemory_main
            code = supermemory_main(rest)
        elif head in ("self_improve", "self"):
            from arka.agent.self_improve import main as self_main, resolve_improve_args, run_self_improve

            argv = list(rest)
            if head == "self" and argv and argv[0] == "improve":
                argv = argv[1:]
            if len(argv) == 1 and argv[0] in ("memory", "status"):
                code = self_main([argv[0]])
            else:
                target, apply, max_rounds, max_steps, yes, auto_init = resolve_improve_args(argv)
                code = run_self_improve(
                    target,
                    max_rounds=max_rounds,
                    max_steps=max_steps,
                    auto_init=auto_init,
                    yes=yes,
                    apply=apply,
                )
        elif head in ("ci", "review", "route_audit", "route-audit", "skill", "security", "doctor", "dev_doctor", "dev-doctor", "hooks"):
            from arka.agent.dev_tools import main as dev_tools_main

            sub_argv = ["doctor" if head in ("dev_doctor", "dev-doctor") else head, *rest]
            if head == "route-audit":
                sub_argv[0] = "route-audit"
            code = dev_tools_main(sub_argv)
            try:
                from arka.core.notifications import notify
                notify(f"Arka {head}", "completed successfully" if code == 0 else f"failed (exit {code})")
            except Exception:
                pass
        elif head in ("design_from_screenshot", "design-screenshot", "designshot"):
            from arka.agent.design_from_screenshot import main as design_main

            code = design_main([head.replace("-", "_"), *rest])
        elif head in ("frontend_loop", "frontend-review", "frontend_review", "ui_loop", "ui-review"):
            from arka.agent.frontend_loop import main as frontend_main

            code = frontend_main([head.replace("-", "_"), *rest])
        elif head in ("ui_copy", "ui-copy", "copy_audit", "copy-audit"):
            from arka.agent.ui_copy_audit import main as copy_main
            code = copy_main(rest)
        elif head in ("web_screenshot", "web-screenshot", "site_screenshot"):
            from arka.agent.web_screenshot import main as screenshot_main
            code = screenshot_main(rest)
        elif head in ("spline", "spline_guide", "spline-guide"):
            from arka.agent.spline_guide import main as spline_main
            code = spline_main(rest)
        elif head in ("three_js_model", "three-js-model", "threejs_model"):
            from arka.agent.three_js_model import main as three_main
            code = three_main(rest)
        elif head in ("text_to_3d", "text-to-3d", "text2_3d", "text23d"):
            from arka.agent.text_to_3d import main as text_to_3d_main
            code = text_to_3d_main(rest)
        elif head in ("scene_3d", "scene-3d", "3d_scene"):
            from arka.agent.scene_3d import main as scene_main
            code = scene_main(rest)
        elif head in ("rig_3d", "rig-3d", "3d_rig"):
            from arka.agent.rig_3d import main as rig_main
            code = rig_main(rest)
        elif head in ("parallax_2d", "parallax-2d", "2.5d", "parallax"):
            from arka.agent.parallax_2d import main as parallax_main
            code = parallax_main(rest)
        elif head in ("visual_diagnose", "visual-diagnose", "visual_qa"):
            from arka.agent.visual_diagnose import main as visual_main
            code = visual_main(rest)
        elif head in ("semantic_alert", "semantic-alert", "alert"):
            from arka.agent.semantic_alert import main as alert_main
            code = alert_main(rest)
        elif head in ("symbolic_image", "symbolic-image", "image_compose"):
            from arka.agent.symbolic_image import main as symbolic_image_main
            code = symbolic_image_main(rest)
        elif head in ("image", "image_generate", "image-generate") and rest and rest[0] == "doctor":
            from arka.agent.local_image_gen import main as local_image_main
            code = local_image_main(rest)
        elif head in ("image", "image_generate", "image-generate") and rest and rest[0] in ("generate", "create"):
            from arka.agent.local_image_gen import main as local_image_main
            code = local_image_main(rest[1:])
        elif head in ("visual", "visuals") and rest and rest[0] in ("space-tech", "space_tech"):
            from arka.agent.space_visual import main as space_visual_main
            code = space_visual_main(rest[1:])
        elif head in ("multi_llm", "multi-llm", "llm_variants"):
            from arka.agent.multi_llm import main as multi_main
            code = multi_main(rest)
        elif head in ("race", "agent_race", "agent-race"):
            from arka.agent.race import main as race_main
            code = race_main(rest)
        elif head in ("app_check", "app-check", "build_app", "test_app"):
            from arka.agent.app_check import main as app_main
            code = app_main(rest)
        elif head in ("design_memory", "design-memory", "remember_design"):
            from arka.agent.design_memory import main as design_memory_main
            code = design_memory_main(rest)
        elif head in ("github_actions", "github-actions", "gha"):
            from arka.agent.github_actions import main as actions_main
            code = actions_main(rest)
        elif head in ("parallel", "parallel_skills", "parallel-skills"):
            from arka.agent.parallel import main as parallel_main
            code = parallel_main(rest)
        elif head in ("understand_script", "understand-script", "script_memory"):
            from arka.agent.script_understanding import main as understand_main
            code = understand_main(rest)
        elif head in ("super_replica", "super-replica", "repo_advisor"):
            from arka.agent.super_replica import main as replica_main
            code = replica_main(rest)
        elif head in ("pdf_interactive", "pdf-to-interactive", "interactive_pdf"):
            from arka.agent.pdf_interactive import main as pdf_interactive_main
            code = pdf_interactive_main(rest)
        elif head in ("media_quiz", "media-quiz", "quiz_website"):
            from arka.agent.media_quiz import main as media_quiz_main
            code = media_quiz_main(rest)
        elif head in ("urlkit", "url-kit"):
            from arka.core.urlkit import main as urlkit_main

            code = urlkit_main(rest)
        elif head in ("lint_project", "lint-project", "lint_all"):
            from arka.agent.lint_project import main as lint_main

            code = lint_main([head.replace("-", "_"), *rest])
        elif head.endswith(".py") and script_path(head).is_file():
            code = run_script(head, rest)
        else:
            py_name = f"{head}.py"
            if script_path(py_name).is_file():
                code = run_script(py_name, rest)
            else:
                code = run_fish_skill(skill_line)

        if span is not None:
            current.set_attribute("arka.skill.exit_code", code)
            if code == 0:
                mark_ok(current)
            else:
                mark_error(current, f"exit {code}")
        try:
            from arka.core.skill_usage import record
            record(head, code, (time.perf_counter() - started) * 1000)
        except Exception:
            pass
        return code


def run_fish_skill(skill_line: str) -> int:
    from arka.fish_bridge import delegate_to_fish

    code = delegate_to_fish([skill_line])
    if code is not None:
        return code
    print(f"Unknown skill: {skill_line}", file=sys.stderr)
    print("Try: arka help  |  arka doctor  |  install fish for full 70+ skills", file=sys.stderr)
    return 1


def run_shell(cmd: str) -> int:
    apply_env()
    return subprocess.call(cmd, shell=True)


def _split_skill_line(line: str) -> list[str]:
    import shlex

    line = line.strip()
    if not line:
        return []
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()
