#!/usr/bin/env python3
"""Fact-check claims using web evidence and structured verdicts."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from datetime import date

FACT_CHECK_SYSTEM_PROMPT = """You are a fact-checker. Assess the user's claim using ONLY the evidence provided.

Output markdown with these sections:

## Verdict
Exactly one of: TRUE, FALSE, PARTIALLY TRUE, UNVERIFIABLE

## Summary
1-3 sentences explaining the verdict in plain language.

## Evidence
Bullet points that support or contradict the claim. Cite sources inline.

## Sources
Numbered list: title — URL (when available)

Rules:
- Do NOT rely on memory for factual claims; use only provided evidence.
- If evidence is insufficient or conflicting, verdict is UNVERIFIABLE.
- Use PARTIALLY TRUE when the claim mixes accurate and inaccurate elements.
- Note dates for time-sensitive claims (prices, events, releases).
- Be concise and neutral; no hedging filler.
"""

_VERIFY_EXCLUDE = re.compile(
    r"(?i)\b(?:"
    r"url|email|e-mail|signature|password|identity|account|loop|certificate|ssl|tls|"
    r"gpg|ssh|pgp|two[- ]factor|2fa|otp|installation|install|setup|configure|"
    r"my\s+email|my\s+account|file\s+hash|checksum"
    r")\b"
)

_TECH_CLAIM = re.compile(
    r"(?i)\b(?:"
    r"python|javascript|typescript|react|next\.js|django|fastapi|flask|"
    r"node\.js|npm|pypi|api|library|framework|package|module|sdk|"
    r"released?\s+in|version\s+\d|supports?\s+|deprecated"
    r")\b"
)

_CLAIM_PREFIXES = (
    r"(?i)^(?:arka\s+)?fact[\s-]?check(?:er)?\s+",
    r"(?i)^(?:arka\s+)?factcheck\s+",
    r"(?i)^fact_check\s+",
    r"(?i)^is\s+it\s+true\s+that\s+",
    r"(?i)^verify\s+that\s+",
    r"(?i)^verify\s+",
)


def _strip_claim_prefix(text: str) -> str:
    t = text.strip()
    for pat in _CLAIM_PREFIXES:
        t = re.sub(pat, "", t).strip()
    return t.strip("'\"")


def _is_fact_check_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.match(r"(?i)^(?:fact_check|fact-check|factcheck|factchecker)\b", t):
        return bool(_strip_claim_prefix(t))
    if re.search(r"(?i)\b(?:fact[\s-]?check(?:er)?|factcheck)\b", t):
        return bool(_strip_claim_prefix(t))
    if re.match(r"(?i)^is\s+it\s+true\s+that\s+\S", t):
        return True
    if re.match(r"(?i)^verify\b", t):
        if _VERIFY_EXCLUDE.search(t):
            return False
        rest = _strip_claim_prefix(t)
        if not rest or len(rest.split()) < 2:
            return False
        return True
    return False


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_fact_check_request(t):
        return []
    claim = _strip_claim_prefix(t)
    if not claim:
        return []
    return [claim]


def format_fact_check_terminal(markdown: str) -> str:
    """Render fact-check markdown with visual section separators."""
    lines = markdown.strip().splitlines()
    out: list[str] = []
    first_section = True
    for line in lines:
        stripped = line.strip()
        if re.match(r"^##\s+", stripped):
            if not first_section:
                out.extend(["", "─" * 60, ""])
            first_section = False
            title = re.sub(r"^##\s+", "", stripped).strip()
            out.extend([f"▸ {title}", ""])
            continue
        if re.match(r"^---+$", stripped):
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def _try_context7_docs(claim: str) -> str:
    """Best-effort Context7 docs for technical/library claims."""
    if not _TECH_CLAIM.search(claim):
        return ""
    try:
        from arka.integrations.context7_mcp import context7_configured
        from arka.integrations.mcp_manager import call_tool
    except ImportError:
        return ""
    if not context7_configured():
        return ""
    try:
        resolved = call_tool(
            "context7",
            "resolve-library-id",
            {"libraryName": claim[:200]},
        )
        if not resolved or not resolved.strip():
            return ""
        lib_id = resolved.strip().splitlines()[0].strip()
        if not lib_id:
            return ""
        docs = call_tool(
            "context7",
            "query-docs",
            {"libraryId": lib_id, "query": claim},
        )
        return (docs or "").strip()
    except Exception:
        return ""


def _gather_evidence(claim: str, *, deep: bool) -> tuple[str, list[str]]:
    """Return (context_text, source_notes)."""
    notes: list[str] = []
    contexts: list[str] = []

    ctx7 = _try_context7_docs(claim)
    if ctx7:
        contexts.append(f"[Context7 library docs]\n{ctx7}")
        notes.append("Context7")

    try:
        from arka.core.security import sanitize_web_context, verify_web_query

        gate = verify_web_query(claim)
        if gate.status == "block":
            return "", [f"blocked: {gate.reason}"]
    except ImportError:
        pass

    snippet = ""
    web_context = ""
    try:
        from arka.agent.chat import gather_web_context, snippet_lookup

        snippet = snippet_lookup(claim) or ""
        if deep:
            web_context = gather_web_context(claim, snippet=snippet) or ""
        else:
            web_context = snippet
    except ImportError:
        pass
    except Exception:
        web_context = snippet

    try:
        from arka.core.security import sanitize_web_context

        if web_context:
            web_context, _ = sanitize_web_context(web_context)
        elif snippet:
            snippet, _ = sanitize_web_context(snippet)
            web_context = snippet
    except ImportError:
        pass

    if web_context:
        contexts.append(f"[Web search results]\n{web_context}")
        notes.append("web search")
    elif snippet:
        contexts.append(f"[Search snippet]\n{snippet}")
        notes.append("search snippet")

    return "\n\n".join(contexts), notes


def _llm_fact_check(system_prompt: str, user: str) -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system_prompt,
            user,
            temperature=0.2,
            task="research",
            skill="fact_check",
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system_prompt, user, temperature=0.2, task="research").strip()


def fact_check(claim: str, *, deep: bool = True) -> int:
    """Verify a claim and print a structured verdict."""
    from arka.output import print_block

    claim = " ".join((claim or "").split()).strip()
    if not claim:
        print(
            "Usage: fact_check <claim>\n"
            "Example: fact_check There are 8 planets in the solar system\n"
            "NL: arka fact check is it true that the earth is flat",
            file=sys.stderr,
        )
        return 1

    evidence, sources = _gather_evidence(claim, deep=deep)
    today = date.today().isoformat()

    if not evidence:
        msg = (
            f"Could not verify — no network or search results for:\n"
            f"  {claim}\n\n"
            "Connect to the internet and ensure GEMINI_API_KEY or GROQ_API_KEY is set."
        )
        print_block("Fact check", msg)
        return 1

    user = (
        f"Claim to verify: {claim}\n"
        f"Date checked: {today}\n"
        f"Evidence sources consulted: {', '.join(sources) or 'none'}\n\n"
        f"{evidence}"
    )

    try:
        answer = _llm_fact_check(FACT_CHECK_SYSTEM_PROMPT, user)
    except Exception as exc:
        print_block(
            "Fact check",
            f"Could not synthesize verdict ({exc}).\n"
            "Raw evidence was retrieved but LLM is unavailable — check API keys.",
        )
        return 1

    if not answer:
        print_block(
            "Fact check",
            "Could not generate a verdict (check LLM API keys).",
        )
        return 1

    body = format_fact_check_terminal(answer) if sys.stdout.isatty() else answer
    print_block("Fact check", body)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fact-check claims with web evidence")
    sub = p.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse natural language → fact_check args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "parse":
        args = build_parser().parse_args(argv)
        return args.func(args)

    if argv and argv[0] in {"-h", "--help", "help"}:
        build_parser().print_help()
        print("\nExamples:", file=sys.stderr)
        print('  fact_check "There are 8 planets in the solar system"', file=sys.stderr)
        print("  fact check Python was created in 1991", file=sys.stderr)
        return 0

    deep = True
    rest = list(argv)
    if rest and rest[0] == "--light":
        deep = False
        rest = rest[1:]

    claim = " ".join(rest).strip()
    nl = nl_to_argv(claim)
    if nl:
        claim = nl[0]

    return fact_check(claim, deep=deep)


if __name__ == "__main__":
    raise SystemExit(main())
