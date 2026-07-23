"""Share or copy LLM responses with model and telemetry metadata in one bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

SHARE_VERSION = 1
SHARE_KIND = "arka-llm-share"

_LLM_SHARE_RE = re.compile(
    r"(?i)\b("
    r"share\s+(?:my\s+)?(?:last\s+)?(?:llm\s+|ai\s+)?(?:response|output|answer|reply|completion)|"
    r"copy\s+(?:my\s+)?(?:last\s+)?(?:llm\s+|ai\s+)?(?:response|output|answer|reply|completion)|"
    r"export\s+(?:my\s+)?(?:last\s+)?(?:llm\s+|ai\s+)?(?:response|output|answer|reply|completion)|"
    r"share\s+(?:the\s+)?model\s+output"
    r")\b"
)


@dataclass
class LlmShareRecord:
    output: str
    provider: str = ""
    model_id: str = ""
    task: str = ""
    skill: str = ""
    timestamp: str = ""
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    attempts: int = 0
    prompt_preview: str = ""
    prompt_hash: str = ""


_LAST: LlmShareRecord | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _truncate(text: str, limit: int = 240) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def _prompt_hash(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def capture_llm_completion(
    *,
    output: str,
    provider: str,
    model_id: str,
    task: str = "",
    skill: str = "",
    user_prompt: str = "",
    run: Any = None,
    latency_ms: float | None = None,
    attempts: int = 0,
) -> None:
    """Remember the latest successful LLM completion for one-go sharing."""
    global _LAST
    text = (output or "").strip()
    if not text or text.startswith("[LLM error:"):
        return

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    if run is not None:
        try:
            from arka.telemetry.llm_obs import usage_attrs_from_run

            attrs = usage_attrs_from_run(run, model_id=model_id)
            if attrs:
                prompt_tokens = int(attrs.get("gen_ai.usage.input_tokens") or 0) or None
                completion_tokens = int(attrs.get("gen_ai.usage.output_tokens") or 0) or None
                total_tokens = int(attrs.get("gen_ai.usage.total_tokens") or 0) or None
                raw_cost = attrs.get("arka.llm.cost_usd", attrs.get("arka.llm.estimated_cost_usd"))
                if raw_cost is not None:
                    cost_usd = float(raw_cost)
                if latency_ms is None:
                    duration = attrs.get("arka.llm.duration_ms")
                    if duration is not None:
                        latency_ms = float(duration)
        except ImportError:
            pass

    preview = _truncate(user_prompt)
    _LAST = LlmShareRecord(
        output=text,
        provider=(provider or "").strip(),
        model_id=(model_id or "").strip(),
        task=(task or "").strip(),
        skill=(skill or "").strip(),
        timestamp=_now_iso(),
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        attempts=max(0, int(attempts or 0)),
        prompt_preview=preview,
        prompt_hash=_prompt_hash(user_prompt),
    )


def llm_last_completion() -> LlmShareRecord | None:
    return _LAST


def record_from_overrides(**overrides: Any) -> LlmShareRecord:
    base = llm_last_completion()
    data = asdict(base) if base else {"output": ""}
    for key, value in overrides.items():
        if value is not None and key in data:
            data[key] = value
    if not data.get("timestamp"):
        data["timestamp"] = _now_iso()
    output = str(data.get("output") or "").strip()
    if not output:
        raise ValueError("no LLM output to share (run a completion first or pass --output)")
    return LlmShareRecord(**data)


def build_share_bundle(record: LlmShareRecord | None = None, **overrides: Any) -> dict[str, Any]:
    row = record if record is not None else record_from_overrides(**overrides)
    if overrides:
        merged = asdict(row)
        for key, value in overrides.items():
            if value is not None and key in merged:
                merged[key] = value
        row = LlmShareRecord(**merged)

    bundle: dict[str, Any] = {
        "kind": SHARE_KIND,
        "version": SHARE_VERSION,
        "provider": row.provider,
        "model": row.model_id,
        "model_label": f"{row.provider}/{row.model_id}".strip("/"),
        "task": row.task,
        "skill": row.skill,
        "timestamp": row.timestamp,
        "output": row.output,
    }
    if row.latency_ms is not None:
        bundle["latency_ms"] = round(float(row.latency_ms), 2)
    if row.prompt_tokens is not None:
        bundle["prompt_tokens"] = row.prompt_tokens
    if row.completion_tokens is not None:
        bundle["completion_tokens"] = row.completion_tokens
    if row.total_tokens is not None:
        bundle["total_tokens"] = row.total_tokens
    if row.cost_usd is not None:
        bundle["cost_usd"] = round(float(row.cost_usd), 6)
    if row.attempts:
        bundle["attempts"] = row.attempts
    if row.prompt_preview:
        bundle["prompt_preview"] = row.prompt_preview
    if row.prompt_hash:
        bundle["prompt_hash"] = row.prompt_hash
    return bundle


def format_llm_share_bundle(
    record: LlmShareRecord | dict[str, Any] | None = None,
    *,
    fmt: Literal["markdown", "json"] = "markdown",
    **overrides: Any,
) -> str:
    if isinstance(record, dict):
        bundle = dict(record)
        bundle.setdefault("kind", SHARE_KIND)
        bundle.setdefault("version", SHARE_VERSION)
    else:
        bundle = build_share_bundle(record, **overrides)

    if fmt == "json":
        return json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"

    lines = ["# Arka LLM Response", ""]
    model_label = bundle.get("model_label") or ""
    if not model_label and bundle.get("provider") and bundle.get("model"):
        model_label = f"{bundle['provider']}/{bundle['model']}"
    if model_label:
        lines.append(f"**Model:** {model_label}")
    if bundle.get("provider"):
        lines.append(f"**Provider:** {bundle['provider']}")
    if bundle.get("task"):
        lines.append(f"**Task:** {bundle['task']}")
    if bundle.get("skill"):
        lines.append(f"**Skill:** {bundle['skill']}")
    if bundle.get("timestamp"):
        lines.append(f"**Timestamp:** {bundle['timestamp']}")
    if bundle.get("latency_ms") is not None:
        lines.append(f"**Latency:** {bundle['latency_ms']} ms")
    tokens_parts: list[str] = []
    if bundle.get("prompt_tokens") is not None:
        tokens_parts.append(f"{bundle['prompt_tokens']} in")
    if bundle.get("completion_tokens") is not None:
        tokens_parts.append(f"{bundle['completion_tokens']} out")
    if bundle.get("total_tokens") is not None:
        tokens_parts.append(f"{bundle['total_tokens']} total")
    if tokens_parts:
        lines.append(f"**Tokens:** {' / '.join(tokens_parts)}")
    if bundle.get("cost_usd") is not None:
        lines.append(f"**Cost (est.):** ${bundle['cost_usd']}")
    if bundle.get("attempts"):
        lines.append(f"**Attempts:** {bundle['attempts']}")
    if bundle.get("prompt_hash"):
        lines.append(f"**Prompt hash:** {bundle['prompt_hash']}")
    if bundle.get("prompt_preview"):
        lines.append(f"**Prompt preview:** {bundle['prompt_preview']}")
    lines.extend(["", "---", "", str(bundle.get("output") or "").strip(), ""])
    return "\n".join(lines)


def copy_share_to_clipboard(
    record: LlmShareRecord | None = None,
    *,
    fmt: Literal["markdown", "json"] = "markdown",
    **overrides: Any,
) -> tuple[bool, str]:
    text = format_llm_share_bundle(record, fmt=fmt, **overrides)
    try:
        from arka.integrations.clipboard_history import write_clipboard
    except ImportError:
        return False, "clipboard support unavailable"
    if write_clipboard(text):
        return True, text
    return False, "clipboard copy failed (no clipboard tool on this platform)"


def is_llm_share_request(cmd: str) -> bool:
    clean = (cmd or "").strip()
    if not clean:
        return False
    if re.search(r"(?i)^share\s+(?:last|llm)\b", clean):
        return True
    return bool(_LLM_SHARE_RE.search(clean))


def route_command(cmd: str) -> str | None:
    if not is_llm_share_request(cmd):
        return None
    return "share last"


def _resolve_flags(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="arka share",
        description="Copy or print the last LLM response with model metadata",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="last",
        choices=["last"],
        help="share target (default: last completion)",
    )
    parser.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--copy", "-c", action="store_true", help="copy bundle to clipboard")
    parser.add_argument("--output", help="override response text")
    parser.add_argument("--provider", help="override provider slug")
    parser.add_argument("--model", help="override model id")
    parser.add_argument("--task", help="override task profile")
    parser.add_argument("--skill", help="override skill name")
    parser.add_argument("--latency-ms", type=float, dest="latency_ms")
    parser.add_argument("--prompt-tokens", type=int, dest="prompt_tokens")
    parser.add_argument("--completion-tokens", type=int, dest="completion_tokens")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _resolve_flags(argv)
    overrides = {
        "output": args.output,
        "provider": args.provider,
        "model_id": args.model,
        "task": args.task,
        "skill": args.skill,
        "latency_ms": args.latency_ms,
        "prompt_tokens": args.prompt_tokens,
        "completion_tokens": args.completion_tokens,
    }
    overrides = {k: v for k, v in overrides.items() if v is not None}

    try:
        record = record_from_overrides(**overrides)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    fmt: Literal["markdown", "json"] = args.format
    if args.copy:
        ok, message = copy_share_to_clipboard(record, fmt=fmt)
        if not ok:
            print(message, file=sys.stderr)
            return 1
        print("Copied LLM share bundle to clipboard.")
        return 0

    print(format_llm_share_bundle(record, fmt=fmt), end="")
    return 0


__all__ = [
    "LlmShareRecord",
    "build_share_bundle",
    "capture_llm_completion",
    "copy_share_to_clipboard",
    "format_llm_share_bundle",
    "is_llm_share_request",
    "llm_last_completion",
    "main",
    "route_command",
]
