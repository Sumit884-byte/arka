"""Arka as a local stdio MCP server — expose skills and memory to other agents."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from arka import __version__
from arka.integrations.mcp_client import MCP_PROTOCOL_VERSION

SERVER_NAME = "arka"
ARKA_MCP_SERVER_KEY = "arka"

ToolHandler = Callable[[dict[str, Any]], str]


def _mcp_int(value: Any, default: int) -> int:
    """Parse MCP tool integer args; Cursor may send \"\" for optional number fields."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mcp_int_optional(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mcp_float_optional(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


MCP_DEFAULT_DISABLED_TOOLS = {
    "arka_spotify",
}

MCP_DEFAULT_DISABLED_SKILL_HEADS = {
    "agent_browser",
    "browse",
    "browse_web",
    "daily_brief",
    "open",
    "open_url",
    "open_urls",
    "play_movie",
    "play_song",
    "play_spotify",
    "play_website_game",
    "verify_web_interaction",
    "play_youtube",
    "search_web",
    "spotify_brave_debug",
    "spotify_control",
    "stop_music",
}


def _csv_env(name: str) -> set[str]:
    return {part.strip().lower() for part in os.environ.get(name, "").split(",") if part.strip()}


def _mcp_personal_skills_enabled() -> bool:
    return os.environ.get("ARKA_MCP_ENABLE_PERSONAL_SKILLS", "").strip().lower() in {"1", "true", "yes", "on"}


def _mcp_disabled_tools() -> set[str]:
    if _mcp_personal_skills_enabled():
        disabled: set[str] = set()
    else:
        disabled = set(MCP_DEFAULT_DISABLED_TOOLS)
    disabled |= _csv_env("ARKA_MCP_DISABLED_TOOLS")
    disabled -= _csv_env("ARKA_MCP_ENABLED_TOOLS")
    try:
        from arka.core.just_ai import JUST_AI_MCP_TOOLS, is_just_ai

        if is_just_ai():
            disabled |= {tool.name for tool in _build_tools() if tool.name not in JUST_AI_MCP_TOOLS}
    except ImportError:
        pass
    return disabled


def _mcp_disabled_skill_heads() -> set[str]:
    if _mcp_personal_skills_enabled():
        disabled: set[str] = set()
    else:
        disabled = set(MCP_DEFAULT_DISABLED_SKILL_HEADS)
    disabled |= _csv_env("ARKA_MCP_DISABLED_SKILLS")
    disabled -= _csv_env("ARKA_MCP_ENABLED_SKILLS")
    return disabled


def _mcp_disabled_message(name: str) -> str:
    return (
        f"Arka MCP skill {name!r} is disabled by default because it can touch personal desktop/browser/media state. "
        "Use a headless/dev-safe skill instead, or opt in with ARKA_MCP_ENABLE_PERSONAL_SKILLS=1 "
        f"or ARKA_MCP_ENABLED_SKILLS={name} / ARKA_MCP_ENABLED_TOOLS={name}."
    )


def _run_skill_captured(skill_line: str, *, allow_browser: bool = False) -> tuple[int, str]:
    """Run a skill while capturing subprocess stdout/stderr for MCP-safe responses."""
    from arka.agent.voice import strip_ansi
    from arka.dispatch import run_skill

    command = skill_line.split(None, 1)[0].lower() if skill_line.strip() else ""
    if command in _mcp_disabled_skill_heads():
        return 2, _mcp_disabled_message(command)
    if command in {"open", "open_url", "browse"} and not (allow_browser or os.environ.get("ARKA_MCP_ALLOW_BROWSER") == "1"):
        return 2, "Website opening is disabled for MCP requests; use a headless browser skill or explicitly approve with allow_browser=true."
    buf = io.StringIO()
    os.environ["ARKA_CAPTURE_STDIO"] = "1"
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = run_skill(skill_line)
    except SystemExit as exc:
        # argparse and several legacy skills use SystemExit for user input or
        # backend errors. Never let that terminate the MCP stdio process.
        code = int(exc.code) if isinstance(exc.code, int) else 2
        if not buf.getvalue().strip() and exc.code not in (None, 0):
            buf.write(str(exc.code))
    finally:
        os.environ.pop("ARKA_CAPTURE_STDIO", None)
    return int(code or 0), strip_ansi(buf.getvalue()).strip()


@dataclass(frozen=True)
class ArkaMcpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        payload["isError"] = True
    return payload


def _handle_arka_ask(arguments: dict[str, Any]) -> str:
    prompt = str(arguments.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    deep = bool(arguments.get("deep", False))
    try:
        from arka.agent.chat import answer_question

        provenance, answer = answer_question(
            prompt,
            deep=deep,
            use_session=True,
            cleanup=True,
        )
        return f"[{provenance}]\n{answer}".strip()
    except ImportError as exc:
        raise RuntimeError(f"chat module unavailable: {exc}") from exc


def _handle_arka_remember(arguments: dict[str, Any]) -> str:
    text = str(arguments.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    layer = str(arguments.get("layer") or "auto").strip().lower()
    if layer not in {"auto", "fact", "note", "channel"}:
        raise ValueError("layer must be auto, fact, note, or channel")
    try:
        from arka.core.unified_memory import remember

        with contextlib.redirect_stdout(io.StringIO()):
            code, err = remember(
                text,
                layer=layer,  # type: ignore[arg-type]
                long_term=bool(arguments.get("long_term", False)),
            )
        if code != 0:
            raise RuntimeError(err or "remember failed")
        return f"Remembered ({layer}): {text[:200]}"
    except ImportError as exc:
        raise RuntimeError(f"unified_memory unavailable: {exc}") from exc


def _handle_arka_recall(arguments: dict[str, Any]) -> str:
    goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    limit_chars = _mcp_int(arguments.get("limit_chars"), 3500)
    try:
        from arka.core.unified_memory import recall

        text = recall(goal, limit_chars=max(200, limit_chars))
        return text or "(no matching memory)"
    except ImportError as exc:
        raise RuntimeError(f"unified_memory unavailable: {exc}") from exc


def _handle_arka_intelligence(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        import arka.memory.graph_memory as gr_mod
    except ImportError as exc:
        raise RuntimeError(f"graph memory unavailable: {exc}") from exc

    if action == "status":
        return json.dumps(gr_mod.status(verbose=bool(arguments.get("verbose", True))), indent=2)
    if action == "remember":
        text = str(arguments.get("text") or "").strip()
        if not text:
            raise ValueError("text is required when action=remember")
        return json.dumps(gr_mod.graph_remember(text), indent=2)
    if action == "recall":
        goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
        if not goal:
            raise ValueError("goal is required when action=recall")
        limit_chars = _mcp_int(arguments.get("limit_chars"), 1200)
        narrative, meta = gr_mod.graph_recall(goal, limit_chars=max(200, limit_chars))
        return json.dumps({"narrative": narrative or "(no graph matches)", "meta": meta}, indent=2)
    if action == "rebuild":
        return json.dumps(gr_mod.rebuild_from_memory_file(), indent=2)
    if action == "export":
        fmt = str(arguments.get("format") or "mermaid").strip().lower()
        if fmt == "json":
            return json.dumps(gr_mod.load_graph(), indent=2)
        return gr_mod.export_mermaid(limit=_mcp_int(arguments.get("limit"), 40))
    raise ValueError("action must be status, remember, recall, rebuild, or export")


def _build_skill_line(skill: str, args: Any) -> str:
    """Join skill + args safely (paths with spaces stay one token)."""
    import shlex

    head = str(skill or "").strip()
    if isinstance(args, str):
        extra = shlex.split(args) if args.strip() else []
    elif isinstance(args, list):
        extra = [str(a) for a in args]
    else:
        raise ValueError("args must be a string or list")
    return shlex.join([head, *extra]) if extra else head


def _direct_mcp_from_skill(skill: str, args: Any) -> tuple[str, dict[str, Any]] | None:
    """Route typed skill invocations (batch, rag, ocr) to dedicated MCP handlers."""
    import shlex

    head = str(skill or "").strip().split(None, 1)[0].lower().replace("-", "_")
    if isinstance(args, str):
        parts = shlex.split(args) if args.strip() else []
    elif isinstance(args, list):
        parts = [str(a) for a in args]
    else:
        parts = []

    if head in {"arka_batch", "batch"}:
        if not parts:
            return "arka_batch", {"action": "list"}
        action = parts[0].lower()
        payload: dict[str, Any] = {"action": action, "name": "default"}
        if action == "start":
            until = ""
            if "--until" in parts:
                idx = parts.index("--until")
                if idx + 1 < len(parts):
                    until = parts[idx + 1]
            elif len(parts) > 1:
                until = parts[1]
            if not until:
                raise ValueError("until is required for batch start")
            payload["until"] = until
            if "--name" in parts:
                idx = parts.index("--name")
                if idx + 1 < len(parts):
                    payload["name"] = parts[idx + 1]
        elif action == "add":
            prompt_parts: list[str] = []
            i = 1
            while i < len(parts):
                if parts[i] in {"--name", "-n"} and i + 1 < len(parts):
                    payload["name"] = parts[i + 1]
                    i += 2
                    continue
                if parts[i] in {"--until", "-u"} and i + 1 < len(parts):
                    payload["until"] = parts[i + 1]
                    i += 2
                    continue
                prompt_parts.append(parts[i])
                i += 1
            payload["prompt"] = " ".join(prompt_parts).strip()
            if not payload["prompt"]:
                raise ValueError("prompt is required for batch add")
        elif action in {"run", "due", "clear", "list"}:
            if "--name" in parts:
                idx = parts.index("--name")
                if idx + 1 < len(parts):
                    payload["name"] = parts[idx + 1]
            if "--print" in parts:
                payload["print_only"] = True
            if "--keep" in parts:
                payload["keep"] = True
        else:
            return None
        return "arka_batch", payload

    if head in {"arka_terminal_video", "terminal_video", "terminal_demo", "cli_demo"}:
        action = parts[0].lower().replace("_", "-") if parts else "build"
        start = 1
        if action not in {"build", "capture", "export-images", "export", "check", "parse"}:
            action = "build"
            start = 0
        if action == "export":
            action = "export-images"
        payload: dict[str, Any] = {"action": action}
        i = start
        while i < len(parts):
            token = parts[i]
            if token in {"-o", "--output"} and i + 1 < len(parts):
                payload["output"] = parts[i + 1]
                i += 2
                continue
            if token == "--project-dir" and i + 1 < len(parts):
                payload["project_dir"] = parts[i + 1]
                i += 2
                continue
            if token == "--captures" and i + 1 < len(parts):
                payload["captures"] = parts[i + 1]
                i += 2
                continue
            if token == "--script" and i + 1 < len(parts):
                payload["script"] = parts[i + 1]
                i += 2
                continue
            if token == "--skip-verify":
                payload["skip_verify"] = True
                i += 1
                continue
            i += 1
        return "arka_terminal_video", payload

    if head in {"arka_local_music", "local_music_gen", "local_music"}:
        action = parts[0].lower() if parts else "generate"
        start = 1
        if action not in {"generate", "parse", "doctor"}:
            action = "generate"
            start = 0
        payload: dict[str, Any] = {"action": action}
        i = start
        while i < len(parts):
            token = parts[i]
            if token in {"-o", "--output"} and i + 1 < len(parts):
                payload["output"] = parts[i + 1]
                i += 2
                continue
            if token in {"-d", "--duration"} and i + 1 < len(parts):
                payload["duration"] = int(parts[i + 1])
                i += 2
                continue
            if token == "--instrumental":
                payload["instrumental"] = True
                i += 1
                continue
            if token == "--lyrics" and i + 1 < len(parts):
                payload["lyrics"] = parts[i + 1]
                i += 2
                continue
            if action == "generate" and "prompt" not in payload:
                payload["prompt"] = parts[i]
            i += 1
        return "arka_local_music", payload

    if head in {"arka_music_generate", "music_generate", "generate_music", "generate-music"}:
        action = parts[0].lower() if parts else "generate"
        start = 1
        if action not in {"generate", "parse", "check"}:
            action = "generate"
            start = 0
        payload: dict[str, Any] = {"action": action}
        prompt_parts: list[str] = []
        i = start
        while i < len(parts):
            token = parts[i]
            if token in {"-o", "--output"} and i + 1 < len(parts):
                payload["output"] = parts[i + 1]
                i += 2
                continue
            if token in {"-d", "--duration"} and i + 1 < len(parts):
                payload["duration"] = int(parts[i + 1])
                i += 2
                continue
            if token in {"-m", "--model"} and i + 1 < len(parts):
                payload["model"] = parts[i + 1]
                i += 2
                continue
            if token == "--instrumental":
                payload["instrumental"] = True
                i += 1
                continue
            if token == "--lyrics" and i + 1 < len(parts):
                payload["lyrics"] = parts[i + 1]
                i += 2
                continue
            if action == "generate":
                prompt_parts.append(token)
            i += 1
        if prompt_parts:
            payload["prompt"] = " ".join(prompt_parts)
        return "arka_music_generate", payload

    if head in {"arka_fetch_lyrics", "fetch_lyrics", "song_lyrics", "lyrics_fetch"}:
        action = parts[0].lower() if parts else "fetch"
        start = 1
        if action not in {"fetch", "translate", "parse", "check"}:
            action = "fetch"
            start = 0
        payload: dict[str, Any] = {"action": action}
        i = start
        positional: list[str] = []
        while i < len(parts):
            token = parts[i]
            if token in {"-t", "--target"} and i + 1 < len(parts):
                payload["target"] = parts[i + 1]
                i += 2
                continue
            if token in {"-q", "--query"} and i + 1 < len(parts):
                payload["query"] = parts[i + 1]
                i += 2
                continue
            if token in {"-o", "--output"} and i + 1 < len(parts):
                payload["output"] = parts[i + 1]
                i += 2
                continue
            if token in {"-d", "--duration"} and i + 1 < len(parts):
                payload["duration"] = int(parts[i + 1])
                i += 2
                continue
            if token == "--generate":
                payload["generate"] = True
                i += 1
                continue
            if token == "--instrumental":
                payload["instrumental"] = True
                i += 1
                continue
            if token == "--style" and i + 1 < len(parts):
                payload["style"] = parts[i + 1]
                i += 2
                continue
            positional.append(token)
            i += 1
        if len(positional) >= 2:
            payload["artist"] = positional[0]
            payload["title"] = " ".join(positional[1:])
        elif len(positional) == 1 and "query" not in payload:
            payload["query"] = positional[0]
        return "arka_fetch_lyrics", payload

    if head in {"arka_play_website_game", "play_website_game", "website_game", "browser_game"}:
        action = parts[0].lower() if parts else "open"
        start = 1
        if action not in {"open", "search", "parse", "check"}:
            if re.match(r"^https?://", action, re.I):
                action = "open"
                start = 0
            else:
                action = "search"
                start = 0
        payload: dict[str, Any] = {"action": action}
        i = start
        positional: list[str] = []
        while i < len(parts):
            token = parts[i]
            if token in {"-q", "--query"} and i + 1 < len(parts):
                payload["query"] = parts[i + 1]
                i += 2
                continue
            if token in {"-u", "--url"} and i + 1 < len(parts):
                payload["url"] = parts[i + 1]
                i += 2
                continue
            if token == "--headless":
                payload["headless"] = True
                i += 1
                continue
            if token == "--open":
                payload["open"] = True
                i += 1
                continue
            if token == "--auto-start":
                payload["auto_start"] = True
                i += 1
                continue
            if token in {"--wait", "-w"} and i + 1 < len(parts):
                payload["wait_seconds"] = int(parts[i + 1])
                i += 2
                continue
            if token in {"--yes", "-y", "--allow-browser"}:
                payload["allow_browser"] = True
                i += 1
                continue
            positional.append(token)
            i += 1
        if action == "open" and positional and "url" not in payload:
            payload["url"] = positional[0]
        elif action == "search" and positional and "query" not in payload:
            payload["query"] = " ".join(positional)
        return "arka_play_website_game", payload

    if head in {"arka_verify_web_interaction", "verify_web_interaction", "web_interaction_check", "site_verify"}:
        action = parts[0].lower() if parts else "check"
        start = 1
        if action not in {"check", "parse", "check-deps"}:
            if re.match(r"^https?://", action, re.I):
                action = "check"
                start = 0
            else:
                action = "check"
                start = 0
        payload: dict[str, Any] = {"action": action}
        i = start
        positional: list[str] = []
        while i < len(parts):
            token = parts[i]
            if token in {"-c", "--context"} and i + 1 < len(parts):
                payload["context"] = parts[i + 1]
                i += 2
                continue
            if token in {"-s", "--spec"} and i + 1 < len(parts):
                payload["spec"] = parts[i + 1]
                i += 2
                continue
            if token in {"-r", "--repo"} and i + 1 < len(parts):
                payload["repo"] = parts[i + 1]
                i += 2
                continue
            if token == "--headless":
                payload["headless"] = True
                i += 1
                continue
            if token == "--headed":
                payload["headed"] = True
                i += 1
                continue
            if token in {"--yes", "-y", "--allow-browser"}:
                payload["allow_browser"] = True
                i += 1
                continue
            if token == "--vision":
                payload["vision"] = True
                i += 1
                continue
            if token == "--no-vision":
                payload["no_vision"] = True
                i += 1
                continue
            if token == "--vllm-verify":
                payload["vllm_verify"] = True
                payload["vision"] = True
                i += 1
                continue
            if token == "--vision-backend" and i + 1 < len(parts):
                payload["vision_backend"] = parts[i + 1]
                i += 2
                continue
            positional.append(token)
            i += 1
        if action == "check" and positional and "url" not in payload:
            payload["url"] = positional[0]
        return "arka_verify_web_interaction", payload

    if head in {"arka_safety_advice", "safety_advice", "crisis_advice", "support_advice"}:
        action = parts[0].lower() if parts else "advice"
        start = 1
        if action not in {"advice", "resources", "topics", "parse"}:
            action = "advice"
            start = 0
        payload: dict[str, Any] = {"action": action}
        query_parts: list[str] = []
        i = start
        while i < len(parts):
            token = parts[i]
            if token == "--topic" and i + 1 < len(parts):
                payload["topic"] = parts[i + 1]
                i += 2
                continue
            if token == "--region" and i + 1 < len(parts):
                payload["region"] = parts[i + 1]
                i += 2
                continue
            query_parts.append(token)
            i += 1
        if query_parts and action == "advice":
            payload["text"] = " ".join(query_parts)
        return "arka_safety_advice", payload

    if head in {
        "arka_reposition_image",
        "reposition_image",
        "fix_image_crop",
        "fix-image-crop",
        "smart_image_frame",
        "smart-image-frame",
    }:
        action = parts[0].lower() if parts else "check"
        start = 1
        if action not in {"check", "fix", "css", "fix-ui", "batch", "parse"}:
            if re.search(r"\.(?:png|jpe?g|webp|gif|bmp|tiff?)$", action, re.I):
                action = "check"
                start = 0
            else:
                action = "check"
                start = 0
        payload: dict[str, Any] = {"action": action}
        i = start
        positional: list[str] = []
        while i < len(parts):
            token = parts[i]
            if token in {"-o", "--output", "--output-dir"} and i + 1 < len(parts):
                key = "output" if action != "batch" else "folder"
                if token == "--output-dir":
                    key = "output_dir"
                payload[key] = parts[i + 1]
                i += 2
                continue
            if token in {"-c", "--context"} and i + 1 < len(parts):
                payload["context"] = parts[i + 1]
                i += 2
                continue
            if token == "--shape" and i + 1 < len(parts):
                payload["shape"] = parts[i + 1]
                i += 2
                continue
            if token == "--selector" and i + 1 < len(parts):
                payload["selector"] = parts[i + 1]
                i += 2
                continue
            if token == "--size" and i + 1 < len(parts):
                payload["size"] = parts[i + 1]
                i += 2
                continue
            if token == "--vision":
                payload["vision"] = True
                i += 1
                continue
            positional.append(token)
            i += 1
        if action == "batch" and positional and "folder" not in payload:
            payload["folder"] = positional[0]
        elif positional and "path" not in payload:
            payload["path"] = positional[0]
        return "arka_reposition_image", payload

    if head in {
        "arka_filter_images",
        "filter_images",
        "filter-images",
        "image_relevance",
        "image-relevance",
        "hybrid_image_filter",
        "hybrid-image-filter",
    }:
        action = parts[0].lower() if parts else "score"
        start = 1
        if action not in {"score", "filter", "check", "parse"}:
            if re.search(r"\.(?:png|jpe?g|webp|gif|bmp|tiff?)$", action, re.I):
                action = "check"
                start = 0
            else:
                action = "score"
                start = 0
        payload: dict[str, Any] = {"action": action}
        i = start
        positional: list[str] = []
        while i < len(parts):
            token = parts[i]
            if token in {"-o", "--output"} and i + 1 < len(parts):
                payload["output"] = parts[i + 1]
                i += 2
                continue
            if token in {"-q", "--query"} and i + 1 < len(parts):
                payload["query"] = parts[i + 1]
                i += 2
                continue
            if token == "--borderline-pct" and i + 1 < len(parts):
                payload["borderline_pct"] = parts[i + 1]
                i += 2
                continue
            if token in {"--vllm-pass", "--vlm-pass"}:
                payload["vlm_pass"] = True
                i += 1
                continue
            positional.append(token)
            i += 1
        if positional and "path" not in payload and "folder" not in payload:
            key = "path" if action == "check" else "folder"
            payload[key] = positional[0]
        return "arka_filter_images", payload

    if not parts:
        return None

    if head in {"arka_rag", "rag_skill"}:
        action = parts[0].lower()
        payload = {"action": action}
        if action in {"ingest", "codebase_ingest", "codebase-ingest", "batch_ingest", "batch-ingest"}:
            if len(parts) < 2:
                raise ValueError(f"path is required for {action}")
            payload["path"] = parts[1]
            if action.startswith("codebase") and "-n" in parts:
                idx = parts.index("-n")
                if idx + 1 < len(parts):
                    payload["name"] = parts[idx + 1]
        elif action == "ask":
            doc = None
            question_parts: list[str] = []
            i = 1
            while i < len(parts):
                if parts[i] in {"-d", "--doc"} and i + 1 < len(parts):
                    doc = parts[i + 1]
                    i += 2
                    continue
                question_parts.append(parts[i])
                i += 1
            payload["document"] = doc
            payload["question"] = " ".join(question_parts).strip()
            if not payload["question"]:
                raise ValueError("question is required for ask")
        return "arka_rag", payload

    if head in {"arka_ocr", "ocr_skill"}:
        action = parts[0].lower()
        if action in {"extract", "pdf", "auto"} and len(parts) >= 2:
            payload = {"action": action, "path": parts[1]}
            for i, token in enumerate(parts):
                if token in {"-o", "--output"} and i + 1 < len(parts):
                    payload["output"] = parts[i + 1]
                if token == "--language" and i + 1 < len(parts):
                    payload["language"] = parts[i + 1]
            return "arka_ocr", payload
        if action in {"extract", "pdf", "auto"}:
            raise ValueError("path is required")
    return None


def _handle_arka_skill(arguments: dict[str, Any]) -> str:
    skill = str(arguments.get("skill") or arguments.get("name") or "").strip()
    if not skill:
        raise ValueError("skill is required")
    try:
        from arka.core.skill_requirements import preflight_skill

        head = skill.split()[0].replace("-", "_")
        ok, msg = preflight_skill(head)
        if not ok and not arguments.get("force"):
            raise ValueError(msg)
    except ImportError:
        pass
    args = arguments.get("args") or []
    routed = _direct_mcp_from_skill(skill, args)
    if routed is not None:
        tool_name, tool_args = routed
        try:
            from arka.integrations.mcp_logs import log_mcp_event

            log_mcp_event(
                "server.route_decision",
                tool="arka_skill",
                route_via="skill_direct",
                route_target=tool_name,
                prompt=skill,
                args_summary=tool_args,
            )
        except ImportError:
            pass
        return call_mcp_tool(tool_name, tool_args)
    skill_line = _build_skill_line(skill, args)
    try:
        code, output = _run_skill_captured(skill_line, allow_browser=bool(arguments.get("allow_browser", False)))
        if code != 0 and not output:
            raise RuntimeError(f"skill exited {code}")
        if output:
            return output
        return f"Skill {skill!r} completed (exit {code})"
    except ImportError as exc:
        raise RuntimeError(f"dispatch unavailable: {exc}") from exc


def _handle_arka_capabilities(arguments: dict[str, Any]) -> str:
    """Return the current MCP and dispatch-backed capability catalog."""
    include_internal = bool(arguments.get("include_internal", False))
    try:
        skill_dir = Path(__file__).resolve().parents[1] / "agent"
        names = sorted(path.stem for path in skill_dir.glob("*.py") if path.stem != "__init__")
        tools = sorted(tool.name for tool in _build_tools() if tool.name not in _mcp_disabled_tools())
        from arka.integrations.mcp_local_files import (
            LOCAL_FILE_TOOL_NOTICE,
            MCP_LOCAL_FILE_TOOLS,
            agent_execution_rules_payload,
        )

        payload = {
            "mcp_tools": tools,
            "dispatch_skills": names,
            "mcp_disabled_by_default": {
                "tools": sorted(_mcp_disabled_tools()),
                "skill_heads": sorted(_mcp_disabled_skill_heads()),
            },
            "agent_execution_rules": agent_execution_rules_payload(),
            "local_file_tools": {
                "tools": sorted(MCP_LOCAL_FILE_TOOLS & set(tools)),
                "notice": LOCAL_FILE_TOOL_NOTICE,
                "use_when": (
                    "Prefer arka_ocr and arka_rag when the agent can read paths on the local machine "
                    "(e.g. Cursor workspace files). Do not call them from cloud agents without mounted files."
                ),
                "verify_with": (
                    "Follow agent_execution_rules.incremental_verify: demo on one local file first, "
                    "confirm output, then a second file — only then report verified."
                ),
            },
            "umbrella_tool": {
                "name": "arka_route",
                "use_when": "The user gives a natural-language Arka request or you are unsure which specific MCP tool/skill to call.",
            },
        }
        if not include_internal:
            payload["dispatch_skills"] = [name for name in names if not name.startswith("_")]
        return json.dumps(payload, indent=2)
    except (OSError, ImportError) as exc:
        raise RuntimeError(f"capability catalog unavailable: {exc}") from exc


def _handle_arka_route(arguments: dict[str, Any]) -> str:
    """Route arbitrary natural language through Arka, not just design skills."""
    prompt = str(arguments.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    try:
        from arka.core.just_ai import is_just_ai

        if is_just_ai():
            try:
                from arka.integrations.mcp_logs import log_mcp_event

                log_mcp_event(
                    "server.route_decision",
                    tool="arka_route",
                    route_via="just_ai",
                    route_target="arka_ask",
                    prompt=prompt,
                )
            except ImportError:
                pass
            return _handle_arka_ask(arguments)
    except ImportError:
        pass
    try:
        from arka.router import route

        decision = route(prompt)
        skill = getattr(decision, "skill", "") or ""
        try:
            from arka.integrations.mcp_logs import log_mcp_event

            log_mcp_event(
                "server.route_decision",
                tool="arka_route",
                route_via="router",
                route_target=skill or "none",
                prompt=prompt,
            )
        except ImportError:
            pass
        if not skill:
            return "No Arka route found; use arka_ask for general questions."
        code, output = _run_skill_captured(skill)
        return output or f"Routed `{skill}` (exit {code})"
    except ImportError as exc:
        raise RuntimeError(f"routing unavailable: {exc}") from exc


def _handle_arka_repo_map(arguments: dict[str, Any]) -> str:
    depth = _mcp_int(arguments.get("depth"), 2)
    include_symbols = bool(arguments.get("symbols", True))
    path_arg = str(arguments.get("path") or "").strip()
    try:
        from arka.agent.pr_check import git_root
        from arka.agent.repo_map import map_text

        root = Path(path_arg).expanduser().resolve() if path_arg else git_root()
        if root is None or not root.is_dir():
            root = Path.cwd()
        return map_text(
            root,
            depth=max(1, min(depth, 5)),
            include_symbols=include_symbols,
        )
    except ImportError as exc:
        raise RuntimeError(f"repo_map unavailable: {exc}") from exc


def _handle_arka_heartbeat(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    activity = str(arguments.get("activity") or "mcp.ping").strip()
    try:
        from arka.integrations.heartbeat import history, ping, status

        if action == "ping":
            ping(activity, source="mcp")
            return f"Heartbeat ping: {activity}"
        if action == "history":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(history(limit=max(1, min(limit, 100))), indent=2)
        if action == "status":
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                status(json_out=bool(arguments.get("json")))
            return buf.getvalue().strip() or "Heartbeat status unavailable"
        raise ValueError("action must be ping, status, or history")
    except ImportError as exc:
        raise RuntimeError(f"heartbeat unavailable: {exc}") from exc


def _handle_arka_sessions(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    channel = str(arguments.get("channel") or "").strip() or None
    chat_id = str(arguments.get("chat_id") or "").strip() or None
    try:
        from arka.integrations.message_sessions import (
            context_for,
            list_sessions,
            push,
            reset,
            resume_payload,
            silence_check,
            status,
        )

        if action == "list":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(list_sessions(limit=max(1, min(limit, 200))), indent=2)
        if action == "status":
            return json.dumps(status(channel, chat_id), indent=2)
        if action == "context":
            if not channel:
                raise ValueError("channel is required for context")
            limit_chars = _mcp_int(arguments.get("limit_chars"), 3000)
            text = context_for(
                channel,
                chat_id or "default",
                limit_chars=max(200, limit_chars),
            )
            return text or "(no session context)"
        if action == "resume":
            if not channel:
                raise ValueError("channel is required for resume")
            limit = _mcp_int(arguments.get("limit"), 12)
            return json.dumps(
                resume_payload(channel, chat_id or "default", limit=limit),
                indent=2,
            )
        if action == "silence_check":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise ValueError("text is required for silence_check")
            return json.dumps(silence_check(text), indent=2)
        if action == "push":
            if not channel:
                raise ValueError("channel is required for push")
            role = str(arguments.get("role") or "user").strip().lower()
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise ValueError("text is required for push")
            title = str(arguments.get("title") or "").strip()
            code, err = push(
                channel,
                chat_id or "default",
                role,
                text,
                title=title,
            )
            if code != 0:
                raise RuntimeError(err or "session push failed")
            return f"Session turn stored: {text[:200]}"
        if action == "reset":
            if not channel:
                raise ValueError("channel is required for reset")
            code = reset(channel, chat_id or "default")
            if code != 0:
                raise RuntimeError("session reset failed")
            return f"Session reset: {channel}:{chat_id or 'default'}"
        raise ValueError(
            "action must be list, status, context, resume, silence_check, push, or reset"
        )
    except ImportError as exc:
        raise RuntimeError(f"message_sessions unavailable: {exc}") from exc


def _handle_arka_routines(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.routines import (
            _security_gate_action,
            list_routines,
            normalize_action,
            routine_add,
            routine_remove,
            routine_set_enabled,
        )

        if action == "list":
            enabled_only = bool(arguments.get("enabled_only", False))
            rows = list_routines(enabled_only=enabled_only)
            return json.dumps(rows, indent=2)
        if action == "add":
            schedule = str(arguments.get("schedule") or "").strip()
            task = str(
                arguments.get("task")
                or arguments.get("routine_action")
                or ""
            ).strip()
            if not schedule:
                raise ValueError("schedule is required for add")
            if not task:
                raise ValueError("task is required for add")
            name = str(arguments.get("name") or arguments.get("id") or "").strip()
            normalized = normalize_action(task) or task
            if not _security_gate_action(normalized):
                raise RuntimeError("routine blocked by security gate")
            with contextlib.redirect_stdout(io.StringIO()):
                rid = routine_add(schedule, normalized, name=name, auto_install=False)
            return json.dumps(
                {"id": rid, "schedule": schedule, "action": normalized, "enabled": True},
                indent=2,
            )
        if action == "remove":
            rid = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not rid:
                raise ValueError("id is required for remove")
            before = {r["id"] for r in list_routines()}
            if rid not in before:
                raise ValueError(f"No routine {rid}")
            with contextlib.redirect_stdout(io.StringIO()):
                routine_remove(rid)
            return f"Removed routine {rid}"
        if action in {"enable", "disable"}:
            rid = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not rid:
                raise ValueError(f"id is required for {action}")
            row = routine_set_enabled(rid, action == "enable")
            if not row:
                raise ValueError(f"No routine {rid}")
            return json.dumps(row, indent=2)
        raise ValueError("action must be list, add, remove, enable, or disable")
    except ImportError as exc:
        raise RuntimeError(f"routines unavailable: {exc}") from exc


def _handle_arka_batch(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    name = str(arguments.get("name") or arguments.get("batch") or "default").strip() or "default"
    try:
        from arka.agent import batch

        if action == "start":
            until = str(arguments.get("until") or arguments.get("due") or "").strip()
            if not until:
                raise ValueError("until is required for start (e.g. '6pm', 'in 1 hour')")
            try:
                created = batch.start_batch(name=name, until=until)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            return json.dumps(batch.batch_to_dict(created), indent=2)
        if action == "add":
            prompt = str(arguments.get("prompt") or arguments.get("text") or "").strip()
            if not prompt:
                raise ValueError("prompt is required for add")
            until = str(arguments.get("until") or arguments.get("due") or "").strip()
            try:
                updated = batch.add_to_batch(name=name, prompt=prompt, until=until)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            return json.dumps(batch.batch_to_dict(updated), indent=2)
        if action == "list":
            rows = batch.batches_to_dict(batch.list_batches())
            return json.dumps(rows, indent=2)
        if action == "clear":
            existed = batch.clear_batch(name=name)
            return json.dumps({"name": name, "cleared": existed}, indent=2)
        if action in {"run", "due"}:
            print_only = bool(arguments.get("print_only", arguments.get("print", False)))
            keep = bool(arguments.get("keep", False))
            try:
                code, message = batch.run_batch(
                    name=name,
                    print_only=print_only,
                    keep=keep,
                    due_only=action == "due",
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if print_only or "not due yet" in message:
                return message
            if code != 0:
                raise RuntimeError(message)
            return message
        raise ValueError("action must be start, add, list, run, due, or clear")
    except ImportError as exc:
        raise RuntimeError(f"batch unavailable: {exc}") from exc


def _handle_arka_service_autostart(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.service_autostart import (
            autostart_status,
            get_service,
            install_autostart,
            list_services,
            run_service,
            service_add,
            service_remove,
            uninstall_autostart,
        )

        if action == "list":
            return json.dumps(list_services(), indent=2)
        if action == "add":
            service_id = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not service_id:
                raise ValueError("id is required for add")
            command = str(arguments.get("command") or "").strip()
            script = str(arguments.get("script") or "").strip()
            description = str(arguments.get("description") or arguments.get("desc") or "").strip()
            if not command and not script and not description:
                raise ValueError("command, script, or description is required for add")
            env_raw = arguments.get("env")
            env_map: dict[str, str] = {}
            if isinstance(env_raw, dict):
                env_map = {str(k): str(v) for k, v in env_raw.items()}
            entry = service_add(
                service_id=service_id,
                name=str(arguments.get("display_name") or arguments.get("label") or "").strip(),
                command=command,
                script=script,
                description=description,
                workdir=str(arguments.get("workdir") or "").strip(),
                env=env_map,
            )
            return json.dumps(entry, indent=2)
        if action == "install":
            service_id = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not service_id:
                raise ValueError("id is required for install")
            with contextlib.redirect_stdout(io.StringIO()):
                code = install_autostart(service_id)
            if code != 0:
                raise RuntimeError(f"install failed with exit code {code}")
            rows = autostart_status(service_id)
            return json.dumps(rows[0] if rows else {"id": service_id, "installed": "true"}, indent=2)
        if action == "uninstall":
            service_id = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not service_id:
                raise ValueError("id is required for uninstall")
            with contextlib.redirect_stdout(io.StringIO()):
                code = uninstall_autostart(service_id)
            if code != 0:
                raise RuntimeError(f"uninstall failed with exit code {code}")
            return f"Removed autostart for {service_id}"
        if action == "remove":
            service_id = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not service_id:
                raise ValueError("id is required for remove")
            if not service_remove(service_id):
                raise ValueError(f"No service {service_id}")
            return f"Removed service {service_id}"
        if action == "status":
            service_id = str(arguments.get("id") or arguments.get("name") or "").strip()
            rows = autostart_status(service_id or None)
            if service_id and not rows:
                raise ValueError(f"No service {service_id}")
            return json.dumps(rows, indent=2)
        if action == "run":
            service_id = str(arguments.get("id") or arguments.get("name") or "").strip()
            if not service_id:
                raise ValueError("id is required for run")
            if not get_service(service_id):
                raise ValueError(f"No service {service_id}")
            with contextlib.redirect_stdout(io.StringIO()):
                code = run_service(service_id)
            return json.dumps({"id": service_id, "exit_code": code}, indent=2)
        raise ValueError("action must be list, add, install, uninstall, remove, status, or run")
    except ImportError as exc:
        raise RuntimeError(f"service_autostart unavailable: {exc}") from exc


def _handle_arka_session_memory(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.core.session_memory import append, clear, context_for, search, status

        if action == "append":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise ValueError("text is required for append")
            long_term = bool(arguments.get("long_term", False))
            with contextlib.redirect_stdout(io.StringIO()):
                code = append(text, long_term=long_term)
            if code != 0:
                raise RuntimeError("session memory append failed")
            return f"Session memory stored: {text[:200]}"
        if action == "search":
            query = str(arguments.get("query") or arguments.get("goal") or "").strip()
            limit = _mcp_int(arguments.get("limit"), 8)
            rows = search(query, limit=max(1, min(limit, 50)))
            payload = [{"file": rel, "text": body} for rel, body in rows]
            return json.dumps(payload, indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
            if not goal:
                raise ValueError("goal is required for context")
            limit_chars = _mcp_int(arguments.get("limit_chars"), 2500)
            text = context_for(goal, limit_chars=max(200, limit_chars))
            return text or "(no session memory context)"
        if action == "status":
            return json.dumps(status(), indent=2)
        if action == "clear":
            scope = str(arguments.get("scope") or "daily").strip()
            return json.dumps(clear(scope=scope), indent=2)
        raise ValueError("action must be append, search, context, status, or clear")
    except ImportError as exc:
        raise RuntimeError(f"session_memory unavailable: {exc}") from exc


def _handle_arka_subagent(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.subagent import (
            agent_status,
            list_agents,
            resume_payload,
            spawn,
            status_summary,
        )

        if action == "spawn":
            task = str(arguments.get("task") or "").strip()
            if not task:
                raise ValueError("task is required for spawn")
            sync = bool(arguments.get("sync", False))
            session_channel = str(arguments.get("session_channel") or "").strip()
            session_chat_id = str(arguments.get("session_chat_id") or "").strip()
            data, err = spawn(
                task,
                session_channel=session_channel,
                session_chat_id=session_chat_id,
                background=not sync,
            )
            if err:
                raise RuntimeError(err)
            assert data is not None
            return json.dumps(data, indent=2)
        if action == "list":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(list_agents(limit=max(1, min(limit, 100))), indent=2)
        if action == "resume":
            agent_id = str(arguments.get("agent_id") or arguments.get("id") or "").strip()
            if not agent_id:
                raise ValueError("agent_id is required for resume")
            data = resume_payload(agent_id)
            if not data:
                raise ValueError(f"unknown sub-agent: {agent_id}")
            return json.dumps(data, indent=2)
        if action == "status":
            agent_id = str(arguments.get("agent_id") or arguments.get("id") or "").strip()
            if agent_id:
                data = agent_status(agent_id)
                if not data:
                    raise ValueError(f"unknown sub-agent: {agent_id}")
                return json.dumps(data, indent=2)
            return json.dumps(status_summary(), indent=2)
        raise ValueError("action must be spawn, list, status, or resume")
    except ImportError as exc:
        raise RuntimeError(f"subagent unavailable: {exc}") from exc


def _handle_arka_parallel(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "plan").strip().lower()
    try:
        from arka.agent.parallel_plan import (
            decompose_parallel,
            format_plan,
            load_run,
            run_parallel_subagents,
        )

        if action == "plan":
            goal = str(arguments.get("goal") or arguments.get("task") or "").strip()
            if not goal:
                raise ValueError("goal is required for plan")
            plan = decompose_parallel(goal)
            if arguments.get("json", True):
                return json.dumps(plan.to_dict(), indent=2)
            return format_plan(plan)
        if action == "run":
            goal = str(arguments.get("goal") or arguments.get("task") or "").strip()
            if not goal:
                raise ValueError("goal is required for run")
            plan = decompose_parallel(goal)
            if not plan.tasks:
                raise ValueError("no tasks produced from goal")
            record = run_parallel_subagents(
                plan,
                sync=bool(arguments.get("sync", False)),
                plan_id=str(arguments.get("plan_id") or "").strip() or None,
            )
            return json.dumps(record, indent=2)
        if action == "status":
            plan_id = str(arguments.get("plan_id") or arguments.get("id") or "").strip()
            if not plan_id:
                raise ValueError("plan_id is required for status")
            record = load_run(plan_id)
            if not record:
                raise ValueError(f"unknown parallel run: {plan_id}")
            return json.dumps(record, indent=2)
        raise ValueError("action must be plan, run, or status")
    except ImportError as exc:
        raise RuntimeError(f"parallel_plan unavailable: {exc}") from exc


def _handle_arka_jules(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.agent.jules import (
            assign,
            assign_issue,
            cancel_session,
            create_pr,
            list_sessions,
            session_status,
            status_summary,
        )

        if action == "assign":
            task = str(arguments.get("task") or "").strip()
            if not task:
                raise ValueError("task is required for assign")
            sync = bool(arguments.get("sync", False))
            if sync:
                os.environ["JULES_SYNC"] = "1"
            max_steps = _mcp_int(arguments.get("max_steps"), 20)
            open_pr = bool(arguments.get("open_pr", False))
            branch = bool(arguments.get("branch", False))
            data, err = assign(
                task,
                max_steps=max_steps,
                open_pr=open_pr,
                branch=branch,
                background=not sync,
            )
            if err:
                raise RuntimeError(err)
            assert data is not None
            return json.dumps(data, indent=2)
        if action == "issue":
            issue_number = _mcp_int(arguments.get("issue_number") or arguments.get("issue"), 0)
            if issue_number <= 0:
                raise ValueError("issue_number is required for issue")
            sync = bool(arguments.get("sync", False))
            if sync:
                os.environ["JULES_SYNC"] = "1"
            repo = str(arguments.get("repo") or "").strip()
            open_pr = bool(arguments.get("open_pr", True))
            max_steps = _mcp_int(arguments.get("max_steps"), 20)
            data, err = assign_issue(
                issue_number,
                repo=repo,
                max_steps=max_steps,
                open_pr=open_pr,
                background=not sync,
            )
            if err:
                raise RuntimeError(err)
            assert data is not None
            return json.dumps(data, indent=2)
        if action == "list":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(list_sessions(limit=max(1, min(limit, 100))), indent=2)
        if action == "status":
            session_id = str(arguments.get("session_id") or arguments.get("id") or "").strip()
            if session_id:
                data = session_status(session_id)
                if not data:
                    raise ValueError(f"unknown session: {session_id}")
                return json.dumps(data, indent=2)
            return json.dumps(status_summary(), indent=2)
        if action == "cancel":
            session_id = str(arguments.get("session_id") or arguments.get("id") or "").strip()
            if not session_id:
                raise ValueError("session_id is required for cancel")
            ok, msg = cancel_session(session_id)
            if not ok:
                raise RuntimeError(msg)
            return json.dumps({"ok": True, "message": msg}, indent=2)
        if action == "pr":
            session_id = str(arguments.get("session_id") or arguments.get("id") or "").strip()
            if not session_id:
                raise ValueError("session_id is required for pr")
            url, err = create_pr(session_id)
            if err:
                raise RuntimeError(err)
            return json.dumps({"pr_url": url}, indent=2)
        raise ValueError("action must be assign, issue, list, status, cancel, or pr")
    except ImportError as exc:
        raise RuntimeError(f"jules unavailable: {exc}") from exc


def _handle_arka_webhook(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations.webhook import health_payload, status_info

        if action == "status":
            return json.dumps(status_info(), indent=2)
        if action == "health":
            return json.dumps(health_payload(), indent=2)
        raise ValueError("action must be status or health")
    except ImportError as exc:
        raise RuntimeError(f"webhook unavailable: {exc}") from exc


def _handle_arka_convert_media(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "convert").strip().lower()
    try:
        from arka.media.convert_media import (
            capabilities_catalog,
            cmd_check,
            convert_media_result,
            media_info,
            nl_to_argv,
        )

        if action == "capabilities":
            return json.dumps(capabilities_catalog(), indent=2)
        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "detect":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=detect")
            return json.dumps(media_info(path), indent=2)
        if action == "formats":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=formats")
            info = media_info(path)
            return json.dumps(
                {
                    "input": info["input"],
                    "media_type": info["media_type"],
                    "formats": info["output_formats"],
                },
                indent=2,
            )
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "convert_media " + " ".join(argv) if argv else ""}, indent=2)
        if action == "convert":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=convert")
            target = str(
                arguments.get("to")
                or arguments.get("format")
                or arguments.get("target")
                or arguments.get("formats")
                or "all"
            ).strip()
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            quality = arguments.get("quality")
            width = arguments.get("width")
            height = arguments.get("height")
            trim_start = arguments.get("trim_start")
            trim_duration = arguments.get("trim_duration")
            result = convert_media_result(
                path,
                target=target,
                output=output,
                quality=_mcp_int_optional(quality),
                width=_mcp_int_optional(width),
                height=_mcp_int_optional(height),
                trim_start=_mcp_float_optional(trim_start),
                trim_duration=_mcp_float_optional(trim_duration),
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be convert, detect, formats, capabilities, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"convert_media unavailable: {exc}") from exc


def _handle_arka_noise_remove(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "remove").strip().lower()
    try:
        from arka.media.noise_remove import cmd_check, media_info, nl_to_argv, noise_remove_result

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "detect":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=detect")
            return json.dumps(media_info(path), indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "noise_remove " + " ".join(argv) if argv else ""}, indent=2)
        if action == "remove":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=remove")
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            strength = arguments.get("strength")
            noise_floor = arguments.get("noise_floor")
            audio_only = bool(arguments.get("audio_only"))
            result = noise_remove_result(
                path,
                output=output,
                strength=float(strength) if strength is not None else 12,
                noise_floor=_mcp_float_optional(noise_floor),
                audio_only=audio_only,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be remove, detect, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"noise_remove unavailable: {exc}") from exc


def _handle_arka_edit_video(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "trim").strip().lower()
    try:
        from arka.media.edit_video import cmd_check, edit_video_result, media_info, nl_to_argv

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "detect":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=detect")
            return json.dumps(media_info(path), indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "edit_video " + " ".join(argv) if argv else ""}, indent=2)
        if action in {"trim", "concat", "overlay-text", "overlay", "extract-audio", "extract", "crop", "resize", "mux-audio", "mux"}:
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip() or None
            paths_raw = arguments.get("paths") or arguments.get("inputs")
            paths = [str(p) for p in paths_raw] if isinstance(paths_raw, list) else None
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            text = str(arguments.get("text") or "").strip() or None
            audio = str(arguments.get("audio") or "").strip() or None
            result = edit_video_result(
                action,
                path=path,
                paths=paths,
                output=output,
                start=float(arguments.get("start") or 0),
                duration=_mcp_float_optional(arguments.get("duration")),
                end=_mcp_float_optional(arguments.get("end")),
                text=text,
                position=str(arguments.get("position") or "bottom"),
                fontsize=int(arguments.get("fontsize") or 48),
                color=str(arguments.get("color") or "white"),
                width=int(arguments["width"]) if arguments.get("width") is not None else None,
                height=int(arguments["height"]) if arguments.get("height") is not None else None,
                x=int(arguments.get("x") or 0),
                y=int(arguments.get("y") or 0),
                format=str(arguments.get("format") or "mp3"),
                audio=audio,
                shortest=not bool(arguments.get("no_shortest")),
            )
            return json.dumps(result, indent=2)
        raise ValueError(
            "action must be trim, concat, overlay-text, extract-audio, crop, resize, mux-audio, detect, check, or parse"
        )
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"edit_video unavailable: {exc}") from exc


def _handle_arka_dub_video(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "dub").strip().lower()
    try:
        from arka.media.dub_video import cmd_check, dub_video_result, nl_to_argv
        from arka.media.edit_video import media_info

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "detect":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            if not path:
                raise ValueError("path is required when action=detect")
            return json.dumps(media_info(path), indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "dub_video " + " ".join(argv) if argv else ""}, indent=2)
        if action == "dub":
            path = str(arguments.get("path") or arguments.get("file") or arguments.get("input") or "").strip()
            target = str(arguments.get("target") or arguments.get("target_lang") or arguments.get("language") or "").strip()
            if not path or not target:
                raise ValueError("path and target are required when action=dub")
            from arka.core.skill_requirements import exit_if_blocked, preflight_skill

            need_stt = not (
                str(arguments.get("script") or arguments.get("script_text") or "").strip()
                or str(arguments.get("script_path") or "").strip()
            )
            checks = ["tts"] if not need_stt else ["stt", "tts"]
            ok, msg = preflight_skill("dub_video", extra={"checks": checks})
            if not ok:
                raise ValueError(msg)
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            script = str(arguments.get("script") or arguments.get("script_text") or "").strip() or None
            script_path = str(arguments.get("script_path") or "").strip()
            if script_path and not script:
                script = Path(script_path).expanduser().read_text(encoding="utf-8")
            result = dub_video_result(
                path,
                target_lang=target,
                output=output,
                source_lang=str(arguments.get("source") or arguments.get("source_lang") or "auto"),
                script=script,
                tts=str(arguments.get("tts") or "auto"),
                voice=str(arguments.get("voice") or "").strip() or None,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be dub, detect, check, or parse")
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"dub_video unavailable: {exc}") from exc


def _handle_arka_fetch_lyrics(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "fetch").strip().lower()
    try:
        from arka.media.fetch_lyrics import (
            cmd_check,
            fetch_lyrics,
            fetch_lyrics_result,
            nl_to_argv,
            parse_song_query,
            translate_lyrics,
        )

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "fetch_lyrics " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "fetch":
            artist = str(arguments.get("artist") or "").strip()
            title = str(arguments.get("title") or "").strip()
            query = str(arguments.get("query") or arguments.get("text") or "").strip()
            if query and (not artist or not title):
                artist, title = parse_song_query(query)
            if not artist or not title:
                raise ValueError("artist and title (or query) are required when action=fetch")
            result = fetch_lyrics(artist, title)
            output = str(arguments.get("output") or arguments.get("out") or "").strip()
            if output:
                from arka.media.fetch_lyrics import _save_text

                saved = _save_text(Path(output).expanduser(), str(result["lyrics"]))
                result["output"] = str(saved)
            return json.dumps(result, indent=2, ensure_ascii=False)
        if action == "translate":
            artist = str(arguments.get("artist") or "").strip()
            title = str(arguments.get("title") or "").strip()
            query = str(arguments.get("query") or arguments.get("text") or "").strip()
            if query and (not artist or not title):
                artist, title = parse_song_query(query)
            target = str(
                arguments.get("target")
                or arguments.get("target_lang")
                or arguments.get("language")
                or ""
            ).strip()
            if not artist or not title or not target:
                raise ValueError("artist, title (or query), and target are required when action=translate")
            result = fetch_lyrics_result(
                artist,
                title,
                target_lang=target,
                style=str(arguments.get("style") or "").strip() or None,
                generate=bool(arguments.get("generate") or arguments.get("remix")),
                output=str(arguments.get("output") or arguments.get("out") or "").strip() or None,
                duration=int(arguments["duration"]) if arguments.get("duration") is not None else None,
                instrumental=bool(arguments.get("instrumental")),
            )
            return json.dumps(result, indent=2, ensure_ascii=False)
        if action == "translate_text":
            lyrics = str(arguments.get("lyrics") or arguments.get("text") or "").strip()
            target = str(
                arguments.get("target")
                or arguments.get("target_lang")
                or arguments.get("language")
                or ""
            ).strip()
            if not lyrics or not target:
                raise ValueError("lyrics and target are required when action=translate_text")
            result = translate_lyrics(
                lyrics,
                target_lang=target,
                source_lang=str(arguments.get("source") or arguments.get("source_lang") or "auto"),
            )
            return json.dumps(result, indent=2, ensure_ascii=False)
        raise ValueError("action must be fetch, translate, translate_text, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"fetch_lyrics unavailable: {exc}") from exc


def _handle_arka_play_website_game(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "open").strip().lower()
    allow_browser = bool(
        arguments.get("allow_browser")
        or arguments.get("yes")
        or os.environ.get("ARKA_MCP_ALLOW_BROWSER") == "1"
    )
    if action in {"open", "search", "agent"} and not allow_browser and not arguments.get("headless"):
        raise ValueError(
            "Opening a headed browser game requires allow_browser=true (or headless=true for CI). "
            "Opt in with ARKA_MCP_ENABLE_PERSONAL_SKILLS=1 for personal desktop skills."
        )
    try:
        from arka.agent.play_website_game import (
            cmd_check,
            nl_to_argv,
            open_game,
            play_website_game_result,
            search_games,
        )
        from arka.agent.game_agent import run_agent

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "play_website_game " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "open":
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("url is required when action=open")
            result = open_game(
                url,
                headless=bool(arguments.get("headless")),
                wait_seconds=_mcp_int_optional(arguments.get("wait_seconds")),
                auto_start=bool(arguments.get("auto_start")),
            )
            return json.dumps(result, indent=2, ensure_ascii=False)
        if action == "search":
            query = str(arguments.get("query") or arguments.get("text") or "").strip()
            if not query:
                raise ValueError("query is required when action=search")
            if arguments.get("open") or arguments.get("open_best"):
                result = play_website_game_result(
                    query=query,
                    headless=bool(arguments.get("headless")),
                    wait_seconds=_mcp_int_optional(arguments.get("wait_seconds")),
                    auto_start=bool(arguments.get("auto_start")),
                    open_best=True,
                )
            else:
                results = search_games(query)
                result = {"query": query, "results": results, "ok": bool(results)}
            return json.dumps(result, indent=2, ensure_ascii=False)
        if action == "agent":
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("url is required when action=agent")
            learn_arg = arguments.get("learn")
            learn = None if learn_arg is None else bool(learn_arg)
            rl_arg = arguments.get("rl")
            rl = None if rl_arg is None else bool(rl_arg)
            backend = str(arguments.get("vision_backend") or "").strip().lower() or None
            if backend == "auto":
                backend = None
            result = run_agent(
                url,
                turns=_mcp_int_optional(arguments.get("turns")),
                vision_backend=backend,
                learn=learn,
                rl=rl,
                headless=bool(arguments.get("headless")),
                auto_start=bool(arguments.get("auto_start", True)),
            )
            return json.dumps(result, indent=2, ensure_ascii=False)
        raise ValueError("action must be open, search, agent, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"play_website_game unavailable: {exc}") from exc


def _handle_arka_verify_web_interaction(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "check").strip().lower()
    allow_browser = bool(
        arguments.get("allow_browser")
        or arguments.get("yes")
        or os.environ.get("ARKA_MCP_ALLOW_BROWSER") == "1"
    )
    headed = bool(arguments.get("headed"))
    headless = bool(arguments.get("headless")) or not headed
    if action == "check" and headed and not allow_browser:
        raise ValueError(
            "Headed browser verification requires allow_browser=true (or use headless=true for CI). "
            "Opt in with ARKA_MCP_ENABLE_PERSONAL_SKILLS=1 for personal desktop skills."
        )
    try:
        from arka.agent.verify_web_interaction import (
            build_interaction_plan,
            cmd_check_deps,
            nl_to_argv,
            parse_code_context,
            parse_spec,
            verify,
        )

        if action == "check-deps":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check_deps(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if text:
                argv = nl_to_argv(text)
                return json.dumps(
                    {"argv": argv, "command": "verify_web_interaction " + " ".join(argv) if argv else ""},
                    indent=2,
                )
            context = parse_code_context(arguments["context"]) if arguments.get("context") else {
                "selectors": [], "texts": [], "routes": [], "hrefs": []
            }
            spec_steps = parse_spec(arguments["spec"]) if arguments.get("spec") else []
            url = str(arguments.get("url") or "http://127.0.0.1:3000")
            plan = build_interaction_plan(url, context=context, spec_steps=spec_steps)
            return json.dumps({"plan": plan, "parsed": context, "spec_steps": spec_steps}, indent=2)
        if action == "check":
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("url is required when action=check")
            result = verify(
                url,
                context_path=str(arguments["context"]) if arguments.get("context") else None,
                spec_path=str(arguments["spec"]) if arguments.get("spec") else None,
                repo=str(arguments["repo"]) if arguments.get("repo") else None,
                headless=headless,
                output=str(arguments["output"]) if arguments.get("output") else None,
                settle_seconds=_mcp_float_optional(arguments.get("settle_seconds")),
                vision=(
                    False
                    if arguments.get("no_vision")
                    else True
                    if arguments.get("vision") or arguments.get("vllm_verify")
                    else None
                ),
                vision_backend=str(arguments["vision_backend"]) if arguments.get("vision_backend") else None,
                vllm_verify=bool(arguments.get("vllm_verify")),
            )
            return json.dumps(result, indent=2, ensure_ascii=False)
        raise ValueError("action must be check, parse, or check-deps")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"verify_web_interaction unavailable: {exc}") from exc


def _handle_arka_safety_advice(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "advice").strip().lower()
    try:
        from arka.agent.safety_advice import (
            TOPICS,
            format_advice,
            nl_to_argv,
            safety_advice_result,
        )

        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "safety_advice " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "topics":
            return json.dumps(
                {key: val["title"] for key, val in TOPICS.items()},
                indent=2,
                ensure_ascii=False,
            )
        if action == "resources":
            topic = str(arguments.get("topic") or "domestic_violence").strip()
            region = str(arguments.get("region") or "").strip() or None
            payload = safety_advice_result("", topic=topic, region=region)
            return json.dumps(
                {
                    "topic": payload["topic"],
                    "region": payload["region"],
                    "emergency": payload["emergency"],
                    "resources": payload["resources"],
                },
                indent=2,
                ensure_ascii=False,
            )
        if action == "advice":
            text = str(
                arguments.get("text")
                or arguments.get("query")
                or arguments.get("prompt")
                or arguments.get("goal")
                or ""
            ).strip()
            topic = str(arguments.get("topic") or "").strip() or None
            region = str(arguments.get("region") or "").strip() or None
            if not text and not topic:
                raise ValueError("text or topic is required when action=advice")
            payload = safety_advice_result(text, topic=topic, region=region)
            if bool(arguments.get("markdown", True)) and not bool(arguments.get("json")):
                return format_advice(payload)
            return json.dumps(payload, indent=2, ensure_ascii=False)
        raise ValueError("action must be advice, resources, topics, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"safety_advice unavailable: {exc}") from exc


def _handle_arka_signoz_publish(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "run").strip().lower()
    try:
        import argparse
        from dataclasses import asdict

        from arka.agent.signoz_publish import (
            build_plan,
            cmd_check,
            nl_to_argv,
            preflight,
            run_publish,
        )

        if action == "check":
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip(), "preflight": asdict(preflight())}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "signoz_publish " + " ".join(argv) if argv else ""}, indent=2)
        if action in ("run", "publish", "dry-run"):
            ns = argparse.Namespace(
                message=str(arguments.get("message") or arguments.get("commit_message") or "").strip() or None,
                m=str(arguments.get("message") or arguments.get("commit_message") or "").strip() or None,
                topic=str(arguments.get("topic") or "").strip() or None,
                content=str(arguments.get("content") or arguments.get("content_path") or "").strip() or None,
                content_text=str(arguments.get("content_text") or "").strip() or None,
                generate_blog=bool(arguments.get("generate_blog")),
                skip_blog=bool(arguments.get("skip_blog")),
                skip_git=bool(arguments.get("skip_git")),
                skip_deploy=bool(arguments.get("skip_deploy")),
                vercel_dir=str(arguments.get("vercel_dir") or "landing"),
                production=bool(arguments.get("production")),
                all_files=bool(arguments.get("all_files")),
                dry_run=action == "dry-run" or bool(arguments.get("dry_run")),
                yes=bool(arguments.get("yes") or arguments.get("confirm")),
                json=True,
            )
            if action == "dry-run":
                ns.yes = False
                ns.dry_run = True
                plan = build_plan(ns)
            elif ns.yes or ns.dry_run:
                plan = run_publish(ns)
            else:
                plan = build_plan(ns)
            return json.dumps(plan.to_dict(), indent=2)
        raise ValueError("action must be run, publish, dry-run, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"signoz_publish unavailable: {exc}") from exc


def _handle_arka_model_video(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "render").strip().lower()
    try:
        from arka.media.model_video import cmd_check, model_video_result, nl_to_argv

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "model_video " + " ".join(argv) if argv else ""}, indent=2)
        if action == "render":
            source = str(
                arguments.get("source")
                or arguments.get("model")
                or arguments.get("path")
                or ""
            ).strip()
            if not source:
                raise ValueError("source is required when action=render")
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            backend = str(arguments.get("backend") or arguments.get("mode") or "").strip() or None
            frames = arguments.get("frames")
            fps = arguments.get("fps")
            size = int(arguments.get("size") or 1024)
            angle = str(arguments.get("angle") or "auto").strip()
            task = str(arguments.get("task") or "").strip()
            renders = str(arguments.get("renders") or "").strip() or None
            slide_duration = float(arguments.get("slide_duration") or 0.5)
            audio = str(arguments.get("audio") or "").strip() or None
            result = model_video_result(
                source,
                output=output,
                backend=backend,
                frames=int(frames) if frames is not None else None,
                fps=int(fps) if fps is not None else None,
                size=size,
                angle=angle,
                task=task,
                renders=renders,
                slide_duration=slide_duration,
                audio=audio,
            )
            return json.dumps(result, indent=2)
        if action == "animate":
            from arka.media.model_video import animation_video_result

            source = str(
                arguments.get("source")
                or arguments.get("model")
                or arguments.get("path")
                or ""
            ).strip()
            if not source:
                raise ValueError("source is required when action=animate")
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            frames = arguments.get("frames")
            fps = arguments.get("fps")
            size = int(arguments.get("size") or 1024)
            background_raw = arguments.get("background")
            background = True if background_raw is None else bool(background_raw)
            result = animation_video_result(
                source,
                output=output,
                frames=int(frames) if frames is not None else None,
                fps=int(fps) if fps is not None else None,
                size=size,
                background=background,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be render, animate, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"model_video unavailable: {exc}") from exc


def _handle_arka_create_video(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "create").strip().lower()
    try:
        from arka.media.create_video import cmd_check, create_video_result, nl_to_argv

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps({"argv": argv, "command": "create_video " + " ".join(argv) if argv else ""}, indent=2)
        if action == "create":
            mode = str(arguments.get("mode") or "slideshow").strip().lower()
            sources_raw = arguments.get("sources") or arguments.get("images") or arguments.get("paths")
            sources = [str(item).strip() for item in sources_raw] if isinstance(sources_raw, list) else None
            if sources is None:
                single = str(arguments.get("source") or arguments.get("path") or "").strip()
                sources = [single] if single else None
            image = str(arguments.get("image") or "").strip() or None
            audio = str(arguments.get("audio") or "").strip() or None
            script = str(arguments.get("script") or "").strip() or None
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            slide_duration = arguments.get("slide_duration", arguments.get("duration", 3.0))
            transparent = bool(arguments.get("transparent") or arguments.get("alpha"))
            format_name = str(arguments.get("format") or "").strip() or None
            result = create_video_result(
                mode,
                sources=sources,
                image=image,
                audio=audio,
                script=script,
                output=output,
                slide_duration=float(slide_duration) if slide_duration is not None else 3.0,
                transparent=transparent,
                alpha=bool(arguments.get("alpha")),
                format_name=format_name,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be create, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"create_video unavailable: {exc}") from exc


def _handle_arka_compose_story(arguments: dict[str, Any]) -> str:
    import argparse

    action = str(arguments.get("action") or "compose").strip().lower()
    try:
        from arka.media.compose_story import cmd_check, nl_to_argv
        from arka.media.compose_video import cmd_compose, cmd_parse

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("topic") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "compose_story " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "compose":
            topic = str(arguments.get("topic") or arguments.get("text") or arguments.get("query") or "").strip()
            script = str(arguments.get("script") or "").strip() or None
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            scenes = arguments.get("scenes")
            duration = str(arguments.get("duration") or "").strip() or None
            ns = argparse.Namespace(
                topic=topic or None,
                script=script,
                llm=bool(arguments.get("llm", True)),
                script_provider="llm",
                api_url="",
                api_key_env="",
                api_header=[],
                scenes=int(scenes) if scenes is not None else None,
                duration=duration,
                output=output,
                mode=None,
                text=bool(arguments.get("text", True)),
                no_text=False,
                video_broll=False,
                use_only_ai_generated_images=bool(arguments.get("ai_images_only")),
                story=True,
                labeled=bool(arguments.get("labeled", True)),
                auto_fill=bool(arguments.get("auto_fill", True)),
                cmd="compose",
            )
            if not topic and not script:
                raise ValueError("topic or script is required when action=compose")
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_compose(ns)
            return json.dumps(
                {
                    "exit_code": code,
                    "output": output,
                    "log": buf.getvalue().strip(),
                },
                indent=2,
            )
        raise ValueError("action must be compose, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"compose_story unavailable: {exc}") from exc


def _handle_arka_terminal_video(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "build").strip().lower().replace("_", "-")
    try:
        from arka.media.terminal_video import cmd_check, nl_to_argv, terminal_video_result

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "terminal_video " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action in {"build", "capture", "export-images", "export"}:
            if action == "export":
                action = "export-images"
            result = terminal_video_result(
                action,
                project_dir=str(arguments.get("project_dir") or arguments.get("project") or "").strip() or None,
                captures=str(arguments.get("captures") or "").strip() or None,
                output=str(arguments.get("output") or arguments.get("out") or "").strip() or None,
                script=str(arguments.get("script") or "").strip() or None,
                skip_verify=bool(arguments.get("skip_verify") or arguments.get("skip_verify_frames")),
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be build, capture, export-images, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"terminal_video unavailable: {exc}") from exc


def _handle_arka_music_generate(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "generate").strip().lower()
    try:
        from arka.media.music_generate import cmd_check, generate, music_generate_result, nl_to_argv

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "music_generate " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "generate":
            prompt = str(arguments.get("prompt") or arguments.get("text") or arguments.get("query") or "").strip()
            if not prompt:
                raise ValueError("prompt is required when action=generate")
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            model = str(arguments.get("model") or "").strip() or None
            duration = arguments.get("duration")
            lyrics = str(arguments.get("lyrics") or "").strip()
            instrumental = bool(arguments.get("instrumental"))
            result = music_generate_result(
                prompt,
                output=output,
                model=model,
                duration=int(duration) if duration is not None else None,
                lyrics=lyrics,
                instrumental=instrumental,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be generate, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"music_generate unavailable: {exc}") from exc


def _handle_arka_local_music(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "generate").strip().lower()
    try:
        from arka.agent.local_music_gen import doctor, local_music_result, nl_to_argv

        if action == "doctor":
            return json.dumps(doctor(), indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            from arka.agent.local_music_gen import route_command

            return json.dumps(
                {"argv": argv or [], "command": route_command(text)},
                indent=2,
            )
        if action == "generate":
            prompt = str(arguments.get("prompt") or arguments.get("text") or arguments.get("query") or "").strip()
            if not prompt:
                raise ValueError("prompt is required when action=generate")
            result = local_music_result(
                prompt,
                output=str(arguments.get("output") or arguments.get("out") or "").strip() or None,
                duration=int(arguments["duration"]) if arguments.get("duration") is not None else None,
                lyrics=str(arguments.get("lyrics") or "").strip(),
                instrumental=bool(arguments.get("instrumental")),
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be generate, parse, or doctor")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"local_music unavailable: {exc}") from exc


def _handle_arka_ai_video(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "generate").strip().lower()
    try:
        from arka.media.ai_video import ai_video_result, cmd_check, nl_to_argv

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "ai_video " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "generate":
            prompt = str(arguments.get("prompt") or arguments.get("text") or arguments.get("query") or "").strip()
            if not prompt:
                raise ValueError("prompt is required when action=generate")
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            model = str(arguments.get("model") or "").strip() or None
            aspect = str(arguments.get("aspect") or "").strip() or None
            duration = arguments.get("duration")
            audio = arguments.get("audio")
            result = ai_video_result(
                prompt,
                output=output,
                model=model,
                aspect=aspect,
                duration=int(duration) if duration is not None else None,
                audio=bool(audio) if audio is not None else None,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be generate, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"ai_video unavailable: {exc}") from exc


def _handle_arka_meme(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "create").strip().lower()
    try:
        from arka.agent.meme_templates import list_meme_templates, meme_result, nl_to_argv

        if action == "templates":
            return json.dumps(list_meme_templates(), indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "meme " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "create":
            template = str(arguments.get("template") or "").strip()
            if not template:
                raise ValueError("template is required when action=create")
            labels = arguments.get("labels")
            label_list = [str(x).strip() for x in labels if str(x).strip()] if isinstance(labels, list) else None
            items = arguments.get("items")
            if label_list is None and isinstance(items, list):
                label_list = [str(x).strip() for x in items if str(x).strip()]
            use_stock = arguments.get("use_stock_images")
            if use_stock is None:
                use_stock = arguments.get("stock")
            result = meme_result(
                template,
                style=str(arguments.get("style") or "").strip() or None,
                output=str(arguments.get("output") or arguments.get("out") or "").strip() or None,
                use_stock_images=bool(use_stock) if use_stock is not None else None,
                left=str(arguments.get("left") or "").strip() or None,
                right=str(arguments.get("right") or "").strip() or None,
                left_title=str(arguments.get("left_title") or "LEFT"),
                right_title=str(arguments.get("right_title") or "RIGHT"),
                left_label=str(arguments.get("left_label") or "").strip() or None,
                right_label=str(arguments.get("right_label") or "").strip() or None,
                left_query=str(arguments.get("left_query") or "").strip() or None,
                right_query=str(arguments.get("right_query") or "").strip() or None,
                reject=str(arguments.get("reject") or "").strip() or None,
                accept=str(arguments.get("accept") or "").strip() or None,
                image=str(arguments.get("image") or "").strip() or None,
                top=str(arguments.get("top") or ""),
                bottom=str(arguments.get("bottom") or ""),
                label=str(arguments.get("label") or "").strip() or None,
                stock_query=str(arguments.get("stock_query") or "").strip() or None,
                labels=label_list,
                images=[str(x) for x in arguments.get("images")] if isinstance(arguments.get("images"), list) else None,
                dilemma=str(arguments.get("dilemma") or "").strip() or None,
                button_left=str(arguments.get("button_left") or arguments.get("left_button") or "").strip() or None,
                button_right=str(arguments.get("button_right") or arguments.get("right_button") or "").strip() or None,
                highlight=str(arguments.get("highlight") or "").strip() or None,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be create, parse, or templates")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"meme unavailable: {exc}") from exc


def _handle_arka_infographic(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "create").strip().lower()
    try:
        from arka.agent.infographic import INFOGRAPHIC_STYLES, choose_layout, infographic_result, nl_to_argv

        if action == "layouts":
            return json.dumps(
                {
                    "auto_rules": {
                        "1-2": "row2",
                        "3": "row3",
                        "4": "grid4",
                        "5-6": "grid6",
                        "7-9": "grid9",
                        "10+": "radial",
                    }
                },
                indent=2,
            )
        if action == "styles":
            return json.dumps({k: v.label for k, v in INFOGRAPHIC_STYLES.items()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "infographic create " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "create":
            title = str(arguments.get("title") or "").strip()
            if not title:
                raise ValueError("title is required when action=create")
            raw_items = arguments.get("items")
            item_list: list[str] = []
            if isinstance(raw_items, list):
                item_list = [str(x).strip() for x in raw_items if str(x).strip()]
            elif isinstance(raw_items, str) and raw_items.strip():
                from arka.agent.infographic import _parse_items

                item_list = _parse_items(raw_items, None)
            repeated = arguments.get("item")
            if isinstance(repeated, list):
                item_list.extend(str(x).strip() for x in repeated if str(x).strip())
            elif isinstance(repeated, str) and repeated.strip():
                item_list.append(repeated.strip())
            layout = str(arguments.get("layout") or "auto").strip() or "auto"
            result = infographic_result(
                title,
                item_list,
                layout=layout,
                style=str(arguments.get("style") or "").strip() or None,
                output=str(arguments.get("output") or arguments.get("out") or "").strip() or None,
            )
            if arguments.get("preview_layout") and result.get("items"):
                result = {**result, "chosen_layout": choose_layout(int(result["items"]), layout)}
            return json.dumps(result, indent=2)
        raise ValueError("action must be create, parse, layouts, or styles")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"infographic unavailable: {exc}") from exc


def _handle_arka_reposition_image(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "check").strip().lower()
    try:
        from arka.agent.reposition_image import nl_to_argv, reposition_image_result

        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "reposition_image " + " ".join(argv) if argv else ""},
                indent=2,
            )
        path = str(arguments.get("path") or arguments.get("image") or "").strip() or None
        output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
        folder = str(arguments.get("folder") or arguments.get("output_dir") or "").strip() or None
        output_dir = str(arguments.get("output_dir") or "").strip() or None
        shape = str(arguments.get("shape") or "square").strip() or "square"
        selector = str(arguments.get("selector") or ".avatar img").strip() or ".avatar img"
        size = _mcp_int_optional(arguments.get("size"))
        vision = bool(arguments.get("vision"))
        result = reposition_image_result(
            action,
            path,
            output=output,
            shape=shape,
            size=size,
            context=str(arguments.get("context") or "").strip() or None,
            selector=selector,
            vision=vision,
            folder=folder,
            output_dir=output_dir,
        )
        return json.dumps(result, indent=2)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"reposition_image unavailable: {exc}") from exc


def _handle_arka_filter_images(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "score").strip().lower()
    try:
        from arka.agent.filter_images import filter_images_result, nl_to_argv

        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "filter_images " + " ".join(argv) if argv else ""},
                indent=2,
            )
        target = (
            str(arguments.get("folder") or arguments.get("path") or arguments.get("image") or "").strip() or None
        )
        query = str(arguments.get("query") or "").strip() or None
        output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
        borderline_raw = arguments.get("borderline_pct")
        borderline_pct = float(borderline_raw) if borderline_raw is not None else None
        vlm_pass = bool(arguments.get("vlm_pass"))
        result = filter_images_result(
            action,
            target,
            query=query,
            output=output,
            vlm_pass=vlm_pass,
            borderline_pct=borderline_pct,
        )
        return json.dumps(result, indent=2)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"filter_images unavailable: {exc}") from exc


def _handle_arka_media_styles(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.media.media_styles import media_styles_catalog

        kind = str(arguments.get("kind") or "all").strip().lower()
        if action == "list":
            payload = media_styles_catalog(kind=kind, as_json=True)
            return json.dumps(payload, indent=2)
        raise ValueError("action must be list")
    except ImportError as exc:
        raise RuntimeError(f"media_styles unavailable: {exc}") from exc


def _handle_arka_tech_stack(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "suggest").strip().lower()
    try:
        from arka.agent.tech_stack import (
            extract_project_name,
            find_similar_folders,
            nl_to_argv,
            suggest_tech_stack,
        )

        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            project = extract_project_name(text)
            return json.dumps(
                {
                    "argv": argv,
                    "project": project,
                    "command": "tech_stack " + " ".join(argv) if argv else "",
                },
                indent=2,
            )
        if action == "search":
            project = str(arguments.get("project") or arguments.get("query") or "").strip()
            if not project:
                raise ValueError("project is required when action=search")
            roots = arguments.get("roots")
            root_list = [str(x) for x in roots] if isinstance(roots, list) else None
            matches = find_similar_folders(project, roots=[Path(r) for r in root_list] if root_list else None)
            return json.dumps([m.to_dict() for m in matches], indent=2)
        if action == "suggest":
            project = str(
                arguments.get("project")
                or arguments.get("query")
                or extract_project_name(str(arguments.get("text") or ""))
                or ""
            ).strip()
            if not project:
                raise ValueError("project or text with a project name is required when action=suggest")
            roots = arguments.get("roots")
            root_list = [str(x) for x in roots] if isinstance(roots, list) else None
            result = suggest_tech_stack(
                project,
                roots=root_list,
                path=str(arguments.get("path") or "").strip() or None,
                assume_yes=bool(arguments.get("yes") or arguments.get("assume_yes")),
                interactive=False if arguments.get("non_interactive") else None,
                include_candidates=bool(arguments.get("candidates")),
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be suggest, search, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"tech_stack unavailable: {exc}") from exc


def _handle_arka_google_flow(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "generate").strip().lower()
    try:
        from arka.media.google_flow import cmd_check, google_flow_result, nl_to_argv, open_flow

        if action == "check":
            import argparse
            import io
            from contextlib import redirect_stderr, redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                code = cmd_check(argparse.Namespace())
            return json.dumps({"exit_code": code, "report": buf.getvalue().strip()}, indent=2)
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("goal") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "google_flow " + " ".join(argv) if argv else ""},
                indent=2,
            )
        if action == "open":
            prompt = str(arguments.get("prompt") or arguments.get("text") or "").strip()
            return json.dumps(open_flow(prompt=prompt), indent=2)
        if action == "generate":
            prompt = str(arguments.get("prompt") or arguments.get("text") or arguments.get("query") or "").strip()
            if not prompt:
                raise ValueError("prompt is required when action=generate")
            output = str(arguments.get("output") or arguments.get("out") or "").strip() or None
            model = str(arguments.get("model") or "").strip() or None
            aspect = str(arguments.get("aspect") or "16:9").strip()
            duration = arguments.get("duration")
            backend = str(arguments.get("backend") or "").strip() or None
            result = google_flow_result(
                prompt,
                output=output,
                aspect=aspect,
                model=model,
                duration=int(duration) if duration is not None else None,
                backend=backend,
            )
            return json.dumps(result, indent=2)
        raise ValueError("action must be generate, open, check, or parse")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"google_flow unavailable: {exc}") from exc


def _handle_arka_human_docs(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "context").strip().lower()
    try:
        from arka.core.human_docs import context_for, read_guide, status
        from arka.agent.human_docs import write_doc

        if action == "guide":
            return read_guide()
        if action == "status":
            return json.dumps(status(), indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
            limit_chars = _mcp_int(arguments.get("limit_chars"), 4000)
            text = context_for(goal, limit_chars=max(200, limit_chars))
            return text or "(human docs bias disabled)"
        if action == "write":
            prompt = str(arguments.get("prompt") or arguments.get("goal") or "").strip()
            if not prompt:
                raise ValueError("prompt is required when action=write")
            out = str(arguments.get("out") or arguments.get("path") or "").strip() or None
            apply = bool(arguments.get("apply", False))
            context_path = str(arguments.get("context") or "").strip() or None
            result = write_doc(prompt, out=out, apply=apply, context_path=context_path)
            if apply:
                return f"Wrote {result['path']} ({result['bytes']} bytes)"
            return json.dumps(result, indent=2)
        raise ValueError("action must be guide, status, context, or write")
    except ImportError as exc:
        raise RuntimeError(f"human_docs unavailable: {exc}") from exc


def _handle_arka_website_pages(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "context").strip().lower()
    try:
        from arka.core.website_pages import context_for, read_guide, status
        from arka.agent.website_pages import plan_pages

        if action == "guide":
            return read_guide()
        if action == "status":
            return json.dumps(status(), indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
            limit_chars = _mcp_int(arguments.get("limit_chars"), 4000)
            text = context_for(goal, limit_chars=max(200, limit_chars))
            return text or "(website pages bias disabled)"
        if action == "plan":
            prompt = str(arguments.get("prompt") or arguments.get("goal") or "").strip()
            if not prompt:
                raise ValueError("prompt is required when action=plan")
            context_path = str(arguments.get("context") or "").strip() or None
            site_type = str(arguments.get("site_type") or arguments.get("type") or "").strip() or None
            result = plan_pages(prompt, context_path=context_path, site_type=site_type)
            return str(result.get("plan") or "")
        raise ValueError("action must be guide, status, context, or plan")
    except ImportError as exc:
        raise RuntimeError(f"website_pages unavailable: {exc}") from exc


def _handle_arka_project_rules(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "context").strip().lower()
    root_raw = str(arguments.get("root") or "").strip()
    root = Path(root_raw).expanduser() if root_raw else None
    try:
        from arka.core.project_rules import context_for, list_rules, status

        if action == "list":
            return json.dumps(list_rules(root=root), indent=2)
        if action == "status":
            return json.dumps(status(root=root), indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("query") or "").strip()
            limit_chars = _mcp_int(arguments.get("limit_chars"), 4000)
            text = context_for(goal, root=root, limit_chars=max(200, limit_chars))
            return text or "(no project rules found)"
        raise ValueError("action must be list, status, or context")
    except ImportError as exc:
        raise RuntimeError(f"project_rules unavailable: {exc}") from exc


def _resolve_markdown_path(path: str) -> str:
    """Resolve bundled guide aliases (e.g. frontend-content-guide, google-design) for MCP reads."""
    raw = path.strip().strip("'\"")
    try:
        from arka.core.design_guides import resolve_markdown_alias

        resolved = resolve_markdown_alias(raw)
        if resolved:
            return resolved
    except ImportError:
        pass
    return raw


def _handle_arka_markdown(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "context").strip().lower()
    path = _resolve_markdown_path(str(arguments.get("path") or arguments.get("file") or ""))
    if not path:
        raise ValueError("path is required")
    try:
        from arka.agent.md_doc import ask_markdown, context_block, read_markdown

        if action == "read":
            return read_markdown(path, max_chars=_mcp_int(arguments.get("max_chars"), 120_000))
        if action == "context":
            limit_chars = _mcp_int(arguments.get("limit_chars") or arguments.get("max_chars"), 8000)
            text = context_block(path, limit_chars=max(200, limit_chars))
            return text or "(empty markdown file)"
        if action == "ask":
            question = str(arguments.get("question") or arguments.get("query") or "").strip()
            if not question:
                raise ValueError("question is required when action=ask")
            return ask_markdown(path, question)
        raise ValueError("action must be read, context, or ask")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"md_doc unavailable: {exc}") from exc


def _handle_arka_view_data(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "preview").strip().lower()
    try:
        from arka.agent.view_data import preview_file

        if action == "preview":
            path = str(arguments.get("path") or arguments.get("file") or "").strip()
            if not path:
                raise ValueError("path is required for preview")
            max_rows = _mcp_int(arguments.get("max_rows") or arguments.get("limit"), 50)
            delimiter = str(arguments.get("delimiter") or "").strip() or None
            plain = bool(arguments.get("plain", True))
            return json.dumps(
                preview_file(path, max_rows=max_rows, plain=plain, delimiter=delimiter),
                indent=2,
            )
        raise ValueError("action must be preview")
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"view_data unavailable: {exc}") from exc


def _handle_arka_view_output(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "render").strip().lower()
    try:
        from arka.web.output_viewer.cli import show_content, show_file
        from arka.web.output_viewer.render import render_content

        path = str(arguments.get("path") or arguments.get("file") or "").strip()
        content = arguments.get("content")
        fmt = str(arguments.get("format") or "").strip() or None
        title = str(arguments.get("title") or "").strip() or None
        open_browser = bool(arguments.get("open_browser", False))

        if action == "render":
            if path:
                src = Path(path).expanduser()
                if not src.is_file():
                    raise ValueError(f"File not found: {path}")
                text = src.read_text(encoding="utf-8", errors="replace")
                payload = render_content(text, fmt=fmt, filename=src.name, title=title or src.name)
                return json.dumps(payload, indent=2, ensure_ascii=False)
            if content is None:
                raise ValueError("path or content is required for render")
            if not isinstance(content, str):
                content = json.dumps(content, indent=2, ensure_ascii=False)
            payload = render_content(content, fmt=fmt, title=title or "Arka output")
            return json.dumps(payload, indent=2, ensure_ascii=False)

        if action == "show":
            if not path:
                raise ValueError("path is required for show")
            result = show_file(path, open_browser=open_browser, fmt=fmt, title=title)
            return json.dumps(result, indent=2)

        if action == "open" and content is not None:
            if not isinstance(content, str):
                content = json.dumps(content, indent=2, ensure_ascii=False)
            result = show_content(content, open_browser=True, fmt=fmt, title=title or "Arka output")
            return json.dumps(result, indent=2)

        raise ValueError("action must be render, show, or open")
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"view_output unavailable: {exc}") from exc


def _handle_arka_share(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "last").strip().lower()
    fmt = str(arguments.get("format") or "markdown").strip().lower()
    if fmt not in {"markdown", "json"}:
        raise ValueError("format must be markdown or json")
    copy = bool(arguments.get("copy", False))
    try:
        from arka.llm.share import (
            build_share_bundle,
            copy_share_to_clipboard,
            format_llm_share_bundle,
            record_from_overrides,
        )

        overrides = {
            "output": arguments.get("output"),
            "provider": arguments.get("provider"),
            "model_id": arguments.get("model"),
            "task": arguments.get("task"),
            "skill": arguments.get("skill"),
            "latency_ms": arguments.get("latency_ms"),
            "prompt_tokens": arguments.get("prompt_tokens"),
            "completion_tokens": arguments.get("completion_tokens"),
        }
        overrides = {k: v for k, v in overrides.items() if v is not None}

        if action == "last":
            record = record_from_overrides(**overrides)
        elif action == "format":
            output = str(arguments.get("output") or "").strip()
            if not output:
                raise ValueError("output is required when action=format")
            format_overrides = {k: v for k, v in overrides.items() if k != "output"}
            record = record_from_overrides(output=output, **format_overrides)
        else:
            raise ValueError("action must be last or format")

        if copy:
            ok, message = copy_share_to_clipboard(record, fmt=fmt)  # type: ignore[arg-type]
            if not ok:
                raise RuntimeError(message)
            payload = {
                "copied": True,
                "format": fmt,
                "bundle": build_share_bundle(record),
                "text": format_llm_share_bundle(record, fmt=fmt),
            }
            return json.dumps(payload, indent=2)

        if fmt == "json":
            return json.dumps(build_share_bundle(record), indent=2)
        return format_llm_share_bundle(record, fmt=fmt)
    except ImportError as exc:
        raise RuntimeError(f"llm share unavailable: {exc}") from exc


def _handle_arka_clipboard(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.clipboard_history import (
            clear_entries,
            get_entry,
            list_entries,
            save_entry,
        )

        if action == "list":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(list_entries(limit=limit), indent=2)
        if action == "save":
            text = arguments.get("text")
            text_arg = None if text is None else str(text)
            row, err = save_entry(text=text_arg)
            if err or row is None:
                raise RuntimeError(err or "clipboard save failed")
            return json.dumps(row, indent=2)
        if action == "get":
            index = _mcp_int(arguments.get("index") or arguments.get("id"), 1)
            row, err = get_entry(index)
            if err or row is None:
                raise ValueError(err or "entry not found")
            return json.dumps(row, indent=2)
        if action == "clear":
            clear_entries()
            return "Clipboard history cleared"
        raise ValueError("action must be list, save, get, or clear")
    except ImportError as exc:
        raise RuntimeError(f"clipboard_history unavailable: {exc}") from exc


def _handle_arka_remind(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.integrations.remind import add_reminder, cancel_reminder, list_reminders

        if action == "list":
            include_done = bool(arguments.get("include_done", False))
            limit = _mcp_int(arguments.get("limit"), 50)
            return json.dumps(
                list_reminders(include_done=include_done, limit=max(1, min(limit, 200))),
                indent=2,
            )
        if action == "add":
            text = str(arguments.get("text") or arguments.get("message") or "").strip()
            at = str(arguments.get("at") or "").strip() or None
            in_spec = str(arguments.get("in") or arguments.get("in_spec") or "").strip() or None
            start = bool(arguments.get("start", False))
            row, err = add_reminder(text, at=at, in_spec=in_spec, start=start)
            if err or row is None:
                raise RuntimeError(err or "failed to add reminder")
            return json.dumps(row, indent=2)
        if action == "cancel":
            rid = str(arguments.get("id") or arguments.get("reminder_id") or "").strip()
            cancelled, err = cancel_reminder(rid)
            if err:
                raise ValueError(err)
            return json.dumps({"cancelled": cancelled}, indent=2)
        raise ValueError("action must be list, add, or cancel")
    except ImportError as exc:
        raise RuntimeError(f"remind unavailable: {exc}") from exc


def _handle_arka_alert(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations import email_alert as alerts

        if action == "status":
            return json.dumps(alerts.status_payload(), indent=2)
        if action == "list":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(alerts.list_history(limit=limit), indent=2)
        if action == "send":
            text = str(arguments.get("text") or arguments.get("message") or "").strip()
            title = str(arguments.get("title") or text[:120] or "Arka alert").strip()
            body = str(arguments.get("body") or text).strip()
            category = str(arguments.get("category") or "").strip().lower() or None
            source = str(arguments.get("source") or "").strip() or None
            if not body and not title:
                raise ValueError("text or message is required for send")
            row = alerts.send_alert(title, body, category=category, source=source)
            return json.dumps(row, indent=2)
        if action == "schedule":
            text = str(arguments.get("text") or arguments.get("message") or "").strip()
            at = str(arguments.get("at") or "").strip() or None
            in_spec = str(arguments.get("in") or arguments.get("in_spec") or "").strip() or None
            category = str(arguments.get("category") or "").strip().lower() or None
            start = bool(arguments.get("start", False))
            row, err = alerts.schedule_alert(
                text,
                at=at,
                in_spec=in_spec,
                category=category,
                start=start,
            )
            if err or row is None:
                raise RuntimeError(err or "failed to schedule alert")
            return json.dumps(row, indent=2)
        if action == "test":
            row = alerts.send_alert(
                "Test alert",
                "Arka email alerts are working.",
                category="general",
            )
            return json.dumps(row, indent=2)
        if action == "config":
            if "auto" in arguments:
                enabled = str(arguments.get("auto")).strip().lower() not in {"0", "false", "no", "off"}
                alerts.set_auto_alert(enabled)
                return json.dumps({"auto": enabled, **alerts.status_payload()}, indent=2)
            return json.dumps(alerts.status_payload(), indent=2)
        raise ValueError("action must be status, list, send, schedule, test, or config")
    except ImportError as exc:
        raise RuntimeError(f"email_alert unavailable: {exc}") from exc


def _handle_arka_bookmarks(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.agent import bookmarks as bm

        if action == "list":
            tag = str(arguments.get("tag") or "").strip() or None
            limit = _mcp_int(arguments.get("limit"), 50)
            return json.dumps(bm.list_bookmarks(tag=tag, limit=limit), indent=2)
        if action == "save":
            url = str(arguments.get("url") or arguments.get("link") or "").strip()
            if not url:
                raise ValueError("url is required for save")
            title = str(arguments.get("title") or "").strip() or None
            tags = arguments.get("tags")
            note = str(arguments.get("note") or "").strip() or None
            return json.dumps(
                bm.save_bookmark(url, title=title, tags=tags, note=note),
                indent=2,
            )
        if action == "search":
            query = str(arguments.get("query") or arguments.get("q") or "").strip()
            limit = _mcp_int(arguments.get("limit"), 50)
            return json.dumps(bm.search_bookmarks(query, limit=limit), indent=2)
        if action == "get":
            index = _mcp_int(arguments.get("index") or arguments.get("id"), 0)
            return json.dumps(bm.get_bookmark(index), indent=2)
        if action == "delete":
            index = _mcp_int(arguments.get("index") or arguments.get("id"), 0)
            return json.dumps(bm.delete_bookmark(index), indent=2)
        raise ValueError("action must be list, save, search, get, or delete")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"bookmarks unavailable: {exc}") from exc


def _handle_arka_docker(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "health").strip().lower()
    try:
        from arka.integrations import docker_status as ds

        if action == "health":
            return json.dumps(ds.health_payload(), indent=2)
        if action in ("ps", "containers"):
            return json.dumps(ds.list_containers(), indent=2)
        if action == "images":
            limit = _mcp_int(arguments.get("limit"), 50)
            return json.dumps(ds.list_images(limit=limit), indent=2)
        if action == "logs":
            name = str(
                arguments.get("container")
                or arguments.get("name")
                or arguments.get("id")
                or ""
            ).strip()
            tail = _mcp_int(arguments.get("tail") or arguments.get("limit"), 50)
            return json.dumps(ds.container_logs(name, tail=tail), indent=2)
        raise ValueError("action must be health, ps, images, or logs")
    except ValueError:
        raise
    except RuntimeError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"docker_status unavailable: {exc}") from exc


def _handle_arka_jsonkit(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "validate").strip().lower()
    try:
        from arka.core import jsonkit as jk

        text = str(arguments.get("json") or arguments.get("text") or arguments.get("data") or "")
        if action == "validate":
            return json.dumps(jk.validate_payload(text), indent=2)
        if action == "pretty":
            indent = _mcp_int(arguments.get("indent"), 2)
            return json.dumps(jk.pretty_payload(text, indent=indent), indent=2)
        if action == "minify":
            return json.dumps(jk.minify_payload(text), indent=2)
        if action == "get":
            path = str(arguments.get("path") or arguments.get("key") or "").strip()
            if not path:
                raise ValueError("path is required for get")
            return json.dumps(jk.get_payload(text, path), indent=2)
        raise ValueError("action must be validate, pretty, minify, or get")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"jsonkit unavailable: {exc}") from exc


def _handle_arka_timekit(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "now").strip().lower()
    try:
        from arka.core import timekit as tk

        if action == "now":
            tz = str(arguments.get("tz") or arguments.get("timezone") or "").strip() or None
            return json.dumps(tk.now_payload(tz=tz), indent=2)
        if action == "convert":
            value = str(
                arguments.get("datetime")
                or arguments.get("value")
                or arguments.get("text")
                or ""
            ).strip()
            to_tz = str(arguments.get("to_tz") or arguments.get("to") or "").strip()
            from_tz = str(arguments.get("from_tz") or arguments.get("from") or "").strip() or None
            if not to_tz:
                raise ValueError("to_tz is required for convert")
            return json.dumps(
                tk.convert_payload(value, to_tz=to_tz, from_tz=from_tz),
                indent=2,
            )
        if action == "relative":
            expression = str(
                arguments.get("expression")
                or arguments.get("text")
                or arguments.get("offset")
                or ""
            ).strip()
            tz = str(arguments.get("tz") or arguments.get("timezone") or "").strip() or None
            base = str(arguments.get("base") or "").strip() or None
            return json.dumps(
                tk.relative_payload(expression, tz=tz, base=base),
                indent=2,
            )
        raise ValueError("action must be now, convert, or relative")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"timekit unavailable: {exc}") from exc


def _handle_arka_urlkit(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "parse").strip().lower()
    try:
        from arka.core import urlkit as uk

        if action == "parse":
            url = str(arguments.get("url") or arguments.get("text") or "").strip()
            return json.dumps(uk.parse_payload(url), indent=2)
        if action == "normalize":
            url = str(arguments.get("url") or arguments.get("text") or "").strip()
            drop_fragment = arguments.get("drop_fragment")
            if drop_fragment is None:
                drop_fragment = True
            return json.dumps(
                uk.normalize_payload(url, drop_fragment=bool(drop_fragment)),
                indent=2,
            )
        if action == "slugify":
            text = str(arguments.get("text") or arguments.get("url") or "").strip()
            max_length = _mcp_int(arguments.get("max_length"), 80)
            return json.dumps(uk.slugify_payload(text, max_length=max_length), indent=2)
        raise ValueError("action must be parse, normalize, or slugify")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"urlkit unavailable: {exc}") from exc


def _handle_arka_password(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "generate").strip().lower()
    try:
        from arka.integrations import password_vault as vault

        if action in ("generate", "once"):
            length = _mcp_int(arguments.get("length"), 16)
            symbols = arguments.get("symbols")
            if symbols is None:
                symbols = True
            return json.dumps(
                vault.generate_payload(length=length, symbols=bool(symbols)),
                indent=2,
            )
        raise ValueError("action must be generate (vault store/get is not exposed via MCP)")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"password_vault unavailable: {exc}") from exc


def _handle_arka_spotify(arguments: dict[str, Any]) -> str:
    if "arka_spotify" in _mcp_disabled_tools():
        return _mcp_disabled_message("arka_spotify")
    action = str(arguments.get("action") or "search").strip().lower()
    try:
        from arka.integrations import spotify as spotify_mod

        if action == "search":
            query = str(
                arguments.get("query")
                or arguments.get("text")
                or arguments.get("q")
                or ""
            ).strip()
            return json.dumps(spotify_mod.search_payload(query), indent=2)
        raise ValueError("action must be search")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"spotify unavailable: {exc}") from exc


def _handle_arka_textkit(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "uuid").strip().lower()
    try:
        from arka.core import textkit as tk

        if action == "uuid":
            version = _mcp_int(arguments.get("version"), 4)
            name = str(arguments.get("name") or "").strip() or None
            namespace = str(arguments.get("namespace") or "url").strip() or "url"
            return json.dumps(
                tk.uuid_payload(version=version, name=name, namespace=namespace),
                indent=2,
            )
        if action == "hash":
            text = str(arguments.get("text") or arguments.get("data") or "")
            algorithm = str(arguments.get("algorithm") or "sha256")
            return json.dumps(tk.hash_payload(text, algorithm=algorithm), indent=2)
        if action == "base64":
            mode = str(arguments.get("mode") or arguments.get("op") or "encode")
            text = str(arguments.get("text") or arguments.get("data") or "")
            return json.dumps(tk.base64_payload(text, action=mode), indent=2)
        raise ValueError("action must be uuid, hash, or base64")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"textkit unavailable: {exc}") from exc


def _handle_arka_calendar(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "today").strip().lower()
    try:
        from arka.integrations import macos_calendar as cal_mod

        if action in ("today", "events"):
            return json.dumps(cal_mod.today_payload(), indent=2)
        raise ValueError("action must be today")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"calendar unavailable: {exc}") from exc


def _handle_arka_platform(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "show").strip().lower()
    try:
        from arka.core import platform as plat_mod

        if action == "show":
            return json.dumps(plat_mod.show_payload(), indent=2)
        if action == "detect":
            force = bool(arguments.get("force", False))
            persist = bool(arguments.get("persist", True))
            return json.dumps(
                plat_mod.detect_payload(force=force, persist=persist),
                indent=2,
            )
        raise ValueError("action must be show or detect")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"platform unavailable: {exc}") from exc


def _handle_arka_personalize(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.core import personalize as pers

        if action == "status":
            return json.dumps(pers.status_payload(), indent=2)
        if action in ("recommend", "recommendations"):
            limit = _mcp_int(arguments.get("limit"), 8)
            return json.dumps(pers.recommend_payload(limit=limit), indent=2)
        if action == "quickstart":
            return json.dumps(pers.quickstart_payload(), indent=2)
        raise ValueError("action must be status, recommend, or quickstart")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"personalize unavailable: {exc}") from exc


def _handle_arka_persona(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.agent.personas import io as persona_io

        if action == "list":
            include_templates = bool(arguments.get("include_templates", False))
            return json.dumps(
                persona_io.list_payload(include_templates=include_templates),
                indent=2,
            )
        if action == "show":
            name = str(
                arguments.get("name")
                or arguments.get("persona")
                or arguments.get("id")
                or ""
            ).strip()
            return json.dumps(persona_io.show_payload(name), indent=2)
        raise ValueError("action must be list or show")
    except ValueError:
        raise
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except ImportError as exc:
        raise RuntimeError(f"personas unavailable: {exc}") from exc


def _handle_arka_github(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "activity").strip().lower()
    try:
        from arka.agent import github_repo as gh_mod

        if action == "resolve":
            query = str(
                arguments.get("query")
                or arguments.get("repo")
                or arguments.get("text")
                or ""
            ).strip()
            return json.dumps(gh_mod.resolve_repo_payload(query), indent=2)
        if action == "resume":
            from arka.agent import github_resume as resume_mod

            username = str(
                arguments.get("username")
                or arguments.get("user")
                or arguments.get("query")
                or ""
            ).strip() or None
            output = str(arguments.get("output") or "").strip() or None
            style = str(arguments.get("style") or "modern").strip().lower()
            write_markdown = bool(arguments.get("markdown") or arguments.get("write_markdown"))
            payload = resume_mod.resume_payload(
                username,
                output=Path(output).expanduser() if output else None,
                style=style,
                write_markdown=write_markdown,
            )
            return json.dumps(payload, indent=2)
        if action == "activity":
            owner = str(arguments.get("owner") or "").strip()
            repo = str(arguments.get("repo") or "").strip()
            query = str(arguments.get("query") or arguments.get("text") or "").strip()
            if (not owner or not repo) and query:
                resolved = gh_mod.resolve_repo_payload(query)
                if not resolved.get("ok"):
                    raise ValueError(str(resolved.get("error") or "could not resolve repo"))
                owner = str(resolved["owner"])
                repo = str(resolved["repo"])
            if not owner or not repo:
                # allow owner/repo in repo field
                if "/" in repo and not owner:
                    owner, _, repo = repo.partition("/")
                elif "/" in owner and not repo:
                    owner, _, repo = owner.partition("/")
            if not owner or not repo:
                raise ValueError("owner and repo are required (or provide query)")
            days = _mcp_int(arguments.get("days"), 7)
            return json.dumps(
                gh_mod.activity_payload(owner, repo, days=days),
                indent=2,
            )
        raise ValueError("action must be activity, resolve, or resume")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"github_repo unavailable: {exc}") from exc


def _handle_arka_price(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "sources").strip().lower()
    try:
        from arka.agent import price_sources as ps

        if action in ("sources", "list"):
            return json.dumps(
                ps.sources_payload(
                    region=str(arguments.get("region") or "").strip() or None,
                    product=str(arguments.get("product") or "").strip() or None,
                    query=str(arguments.get("query") or arguments.get("text") or "").strip()
                    or None,
                ),
                indent=2,
            )
        if action == "parse":
            query = str(arguments.get("query") or arguments.get("text") or "").strip()
            return json.dumps(ps.parse_price_payload(query), indent=2)
        raise ValueError("action must be sources or parse")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"price_sources unavailable: {exc}") from exc


def _handle_arka_config(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "list").strip().lower()
    try:
        from arka.core import config_backup as cb

        if action == "list":
            return json.dumps(cb.list_payload(), indent=2)
        if action == "path":
            path = str(arguments.get("path") or arguments.get("target") or "").strip() or None
            return json.dumps(cb.path_payload(path), indent=2)
        raise ValueError("action must be list or path")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"config_backup unavailable: {exc}") from exc


def _handle_arka_model(arguments: dict[str, Any]) -> str:
    """Recommend, inspect, and set LLM models/providers."""
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from dataclasses import asdict

        from arka.llm import model_advisor as advisor
        from arka.llm import provider_select as ps

        if action in ("status", "show"):
            provider, model = ps.get_preferred()
            models, source = ps.detect_provider_models(provider) if provider else ([], "none")
            payload: dict[str, Any] = {
                "provider": provider or None,
                "model": model or None,
                "models_detected": len(models),
                "models_source": source,
                "model_valid": bool(model and (not models or model in models)),
            }
            if models:
                payload["models"] = models[:40]
            try:
                from arka.llm.retired_models import ensure_config_not_retired, is_retired, list_retired

                payload["model_retired"] = bool(provider and model and is_retired(provider, model))
                remediated = ensure_config_not_retired()
                if remediated:
                    provider, model = ps.get_preferred()
                    payload["provider"] = provider or None
                    payload["model"] = model or None
                    payload["auto_remediated"] = remediated
                payload["retired_models"] = list_retired()[:20]
            except ImportError:
                pass
            return json.dumps(payload, indent=2)

        if action == "probe":
            hw = advisor.probe_hardware()
            return json.dumps(asdict(hw), indent=2)

        if action == "recommend":
            report = advisor.build_report()
            if bool(arguments.get("local")):
                limit = max(1, _mcp_int(arguments.get("top"), 1))
                models = advisor.strongest_runnable_local_models(report.hardware, limit=limit)
                payload = {
                    "mode": "local",
                    "tier": report.tier,
                    "tier_label": report.tier_label,
                    "models": [f"ollama/{m}" for m in models],
                    "hardware": asdict(report.hardware),
                    "notes": report.notes,
                }
            else:
                payload = report.to_dict()
            if bool(arguments.get("apply")):
                if bool(arguments.get("local")) and payload.get("models"):
                    from arka.llm.skill_models import set_skill_model

                    chosen = str(payload["models"][0])
                    for profile in advisor.known_task_profiles():
                        set_skill_model(profile, chosen)
                    payload["applied"] = {"mode": "local", "model": chosen}
                else:
                    path = advisor.apply_recommendations(report)
                    payload["applied"] = {"mode": "profiles", "path": str(path)}
            return json.dumps(payload, indent=2)

        if action == "apply":
            path = advisor.apply_recommendations()
            return json.dumps({"ok": True, "path": str(path)}, indent=2)

        if action in ("list_providers", "providers"):
            rows = [
                {
                    "slug": row.slug,
                    "display_name": row.display_name,
                    "configured": row.configured,
                    "default_model": row.default_model,
                    "env_keys": list(row.env_keys),
                }
                for row in ps.list_provider_rows()
            ]
            return json.dumps({"providers": rows}, indent=2)

        if action in ("list_models", "models"):
            provider = str(
                arguments.get("provider")
                or arguments.get("slug")
                or ps.get_preferred()[0]
                or ""
            ).strip()
            if not provider:
                raise ValueError("provider is required when no preferred provider is set")
            slug = ps.normalize_provider_slug(provider)
            models, source = ps.detect_provider_models(
                slug,
                force=bool(arguments.get("refresh")),
                include_all=bool(arguments.get("all")),
            )
            return json.dumps(
                {
                    "provider": slug,
                    "models": models,
                    "count": len(models),
                    "source": source,
                },
                indent=2,
            )

        if action == "set":
            provider = str(arguments.get("provider") or arguments.get("slug") or "").strip()
            model = str(arguments.get("model") or arguments.get("model_id") or "").strip() or None
            if not provider and model:
                provider, model = ps.resolve_model_set_target(model)
            if not provider:
                raise ValueError("provider or model is required for action=set")
            slug, chosen, path = ps.set_preferred_provider(
                provider,
                model=model,
                autodetect=bool(arguments.get("autodetect", True)),
                force_refresh=bool(arguments.get("refresh")),
            )
            return json.dumps(
                {
                    "ok": True,
                    "provider": slug,
                    "model": chosen,
                    "env_file": str(path),
                },
                indent=2,
            )

        if action in ("dashboard", "health"):
            from arka.llm.credits_usage import build_dashboard_payload

            live = bool(arguments.get("live"))
            check_balance = bool(arguments.get("balance")) or live
            include_chain = bool(arguments.get("chain")) or live
            return json.dumps(
                build_dashboard_payload(
                    live=live,
                    check_balance=check_balance,
                    include_chain=include_chain,
                ),
                indent=2,
            )

        if action == "arbitrage":
            from arka.llm import arbitrage as arb

            sub = str(arguments.get("mode") or arguments.get("subaction") or "status").strip().lower()
            if sub in ("status", "show"):
                return json.dumps(arb.status_payload(), indent=2)
            if sub in ("once", "swap", "run"):
                return json.dumps(
                    arb.run_once(dry_run=bool(arguments.get("dry_run"))),
                    indent=2,
                )
            if sub == "start":
                interval = arguments.get("interval")
                return json.dumps(
                    arb.start_monitor(
                        interval=float(interval) if interval is not None else None,
                        foreground=bool(arguments.get("foreground")),
                    ),
                    indent=2,
                )
            if sub == "stop":
                return json.dumps(arb.stop_monitor(), indent=2)
            raise ValueError("arbitrage mode must be status, once, start, or stop")

        raise ValueError(
            "action must be status, recommend, apply, probe, list_providers, "
            "list_models, set, dashboard, or arbitrage"
        )
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"model selection unavailable: {exc}") from exc


def _handle_arka_finetune_model(arguments: dict[str, Any]) -> str:
    """Plan, validate, and scaffold local LLM fine-tuning jobs."""
    action = str(arguments.get("action") or "plan").strip().lower()
    try:
        from arka.llm.finetune_model import (
            generate_artifacts,
            job_status,
            nl_to_argv,
            plan_job,
            validate_dataset,
        )

        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or arguments.get("task") or "").strip()
            if not text:
                raise ValueError("text is required when action=parse")
            argv = nl_to_argv(text)
            return json.dumps(
                {"argv": argv, "command": "finetune_model " + " ".join(argv) if argv else ""},
                indent=2,
            )

        if action == "check":
            from arka.llm.finetune_model import main as finetune_main
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                finetune_main(["check"])
            return buf.getvalue().strip() or json.dumps({"ok": True})

        if action == "validate":
            path = str(arguments.get("path") or arguments.get("dataset") or "").strip()
            if not path:
                raise ValueError("path is required when action=validate")
            return json.dumps(validate_dataset(Path(path).expanduser()), indent=2)

        if action == "status":
            output_dir = str(arguments.get("output_dir") or arguments.get("path") or "").strip()
            if not output_dir:
                raise ValueError("output_dir is required when action=status")
            return json.dumps(job_status(output_dir), indent=2)

        if action == "generate":
            base_model = str(arguments.get("base_model") or arguments.get("model") or "").strip()
            dataset = str(arguments.get("dataset") or arguments.get("path") or "").strip()
            if not base_model or not dataset:
                raise ValueError("base_model and dataset are required when action=generate")
            apply = bool(arguments.get("apply"))
            return json.dumps(
                generate_artifacts(
                    base_model=base_model,
                    dataset=dataset,
                    method=str(arguments.get("method") or "auto"),
                    backend=str(arguments.get("backend") or "auto"),
                    output_dir=str(arguments.get("output_dir") or "./finetune-out"),
                    apply=apply,
                ),
                indent=2,
            )

        if action == "plan":
            task = str(
                arguments.get("task")
                or arguments.get("text")
                or arguments.get("query")
                or arguments.get("prompt")
                or ""
            ).strip()
            if not task:
                raise ValueError("task is required when action=plan")
            return json.dumps(
                plan_job(
                    task,
                    method=str(arguments.get("method") or "auto"),
                    backend=str(arguments.get("backend") or "auto"),
                    base_model=str(arguments.get("base_model") or arguments.get("model") or "") or None,
                    dataset=str(arguments.get("dataset") or arguments.get("path") or "") or None,
                    output_dir=str(arguments.get("output_dir") or "") or None,
                ),
                indent=2,
            )

        raise ValueError("action must be plan, validate, generate, status, parse, or check")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"finetune_model unavailable: {exc}") from exc


def _handle_arka_tunnel(arguments: dict[str, Any]) -> str:
    """Expose local Ollama via authenticated proxy and optional public tunnel."""
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations import ollama_tunnel as tunnel

        if action in ("status", "show"):
            return json.dumps(tunnel.status_payload(), indent=2)
        if action == "start":
            port_raw = arguments.get("port")
            return json.dumps(
                tunnel.start_stack(
                    host=str(arguments.get("host") or "127.0.0.1"),
                    port=int(port_raw) if port_raw is not None else None,
                    with_tunnel=not bool(arguments.get("no_tunnel")),
                ),
                indent=2,
            )
        if action == "stop":
            return json.dumps(tunnel.stop_stack(), indent=2)
        raise ValueError("action must be status, start, or stop")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"ollama_tunnel unavailable: {exc}") from exc


def _handle_arka_sports(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "scores").strip().lower()
    try:
        from arka.integrations import sports as sports_mod

        if action in ("scores", "live"):
            query = str(arguments.get("query") or arguments.get("league") or "").strip()
            limit = _mcp_int(arguments.get("limit") or arguments.get("limit_per_league"), 3)
            return json.dumps(
                sports_mod.scores_payload(query, limit_per_league=max(1, min(limit, 20))),
                indent=2,
            )
        if action in ("leagues", "list"):
            return json.dumps(sports_mod.leagues_payload(), indent=2)
        raise ValueError("action must be scores or leagues")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"sports unavailable: {exc}") from exc


def _handle_arka_qr(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "ascii").strip().lower()
    try:
        from arka.integrations import qr_code as qr_mod

        text = str(
            arguments.get("text")
            or arguments.get("url")
            or arguments.get("data")
            or ""
        ).strip()
        if action in ("ascii", "generate", "encode"):
            return json.dumps(qr_mod.ascii_payload(text), indent=2)
        raise ValueError("action must be ascii")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"qr_code unavailable: {exc}") from exc


def _handle_arka_currency(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "convert").strip().lower()
    try:
        from arka.integrations import currency as currency_mod

        if action == "convert":
            amount = arguments.get("amount")
            if amount is None:
                raise ValueError("amount is required")
            from_ccy = str(
                arguments.get("from")
                or arguments.get("from_ccy")
                or arguments.get("source")
                or ""
            ).strip()
            to_ccy = str(
                arguments.get("to")
                or arguments.get("to_ccy")
                or arguments.get("target")
                or ""
            ).strip()
            if not from_ccy or not to_ccy:
                raise ValueError("from and to currencies are required")
            return json.dumps(
                currency_mod.convert_payload(amount, from_ccy, to_ccy),
                indent=2,
            )
        if action == "parse":
            text = str(arguments.get("text") or arguments.get("query") or "").strip()
            if not text:
                raise ValueError("text is required for parse")
            parsed = currency_mod.parse_convert(text)
            if parsed is None:
                raise ValueError(f"could not parse currency query: {text!r}")
            amount, from_ccy, to_ccy = parsed
            return json.dumps(
                currency_mod.convert_payload(amount, from_ccy, to_ccy),
                indent=2,
            )
        raise ValueError("action must be convert or parse")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"currency unavailable: {exc}") from exc


def _handle_arka_disk(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "usage").strip().lower()
    try:
        from arka.core import disk as disk_mod

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        if action == "usage":
            return json.dumps(disk_mod.usage_payload(path), indent=2)
        if action in ("breakdown", "categories"):
            return json.dumps(disk_mod.breakdown_payload(path), indent=2)
        raise ValueError("action must be usage or breakdown")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"disk unavailable: {exc}") from exc


def _handle_arka_ocr(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "auto").strip().lower()
    try:
        from arka.agent import ocr_skill as ocr

        path = str(arguments.get("path") or arguments.get("file") or "").strip()
        if action in {"extract", "image", "text"}:
            if not path:
                raise ValueError("path is required for extract")
            return json.dumps(
                ocr.extract_image_payload(
                    path,
                    with_blocks=not bool(arguments.get("no_blocks", False)),
                    with_zones=bool(arguments.get("zones", False)),
                ),
                indent=2,
            )
        if action in {"pdf", "searchable"}:
            if not path:
                raise ValueError("path is required for pdf")
            return json.dumps(
                ocr.pdf_ocr_payload(
                    path,
                    output=str(arguments.get("output") or "").strip() or None,
                    language=str(arguments.get("language") or "eng"),
                ),
                indent=2,
            )
        if action == "auto":
            if not path:
                raise ValueError("path is required")
            return json.dumps(
                ocr.ocr_payload(
                    path,
                    mode="auto",
                    output=str(arguments.get("output") or "").strip() or None,
                    language=str(arguments.get("language") or "eng"),
                    with_blocks=not bool(arguments.get("no_blocks", False)),
                    with_zones=bool(arguments.get("zones", False)),
                ),
                indent=2,
            )
        raise ValueError("action must be auto, extract, or pdf")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"ocr_skill unavailable: {exc}") from exc


def _handle_arka_rag(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.agent import rag_skill as rag

        extensions = arguments.get("extensions")
        ext_list: list[str] | None = None
        if isinstance(extensions, list):
            ext_list = [str(item) for item in extensions if str(item).strip()]
        elif isinstance(extensions, str) and extensions.strip():
            ext_list = [part.strip() for part in extensions.split(",") if part.strip()]

        payload = rag.rag_payload(
            action=action,
            path=str(arguments.get("path") or arguments.get("file") or "").strip() or None,
            question=str(arguments.get("question") or arguments.get("query") or "").strip() or None,
            document=str(arguments.get("document") or arguments.get("doc") or "").strip() or None,
            name=str(arguments.get("name") or "").strip() or None,
            extensions=ext_list,
            recursive=not bool(arguments.get("no_recursive", False)),
        )
        return json.dumps(payload, indent=2)
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"rag_skill unavailable: {exc}") from exc


def _handle_arka_ci(arguments: dict[str, Any]) -> str:
    try:
        from arka.agent.dev_tools import ci_payload

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        full = bool(arguments.get("full", False))
        changed_only = bool(arguments.get("changed_only", arguments.get("changed", False)))
        payload = ci_payload(path, full=full, changed_only=changed_only)
        if bool(arguments.get("fix")) and not payload.get("ok", True):
            from arka.agent.goal import run_goal

            run_goal(
                "Fix the first failing developer-tools CI gate and re-run verification.",
                max_steps=8,
                auto_yes=True,
                auto_continue=True,
            )
            payload = ci_payload(path, full=full, changed_only=changed_only)
        return json.dumps(payload, indent=2)
    except ImportError as exc:
        raise RuntimeError(f"dev_tools unavailable: {exc}") from exc


def _handle_arka_review(arguments: dict[str, Any]) -> str:
    try:
        from arka.agent.dev_tools import review_payload

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        payload = review_payload(
            path,
            base=str(arguments.get("base") or "").strip() or None,
            staged=bool(arguments.get("staged", False)),
        )
        return json.dumps(payload, indent=2)
    except ImportError as exc:
        raise RuntimeError(f"dev_tools unavailable: {exc}") from exc


def _handle_arka_repo_context(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "query").strip().lower()
    try:
        from arka.agent.repo_context import context_payload

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        query = str(arguments.get("query") or arguments.get("prompt") or "").strip()
        payload = context_payload(
            query,
            root=path,
            action=action,
            limit_chars=_mcp_int(arguments.get("limit_chars"), 12000),
        )
        return json.dumps(payload, indent=2)
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"repo_context unavailable: {exc}") from exc


def _handle_arka_coderabbit(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "comments").strip().lower()
    try:
        from arka.agent.coderabbit_review import coderabbit_payload, format_feedback

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        payload = coderabbit_payload(
            action,
            root=path,
            pr=_mcp_int_optional(arguments.get("pr")),
            full=bool(arguments.get("full", False)),
        )
        if action == "comments" and payload.get("ok") and not arguments.get("json"):
            return format_feedback(payload)
        return json.dumps(payload, indent=2)
    except ImportError as exc:
        raise RuntimeError(f"coderabbit unavailable: {exc}") from exc


def _handle_arka_pr_check(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "diff").strip().lower()
    try:
        from arka.agent.pr_check import pr_check_payload

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        payload = pr_check_payload(
            action,
            root=path,
            base=str(arguments.get("base") or "").strip() or None,
            pr=_mcp_int_optional(arguments.get("pr")),
            run_id=_mcp_int_optional(arguments.get("run_id") or arguments.get("run")),
            stat_only=bool(arguments.get("stat_only", False)),
        )
        return json.dumps(payload, indent=2)
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"pr_check unavailable: {exc}") from exc


def _handle_arka_code_search(arguments: dict[str, Any]) -> str:
    query = str(arguments.get("query") or arguments.get("pattern") or "").strip()
    if not query:
        raise ValueError("query is required")
    try:
        from arka.agent.code_search import search_payload

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        payload = search_payload(
            query,
            root=path,
            glob=str(arguments.get("glob") or "").strip() or None,
            limit=max(1, min(_mcp_int(arguments.get("limit"), 40), 200)),
            use_embeddings=bool(arguments.get("use_embeddings", False)),
        )
        return json.dumps(payload, indent=2)
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"code_search unavailable: {exc}") from exc


def _handle_arka_read_file(arguments: dict[str, Any]) -> str:
    path = str(arguments.get("path") or arguments.get("file") or "").strip()
    if not path:
        raise ValueError("path (or file) is required")
    try:
        from arka.agent.read_file import DEFAULT_MAX_BYTES, read_file_payload

        root = str(arguments.get("root") or arguments.get("project") or "").strip() or None
        limit_raw = arguments.get("limit")
        limit = _mcp_int_optional(limit_raw) if limit_raw not in (None, "") else None
        payload = read_file_payload(
            path,
            root=root,
            offset=max(1, _mcp_int(arguments.get("offset"), 1)),
            limit=limit,
            max_bytes=max(1024, min(_mcp_int(arguments.get("max_bytes"), DEFAULT_MAX_BYTES), 1_048_576)),
        )
        return json.dumps(payload, indent=2)
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"read_file unavailable: {exc}") from exc


def _handle_arka_apply_patch(arguments: dict[str, Any]) -> str:
    try:
        from arka.agent.apply_patch import PatchError, apply_patch_payload
        from arka.core.edit_guard import EditGuardError

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        payload = apply_patch_payload(
            root=path,
            diff=str(arguments.get("diff") or arguments.get("patch") or ""),
            file=str(arguments.get("file") or "").strip(),
            search=str(arguments.get("search") or arguments.get("old") or ""),
            replace=str(arguments.get("replace") or arguments.get("new") or ""),
        )
        return json.dumps(payload, indent=2)
    except (ValueError, PatchError, EditGuardError) as exc:
        if "edit blocked" in str(exc).lower():
            return json.dumps({"ok": False, "blocked": True, "error": str(exc)}, indent=2)
        raise
    except ImportError as exc:
        raise RuntimeError(f"apply_patch unavailable: {exc}") from exc


def _handle_arka_edit_guard(arguments: dict[str, Any]) -> str:
    try:
        from arka.core.edit_guard import guard_payload

        path = str(arguments.get("path") or arguments.get("file") or "").strip()
        root = str(arguments.get("root") or arguments.get("project") or "").strip() or None
        payload = guard_payload(
            action=str(arguments.get("action") or "check").strip().lower(),
            path=path,
            root=root,
            diff=str(arguments.get("diff") or arguments.get("patch") or ""),
        )
        return json.dumps(payload, indent=2)
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"edit_guard unavailable: {exc}") from exc


def _handle_arka_repo_health(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "scan").strip().lower()
    try:
        from arka.agent import repo_health as rh

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        if action == "scan":
            return json.dumps(rh.scan_payload(path), indent=2)
        if action == "run":
            cats: set[str] | None = None
            if bool(arguments.get("test")) and not bool(arguments.get("lint")):
                cats = {"test"}
            elif bool(arguments.get("lint")) and not bool(arguments.get("test")):
                cats = {"lint"}
            category = str(arguments.get("category") or "").strip().lower()
            if category in ("test", "lint"):
                cats = {category}
            return json.dumps(rh.run_payload(path, categories=cats), indent=2)
        raise ValueError("action must be scan or run")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"repo_health unavailable: {exc}") from exc


def _handle_arka_qa(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "plan").strip().lower()
    try:
        from arka.agent import qa_engineering as qa

        path = str(arguments.get("path") or arguments.get("root") or "").strip() or None
        feature = str(arguments.get("feature") or "").strip() or None
        base = str(arguments.get("base") or "").strip() or None
        if action == "plan":
            return json.dumps(qa.plan_payload(path, feature=feature), indent=2)
        if action == "extreme":
            return json.dumps(qa.extreme_payload(path, feature=feature), indent=2)
        if action == "checklist":
            return json.dumps(qa.checklist_payload(path, feature=feature, base=base), indent=2)
        if action == "triage":
            return json.dumps(qa.triage_payload(path, base=base), indent=2)
        if action == "coverage":
            return json.dumps(qa.coverage_payload(path), indent=2)
        if action == "report":
            return json.dumps(
                qa.report_payload(
                    title=str(arguments.get("title") or "Bug report"),
                    steps=str(arguments.get("steps") or ""),
                    expected=str(arguments.get("expected") or ""),
                    actual=str(arguments.get("actual") or ""),
                    severity=str(arguments.get("severity") or "medium"),
                    from_failure=bool(arguments.get("from_failure")),
                    root=path,
                ),
                indent=2,
            )
        if action == "explore":
            return json.dumps(qa.explore_payload(feature=feature), indent=2)
        raise ValueError("action must be plan, extreme, checklist, triage, coverage, report, or explore")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"qa_engineering unavailable: {exc}") from exc


def _handle_arka_connector(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations import cli_connector as cc

        if action == "connect":
            return json.dumps(
                cc.connect(
                    sync=not bool(arguments.get("no_sync")),
                    unify=bool(arguments.get("unify")),
                ),
                indent=2,
            )
        if action == "status":
            return json.dumps(cc.status_payload(), indent=2)
        if action == "context":
            goal = str(arguments.get("goal") or arguments.get("text") or "").strip()
            limit = _mcp_int(arguments.get("limit") or arguments.get("limit_chars"), 2500)
            block = cc.shared_context_block(goal, limit_chars=limit)
            return json.dumps({"goal": goal, "context": block, "chars": len(block)}, indent=2)
        if action == "doctor":
            return json.dumps(cc.doctor_payload(), indent=2)
        if action == "disconnect":
            return json.dumps(cc.disconnect(), indent=2)
        if action == "shell_init":
            shell = str(arguments.get("shell") or "auto").strip() or "auto"
            return json.dumps({"shell": shell, "script": cc.shell_init(shell=shell)}, indent=2)
        if action == "suggest":
            return json.dumps(cc.suggest_payload(), indent=2)
        raise ValueError("action must be connect, status, context, doctor, disconnect, shell_init, or suggest")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"cli_connector unavailable: {exc}") from exc


def _handle_arka_agent_hub(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "status").strip().lower()
    try:
        from arka.integrations import agent_hub

        if action == "status":
            return json.dumps(agent_hub.status_payload(), indent=2)
        if action == "adapters":
            return json.dumps(agent_hub.list_adapters(), indent=2)
        if action == "detect":
            return json.dumps(agent_hub.detect_agents(), indent=2)
        if action == "doctor":
            return json.dumps(agent_hub.doctor(), indent=2)
        if action == "memory_sources":
            return json.dumps(agent_hub.list_memory_sources(), indent=2)
        if action == "import_memory":
            path = str(arguments.get("path") or "").strip()
            source = str(
                arguments.get("source") or arguments.get("agent") or arguments.get("ide") or ""
            ).strip()
            all_sources = bool(arguments.get("all") or arguments.get("all_sources"))
            if path:
                return json.dumps(agent_hub.import_memory(Path(path)), indent=2)
            if source or all_sources:
                return json.dumps(
                    agent_hub.import_ide_memory(source=source or None, all_sources=all_sources),
                    indent=2,
                )
            raise ValueError("import_memory requires path, source/ide/agent, or all=true")
        if action in ("list", "agents"):
            return json.dumps(
                [
                    {
                        "key": key,
                        "name": meta.get("name", key),
                        "ollama_launch": meta.get("ollama_launch", key),
                    }
                    for key, meta in agent_hub.list_agents()
                ],
                indent=2,
            )
        raise ValueError(
            "action must be status, adapters, detect, doctor, list, memory_sources, or import_memory"
        )
    except ImportError as exc:
        raise RuntimeError(f"agent_hub unavailable: {exc}") from exc


def call_mcp_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Invoke an Arka MCP tool handler in-process (no stdio client)."""
    tool_name = str(name or "").strip()
    if not tool_name:
        raise ValueError("tool name is required")
    args = arguments or {}
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    for tool in _build_tools():
        if tool.name == tool_name:
            if tool.name in _mcp_disabled_tools():
                raise RuntimeError(_mcp_disabled_message(tool_name))
            return tool.handler(args)
    raise ValueError(f"Unknown MCP tool: {tool_name}")


def _handle_arka_self_build(arguments: dict[str, Any]) -> str:
    action = str(arguments.get("action") or "run").strip().lower()
    try:
        from arka.agent.self_build import (
            list_sessions,
            run_self_build,
            session_status,
            status_summary,
        )

        if action == "run":
            target = str(arguments.get("target") or arguments.get("focus") or "").strip()
            return json.dumps(
                {
                    "exit_code": run_self_build(
                        target,
                        apply=bool(arguments.get("apply", False)),
                        yes=bool(arguments.get("yes", False)),
                        max_rounds=_mcp_int(arguments.get("max_rounds"), 2),
                        max_steps=_mcp_int(arguments.get("max_steps"), 15),
                        auto_init=not bool(arguments.get("no_auto_init", False)),
                        use_jules=bool(arguments.get("use_jules", False)),
                        session_id=str(arguments.get("session_id") or "").strip(),
                    ),
                    "target": target or "general",
                },
                indent=2,
            )
        if action == "list":
            limit = _mcp_int(arguments.get("limit"), 20)
            return json.dumps(list_sessions(limit=max(1, min(limit, 100))), indent=2)
        if action == "status":
            session_id = str(arguments.get("session_id") or arguments.get("id") or "").strip()
            if session_id:
                data = session_status(session_id)
                if not data:
                    raise ValueError(f"unknown self-build session: {session_id}")
                return json.dumps(data, indent=2)
            return json.dumps(status_summary(), indent=2)
        raise ValueError("action must be run, list, or status")
    except ValueError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"self_build unavailable: {exc}") from exc


def _handle_arka_team_run(arguments: dict[str, Any]) -> str:
    team = str(arguments.get("team") or arguments.get("name") or "").strip()
    task = str(arguments.get("task") or "").strip()
    if not team:
        raise ValueError("team is required")
    if not task:
        raise ValueError("task is required")
    workflow = str(arguments.get("workflow") or "").strip() or None
    try:
        from arka.teams.executor import format_run_result, run_team

        result = run_team(
            team,
            task,
            workflow_name=workflow,
            promote_final=bool(arguments.get("promote_final", False)),
        )
        if arguments.get("json"):
            return json.dumps(result, indent=2)
        return format_run_result(result)
    except ImportError as exc:
        raise RuntimeError(f"teams unavailable: {exc}") from exc


def _build_tools() -> list[ArkaMcpTool]:
    return [
        ArkaMcpTool(
            name="arka_ask",
            description="Ask Arka a question — web search, memory, calc, weather, or chat.",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Question or request"},
                    "deep": {
                        "type": "boolean",
                        "description": "Use deep web search when applicable",
                        "default": False,
                    },
                },
                "required": ["prompt"],
            },
            handler=_handle_arka_ask,
        ),
        ArkaMcpTool(
            name="arka_remember",
            description="Store a fact, note, or channel turn in Arka unified memory.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Content to remember"},
                    "layer": {
                        "type": "string",
                        "enum": ["auto", "fact", "note", "channel"],
                        "default": "auto",
                    },
                    "long_term": {
                        "type": "boolean",
                        "description": "Persist note to long-term session memory",
                        "default": False,
                    },
                },
                "required": ["text"],
            },
            handler=_handle_arka_remember,
        ),
        ArkaMcpTool(
            name="arka_recall",
            description="Recall facts, notes, and channel context from Arka unified memory.",
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "What to recall or search for"},
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters in response",
                        "default": 3500,
                    },
                },
                "required": ["goal"],
            },
            handler=_handle_arka_recall,
        ),
        ArkaMcpTool(
            name="arka_intelligence",
            description=(
                "Arka Intelligence — live entity/relationship graph memory. "
                "Distills facts into entities and traverses relational links on recall "
                "(not vector chunk RAG). Actions: status, remember, recall, rebuild, export."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "remember", "recall", "rebuild", "export"],
                        "default": "status",
                    },
                    "text": {"type": "string", "description": "Fact to ingest when action=remember"},
                    "goal": {
                        "type": "string",
                        "description": "Recall goal when action=recall",
                    },
                    "query": {
                        "type": "string",
                        "description": "Alias for goal when action=recall",
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max chars for recall narrative",
                        "default": 1200,
                    },
                    "format": {
                        "type": "string",
                        "enum": ["mermaid", "json"],
                        "description": "Export format when action=export",
                        "default": "mermaid",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Include sample edges when action=status",
                        "default": True,
                    },
                },
            },
            handler=_handle_arka_intelligence,
        ),
        ArkaMcpTool(
            name="arka_skill",
            description=(
                "Invoke any Arka skill or routed command by name—not only design. "
                "Supports repo_health, lint_project, pr_check, qa_engineering, review, route_audit, "
                "self_improve, design_from_screenshot, compose_slides, urlkit, mcp, "
                "agent_hub, frontend_loop, sandbox, text, web_screenshot, spline, "
                "multi_llm, data collection, media transforms, races, reusable blocks, "
                "ultra-fast development, and all future dispatch-backed skills. "
                "Do not call generate_image for real-world subjects (breeds, places, people) "
                "or search/research tasks—use search_web, generate_thumbnail (Unsplash), or arka_ask instead."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill name or command head"},
                    "args": {
                        "description": "Skill arguments (string or list)",
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                    },
                },
                "required": ["skill"],
            },
            handler=_handle_arka_skill,
        ),
        ArkaMcpTool(
            name="arka_capabilities",
            description="List all MCP tools and dispatch-backed Arka skills currently available.",
            input_schema={"type": "object", "properties": {"include_internal": {"type": "boolean", "default": False}}},
            handler=_handle_arka_capabilities,
        ),
        ArkaMcpTool(
            name="arka_route",
            description=(
                "Umbrella Arka MCP tool: route and execute the user's complete natural-language request "
                "across Arka's CLI skills and MCP-backed capabilities. Prefer this when no narrower "
                "Arka MCP tool exactly matches, or for coding, CI/CD, research, data, media, browser QA, "
                "3D, sandbox, text editing, plugin, and skill workflows."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The user's complete natural-language Arka request; do not reduce it to a single guessed skill name.",
                    }
                },
                "required": ["prompt"],
            },
            handler=_handle_arka_route,
        ),
        ArkaMcpTool(
            name="arka_repo_map",
            description="Summarize repository layout and optional Python symbols.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo path (default: git root or cwd)"},
                    "depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
                    "symbols": {"type": "boolean", "default": True},
                },
            },
            handler=_handle_arka_repo_map,
        ),
        ArkaMcpTool(
            name="arka_heartbeat",
            description="OpenClaw-style agent heartbeat — ping, status, or recent activity history.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "ping", "history"],
                        "default": "status",
                        "description": "status snapshot, ping activity, or recent history",
                    },
                    "activity": {
                        "type": "string",
                        "description": "Activity label when action=ping",
                        "default": "mcp.ping",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events when action=history",
                        "default": 20,
                    },
                    "json": {
                        "type": "boolean",
                        "description": "Return JSON when action=status",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_heartbeat,
        ),
        ArkaMcpTool(
            name="arka_sessions",
            description="Hermes-style channel sessions — list, context, resume, silence_check, push, or reset.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "status",
                            "context",
                            "resume",
                            "silence_check",
                            "push",
                            "reset",
                        ],
                        "default": "list",
                        "description": "list, status, context, resume, silence_check, push, or reset",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Channel name (required for context, resume, push, reset)",
                    },
                    "chat_id": {
                        "type": "string",
                        "description": "Chat id within the channel (default: default)",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["user", "assistant", "system"],
                        "description": "Turn role when action=push",
                        "default": "user",
                    },
                    "text": {
                        "type": "string",
                        "description": "Turn text when action=push, or reply text when action=silence_check",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional session title when action=push",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max sessions (list) or turns (resume)",
                        "default": 20,
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 3000,
                    },
                },
            },
            handler=_handle_arka_sessions,
        ),
        ArkaMcpTool(
            name="arka_routines",
            description="OpenClaw-style scheduled routines — list, add, remove, enable, or disable.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "remove", "enable", "disable"],
                        "default": "list",
                        "description": "list, add, remove, enable, or disable a routine",
                    },
                    "schedule": {
                        "type": "string",
                        "description": "When to run (daily, hourly, or HH:MM) for action=add",
                    },
                    "task": {
                        "type": "string",
                        "description": "Task/command to schedule for action=add",
                    },
                    "id": {
                        "type": "string",
                        "description": "Routine id (required for remove/enable/disable; optional name for add)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional routine id when action=add",
                    },
                    "enabled_only": {
                        "type": "boolean",
                        "description": "Only include enabled routines when action=list",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_routines,
        ),
        ArkaMcpTool(
            name="arka_batch",
            description=(
                "Collect prompts until a due time, then run them as one combined coding task. "
                "Actions: start (open batch), add (queue prompt), list, run, due (run when due), clear."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "add", "list", "run", "due", "clear"],
                        "default": "list",
                        "description": "start, add, list, run, due, or clear a prompt batch",
                    },
                    "name": {
                        "type": "string",
                        "description": "Batch name (default: default)",
                        "default": "default",
                    },
                    "until": {
                        "type": "string",
                        "description": "Due time for start/add (e.g. '6pm', 'in 1 hour', ISO datetime)",
                    },
                    "due": {
                        "type": "string",
                        "description": "Alias for until",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Prompt text to queue when action=add",
                    },
                    "text": {
                        "type": "string",
                        "description": "Alias for prompt when action=add",
                    },
                    "print_only": {
                        "type": "boolean",
                        "description": "Return combined prompt without running agent_code when action=run/due",
                        "default": False,
                    },
                    "keep": {
                        "type": "boolean",
                        "description": "Keep batch after successful run when action=run/due",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_batch,
        ),
        ArkaMcpTool(
            name="arka_service_autostart",
            description=(
                "Register and autostart any service at login — add a command, script, or natural-language "
                "description (LLM infers command), install via launchd/systemd, list/status/run/uninstall."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "install", "uninstall", "remove", "status", "run"],
                        "default": "list",
                    },
                    "id": {
                        "type": "string",
                        "description": "Service id (required for add/install/uninstall/remove/status/run)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Alias for id",
                    },
                    "display_name": {
                        "type": "string",
                        "description": "Human-readable service name for action=add",
                    },
                    "command": {
                        "type": "string",
                        "description": "Shell command to run at login for action=add",
                    },
                    "script": {
                        "type": "string",
                        "description": "Path to an existing start script for action=add",
                    },
                    "description": {
                        "type": "string",
                        "description": "Natural-language service description; LLM infers command when command/script omitted",
                    },
                    "desc": {
                        "type": "string",
                        "description": "Alias for description",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory for action=add",
                    },
                    "env": {
                        "type": "object",
                        "description": "Environment variables for action=add",
                        "additionalProperties": {"type": "string"},
                    },
                },
            },
            handler=_handle_arka_service_autostart,
        ),
        ArkaMcpTool(
            name="arka_session_memory",
            description="OpenClaw-style markdown session memory — append, search, context, status, or clear.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["append", "search", "context", "status", "clear"],
                        "default": "status",
                        "description": "append, search, context, status, or clear notes",
                    },
                    "text": {
                        "type": "string",
                        "description": "Note text when action=append",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Recall goal when action=context (alias: query)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query when action=search",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["daily", "long_term", "all"],
                        "description": "What to clear when action=clear",
                        "default": "daily",
                    },
                    "long_term": {
                        "type": "boolean",
                        "description": "Also append to MEMORY.md when action=append",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max hits when action=search",
                        "default": 8,
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 2500,
                    },
                },
            },
            handler=_handle_arka_session_memory,
        ),
        ArkaMcpTool(
            name="arka_subagent",
            description="Hermes-style sub-agent delegation — spawn, list, status, or resume results.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["spawn", "list", "status", "resume"],
                        "default": "list",
                        "description": "spawn, list, status, or resume a sub-agent result",
                    },
                    "task": {
                        "type": "string",
                        "description": "Task prompt when action=spawn",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Sub-agent id when action=status or resume",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "Wait for completion when action=spawn (default: background)",
                        "default": False,
                    },
                    "session_channel": {
                        "type": "string",
                        "description": "Optional channel for session context + result push",
                    },
                    "session_chat_id": {
                        "type": "string",
                        "description": "Chat id within session_channel",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max agents when action=list",
                        "default": 20,
                    },
                },
            },
            handler=_handle_arka_subagent,
        ),
        ArkaMcpTool(
            name="arka_parallel",
            description=(
                "Symbolically decompose a goal into parallel subtasks and optionally "
                "spawn sub-agents (plan, run, status)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["plan", "run", "status"],
                        "default": "plan",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Natural-language goal when action=plan or run",
                    },
                    "task": {
                        "type": "string",
                        "description": "Alias for goal",
                    },
                    "plan_id": {
                        "type": "string",
                        "description": "Run id when action=status or optional override for run",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "Wait for sub-agents when action=run",
                        "default": False,
                    },
                    "json": {
                        "type": "boolean",
                        "description": "Return JSON for plan (default true)",
                        "default": True,
                    },
                },
            },
            handler=_handle_arka_parallel,
        ),
        ArkaMcpTool(
            name="arka_jules",
            description="Jules-style async coding sessions — assign tasks, fix GitHub issues, track status, open PRs.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["assign", "issue", "list", "status", "cancel", "pr"],
                        "default": "list",
                        "description": "assign, issue, list, status, cancel, or pr",
                    },
                    "task": {
                        "type": "string",
                        "description": "Coding task when action=assign",
                    },
                    "issue_number": {
                        "type": "integer",
                        "description": "GitHub issue number when action=issue",
                    },
                    "repo": {
                        "type": "string",
                        "description": "owner/repo when action=issue",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Session id when action=status, cancel, or pr",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "Wait for completion (default: background)",
                        "default": False,
                    },
                    "open_pr": {
                        "type": "boolean",
                        "description": "Open PR when session completes",
                        "default": False,
                    },
                    "branch": {
                        "type": "boolean",
                        "description": "Create jules/* branch before assign",
                        "default": False,
                    },
                    "max_steps": {
                        "type": "integer",
                        "description": "Goal agent max steps",
                        "default": 20,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows when action=list",
                        "default": 20,
                    },
                },
            },
            handler=_handle_arka_jules,
        ),
        ArkaMcpTool(
            name="arka_project_rules",
            description="Cursor-style project rules — list or read AGENTS.md, CLAUDE.md, .cursor/rules.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "status", "context"],
                        "default": "context",
                        "description": "list files, status, or truncated context block",
                    },
                    "root": {
                        "type": "string",
                        "description": "Project root (default: walk up from cwd)",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Optional goal to rank relevant rule files",
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 4000,
                    },
                },
            },
            handler=_handle_arka_project_rules,
        ),
        ArkaMcpTool(
            name="arka_human_docs",
            description=(
                "Human-sounding README/markdown bias — writing guide, prompt context, "
                "or generate docs to files instead of chat."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["guide", "status", "context", "write"],
                        "default": "context",
                    },
                    "goal": {"type": "string", "description": "Goal for context ranking or write prompt"},
                    "prompt": {"type": "string", "description": "Write prompt when action=write"},
                    "out": {"type": "string", "description": "Output path when action=write"},
                    "apply": {
                        "type": "boolean",
                        "description": "Write file to disk when action=write",
                        "default": False,
                    },
                    "context": {
                        "type": "string",
                        "description": "Existing markdown path to revise when action=write",
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 4000,
                    },
                },
            },
            handler=_handle_arka_human_docs,
        ),
        ArkaMcpTool(
            name="arka_website_pages",
            description=(
                "Website information architecture — page organization guide, prompt context, "
                "or generate a sitemap/page plan before building UI."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["guide", "status", "context", "plan"],
                        "default": "context",
                    },
                    "goal": {"type": "string", "description": "Goal for context or plan prompt"},
                    "prompt": {"type": "string", "description": "Plan prompt when action=plan"},
                    "context": {
                        "type": "string",
                        "description": "File with content to organize when action=plan",
                    },
                    "site_type": {
                        "type": "string",
                        "description": "Archetype hint: saas, docs, portfolio, app, marketing",
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters when action=context",
                        "default": 4000,
                    },
                },
            },
            handler=_handle_arka_website_pages,
        ),
        ArkaMcpTool(
            name="arka_convert_media",
            description=(
                "Convert images, video/audio, and slide decks between formats. "
                "Use action=convert with to=all for every supported output format."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["convert", "detect", "formats", "capabilities", "check", "parse"],
                        "default": "convert",
                    },
                    "path": {
                        "type": "string",
                        "description": "Input file path (convert, detect, formats)",
                    },
                    "to": {
                        "type": "string",
                        "description": "Target format, comma-separated formats, or all (default: all)",
                        "default": "all",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output path (single format or stem for multi-export)",
                    },
                    "quality": {
                        "type": "integer",
                        "description": "JPEG/WebP quality 1-100 (images)",
                    },
                    "width": {"type": "integer", "description": "Resize width (images)"},
                    "height": {"type": "integer", "description": "Resize height (images)"},
                    "trim_start": {
                        "type": "number",
                        "description": "Trim start seconds (video/audio)",
                    },
                    "trim_duration": {
                        "type": "number",
                        "description": "Trim duration seconds (video/audio)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_convert_media,
        ),
        ArkaMcpTool(
            name="arka_noise_remove",
            description=(
                "Remove background noise from audio or video files using ffmpeg afftdn. "
                "Video inputs keep the original video stream and replace the audio track."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["remove", "detect", "check", "parse"],
                        "default": "remove",
                    },
                    "path": {
                        "type": "string",
                        "description": "Input audio or video file (remove, detect)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                    "strength": {
                        "type": "number",
                        "description": "Noise reduction strength in dB (0-97, default 12)",
                        "default": 12,
                    },
                    "noise_floor": {
                        "type": "number",
                        "description": "Optional afftdn noise floor in dB (-80 to -20)",
                    },
                    "audio_only": {
                        "type": "boolean",
                        "description": "For video input, export denoised audio only",
                        "default": False,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_noise_remove,
        ),
        ArkaMcpTool(
            name="arka_edit_video",
            description=(
                "Edit local video/audio with ffmpeg — trim, concat, text overlay, extract audio, "
                "crop, resize, and mux audio. Use action=parse for natural language, action=detect "
                "for duration/metadata, action=check for ffmpeg setup."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "trim",
                            "concat",
                            "overlay-text",
                            "extract-audio",
                            "crop",
                            "resize",
                            "mux-audio",
                            "detect",
                            "check",
                            "parse",
                        ],
                        "default": "trim",
                    },
                    "path": {
                        "type": "string",
                        "description": "Input media file",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Input files for concat",
                    },
                    "output": {
                        "type": "string",
                        "description": "Output path",
                    },
                    "start": {
                        "type": "number",
                        "description": "Trim start offset in seconds",
                        "default": 0,
                    },
                    "duration": {
                        "type": "number",
                        "description": "Trim duration in seconds",
                    },
                    "end": {
                        "type": "number",
                        "description": "Trim end time in seconds",
                    },
                    "text": {
                        "type": "string",
                        "description": "Overlay caption text, or natural language when action=parse",
                    },
                    "position": {
                        "type": "string",
                        "enum": ["top", "center", "bottom"],
                        "default": "bottom",
                    },
                    "fontsize": {"type": "integer", "default": 48},
                    "color": {"type": "string", "default": "white"},
                    "width": {"type": "integer", "description": "Width for crop/resize"},
                    "height": {"type": "integer", "description": "Height for crop/resize"},
                    "x": {"type": "integer", "default": 0, "description": "Crop x offset"},
                    "y": {"type": "integer", "default": 0, "description": "Crop y offset"},
                    "format": {
                        "type": "string",
                        "description": "Output audio format for extract-audio",
                        "default": "mp3",
                    },
                    "audio": {
                        "type": "string",
                        "description": "Audio file for mux-audio action",
                    },
                    "no_shortest": {
                        "type": "boolean",
                        "description": "For mux-audio, do not trim to shorter stream",
                        "default": False,
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_edit_video,
        ),
        ArkaMcpTool(
            name="arka_dub_video",
            description=(
                "Dub a local video into another language — transcribe speech, translate, "
                "synthesize TTS (Edge or Sarvam), and mux onto the video. "
                "Use action=parse for natural language, action=detect for metadata."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["dub", "detect", "check", "parse"],
                        "default": "dub",
                    },
                    "path": {"type": "string", "description": "Input video file"},
                    "target": {
                        "type": "string",
                        "description": "Target language (hindi, es, tamil, …)",
                    },
                    "target_lang": {
                        "type": "string",
                        "description": "Alias for target",
                    },
                    "output": {"type": "string", "description": "Output video path"},
                    "source": {
                        "type": "string",
                        "description": "Source language code (default auto)",
                        "default": "auto",
                    },
                    "script": {
                        "type": "string",
                        "description": "Skip STT — use this narration text directly",
                    },
                    "script_path": {
                        "type": "string",
                        "description": "Path to narration text file (skip STT)",
                    },
                    "tts": {
                        "type": "string",
                        "enum": ["auto", "edge", "sarvam"],
                        "default": "auto",
                    },
                    "voice": {"type": "string", "description": "Optional TTS voice id"},
                    "text": {"type": "string", "description": "Natural language for action=parse"},
                    "query": {"type": "string", "description": "Natural language for action=parse"},
                },
            },
            handler=_handle_arka_dub_video,
        ),
        ArkaMcpTool(
            name="arka_fetch_lyrics",
            description=(
                "Fetch song lyrics (LRCLIB / lyrics.ovh), translate them, and optionally "
                "generate a new track with translated lyrics via Pollinations. "
                "Use action=parse for natural language like 'fetch lyrics for X by Y'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["fetch", "translate", "translate_text", "check", "parse"],
                        "default": "fetch",
                    },
                    "artist": {"type": "string", "description": "Artist name"},
                    "title": {"type": "string", "description": "Song title"},
                    "query": {
                        "type": "string",
                        "description": "Song as 'Title by Artist' (alternative to artist+title)",
                    },
                    "target": {
                        "type": "string",
                        "description": "Target language for translate (hindi, ta, es, …)",
                    },
                    "lyrics": {
                        "type": "string",
                        "description": "Raw lyrics for action=translate_text",
                    },
                    "generate": {
                        "type": "boolean",
                        "description": "Generate a new song with translated lyrics",
                        "default": False,
                    },
                    "remix": {
                        "type": "boolean",
                        "description": "Alias for generate",
                        "default": False,
                    },
                    "style": {
                        "type": "string",
                        "description": "Music style prompt when generate=true",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Generated song length in seconds",
                    },
                    "instrumental": {
                        "type": "boolean",
                        "description": "Instrumental only when generating music",
                        "default": False,
                    },
                    "output": {
                        "type": "string",
                        "description": "Output path (.txt for fetch, .mp3 when generate=true)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_fetch_lyrics,
        ),
        ArkaMcpTool(
            name="arka_play_website_game",
            description=(
                "Search for or open browser games in Playwright, or run the experimental vision agent. "
                "Headed play requires allow_browser=true. "
                "Disabled by default in MCP — opt in with ARKA_MCP_ENABLE_PERSONAL_SKILLS=1. "
                "Use action=parse for 'play snake online' or 'open browser game at https://…'. "
                "Use action=agent with learn=true for pattern learning + lightweight RL."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "search", "agent", "check", "parse"],
                        "default": "open",
                    },
                    "url": {"type": "string", "description": "Game URL for action=open"},
                    "query": {
                        "type": "string",
                        "description": "Search query e.g. snake game (action=search)",
                    },
                    "open": {
                        "type": "boolean",
                        "description": "Open best search result (action=search)",
                        "default": False,
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run headless (CI/tests; no allow_browser needed)",
                        "default": False,
                    },
                    "allow_browser": {
                        "type": "boolean",
                        "description": "Confirm headed browser open (required unless headless=true)",
                        "default": False,
                    },
                    "auto_start": {
                        "type": "boolean",
                        "description": "Try clicking Play/Start and focus canvas",
                        "default": False,
                    },
                    "wait_seconds": {
                        "type": "integer",
                        "description": "Seconds to keep headed browser open",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                    "turns": {
                        "type": "integer",
                        "description": "Agent turns for action=agent (default ARKA_GAME_AGENT_TURNS or 10)",
                    },
                    "learn": {
                        "type": "boolean",
                        "description": "Store successful patterns after agent session (action=agent)",
                        "default": True,
                    },
                    "rl": {
                        "type": "boolean",
                        "description": "Enable epsilon-greedy Q-table RL during agent play (experimental)",
                        "default": True,
                    },
                    "vision_backend": {
                        "type": "string",
                        "enum": ["vllm", "gemini", "ollama", "auto"],
                        "description": "Vision backend override for action=agent",
                    },
                },
            },
            handler=_handle_arka_play_website_game,
        ),
        ArkaMcpTool(
            name="arka_verify_web_interaction",
            description=(
                "Verify live website interactions using local code or Playwright/Cypress spec context. "
                "Optionally verify screenshots with vLLM/Gemini/Ollama vision via describe_source. "
                "Headed runs require allow_browser=true; headless=true is the CI default. "
                "Disabled by default in MCP — opt in with ARKA_MCP_ENABLE_PERSONAL_SKILLS=1. "
                "Use action=parse for NL like 'verify website interactions on https://… with component.tsx'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check", "parse", "check-deps"],
                        "default": "check",
                    },
                    "url": {"type": "string", "description": "Site URL for action=check"},
                    "context": {"type": "string", "description": "Component/source file path"},
                    "spec": {"type": "string", "description": "Playwright/Cypress spec file path"},
                    "repo": {"type": "string", "description": "Repo path to auto-find related UI files"},
                    "output": {"type": "string", "description": "Artifact directory"},
                    "headless": {
                        "type": "boolean",
                        "description": "Run headless (default true unless headed=true)",
                        "default": True,
                    },
                    "headed": {
                        "type": "boolean",
                        "description": "Show browser window (requires allow_browser=true)",
                        "default": False,
                    },
                    "allow_browser": {
                        "type": "boolean",
                        "description": "Confirm headed browser open",
                        "default": False,
                    },
                    "settle_seconds": {
                        "type": "number",
                        "description": "Seconds to wait after page load",
                    },
                    "vision": {
                        "type": "boolean",
                        "description": "Enable screenshot verification with describe_source vision",
                        "default": False,
                    },
                    "no_vision": {
                        "type": "boolean",
                        "description": "Disable vision verification even when ARKA_WEB_VERIFY_VISION=1",
                        "default": False,
                    },
                    "vllm_verify": {
                        "type": "boolean",
                        "description": "Enable vision verification using the vLLM backend",
                        "default": False,
                    },
                    "vision_backend": {
                        "type": "string",
                        "enum": ["vllm", "gemini", "ollama", "auto"],
                        "description": "Vision backend (default DESCRIBE_IMAGE_BACKEND or auto)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_verify_web_interaction,
        ),
        ArkaMcpTool(
            name="arka_safety_advice",
            description=(
                "Curated, inclusive safety guidance for domestic violence, sexual harassment, stalking, "
                "and abuse — gender-neutral playbooks and vetted hotlines from a fixed playbook, "
                "not improvised LLM legal advice. Use action=parse for NL detection."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["advice", "resources", "topics", "parse"],
                        "default": "advice",
                    },
                    "text": {
                        "type": "string",
                        "description": "Describe the situation (advice/parse)",
                    },
                    "topic": {
                        "type": "string",
                        "enum": [
                            "domestic_violence",
                            "sexual_harassment",
                            "workplace_harassment",
                            "stalking",
                            "digital_harassment",
                        ],
                        "description": "Force a topic instead of auto-classifying",
                    },
                    "region": {
                        "type": "string",
                        "enum": ["us", "in", "intl"],
                        "description": "Hotline region (default from ARKA_SAFETY_REGION or intl)",
                    },
                    "json": {
                        "type": "boolean",
                        "description": "Return JSON instead of markdown (advice action)",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_safety_advice,
        ),
        ArkaMcpTool(
            name="arka_signoz_publish",
            description=(
                "One-shot SigNoz hackathon publish: update signoz/BLOG.md, git push to GitHub, "
                "deploy landing/ to Vercel. Preview without yes/confirm; pass yes=true to execute."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run", "publish", "dry-run", "check", "parse"],
                        "default": "run",
                    },
                    "message": {
                        "type": "string",
                        "description": "Git commit message (required unless yes=true)",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Blog update topic for LLM refresh of signoz/BLOG.md",
                    },
                    "content": {
                        "type": "string",
                        "description": "Path to markdown file to write as signoz/BLOG.md",
                    },
                    "content_text": {
                        "type": "string",
                        "description": "Extra hint for blog generation",
                    },
                    "generate_blog": {
                        "type": "boolean",
                        "description": "Generate blog from git diff / topic",
                        "default": False,
                    },
                    "skip_blog": {"type": "boolean", "default": False},
                    "skip_git": {"type": "boolean", "default": False},
                    "skip_deploy": {"type": "boolean", "default": False},
                    "vercel_dir": {
                        "type": "string",
                        "default": "landing",
                        "description": "Directory for vercel deploy",
                    },
                    "production": {
                        "type": "boolean",
                        "description": "Run vercel --prod",
                        "default": False,
                    },
                    "yes": {
                        "type": "boolean",
                        "description": "Execute destructive steps (commit, push, deploy)",
                        "default": False,
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Alias for yes",
                        "default": False,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Simulate without git push or vercel deploy",
                        "default": False,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_signoz_publish,
        ),
        ArkaMcpTool(
            name="arka_create_video",
            description=(
                "Create local videos with ffmpeg — slideshow from images, still image with audio, "
                "or simple text slides from JSON. Supports transparent output (webm-alpha, mov-prores, "
                "mov-png, apng, gif). For AI/topic explainers use compose_video instead."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "check", "parse"],
                        "default": "create",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["slideshow", "image-audio", "text"],
                        "default": "slideshow",
                        "description": "slideshow: images/folder; image-audio: one image + audio; text: JSON slides",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Image files or directories (slideshow mode)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Single source path (slideshow shorthand)",
                    },
                    "image": {
                        "type": "string",
                        "description": "Still image path (image-audio mode)",
                    },
                    "audio": {
                        "type": "string",
                        "description": "Optional audio track",
                    },
                    "script": {
                        "type": "string",
                        "description": "JSON slide script path or inline JSON (text mode)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output path (.mp4, .webm, .mov, .apng, .gif)",
                    },
                    "transparent": {
                        "type": "boolean",
                        "description": "Preserve alpha channel (defaults to webm-alpha)",
                    },
                    "alpha": {
                        "type": "boolean",
                        "description": "Alias for transparent",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["mp4", "webm-alpha", "mov-prores", "mov-png", "apng", "gif"],
                        "description": "Output format; transparent formats preserve PNG alpha",
                    },
                    "slide_duration": {
                        "type": "number",
                        "description": "Seconds per slide in slideshow mode (default 3)",
                        "default": 3,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_create_video,
        ),
        ArkaMcpTool(
            name="arka_model_video",
            description=(
                "Create turntable or animated character videos from 3D models (.obj, .glb, .fbx, .stl) "
                "using Blender headless rendering, or build a slideshow from existing preview frames. "
                "Use action=animate for rigged FBX run cycles; action=parse for NL routing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["render", "animate", "check", "parse"],
                        "default": "render",
                    },
                    "source": {
                        "type": "string",
                        "description": "3D model path (.obj, .glb, .fbx, .stl)",
                    },
                    "model": {
                        "type": "string",
                        "description": "Alias for source",
                    },
                    "output": {
                        "type": "string",
                        "description": "Output MP4 path",
                    },
                    "backend": {
                        "type": "string",
                        "enum": ["auto", "blender", "turntable", "slideshow"],
                        "description": "auto: Blender turntable or preview slideshow fallback",
                    },
                    "mode": {
                        "type": "string",
                        "description": "Alias for backend (e.g. 3d, blender, slideshow)",
                    },
                    "frames": {
                        "type": "integer",
                        "description": "Turntable frame count (default 120)",
                    },
                    "fps": {
                        "type": "integer",
                        "description": "Output video FPS (default 30)",
                    },
                    "size": {
                        "type": "integer",
                        "description": "Square render resolution (default 1024)",
                    },
                    "angle": {
                        "type": "string",
                        "description": "Camera preset: auto, front, three-quarter, top, etc.",
                    },
                    "renders": {
                        "type": "string",
                        "description": "Directory of preview PNG/JPG frames (slideshow backend)",
                    },
                    "slide_duration": {
                        "type": "number",
                        "description": "Seconds per preview image in slideshow mode",
                        "default": 0.5,
                    },
                    "audio": {
                        "type": "string",
                        "description": "Optional background audio for slideshow mode",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Ground plane for action=animate (default true)",
                        "default": True,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_model_video,
        ),
        ArkaMcpTool(
            name="arka_compose_story",
            description=(
                "Labeled story videos — LLM narrative script with beat labels (intro, conflict, climax), "
                "TTS voiceover, captions, stock B-roll, and AI-generated images to auto-fill visual gaps. "
                "Use action=parse for 'tell a story about a robot learning to paint'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["compose", "check", "parse"],
                        "default": "compose",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Story topic or premise (compose, parse)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language alias for topic",
                    },
                    "script": {
                        "type": "string",
                        "description": "Optional JSON scene script file path",
                    },
                    "output": {
                        "type": "string",
                        "description": "Output .mp4 path",
                    },
                    "scenes": {
                        "type": "integer",
                        "description": "Fixed scene count",
                    },
                    "duration": {
                        "type": "string",
                        "description": "Target runtime e.g. 2m, 90s",
                    },
                    "labeled": {
                        "type": "boolean",
                        "description": "Show beat labels on screen (default true)",
                        "default": True,
                    },
                    "auto_fill": {
                        "type": "boolean",
                        "description": "AI images when stock misses (default true)",
                        "default": True,
                    },
                    "ai_images_only": {
                        "type": "boolean",
                        "description": "Use AI for all stills instead of stock",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_compose_story,
        ),
        ArkaMcpTool(
            name="arka_terminal_video",
            description=(
                "Create animated terminal demo videos from Arka CLI captures with optional "
                "edge-tts voiceover (ffmpeg + Pillow). Actions: build (full MP4), capture "
                "(record CLI output to text files), export-images (JPG showcase frames), "
                "check (deps), parse (NL → terminal_video args). Not compose_video or create_video."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["build", "capture", "export-images", "check", "parse"],
                        "default": "build",
                    },
                    "project_dir": {
                        "type": "string",
                        "description": "Repo/project root (default: auto-detect from cwd)",
                    },
                    "captures": {
                        "type": "string",
                        "description": "Directory with *.txt CLI captures (build)",
                    },
                    "script": {
                        "type": "string",
                        "description": "Voiceover script path with [M:SS] markers (build)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Output .mp4 (build) or JPG directory (export-images)",
                    },
                    "skip_verify": {
                        "type": "boolean",
                        "description": "Skip frame visibility checks during build",
                        "default": False,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_terminal_video,
        ),
        ArkaMcpTool(
            name="arka_music_generate",
            description=(
                "Generate original music with Pollinations (elevenmusic) or local ffmpeg tone synthesis. "
                "Use action=parse for natural language like 'create a song about summer'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "check", "parse"],
                        "default": "generate",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Music style or theme (generate)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output .mp3 path",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Length in seconds (3–300, default from MUSIC_DURATION or 30)",
                    },
                    "model": {
                        "type": "string",
                        "description": "Pollinations model (default elevenmusic)",
                    },
                    "lyrics": {
                        "type": "string",
                        "description": "Optional lyrics (Pollinations only)",
                    },
                    "instrumental": {
                        "type": "boolean",
                        "description": "Instrumental only — no vocals (Pollinations only)",
                        "default": False,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse or prompt fallback",
                    },
                },
            },
            handler=_handle_arka_music_generate,
        ),
        ArkaMcpTool(
            name="arka_local_music",
            description=(
                "Generate music locally with ffmpeg tone synthesis — no Pollinations or cloud API. "
                "Instrumental melodies only (no AI vocals). Requires ffmpeg. "
                "Use action=parse for 'generate music locally …'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "parse", "doctor"],
                        "default": "generate",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Music style or theme (generate)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output .mp3 path",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Length in seconds (3–300)",
                    },
                    "instrumental": {
                        "type": "boolean",
                        "description": "Instrumental only (default true for local synth)",
                        "default": True,
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_local_music,
        ),
        ArkaMcpTool(
            name="arka_ai_video",
            description=(
                "Full AI text-to-video (Pollinations, Gemini Veo 3.1 chain, Replicate). "
                "Not compose_video (stock photos) or create_video (ffmpeg slideshows). "
                "Use action=parse for 'generate full ai video of a sunset'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "check", "parse"],
                        "default": "generate",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Video description (generate)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output .mp4 path",
                    },
                    "aspect": {
                        "type": "string",
                        "enum": ["16:9", "9:16", "1:1"],
                        "default": "16:9",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Clip length in seconds (2–15)",
                    },
                    "model": {
                        "type": "string",
                        "description": "Preferred Gemini Veo model (fallback chain applies)",
                    },
                    "audio": {
                        "type": "boolean",
                        "description": "Pollinations audio track (default true)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_ai_video,
        ),
        ArkaMcpTool(
            name="arka_meme",
            description=(
                "Local meme templates with optional stock photos — Drake, comparison, caption, "
                "expanding-brain, two-button, vibe-coding. No AI tokens. "
                "Use action=parse for 'make a drake meme reject tests accept write tests'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "parse", "templates"],
                        "default": "create",
                    },
                    "template": {
                        "type": "string",
                        "description": "comparison | drake | caption | expanding-brain | two-button | vibe-coding",
                    },
                    "style": {
                        "type": "string",
                        "description": "Meme visual preset (classic, neon, retro, …)",
                    },
                    "output": {"type": "string", "description": "Optional output PNG path"},
                    "use_stock_images": {
                        "type": "boolean",
                        "description": "Fetch relevant stock photos for panels (default env MEME_USE_STOCK_PHOTOS)",
                    },
                    "reject": {"type": "string", "description": "Drake top panel text"},
                    "accept": {"type": "string", "description": "Drake bottom panel text"},
                    "left_label": {"type": "string"},
                    "right_label": {"type": "string"},
                    "left_title": {"type": "string"},
                    "right_title": {"type": "string"},
                    "top": {"type": "string", "description": "Caption meme top text"},
                    "bottom": {"type": "string", "description": "Caption meme bottom text"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Four labels for expanding-brain",
                    },
                    "dilemma": {"type": "string", "description": "Two-button dilemma text"},
                    "button_left": {"type": "string"},
                    "button_right": {"type": "string"},
                    "text": {"type": "string", "description": "Natural language for action=parse"},
                },
            },
            handler=_handle_arka_meme,
        ),
        ArkaMcpTool(
            name="arka_infographic",
            description=(
                "Adaptive infographic PNG — layout auto-picks row/grid/radial from item count. "
                "Local Pillow only, exact typography. "
                "Use action=parse for 'infographic about headaches items: tension, migraine'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "parse", "layouts", "styles"],
                        "default": "create",
                    },
                    "title": {"type": "string", "description": "Main headline"},
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Cell labels (layout follows count)",
                    },
                    "item": {
                        "type": "string",
                        "description": "Single item label (repeat via array in clients that support it)",
                    },
                    "layout": {
                        "type": "string",
                        "enum": ["auto", "row2", "row3", "grid4", "grid6", "grid9", "radial"],
                        "default": "auto",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["clean", "doodle", "dark", "meme"],
                        "description": "Infographic visual preset",
                    },
                    "output": {"type": "string", "description": "Optional output PNG path"},
                    "text": {"type": "string", "description": "Natural language for action=parse"},
                },
            },
            handler=_handle_arka_infographic,
        ),
        ArkaMcpTool(
            name="arka_reposition_image",
            description=(
                "Detect bad avatar/profile image crops (head clipped in circles) and reframe images "
                "or suggest CSS object-position. Local Pillow + optional face detection/vision. "
                "Use action=parse for 'fix profile picture cropping on photo.jpg'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check", "fix", "css", "fix-ui", "batch", "parse"],
                        "default": "check",
                    },
                    "path": {"type": "string", "description": "Image path for check/fix/css/fix-ui"},
                    "output": {"type": "string", "description": "Output path when action=fix"},
                    "folder": {"type": "string", "description": "Folder path when action=batch"},
                    "context": {"type": "string", "description": "Component/stylesheet path for fix-ui"},
                    "shape": {
                        "type": "string",
                        "enum": ["square", "circle"],
                        "default": "square",
                        "description": "Avatar shape context (circle for profile cards)",
                    },
                    "selector": {
                        "type": "string",
                        "default": ".avatar img",
                        "description": "CSS selector for css/fix-ui output",
                    },
                    "size": {"type": "integer", "description": "Output square size in pixels for fix/batch"},
                    "vision": {
                        "type": "boolean",
                        "description": "Use describe_source vision to refine framing (optional)",
                    },
                    "text": {"type": "string", "description": "Natural language for action=parse"},
                },
            },
            handler=_handle_arka_reposition_image,
        ),
        ArkaMcpTool(
            name="arka_filter_images",
            description=(
                "Hybrid two-pass image relevance filter: CLIP embeddings for fast scoring, "
                "VLM only on borderline cases. Score, filter, or check images against a text query. "
                "Use action=parse for 'filter irrelevant images in ./photos for laptop on desk'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["score", "filter", "check", "parse"],
                        "default": "score",
                    },
                    "folder": {"type": "string", "description": "Folder of images (score/filter)"},
                    "path": {"type": "string", "description": "Single image path (check)"},
                    "image": {"type": "string", "description": "Alias for path"},
                    "query": {"type": "string", "description": "Relevance query text"},
                    "output": {"type": "string", "description": "Copy kept images here (filter)"},
                    "borderline_pct": {
                        "type": "number",
                        "description": "Borderline band width percent (default 20)",
                    },
                    "vlm_pass": {
                        "type": "boolean",
                        "description": "Run VLM on borderline images",
                    },
                    "text": {"type": "string", "description": "NL input when action=parse"},
                },
            },
            handler=_handle_arka_filter_images,
        ),
        ArkaMcpTool(
            name="arka_media_styles",
            description=(
                "List shared visual style presets for meme templates, video generation, and infographics."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list"],
                        "default": "list",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["all", "meme", "video", "infographic"],
                        "default": "all",
                    },
                },
            },
            handler=_handle_arka_media_styles,
        ),
        ArkaMcpTool(
            name="arka_tech_stack",
            description=(
                "Suggest a project's tech stack by searching for a similarly named folder, "
                "confirming with y/n when the folder name is not an exact match, then reading "
                "pyproject.toml, package.json, README, and workspace manifests. "
                "Use action=parse for 'what is the best tech stack for arka-agent'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["suggest", "search", "parse"],
                        "default": "suggest",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name to search for (e.g. arka-agent)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language query (suggest, parse)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Use this directory instead of fuzzy search",
                    },
                    "roots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Extra search roots (e.g. ~/dev)",
                    },
                    "yes": {
                        "type": "boolean",
                        "description": "Accept best fuzzy folder match without prompting",
                    },
                    "non_interactive": {
                        "type": "boolean",
                        "description": "Fail on fuzzy match instead of prompting",
                    },
                    "candidates": {
                        "type": "boolean",
                        "description": "Include candidate folders when suggest fails",
                    },
                },
            },
            handler=_handle_arka_tech_stack,
        ),
        ArkaMcpTool(
            name="arka_google_flow",
            description=(
                "Create AI video with Google Flow (labs.google/fx/tools/flow) via browser automation "
                "or Gemini Veo API fallback. Use action=parse for natural language like "
                "'create video in google flow of a sunset'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "open", "check", "parse"],
                        "default": "generate",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Video description (generate, open)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output .mp4 path",
                    },
                    "aspect": {
                        "type": "string",
                        "enum": ["16:9", "9:16", "1:1"],
                        "default": "16:9",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Clip length in seconds (4–8, gemini backend)",
                    },
                    "model": {
                        "type": "string",
                        "description": "Gemini Veo model (default GOOGLE_FLOW_VEO_MODEL or veo-2.0-generate-001)",
                    },
                    "backend": {
                        "type": "string",
                        "enum": ["auto", "browser", "gemini", "open"],
                        "description": "auto | browser | gemini | open",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural language for action=parse",
                    },
                },
            },
            handler=_handle_arka_google_flow,
        ),
        ArkaMcpTool(
            name="arka_webhook",
            description="OpenClaw/Hermes-style webhook gateway — status or health (no serve via MCP).",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "health"],
                        "default": "status",
                        "description": "status: listener config; health: /v1/health payload",
                    },
                },
            },
            handler=_handle_arka_webhook,
        ),
        ArkaMcpTool(
            name="arka_markdown",
            description=(
                "Read or ask about any local .md/.mdx file without document ingest. "
                "Alias paths `frontend-content-guide`, `google-design` / `design.md`, and "
                "`ascii-isometric-landing-page` load bundled design guides."
                "Arka's bundled UI guides (also auto-injected for frontend/UI goals via memory_context)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "context", "ask"],
                        "default": "context",
                        "description": "read: full text; context: agent block; ask: LLM Q&A over file",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Path to a .md, .mdx, or .markdown file, or alias "
                            "frontend-content-guide / google-design / design.md / ascii-isometric-landing-page"
                        ),
                    },
                    "question": {
                        "type": "string",
                        "description": "Required when action=ask",
                    },
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max chars for read/context",
                        "default": 8000,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_arka_markdown,
        ),
        ArkaMcpTool(
            name="arka_view_data",
            description="Preview CSV/TSV tables as plain text (csvlook-style) for agents.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["preview"],
                        "default": "preview",
                        "description": "preview: return table text and column metadata",
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to a .csv or .tsv file",
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Max data rows to include",
                        "default": 50,
                    },
                    "delimiter": {
                        "type": "string",
                        "description": "Optional delimiter override (default: auto)",
                    },
                    "plain": {
                        "type": "boolean",
                        "description": "Disable ANSI colors (default: true for MCP)",
                        "default": True,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_arka_view_data,
        ),
        ArkaMcpTool(
            name="arka_view_output",
            description=(
                "Render JSON, CSV, markdown, or text in the Arka Output Viewer — "
                "returns HTML metadata or opens a browser for local files."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["render", "show", "open"],
                        "default": "render",
                        "description": "render: HTML payload; show: open file in browser; open: open content in browser",
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to a local data file",
                    },
                    "content": {
                        "type": "string",
                        "description": "Inline content when path is omitted",
                    },
                    "format": {
                        "type": "string",
                        "description": "Optional format override (json, csv, markdown, text, …)",
                    },
                    "title": {
                        "type": "string",
                        "description": "Viewer title",
                    },
                    "open_browser": {
                        "type": "boolean",
                        "description": "When action=show, open the browser (default false for MCP)",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_view_output,
        ),
        ArkaMcpTool(
            name="arka_clipboard",
            description="Clipboard history — list, save, get, or clear saved clips (Cursor-style pasteboard memory).",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "save", "get", "clear"],
                        "default": "list",
                        "description": "list previews, save text/clipboard, get full entry, or clear",
                    },
                    "text": {
                        "type": "string",
                        "description": "Optional text to save (otherwise reads system clipboard)",
                    },
                    "index": {
                        "type": "integer",
                        "description": "1-based entry index when action=get",
                        "default": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows when action=list",
                        "default": 20,
                    },
                },
            },
            handler=_handle_arka_clipboard,
        ),
        ArkaMcpTool(
            name="arka_share",
            description=(
                "Share the last LLM response in one bundle with model, provider, tokens, "
                "latency, task/skill, and output text (markdown or JSON)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["last", "format"],
                        "default": "last",
                        "description": "Share last completion or format explicit output",
                    },
                    "output": {
                        "type": "string",
                        "description": "Response text (required for action=format)",
                    },
                    "provider": {"type": "string", "description": "Override provider slug"},
                    "model": {"type": "string", "description": "Override model id"},
                    "task": {"type": "string", "description": "Override task profile"},
                    "skill": {"type": "string", "description": "Override skill name"},
                    "latency_ms": {"type": "number", "description": "Override latency in ms"},
                    "prompt_tokens": {"type": "integer"},
                    "completion_tokens": {"type": "integer"},
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "json"],
                        "default": "markdown",
                    },
                    "copy": {
                        "type": "boolean",
                        "description": "Copy formatted bundle to system clipboard",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_share,
        ),
        ArkaMcpTool(
            name="arka_remind",
            description="OpenClaw-style reminders — list, add, or cancel scheduled nudges.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "cancel"],
                        "default": "list",
                        "description": "list, add, or cancel a reminder",
                    },
                    "text": {
                        "type": "string",
                        "description": "Reminder message (may include 'in 30m' / 'at 5pm')",
                    },
                    "at": {
                        "type": "string",
                        "description": "Optional absolute time for action=add",
                    },
                    "in": {
                        "type": "string",
                        "description": "Optional relative delay (30m, 2h) for action=add",
                    },
                    "id": {
                        "type": "string",
                        "description": "Reminder id prefix when action=cancel",
                    },
                    "include_done": {
                        "type": "boolean",
                        "description": "Include cancelled/done when action=list",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows when action=list",
                        "default": 50,
                    },
                    "start": {
                        "type": "boolean",
                        "description": "Start reminder daemon after add (default: false for MCP)",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_remind,
        ),
        ArkaMcpTool(
            name="arka_alert",
            description=(
                "Email alerts — send or schedule cross-platform notifications for selections, "
                "credits, hackathons, and study deadlines."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "list", "send", "schedule", "test"],
                        "default": "status",
                        "description": "status, list, send, schedule, or test",
                    },
                    "text": {
                        "type": "string",
                        "description": "Alert message for send/schedule",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional subject/title for action=send",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional email body for action=send",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["selection", "credits", "hackathon", "studies", "general"],
                        "description": "Alert category (auto-detected when omitted)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Optional source URL or citation for action=send",
                    },
                    "at": {
                        "type": "string",
                        "description": "Absolute deadline for action=schedule",
                    },
                    "in": {
                        "type": "string",
                        "description": "Relative delay for action=schedule (30m, 2h)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows when action=list",
                        "default": 20,
                    },
                    "start": {
                        "type": "boolean",
                        "description": "Start remind daemon after schedule (default: false for MCP)",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_alert,
        ),
        ArkaMcpTool(
            name="arka_bookmarks",
            description="Cursor-style bookmarks — list, save, search, get, or delete saved links.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "save", "search", "get", "delete"],
                        "default": "list",
                        "description": "list, save, search, get, or delete bookmarks",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL when action=save",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title when action=save",
                    },
                    "tags": {
                        "description": "Optional tags (comma string or array) when action=save",
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional note when action=save",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search keywords when action=search",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Filter tag when action=list",
                    },
                    "index": {
                        "type": "integer",
                        "description": "1-based index when action=get or delete",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows for list/search",
                        "default": 50,
                    },
                },
            },
            handler=_handle_arka_bookmarks,
        ),
        ArkaMcpTool(
            name="arka_docker",
            description=(
                "Docker status — health, running containers, images, or container logs "
                "(OpenClaw-style local infra awareness)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["health", "ps", "images", "logs"],
                        "default": "health",
                        "description": "health, ps (containers), images, or logs",
                    },
                    "container": {
                        "type": "string",
                        "description": "Container name when action=logs",
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Log lines when action=logs",
                        "default": 50,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max images when action=images",
                        "default": 50,
                    },
                },
            },
            handler=_handle_arka_docker,
        ),
        ArkaMcpTool(
            name="arka_jsonkit",
            description=(
                "JSON helpers — validate, pretty-print, minify, or get a value "
                "by dotted path like a.b[0] (offline)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["validate", "pretty", "minify", "get"],
                        "default": "validate",
                        "description": "validate, pretty, minify, or get",
                    },
                    "json": {"type": "string", "description": "JSON text input"},
                    "text": {"type": "string", "description": "Alias for json"},
                    "indent": {
                        "type": "integer",
                        "description": "Indent when action=pretty",
                        "default": 2,
                    },
                    "path": {
                        "type": "string",
                        "description": "Dotted/bracket path when action=get",
                    },
                },
            },
            handler=_handle_arka_jsonkit,
        ),
        ArkaMcpTool(
            name="arka_timekit",
            description=(
                "Time helpers — current time in a timezone, convert datetimes, "
                "or apply simple relative offsets like 2h / in 3 days (offline)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["now", "convert", "relative"],
                        "default": "now",
                        "description": "now, convert, or relative",
                    },
                    "tz": {"type": "string", "description": "Timezone e.g. Asia/Kolkata"},
                    "timezone": {"type": "string", "description": "Alias for tz"},
                    "datetime": {"type": "string", "description": "ISO datetime for convert"},
                    "to_tz": {"type": "string", "description": "Target timezone for convert"},
                    "from_tz": {"type": "string", "description": "Source timezone if datetime is naive"},
                    "expression": {
                        "type": "string",
                        "description": "Relative offset e.g. 2h, -30m, in 3 days",
                    },
                    "base": {
                        "type": "string",
                        "description": "Optional base ISO datetime for relative",
                    },
                },
            },
            handler=_handle_arka_timekit,
        ),
        ArkaMcpTool(
            name="arka_urlkit",
            description=(
                "URL helpers — parse components, normalize a URL, or slugify text "
                "for paths/filenames (offline)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["parse", "normalize", "slugify"],
                        "default": "parse",
                        "description": "parse, normalize, or slugify",
                    },
                    "url": {"type": "string", "description": "URL for parse/normalize"},
                    "text": {"type": "string", "description": "Text for slugify (or URL alias)"},
                    "drop_fragment": {
                        "type": "boolean",
                        "description": "Drop #fragment when normalizing",
                        "default": True,
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Max slug length",
                        "default": 80,
                    },
                },
            },
            handler=_handle_arka_urlkit,
        ),
        ArkaMcpTool(
            name="arka_password",
            description=(
                "Generate a strong one-shot password (not stored). "
                "Vault get/set is intentionally not exposed via MCP."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate"],
                        "default": "generate",
                        "description": "generate: create a random password",
                    },
                    "length": {
                        "type": "integer",
                        "description": "Password length (8-128)",
                        "default": 16,
                    },
                    "symbols": {
                        "type": "boolean",
                        "description": "Include symbol characters",
                        "default": True,
                    },
                },
            },
            handler=_handle_arka_password,
        ),
        ArkaMcpTool(
            name="arka_spotify",
            description=(
                "Spotify search — resolve a song query to track id, URI, and URL "
                "(search only; does not start playback)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search"],
                        "default": "search",
                        "description": "search: resolve query to a track",
                    },
                    "query": {
                        "type": "string",
                        "description": "Song or artist query",
                    },
                },
            },
            handler=_handle_arka_spotify,
        ),
        ArkaMcpTool(
            name="arka_textkit",
            description=(
                "Offline text utilities — generate UUIDs, hash strings "
                "(sha256/md5/…), or base64 encode/decode."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["uuid", "hash", "base64"],
                        "default": "uuid",
                        "description": "uuid, hash, or base64",
                    },
                    "text": {
                        "type": "string",
                        "description": "Input text for hash or base64",
                    },
                    "algorithm": {
                        "type": "string",
                        "description": "Hash algorithm (sha256, sha512, sha1, md5)",
                        "default": "sha256",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["encode", "decode"],
                        "description": "Base64 mode when action=base64",
                        "default": "encode",
                    },
                    "version": {
                        "type": "integer",
                        "description": "UUID version 4 or 5",
                        "default": 4,
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for uuid5",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "uuid5 namespace: dns, url, oid, x500",
                        "default": "url",
                    },
                },
            },
            handler=_handle_arka_textkit,
        ),
        ArkaMcpTool(
            name="arka_calendar",
            description=(
                "macOS Calendar — list today's events from Calendar.app "
                "(requires Calendar automation permission)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["today"],
                        "default": "today",
                        "description": "today: events starting today",
                    },
                },
            },
            handler=_handle_arka_calendar,
        ),
        ArkaMcpTool(
            name="arka_platform",
            description=(
                "Host platform — show cached OS/capabilities or run detection "
                "(macos/linux/windows clipboard, open, package manager)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["show", "detect"],
                        "default": "show",
                        "description": "show: cached/live profile; detect: (re)detect capabilities",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "When action=detect, refresh even if cache exists",
                        "default": False,
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "When action=detect, write platform.json cache",
                        "default": True,
                    },
                },
            },
            handler=_handle_arka_platform,
        ),
        ArkaMcpTool(
            name="arka_personalize",
            description=(
                "Personalization — profile status, ranked skill recommendations, "
                "or quickstart steps (read-only)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "recommend", "quickstart"],
                        "default": "status",
                        "description": "status: profile; recommend: ranked skills; quickstart: setup steps",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max recommendations when action=recommend",
                        "default": 8,
                    },
                },
            },
            handler=_handle_arka_personalize,
        ),
        ArkaMcpTool(
            name="arka_persona",
            description=(
                "Personas — list installed persona configs or show one persona's "
                "metadata and system prompt (read-only)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "show"],
                        "default": "list",
                        "description": "list: inventory; show: details for one persona",
                    },
                    "name": {
                        "type": "string",
                        "description": "Persona slug when action=show",
                    },
                    "include_templates": {
                        "type": "boolean",
                        "description": "Include bundled templates when action=list",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_persona,
        ),
        ArkaMcpTool(
            name="arka_github",
            description=(
                "GitHub repo activity — resolve owner/repo from text or fetch recent "
                "commits and modified files (local git or gh API). "
                "Use action=resume to build a resume PDF from a GitHub profile."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["activity", "resolve", "resume"],
                        "default": "activity",
                        "description": "activity: commits/files; resolve: parse owner/repo; resume: profile PDF",
                    },
                    "owner": {"type": "string", "description": "GitHub owner/org"},
                    "repo": {"type": "string", "description": "Repository name or owner/repo"},
                    "query": {
                        "type": "string",
                        "description": "Free text containing a GitHub repo reference or username",
                    },
                    "username": {
                        "type": "string",
                        "description": "GitHub username for action=resume",
                    },
                    "user": {
                        "type": "string",
                        "description": "Alias for username (resume action)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Output PDF path for action=resume",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["modern", "classic"],
                        "description": "Resume style for action=resume",
                    },
                    "markdown": {
                        "type": "boolean",
                        "description": "Also write markdown when action=resume",
                        "default": False,
                    },
                    "days": {
                        "type": "integer",
                        "description": "Lookback window in days",
                        "default": 7,
                    },
                },
            },
            handler=_handle_arka_github,
        ),
        ArkaMcpTool(
            name="arka_price",
            description=(
                "Product price-check helpers — list retailer sources by region/product "
                "or parse a natural-language price query (no live scrape)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["sources", "parse"],
                        "default": "sources",
                        "description": "sources: list retailers; parse: extract product/region",
                    },
                    "region": {
                        "type": "string",
                        "description": "india or us",
                    },
                    "product": {
                        "type": "string",
                        "description": "Product name for category-aware sources",
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural-language query for parse or sources",
                    },
                },
            },
            handler=_handle_arka_price,
        ),
        ArkaMcpTool(
            name="arka_config",
            description=(
                "Arka config inventory — list known config files/dirs or show "
                "config/cache paths and an export snippet (read-only)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "path"],
                        "default": "list",
                        "description": "list: inventory entries; path: config/cache roots",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional config root override when action=path",
                    },
                },
            },
            handler=_handle_arka_config,
        ),
        ArkaMcpTool(
            name="arka_model",
            description=(
                "Select and inspect LLM models — show current provider/model, "
                "provider health dashboard, recommend models from hardware, list "
                "providers/models, or set AI_PREFERRED_PROVIDER / AI_PREFERRED_MODEL."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "dashboard",
                            "recommend",
                            "apply",
                            "probe",
                            "list_providers",
                            "list_models",
                            "set",
                            "arbitrage",
                        ],
                        "default": "status",
                        "description": (
                            "status: current provider/model; dashboard: provider health, "
                            "rate-limit exhaustion, fallback chain; recommend: hardware-based "
                            "profile suggestions; apply: write recommendations; probe: "
                            "hardware snapshot; list_providers/list_models: catalogs; "
                            "set: choose provider and optional model; "
                            "arbitrage: cost-based provider hot-swap (mode=status|once|start|stop)"
                        ),
                    },
                    "provider": {
                        "type": "string",
                        "description": "Provider slug for set/list_models (openrouter, ollama, gemini, …)",
                    },
                    "model": {
                        "type": "string",
                        "description": "Model id for set (e.g. claude-sonnet-4, openrouter/anthropic/claude-3.5-sonnet)",
                    },
                    "apply": {
                        "type": "boolean",
                        "description": "When action=recommend, write profile models to llm-skill-models.json",
                        "default": False,
                    },
                    "local": {
                        "type": "boolean",
                        "description": "When action=recommend, pick strongest runnable local Ollama model(s)",
                        "default": False,
                    },
                    "top": {
                        "type": "integer",
                        "description": "With local recommend, how many models to return",
                        "default": 1,
                    },
                    "refresh": {
                        "type": "boolean",
                        "description": "Force-refresh live model catalog from provider API",
                        "default": False,
                    },
                    "autodetect": {
                        "type": "boolean",
                        "description": "When action=set without model, pick a default from the provider catalog",
                        "default": True,
                    },
                    "all": {
                        "type": "boolean",
                        "description": "When action=list_models, include exhausted/unavailable models",
                        "default": False,
                    },
                    "live": {
                        "type": "boolean",
                        "description": "When action=dashboard, live provider probes + balance + chain",
                        "default": False,
                    },
                    "balance": {
                        "type": "boolean",
                        "description": "When action=dashboard, fetch OpenRouter balance",
                        "default": False,
                    },
                    "chain": {
                        "type": "boolean",
                        "description": "When action=dashboard, include fallback chain candidates",
                        "default": False,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["status", "once", "start", "stop"],
                        "description": "When action=arbitrage: status, once (swap), start monitor, stop monitor",
                    },
                    "subaction": {
                        "type": "string",
                        "description": "Alias for mode when action=arbitrage",
                    },
                    "interval": {
                        "type": "number",
                        "description": "When action=arbitrage and mode=start, poll interval seconds",
                    },
                    "foreground": {
                        "type": "boolean",
                        "description": "When action=arbitrage and mode=start, run monitor in foreground",
                        "default": False,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "When action=arbitrage and mode=once, evaluate without writing .env",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_model,
        ),
        ArkaMcpTool(
            name="arka_finetune_model",
            description=(
                "Plan, validate, and scaffold local LLM fine-tuning (LoRA/QLoRA/full). "
                "Generates training config and shell script; dry-run by default. "
                "Use action=parse for NL routing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["plan", "validate", "generate", "status", "parse", "check"],
                        "default": "plan",
                    },
                    "task": {
                        "type": "string",
                        "description": "Natural language fine-tune goal (plan, parse)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Alias for task",
                    },
                    "base_model": {
                        "type": "string",
                        "description": "HuggingFace or local base model id (generate, plan)",
                    },
                    "dataset": {
                        "type": "string",
                        "description": "Dataset path (validate, generate, plan)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Alias for dataset or output_dir depending on action",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["auto", "lora", "qlora", "full"],
                        "default": "auto",
                    },
                    "backend": {
                        "type": "string",
                        "enum": ["auto", "mlx", "unsloth", "axolotl", "huggingface", "trl"],
                        "default": "auto",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory for configs/checkpoints",
                        "default": "./finetune-out",
                    },
                    "apply": {
                        "type": "boolean",
                        "description": "When action=generate, write config/script files",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_finetune_model,
        ),
        ArkaMcpTool(
            name="arka_tunnel",
            description=(
                "Expose local Ollama as a production OpenAI-compatible endpoint — "
                "start/stop authenticated proxy, optional cloudflared/ngrok tunnel, "
                "API key management, and rate limiting."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "start", "stop"],
                        "default": "status",
                        "description": "status: proxy/tunnel state; start: proxy (+ tunnel); stop: shutdown",
                    },
                    "host": {
                        "type": "string",
                        "description": "Proxy bind host when action=start (default 127.0.0.1)",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Proxy port when action=start (default OLLAMA_TUNNEL_PORT or 11435)",
                    },
                    "no_tunnel": {
                        "type": "boolean",
                        "description": "When action=start, skip cloudflared/ngrok public tunnel",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_tunnel,
        ),
        ArkaMcpTool(
            name="arka_sports",
            description=(
                "Live sports scores (ESPN) — fetch scores by league query "
                "or list supported leagues (IPL, NFL, EPL, NBA, …)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scores", "leagues"],
                        "default": "scores",
                        "description": "scores: live scoreboard; leagues: supported aliases",
                    },
                    "query": {
                        "type": "string",
                        "description": "League/sport query e.g. ipl, nfl, epl, all",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events per league",
                        "default": 3,
                    },
                },
            },
            handler=_handle_arka_sports,
        ),
        ArkaMcpTool(
            name="arka_qr",
            description=(
                "Generate a QR code as ASCII art from text or a URL "
                "(useful for sharing links offline in the terminal)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["ascii"],
                        "default": "ascii",
                        "description": "ascii: return QR as terminal ASCII art",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text or URL to encode",
                    },
                    "url": {
                        "type": "string",
                        "description": "Alias for text when encoding a URL",
                    },
                },
                            },
            handler=_handle_arka_qr,
        ),
        ArkaMcpTool(
            name="arka_currency",
            description=(
                "Currency conversion — convert amounts between ISO currencies "
                "or parse a natural-language query like '100 USD to INR'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["convert", "parse"],
                        "default": "convert",
                        "description": "convert: explicit amount/from/to; parse: natural language",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount when action=convert",
                    },
                    "from": {
                        "type": "string",
                        "description": "Source currency (ISO code or name)",
                    },
                    "to": {
                        "type": "string",
                        "description": "Target currency (ISO code or name)",
                    },
                    "text": {
                        "type": "string",
                        "description": "Natural-language query when action=parse",
                    },
                },
            },
            handler=_handle_arka_currency,
        ),
        ArkaMcpTool(
            name="arka_disk",
            description=(
                "Disk space — quick usage summary or home-folder breakdown by category "
                "(videos, downloads, cache, etc.)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["usage", "breakdown"],
                        "default": "usage",
                        "description": "usage: df summary; breakdown: category scan",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional path to measure (default: home directory)",
                    },
                },
            },
            handler=_handle_arka_disk,
        ),
        ArkaMcpTool(
            name="arka_repo_health",
            description=(
                "Cursor-style repo health — scan for lint/test commands or run them "
                "in the current project."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scan", "run"],
                        "default": "scan",
                        "description": "scan: detect checks; run: execute checks",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional project root (default: git root / cwd)",
                    },
                    "test": {
                        "type": "boolean",
                        "description": "When action=run, only run test checks",
                        "default": False,
                    },
                    "lint": {
                        "type": "boolean",
                        "description": "When action=run, only run lint checks",
                        "default": False,
                    },
                    "category": {
                        "type": "string",
                        "enum": ["test", "lint"],
                        "description": "Optional category filter when action=run",
                    },
                },
            },
            handler=_handle_arka_repo_health,
        ),
        ArkaMcpTool(
            name="arka_ci",
            description="Run repository CI gates (ruff, pytest, or .arka/ci.yaml overrides).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional project root"},
                    "full": {
                        "type": "boolean",
                        "description": "Run full CI suite",
                        "default": False,
                    },
                    "changed_only": {
                        "type": "boolean",
                        "description": "Run changed-file gates only",
                        "default": False,
                    },
                    "fix": {
                        "type": "boolean",
                        "description": "Hand first failure to goal agent",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_ci,
        ),
        ArkaMcpTool(
            name="arka_review",
            description="Review git diff with security and test-gap hints.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional project root"},
                    "base": {"type": "string", "description": "Base branch for diff review"},
                    "staged": {
                        "type": "boolean",
                        "description": "Review staged changes only",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_review,
        ),
        ArkaMcpTool(
            name="arka_repo_context",
            description="Query llm.txt repo context, sync index, or read index status.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["query", "index", "status"],
                        "default": "query",
                    },
                    "query": {"type": "string", "description": "Context question when action=query"},
                    "path": {"type": "string", "description": "Optional project root"},
                    "limit_chars": {
                        "type": "integer",
                        "description": "Max characters in context response",
                        "default": 12000,
                    },
                },
            },
            handler=_handle_arka_repo_context,
        ),
        ArkaMcpTool(
            name="arka_pr_check",
            description="PR diff, GitHub CI status, failure explanation, and change summary.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["diff", "ci", "explain", "summary"],
                        "default": "diff",
                    },
                    "path": {"type": "string", "description": "Optional git repo root"},
                    "base": {"type": "string", "description": "Base branch for diff/summary"},
                    "pr": {"type": "integer", "description": "PR number for CI checks"},
                    "run_id": {"type": "integer", "description": "Workflow run id for explain"},
                    "stat_only": {
                        "type": "boolean",
                        "description": "Diff stat only when action=diff",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_pr_check,
        ),
        ArkaMcpTool(
            name="arka_coderabbit",
            description=(
                "CodeRabbit AI code review — trigger PR reviews (@coderabbitai), fetch feedback, "
                "or run local CLI review when `cr` is installed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["comments", "trigger", "review", "doctor"],
                        "default": "comments",
                    },
                    "path": {"type": "string", "description": "Optional git repo root"},
                    "pr": {"type": "integer", "description": "PR number (default: current branch PR)"},
                    "full": {
                        "type": "boolean",
                        "description": "When action=trigger, request @coderabbitai full review",
                        "default": False,
                    },
                    "json": {
                        "type": "boolean",
                        "description": "Return raw JSON for comments action",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_coderabbit,
        ),
        ArkaMcpTool(
            name="arka_code_search",
            description="Search code in the active project with ripgrep/grep (optional embedding hook).",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Regex or text pattern to search"},
                    "path": {"type": "string", "description": "Optional project root"},
                    "glob": {"type": "string", "description": "Optional glob filter (rg --glob)"},
                    "limit": {"type": "integer", "default": 40},
                    "use_embeddings": {
                        "type": "boolean",
                        "description": "Reserved embedding hook (falls back to ripgrep)",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
            handler=_handle_arka_code_search,
        ),
        ArkaMcpTool(
            name="arka_read_file",
            description=(
                "Read full contents of a local workspace file (text/source). "
                "Blocked paths (.env, secrets/, keys) match arka_edit_guard. Max 512KB default; use offset/limit for slices."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (relative to project root or absolute)"},
                    "file": {"type": "string", "description": "Alias for path"},
                    "root": {"type": "string", "description": "Optional project root"},
                    "offset": {
                        "type": "integer",
                        "description": "1-based start line (default 1)",
                        "default": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return (default: entire file up to max_bytes)",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Max file size in bytes (default 524288, max 1048576)",
                        "default": 524288,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_arka_read_file,
        ),
        ArkaMcpTool(
            name="arka_apply_patch",
            description=(
                "Apply a unified diff or search-replace patch inside the code project scope. "
                "Protected paths (.env, secrets/, node_modules/, bundled/, keys) are blocked by EDIT_GUARD."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional code project root"},
                    "diff": {"type": "string", "description": "Unified diff to apply via git apply"},
                    "file": {"type": "string", "description": "Target file for search-replace mode"},
                    "search": {"type": "string", "description": "Exact text to replace"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "old": {"type": "string", "description": "Alias for search"},
                    "new": {"type": "string", "description": "Alias for replace"},
                    "patch": {"type": "string", "description": "Alias for diff"},
                },
            },
            handler=_handle_arka_apply_patch,
        ),
        ArkaMcpTool(
            name="arka_edit_guard",
            description=(
                "Check whether a file or diff is allowed to be edited before calling arka_apply_patch. "
                "Blocks .env, secrets/, node_modules/, bundled/, and custom patterns from BLOCKED_EDIT_PATHS."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check", "list", "status"],
                        "default": "check",
                    },
                    "path": {"type": "string", "description": "File path to check (relative to project root)"},
                    "root": {"type": "string", "description": "Optional project root"},
                    "diff": {"type": "string", "description": "Unified diff to validate when action=check"},
                },
            },
            handler=_handle_arka_edit_guard,
        ),
        ArkaMcpTool(
            name="arka_qa",
            description=(
                "QA Engineering — test strategy plan, extreme QA constraints, PR/feature checklists, coverage analysis, "
                "CI test failure triage, bug report drafts, and exploratory testing guidance."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["plan", "extreme", "checklist", "triage", "coverage", "report", "explore"],
                        "default": "plan",
                        "description": "QA workflow action",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional project root (default: git root / cwd)",
                    },
                    "feature": {
                        "type": "string",
                        "description": "Feature or area under test",
                    },
                    "base": {
                        "type": "string",
                        "description": "Base branch for checklist/triage (default: main/master)",
                    },
                    "title": {"type": "string", "description": "Bug report title when action=report"},
                    "steps": {"type": "string", "description": "Reproduction steps when action=report"},
                    "expected": {"type": "string", "description": "Expected behavior when action=report"},
                    "actual": {"type": "string", "description": "Actual behavior when action=report"},
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "default": "medium",
                    },
                    "from_failure": {
                        "type": "boolean",
                        "description": "Seed bug report from latest CI test failure",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_qa,
        ),
        ArkaMcpTool(
            name="arka_ocr",
            description=(
                "OCR local images (text + optional coordinates) or scanned PDFs (searchable PDF output). "
                "Requires local filesystem access to the path you provide — not usable in cloud/sandbox "
                "agents unless workspace files are mounted. "
                "Verify incrementally: run one demo file first, inspect the result without waiting for "
                "full batch logs, then a second file — only then report verified."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["auto", "extract", "pdf"],
                        "default": "auto",
                        "description": "auto: image text or PDF searchable; extract: image OCR; pdf: searchable PDF",
                    },
                    "path": {
                        "type": "string",
                        "description": "Local path to an image (.png, .jpg, …) or scanned PDF",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output PDF path when action=pdf or auto on a PDF",
                    },
                    "language": {
                        "type": "string",
                        "description": "Tesseract language code for PDF OCR",
                        "default": "eng",
                    },
                    "no_blocks": {
                        "type": "boolean",
                        "description": "Omit per-word coordinate blocks for image OCR",
                        "default": False,
                    },
                    "zones": {
                        "type": "boolean",
                        "description": "Include top/middle/bottom spatial zones for image OCR",
                        "default": False,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_arka_ocr,
        ),
        ArkaMcpTool(
            name="arka_rag",
            description=(
                "Document RAG — ingest local files, list ingested docs, and ask questions over them "
                "(PrivateGPT + optional TurboQuant). Actions ingest, codebase_ingest, and batch_ingest "
                "require local filesystem access to the given path(s). Not usable in cloud/sandbox "
                "agents unless workspace files are mounted. "
                "Verify incrementally: ingest/ask on one local file first, confirm output without "
                "waiting for full batch logs, then repeat on a second file — only then report verified."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "list",
                            "formats",
                            "ingest",
                            "ask",
                            "codebase_ingest",
                            "batch_ingest",
                        ],
                        "default": "status",
                    },
                    "path": {
                        "type": "string",
                        "description": "Local file or directory for ingest/codebase_ingest/batch_ingest",
                    },
                    "question": {
                        "type": "string",
                        "description": "Question when action=ask",
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional ingested document name or artifact when action=ask",
                    },
                    "name": {
                        "type": "string",
                        "description": "Short codebase label when action=codebase_ingest",
                    },
                    "extensions": {
                        "description": "File extensions for batch_ingest (e.g. [\".pdf\"] or \".pdf,.md\")",
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                    },
                    "no_recursive": {
                        "type": "boolean",
                        "description": "Only top-level files for batch_ingest",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_rag,
        ),
        ArkaMcpTool(
            name="arka_connector",
            description=(
                "Arka CLI connector — connect terminal sessions to Agent Hub shared context "
                "(memory/context.md, MCP config, skills manifest)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "connect",
                            "status",
                            "context",
                            "doctor",
                            "disconnect",
                            "shell_init",
                            "suggest",
                        ],
                        "default": "status",
                        "description": (
                            "connect: sync hub and attach shared context; "
                            "status: connector state; "
                            "context: preview shared context block; "
                            "doctor: verify setup; "
                            "disconnect: clear connector marker; "
                            "shell_init: shell snippet for launch.env"
                        ),
                    },
                    "goal": {
                        "type": "string",
                        "description": "When action=context: optional goal to filter context",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "When action=context: max characters",
                        "default": 2500,
                    },
                    "unify": {
                        "type": "boolean",
                        "description": "When action=connect: run agent_hub sync --unify",
                        "default": False,
                    },
                    "no_sync": {
                        "type": "boolean",
                        "description": "When action=connect: skip agent_hub sync",
                        "default": False,
                    },
                    "shell": {
                        "type": "string",
                        "description": "When action=shell_init: auto, bash, or fish",
                        "default": "auto",
                    },
                },
            },
            handler=_handle_arka_connector,
        ),
        ArkaMcpTool(
            name="arka_agent_hub",
            description=(
                "Agent Hub — status, adapters, detect installed agents, doctor checks, "
                "list IDE memory sources, or import memory from hub/IDE exports."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "adapters",
                            "detect",
                            "doctor",
                            "list",
                            "memory_sources",
                            "import_memory",
                        ],
                        "default": "status",
                        "description": (
                            "status: hub paths and sync timestamps; "
                            "adapters: MCP merge status per agent; "
                            "detect: which agent configs exist; "
                            "doctor: health checks; "
                            "list: registered launch agents; "
                            "memory_sources: importable IDE/agent memory files; "
                            "import_memory: ingest JSON/markdown from path or IDE source"
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": "When action=import_memory: explicit JSON/markdown path",
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "When action=import_memory: IDE source id "
                            "(e.g. cursor, arka_session, agent:openclaw)"
                        ),
                    },
                    "ide": {
                        "type": "string",
                        "description": "Alias for source when action=import_memory",
                    },
                    "agent": {
                        "type": "string",
                        "description": "Alias for source when action=import_memory",
                    },
                    "all": {
                        "type": "boolean",
                        "description": "When action=import_memory: import every detected source",
                        "default": False,
                    },
                },
            },
            handler=_handle_arka_agent_hub,
        ),
        ArkaMcpTool(
            name="arka_team_run",
            description="Run an Arka agent team workflow on a task.",
            input_schema={
                "type": "object",
                "properties": {
                    "team": {"type": "string", "description": "Team name"},
                    "task": {"type": "string", "description": "Task description"},
                    "workflow": {"type": "string", "description": "Optional workflow override"},
                    "promote_final": {"type": "boolean", "default": False},
                    "json": {"type": "boolean", "default": False},
                },
                "required": ["team", "task"],
            },
            handler=_handle_arka_team_run,
        ),
        ArkaMcpTool(
            name="arka_self_build",
            description=(
                "Run Arka's MCP-orchestrated self-build loop — repo health audit, plan, "
                "optional apply via goal/jules, verify with tests."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run", "list", "status"],
                        "default": "run",
                    },
                    "target": {"type": "string", "description": "Optional improvement focus"},
                    "apply": {"type": "boolean", "default": False},
                    "yes": {"type": "boolean", "default": False},
                    "use_jules": {"type": "boolean", "default": False},
                    "max_rounds": {"type": "integer", "default": 2},
                    "max_steps": {"type": "integer", "default": 15},
                    "session_id": {"type": "string", "description": "Optional session id to reuse"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            handler=_handle_arka_self_build,
        ),
    ]


def list_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in _build_tools()
        if tool.name not in _mcp_disabled_tools()
    ]


def list_tool_names() -> list[str]:
    return [tool.name for tool in _build_tools() if tool.name not in _mcp_disabled_tools()]


def mcp_server_launch_spec() -> dict[str, Any]:
    """Cursor-compatible stdio launch spec for this MCP server."""
    arka_cmd = shutil.which("arka")
    if arka_cmd:
        return {"command": arka_cmd, "args": ["mcp", "serve"]}
    from arka.paths import python_executable

    # Direct module entry avoids CLI side effects (auto-refetch, mode load) on stdio startup.
    return {"command": python_executable(), "args": ["-m", "arka.integrations.mcp_server"]}


def install_config_snippet(*, agent: str = "cursor") -> str:
    """Return JSON config snippet for Cursor, Claude Desktop, or generic clients."""
    entry = mcp_server_launch_spec()
    payload: dict[str, Any] = {"mcpServers": {ARKA_MCP_SERVER_KEY: entry}}
    if agent.strip().lower() in {"claude", "claude_desktop", "claude-desktop"}:
        payload = {
            "mcpServers": {
                ARKA_MCP_SERVER_KEY: {
                    **entry,
                    "env": {},
                }
            }
        }
    return json.dumps(payload, indent=2) + "\n"


def ensure_arka_self_in_config() -> bool:
    """Add arka self-MCP entry to ~/.config/arka/mcp.json if missing."""
    from arka.integrations.mcp_manager import load_mcp_config, save_mcp_config

    data = load_mcp_config()
    servers = data.setdefault("mcpServers", {})
    if ARKA_MCP_SERVER_KEY in servers:
        return False
    servers[ARKA_MCP_SERVER_KEY] = mcp_server_launch_spec()
    save_mcp_config(data)
    return True


class ArkaMcpServer:
    """Minimal newline-delimited JSON-RPC MCP server over stdio."""

    @staticmethod
    def _observe_request(
        method: str,
        *,
        tool_name: str = "",
        success: bool = True,
        duration_ms: int = 0,
        error: str = "",
        prompt: str = "",
        args_summary: dict[str, Any] | None = None,
    ) -> None:
        try:
            from arka.telemetry.mcp_obs import observe_mcp_server_request

            observe_mcp_server_request(
                method=method,
                tool_name=tool_name,
                success=success,
                duration_ms=duration_ms,
                error=error,
                prompt=prompt,
                args_summary=args_summary,
            )
        except ImportError:
            pass

    def __init__(
        self,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self._tools = {tool.name: tool for tool in _build_tools()}
        self._lock = threading.Lock()
        self._initialized = False

    def _send(self, payload: dict[str, Any]) -> None:
        self.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.stdout.flush()

    def _error_response(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def handle_message(self, body: dict[str, Any]) -> dict[str, Any] | None:
        started = time.monotonic()
        method = str(body.get("method", "")).strip()
        request_id = body.get("id")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "notifications/initialized":
            return None

        if method == "ping":
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                from arka.integrations.mcp_logs import log_mcp_event

                log_mcp_event("server.ping", method=method, status="ok", duration_ms=duration_ms)
            except ImportError:
                pass
            self._observe_request("ping", duration_ms=duration_ms)
            if request_id is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}

        if method == "initialize":
            self._initialized = True
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                from arka.integrations.mcp_logs import log_mcp_event

                log_mcp_event("server.initialize", method=method, status="ok", duration_ms=duration_ms)
            except ImportError:
                pass
            self._observe_request("initialize", duration_ms=duration_ms)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            }

        if method == "tools/list":
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                from arka.integrations.mcp_logs import log_mcp_event

                log_mcp_event(
                    "server.tools_list",
                    method=method,
                    status="ok",
                    tools=len(self._tools),
                    duration_ms=duration_ms,
                )
            except ImportError:
                pass
            self._observe_request("tools/list", duration_ms=duration_ms)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": list_tool_definitions()},
            }

        if method == "tools/call":
            name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            try:
                from arka.integrations.mcp_logs import mcp_tool_call_fields

                call_fields = mcp_tool_call_fields(name, arguments)
            except ImportError:
                call_fields = {}
            prompt = str(call_fields.get("prompt") or "")
            args_summary = call_fields.get("args_summary")
            if not isinstance(args_summary, dict):
                args_summary = None
            tool = self._tools.get(name)
            if not tool:
                duration_ms = int((time.monotonic() - started) * 1000)
                try:
                    from arka.integrations.mcp_logs import log_mcp_event

                    log_mcp_event(
                        "server.tools_call",
                        method=method,
                        tool=name,
                        status="unknown_tool",
                        **call_fields,
                    )
                except ImportError:
                    pass
                self._observe_request(
                    "tools/call",
                    tool_name=name,
                    success=False,
                    duration_ms=duration_ms,
                    error="unknown_tool",
                    prompt=prompt,
                    args_summary=args_summary,
                )
                return self._error_response(request_id, -32602, f"Unknown tool: {name}")
            try:
                from arka.telemetry.mcp_obs import trace_mcp_server_tool_call
            except ImportError:
                trace_mcp_server_tool_call = None  # type: ignore[assignment,misc]

            try:
                if trace_mcp_server_tool_call is not None:
                    with trace_mcp_server_tool_call(
                        tool_name=name,
                        prompt=prompt,
                        args_summary=args_summary,
                    ):
                        text = tool.handler(arguments)
                else:
                    text = tool.handler(arguments)
                    self._observe_request(
                        "tools/call",
                        tool_name=name,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        prompt=prompt,
                        args_summary=args_summary,
                    )
                duration_ms = int((time.monotonic() - started) * 1000)
                try:
                    from arka.integrations.mcp_logs import log_mcp_event

                    log_mcp_event(
                        "server.tools_call",
                        method=method,
                        tool=name,
                        status="ok",
                        duration_ms=duration_ms,
                        **call_fields,
                    )
                except ImportError:
                    pass
                if trace_mcp_server_tool_call is not None:
                    try:
                        from arka.telemetry.tracing import log_response_duration

                        duration_attrs: dict[str, Any] = {
                            "arka.mcp.method": method,
                            "arka.mcp.tool_name": name[:200],
                            "arka.mcp.role": "server",
                        }
                        if prompt:
                            duration_attrs["arka.mcp.prompt"] = prompt[:500]
                        log_response_duration(
                            f"mcp tools/call {name}",
                            elapsed_ms=float(duration_ms),
                            attributes=duration_attrs,
                        )
                    except ImportError:
                        pass
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _text_result(text),
                }
            except (Exception, SystemExit) as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                try:
                    from arka.integrations.mcp_logs import log_mcp_event

                    log_mcp_event(
                        "server.tools_call",
                        method=method,
                        tool=name,
                        status="error",
                        error=str(exc),
                        duration_ms=duration_ms,
                        **call_fields,
                    )
                except ImportError:
                    pass
                if trace_mcp_server_tool_call is None:
                    self._observe_request(
                        "tools/call",
                        tool_name=name,
                        success=False,
                        duration_ms=duration_ms,
                        error=str(exc),
                        prompt=prompt,
                        args_summary=args_summary,
                    )
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _text_result(str(exc)[:2000], is_error=True),
                }

        if request_id is None:
            return None
        try:
            from arka.integrations.mcp_logs import log_mcp_event

            log_mcp_event("server.method_missing", method=method, status="error")
        except ImportError:
            pass
        return self._error_response(request_id, -32601, f"Method not found: {method}")

    def process_line(self, line: str) -> dict[str, Any] | None:
        line = line.strip()
        if not line:
            return None
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            try:
                from arka.integrations.mcp_logs import log_mcp_event

                log_mcp_event("server.parse_error", status="error", error="invalid json")
            except ImportError:
                pass
            return None
        if not isinstance(body, dict):
            return None
        with self._lock:
            return self.handle_message(body)

    def run(self) -> None:
        for line in self.stdin:
            response = self.process_line(line)
            if response is not None:
                self._send(response)


def serve_stdio() -> int:
    """Run the MCP server on stdio until stdin closes."""
    ArkaMcpServer().run()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry for bundled arka_mcp_server.py — defaults to serve."""
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in ("-h", "--help", "help"):
        print("Usage: arka mcp serve  |  python -m arka.integrations.mcp_server")
        return 0
    return serve_stdio()


def doctor(*, timeout: float = 8.0) -> tuple[str, int]:
    """Verify the stdio MCP server initializes and lists tools."""
    from arka.integrations.mcp_manager import McpStdioClient

    spec = mcp_server_launch_spec()
    client = McpStdioClient(
        server=ARKA_MCP_SERVER_KEY,
        command=spec["command"],
        args=list(spec.get("args") or []),
        timeout=timeout,
    )
    lines: list[str] = [
        f"command\t{spec['command']}",
        f"args\t{' '.join(spec.get('args') or [])}",
        f"tools_expected\t{len(list_tool_names())}",
    ]
    try:
        info = client.connect()
        tools = client.list_tools()
        server_info = info.get("serverInfo") if isinstance(info, dict) else {}
        lines.append(f"initialize\tok\t{server_info}")
        ping = client.ping()
        lines.append(f"ping\tok\t{ping or '{}'}")
        lines.append(f"tools_list\tok\tcount={len(tools)}")
        for tool in tools:
            lines.append(f"tool\t{tool.name}")
        missing = [name for name in list_tool_names() if name not in {t.name for t in tools}]
        if missing:
            lines.append(f"missing\t{','.join(missing)}")
            return "\n".join(lines), 1
        lines.append("summary\tok")
        return "\n".join(lines), 0
    except Exception as exc:
        lines.append(f"error\t{exc}")
        return "\n".join(lines), 1
    finally:
        client.close()


__all__ = [
    "ARKA_MCP_SERVER_KEY",
    "ArkaMcpServer",
    "call_mcp_tool",
    "doctor",
    "ensure_arka_self_in_config",
    "install_config_snippet",
    "list_tool_definitions",
    "list_tool_names",
    "main",
    "mcp_server_launch_spec",
    "serve_stdio",
]

if __name__ == "__main__":
    raise SystemExit(main())
