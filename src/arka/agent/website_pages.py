"""Plan website page structure and information architecture before building."""

from __future__ import annotations

import argparse
import json
import re
import sys


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    try:
        from arka.core.website_pages import is_website_goal, wants_page_plan
    except ImportError:
        return ""
    if not is_website_goal(clean) and not wants_page_plan(clean):
        return ""
    if not wants_page_plan(clean) and not re.search(
        r"(?i)\b(?:sitemap|site map|page plan|website pages|site structure)\b",
        clean,
    ):
        return ""
    import shlex

    return "website_pages plan " + shlex.quote(clean)


def _llm_plan(system: str, user: str) -> str:
    try:
        from arka.llm.complete import llm_complete

        return llm_complete(system, user, temperature=0.35, task="website_pages").strip()
    except ImportError:
        from arka.agent.core import _llm

        return _llm(system, user, temperature=0.35, task="chat")


def _system_prompt() -> str:
    try:
        from arka.core.website_pages import read_guide

        guide = read_guide(max_chars=6000)
    except ImportError:
        guide = ""
    base = (
        "You are an information architect for websites and web apps. "
        "Produce a clear page plan BEFORE any UI or copy. "
        "Follow: one primary job per page, hub+detail for lists, split tutorials from reference, "
        "primary nav ≤7 items. "
        "Output markdown with: Assumptions, Sitemap table, Per-page outlines, Split/merge notes, Next steps. "
        "Do not write full page copy or code—only structure."
    )
    if guide:
        return base + "\n\nFollow this guide:\n" + guide
    return base


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$", stripped)
    if m:
        return m.group(1).strip()
    return stripped


def plan_pages(
    prompt: str,
    *,
    context_path: str | None = None,
    site_type: str | None = None,
) -> dict[str, object]:
    if not context_path:
        try:
            from arka.core.website_archetypes import cached_plan

            hit = cached_plan(prompt, site_type=site_type)
            if hit:
                return {
                    "lines": len(hit.splitlines()),
                    "bytes": len(hit.encode("utf-8")),
                    "plan": hit,
                    "source": "archetype_cache",
                }
        except ImportError:
            pass
    user_parts = [f"Request: {prompt}"]
    if site_type:
        user_parts.append(f"Site type hint: {site_type}")
    if context_path:
        from pathlib import Path

        ctx = Path(context_path).expanduser()
        if ctx.is_file():
            user_parts.append(
                "Existing content or notes to organize into pages:\n"
                + ctx.read_text(encoding="utf-8")[:16000]
            )
    body = _strip_code_fence(_llm_plan(_system_prompt(), "\n\n".join(user_parts)))
    if not body:
        raise ValueError("LLM returned empty page plan")
    return {
        "lines": len(body.splitlines()),
        "bytes": len(body.encode("utf-8")),
        "plan": body,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka website_pages",
        description="Plan website page structure and sitemap before building",
    )
    sub = parser.add_subparsers(dest="cmd")

    plan_p = sub.add_parser("plan", help="Generate a sitemap and page breakdown")
    plan_p.add_argument("prompt", nargs="+")
    plan_p.add_argument("--context", help="Markdown/text file with content to organize")
    plan_p.add_argument(
        "--type",
        dest="site_type",
        help="Site archetype hint: saas, docs, portfolio, app, marketing",
    )
    plan_p.add_argument("--json", action="store_true", help="Emit JSON with plan field")

    sub.add_parser("guide", help="Print the website page organization guide")
    sub.add_parser("status", help="Show configuration")

    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    if args.cmd == "guide":
        from arka.core.website_pages import read_guide

        print(read_guide(max_chars=12000))
        return 0
    if args.cmd == "status":
        from arka.core.website_pages import status

        print(json.dumps(status(), indent=2))
        return 0
    if args.cmd == "plan":
        prompt = " ".join(args.prompt)
        try:
            result = plan_pages(
                prompt,
                context_path=args.context,
                site_type=args.site_type,
            )
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, indent=2))
            return 0
        print(result["plan"])
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
