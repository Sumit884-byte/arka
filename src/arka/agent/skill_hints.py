"""Small symbolic skill hints for model prompts.

This is intentionally local and bounded: it recommends at most one canonical
skill from high-signal phrases, without replacing the normal router.
"""

from __future__ import annotations

import re

_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("repo_health", ("repo health", "repository health", "health check")),
    ("lint_project", ("lint", "format code", "static analysis")),
    ("pr_check", ("pull request", "pr check", "ci failure", "why did ci fail")),
    ("route_audit", ("route audit", "routing parity", "nl routing")),
    ("design_from_screenshot", ("from screenshot", "screenshot to", "design screenshot")),
    ("frontend_loop", ("frontend", "ui review", "visual regression")),
    ("three_js_model", ("satellite", "spacecraft", "realistic 3d model", "realistic 3d asset", "real world model")),
    ("compose_slides", ("pitch deck", "slides", "presentation")),
    ("urlkit", ("broken links", "repair links", "url validation")),
    ("self_improve", ("self improve", "improve arka", "improve routing")),
)


def recommend_skill_hint(text: str) -> str:
    """Return a compact model-facing hint, or an empty string."""
    normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not normalized:
        return ""
    for skill, phrases in _HINTS:
        if any(phrase in normalized for phrase in phrases):
            return f"Symbolic skill hint: prefer `{skill}` if it directly matches; do not invent a different skill."
    return ""
