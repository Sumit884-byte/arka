"""Shared helpers for MCP tools that read or write local filesystem paths."""

from __future__ import annotations

from pathlib import Path

LOCAL_FILE_TOOL_NOTICE = (
    "Requires local filesystem access to the path(s) you provide. "
    "Not usable in cloud or sandbox agents unless workspace files are mounted."
)

INCREMENTAL_VERIFY_NOTICE = (
    "Do not wait for an entire long log or batch job to finish before checking results. "
    "Run a minimal first demo (one file, one page, or one sample), inspect the outcome, "
    "then proceed to a second increment only if the first succeeded. "
    "Report the workflow as verified only after both increments succeed — not from a single "
    "demo or from tailing partial logs."
)

VERIFY_AFTER_FIX_NOTICE = (
    "After any fix, run relevant verification (tests, CLI repro, log check, etc.). "
    "If verification fails, iterate — do not mark done or say 'fixed' until it passes. "
    "Report what was verified and how."
)

MCP_AGENT_EXECUTION_RULES: tuple[dict[str, str], ...] = (
    {
        "id": "edit_guard_before_patch",
        "summary": "Call arka_edit_guard before arka_apply_patch on sensitive or unknown paths.",
        "rule": (
            "Before editing files via arka_apply_patch, call arka_edit_guard with action=check "
            "for the target path or diff. Protected paths include .env, secrets/, node_modules/, "
            "bundled/, and custom BLOCKED_EDIT_PATHS patterns."
        ),
    },
    {
        "id": "incremental_verify",
        "summary": "Demo first, then scale; declare verified only after two successful increments.",
        "rule": INCREMENTAL_VERIFY_NOTICE,
    },
    {
        "id": "no_log_blocking",
        "summary": "Do not block on full log completion when a partial result is enough to decide.",
        "rule": (
            "Poll or read just enough output to confirm success or failure on the current step. "
            "Move on to the next demo increment instead of waiting for all pages, files, or batches."
        ),
    },
    {
        "id": "verify_after_fix",
        "summary": "After any fix, run verification before marking done.",
        "rule": VERIFY_AFTER_FIX_NOTICE,
    },
    {
        "id": "local_file_tools",
        "summary": "arka_ocr and arka_rag need mounted local paths.",
        "rule": LOCAL_FILE_TOOL_NOTICE,
    },
)

MCP_LOCAL_FILE_TOOLS = frozenset(
    {
        "arka_ocr",
        "arka_rag",
        "arka_view_data",
        "arka_markdown",
        "arka_repo_map",
        "arka_repo_health",
        "arka_ci",
        "arka_review",
        "arka_repo_context",
        "arka_pr_check",
        "arka_code_search",
        "arka_read_file",
        "arka_apply_patch",
        "arka_qa",
        "arka_disk",
        "arka_convert_media",
        "arka_noise_remove",
        "arka_signoz_publish",
        "arka_create_video",
        "arka_edit_video",
        "arka_dub_video",
        "arka_google_flow",
    }
)


def local_file_tool_notice() -> str:
    return LOCAL_FILE_TOOL_NOTICE


def agent_execution_rules_payload() -> dict[str, object]:
    return {
        "rules": list(MCP_AGENT_EXECUTION_RULES),
        "verify_after_fix": {
            "steps": [
                "Apply the fix.",
                "Run relevant verification (tests, CLI repro, log check, etc.).",
                "If verification fails, iterate on the fix — do not mark done.",
                "When verification passes, report what was verified and how.",
            ],
            "notice": VERIFY_AFTER_FIX_NOTICE,
        },
        "incremental_verify": {
            "steps": [
                "Run the smallest useful demo first (one file/page/sample).",
                "Inspect that result — do not wait for the full log or entire batch.",
                "If the first demo succeeds, run a second increment.",
                "Only then say the workflow is verified.",
            ],
            "notice": INCREMENTAL_VERIFY_NOTICE,
        },
    }


def require_local_path(
    path_str: str,
    *,
    kind: str = "file",
    label: str = "path",
) -> Path:
    """Resolve and validate a local path for MCP tools."""
    raw = str(path_str or "").strip()
    if not raw:
        raise ValueError(f"{label} is required — {LOCAL_FILE_TOOL_NOTICE}")
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError(f"invalid {label}: {path} ({exc}) — {LOCAL_FILE_TOOL_NOTICE}") from exc
    if kind == "file" and not resolved.is_file():
        raise ValueError(f"local file not found: {resolved} — {LOCAL_FILE_TOOL_NOTICE}")
    if kind == "dir" and not resolved.is_dir():
        raise ValueError(f"local directory not found: {resolved} — {LOCAL_FILE_TOOL_NOTICE}")
    return resolved
