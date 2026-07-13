#!/usr/bin/env python3
"""Profession domains — curated source registries, strict routing, cited answers."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

MEMORY_FILE = cache_dir() / "memory.json"

ROLE_TO_DOMAIN: dict[str, str] = {
    "doctor": "health",
    "physician": "health",
    "nurse": "health",
    "clinician": "health",
    "surgeon": "health",
    "nutritionist": "nutrition",
    "dietitian": "nutrition",
    "dietician": "nutrition",
    "founder": "startup",
    "entrepreneur": "startup",
    "startup": "startup",
    "investor": "investor",
    "vc": "investor",
    "teacher": "teacher",
    "educator": "teacher",
    "tutor": "teacher",
    "professor": "teacher",
    "instructor": "teacher",
    "lawyer": "legal",
    "attorney": "legal",
    "solicitor": "legal",
    "barrister": "legal",
    "paralegal": "legal",
    "developer": "engineer",
    "engineer": "engineer",
    "programmer": "engineer",
    "news anchor": "journalism",
    "anchor": "journalism",
    "journalist": "journalism",
    "reporter": "journalism",
    "broadcaster": "journalism",
    "correspondent": "journalism",
    "presenter": "journalism",
    "marketer": "marketing",
    "copywriter": "marketing",
    "content creator": "marketing",
    "social media manager": "marketing",
    "accountant": "finance",
    "cpa": "finance",
    "bookkeeper": "finance",
    "cfo": "finance",
    "counselor": "counselor",
    "therapist": "counselor",
    "psychologist": "counselor",
    "chef": "chef",
    "cook": "chef",
    "product reviewer": "product",
    "ingredient analyst": "product",
}


BUILTIN_ROLE_TO_DOMAIN = ROLE_TO_DOMAIN


@dataclass(frozen=True)
class Domain:
    id: str
    title: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    disclaimer: str
    project_key: str | None = None


BUILTIN_DOMAINS: tuple[Domain, ...] = (
    Domain(
        "health",
        "Health & Clinical",
        ("doctor", "physician", "nurse", "clinician", "gp", "surgeon"),
        (
            "symptom", "diagnosis", "treatment", "patient", "clinical",
            "prescription", "medication", "hospital", "disease",
        ),
        "Educational only — not medical advice. See a licensed clinician for care.",
    ),
    Domain(
        "nutrition",
        "Nutrition & Diet",
        ("nutritionist", "dietitian", "dietician", "diet coach"),
        (
            "meal plan", "nutrition", "diet", "calories", "macros", "vitamins",
            "protein", "weight loss", "balanced diet", "bmi",
        ),
        "General nutrition information — not personalized medical nutrition therapy.",
        project_key="nutrition",
    ),
    Domain(
        "startup",
        "Startup & Founder",
        ("startup", "founder", "entrepreneur", "co-founder", "cofounder"),
        (
            "pitch deck", "mvp", "product-market fit", "go-to-market", "runway",
            "fundraising", "seed round", "series a", "incubator", "accelerator",
        ),
        "",
        project_key="startup",
    ),
    Domain(
        "investor",
        "Investor & Markets",
        ("investor", "vc", "venture capitalist", "angel investor"),
        (
            "due diligence", "term sheet", "cap table", "valuation", "portfolio",
            "stock pick", "market outlook",
        ),
        "Not investment advice. Do your own research.",
        project_key="investor",
    ),
    Domain(
        "teacher",
        "Education & Teaching",
        ("teacher", "educator", "tutor", "professor", "instructor"),
        (
            "lesson plan", "curriculum", "syllabus", "homework", "exam",
            "classroom", "pedagogy", "explain to students",
        ),
        "",
    ),
    Domain(
        "legal",
        "Legal",
        ("lawyer", "attorney", "solicitor", "legal counsel", "barrister", "paralegal"),
        (
            "contract", "litigation", "compliance", "regulation", "clause",
            "legal advice", "lawsuit", "nda", "fine", "penalty", "traffic",
            "violation", "ticket", "statute", "offense", "offence",
        ),
        "General legal information — not legal advice. Consult a licensed attorney.",
    ),
    Domain(
        "engineer",
        "Software Engineering",
        ("engineer", "developer", "software engineer", "devops", "sre"),
        (
            "system design", "architecture", "scalability", "code review",
            "api design", "refactor", "debug production",
        ),
        "",
        project_key="engineer",
    ),
    Domain(
        "journalism",
        "Journalism & Broadcasting",
        ("news anchor", "anchor", "journalist", "reporter", "broadcaster", "correspondent", "presenter"),
        (
            "headline", "broadcast", "teleprompter", "breaking news", "lead story",
            "newsroom", "news script", "on air", "segment", "interview",
        ),
        "News context only — verify facts before airing or publishing.",
    ),
    Domain(
        "marketing",
        "Marketing & Content",
        ("marketer", "copywriter", "content creator", "brand manager", "social media manager"),
        (
            "campaign", "seo", "conversion", "brand voice", "ad copy", "landing page",
            "funnel", "audience", "content strategy", "email marketing",
        ),
        "",
    ),
    Domain(
        "finance",
        "Accounting & Business Finance",
        ("accountant", "cpa", "bookkeeper", "cfo", "financial analyst"),
        (
            "balance sheet", "income statement", "cash flow", "tax", "audit",
            "gaap", "bookkeeping", "p&l", "accounts payable", "ledger",
        ),
        "General finance information — not tax or investment advice. Consult a licensed CPA.",
    ),
    Domain(
        "counselor",
        "Counseling & Mental Health",
        ("counselor", "therapist", "psychologist", "psychotherapist"),
        (
            "therapy", "mental health", "anxiety", "depression", "cbt", "counseling",
            "coping", "stress", "burnout", "mindfulness",
        ),
        "Educational only — not therapy or crisis care. Seek licensed help for emergencies.",
    ),
    Domain(
        "chef",
        "Culinary & Kitchen",
        ("chef", "cook", "sous chef", "pastry chef", "line cook"),
        (
            "recipe", "menu", "ingredient", "cooking technique", "plating",
            "kitchen", "prep", "seasoning", "food safety", "mise en place",
        ),
        "",
    ),
    Domain(
        "product",
        "Product Review & Ingredients",
        ("product reviewer", "ingredient analyst"),
        (
            "ingredients", "ingredient list", "product review", "allergen",
            "vegan", "cruelty-free", "sensitive skin", "incidecoder",
            "shampoo", "skincare", "cosmetic", "supplement",
        ),
        "General product information — not medical or dermatological advice. Patch-test new products.",
    ),
)

DOMAINS = BUILTIN_DOMAINS  # back-compat

_PATTERN_CACHE: tuple | None = None


def _load_plugins():
    try:
        from arka.agent import profession_plugins as pp

        return pp
    except ImportError:
        return None


def all_domains() -> tuple[Domain, ...]:
    pp = _load_plugins()
    if pp is None:
        return BUILTIN_DOMAINS
    return pp.all_domains()


def _by_id() -> dict[str, Domain]:
    return {d.id: d for d in all_domains()}


def _alias_to_domain() -> dict[str, str]:
    pp = _load_plugins()
    if pp is None:
        mapping: dict[str, str] = {}
        for d in BUILTIN_DOMAINS:
            mapping[d.id] = d.id
            for a in d.aliases:
                mapping[a.lower()] = d.id
        for role, dom in ROLE_TO_DOMAIN.items():
            mapping[role] = dom
        return mapping
    return pp.all_alias_to_domain()


def _setup_domain_ids() -> tuple[str, ...]:
    ids = {d.id for d in all_domains()} | {"nutritionist"}
    return tuple(sorted(ids, key=len, reverse=True))


def _patterns() -> tuple[re.Pattern[str], re.Pattern[str], dict[str, str], dict[str, Domain]]:
    global _PATTERN_CACHE
    if _PATTERN_CACHE is not None:
        return _PATTERN_CACHE
    alias_map = _alias_to_domain()
    by_id = _by_id()
    explicit_re = re.compile(
        r"(?i)(?:as a|for a|i(?:'m| am) a|acting as a)\s+"
        r"(?P<role>" + "|".join(re.escape(k) for k in sorted(alias_map.keys(), key=len, reverse=True)) + r")\b"
    )
    prefix_re = re.compile(
        r"(?i)^(?:profession\s+)?(?P<role>"
        + "|".join(re.escape(d.id) for d in all_domains())
        + r")\s*[:\-]\s+"
    )
    _PATTERN_CACHE = (explicit_re, prefix_re, alias_map, by_id)
    return _PATTERN_CACHE


def invalidate_profession_cache() -> None:
    global _PATTERN_CACHE
    _PATTERN_CACHE = None
    pp = _load_plugins()
    if pp is not None:
        pp.invalidate_cache()


_CMD_RE = re.compile(
    r"(?i)^profession\s+(ask|run|open|setup|status|list|combine|install|plugins)(?:\s+(\S+))?"
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _role_to_domain(role: str) -> str | None:
    role = role.strip().lower()
    by_id = _by_id()
    if role in by_id:
        return role
    return _alias_to_domain().get(role)


def user_domain_from_memory() -> str | None:
    if not MEMORY_FILE.is_file():
        return None
    try:
        items = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(items, list):
        return None
    for row in reversed(items):
        text = str(row.get("text", ""))
        m = re.search(r"(?i)user is an?\s+([a-z ]+)", text)
        if not m:
            continue
        role = m.group(1).strip().lower()
        dom = _role_to_domain(role)
        if dom:
            return dom
        dom = _role_to_domain(role.split()[0] if role else "")
        if dom:
            return dom
        for word in role.split():
            dom = _role_to_domain(word)
            if dom:
                return dom
    return None


def _keyword_score(text: str, domain: Domain) -> int:
    low = text.lower()
    return sum(1 for k in domain.keywords if k in low)


def _is_skill_command(text: str) -> bool:
    low = text.lower()
    if re.search(r"(?i)^(install|play|open|run|weather|timer|generate_password|stock|predict)\b", low):
        return True
    if re.search(r"(?i)\b(where to invest|stock price|analyze [A-Z]{2,})\b", text):
        return True
    return False


def detect(text: str) -> tuple[str, str] | None:
    """Strict: explicit profession mention, profession command, or memory+keywords."""
    raw = _normalize(text)
    if not raw or _is_skill_command(raw):
        return None

    explicit_re, prefix_re, _alias_map, by_id = _patterns()

    m = _CMD_RE.match(raw)
    if m and m.group(1).lower() in ("ask", "run"):
        role = (m.group(2) or "").lower()
        rest = _normalize(raw[m.end() :])
        if role and _role_to_domain(role):
            return _role_to_domain(role), rest or raw
        saved = user_domain_from_memory()
        if saved:
            return saved, rest or raw

    m = prefix_re.match(raw)
    if m:
        dom = _role_to_domain(m.group("role"))
        if dom:
            return dom, _normalize(raw[m.end() :]) or raw

    m = explicit_re.search(raw)
    if m:
        dom = _role_to_domain(m.group("role").strip())
        if dom:
            q = _normalize(raw[m.end() :]) or raw
            return dom, q

    for d in all_domains():
        for alias in d.aliases:
            if re.search(rf"(?i)\b{re.escape(alias)}\b", raw):
                if _keyword_score(raw, d) >= 1 or len(raw.split()) >= 5:
                    q = re.sub(rf"(?i)\b{re.escape(alias)}\b", "", raw, count=1).strip()
                    return d.id, _normalize(q) or raw

    saved = user_domain_from_memory()
    if saved and saved in by_id and _keyword_score(raw, by_id[saved]) >= 2:
        return saved, raw

    return None


def profession_ask(domain_id: str, question: str, *, deep: bool = False) -> int:
    dom = _by_id().get(domain_id)
    if not dom:
        print(f"Unknown domain: {domain_id}. Try: profession list", file=sys.stderr)
        return 1
    question = _normalize(question)
    if not question:
        print("Usage: profession ask <domain> <question>", file=sys.stderr)
        return 1

    # Teacher: source registry first; study_agent enriches lesson/explain flows.
    if domain_id == "teacher" and re.search(
        r"(?i)\b(lesson plan|curriculum|syllabus|homework|exam|explain to students|quiz)\b",
        question,
    ):
        return _dispatch_skill(f"study_agent {shlex.quote(question)}")

    # Product: ingredient review uses deep web research via product_reviewer skill.
    if domain_id == "product":
        return _dispatch_skill(f"product_reviewer {shlex.quote(question)}")

    return _ask_from_sources(dom, question, deep=deep or _needs_deep_sources(domain_id, question))


_INSUFFICIENT_RE = re.compile(
    r"(?i)(source material does not|sources do not contain|sources do not|"
    r"do not contain enough|not enough information|cannot find|"
    r"no information regarding|provided sources do not|does not address|"
    r"unable to answer based on|does not contain information)",
)


def _needs_deep_sources(domain_id: str, question: str) -> bool:
    if domain_id != "legal":
        return False
    return bool(
        re.search(
            r"(?i)\b(fine|penalty|traffic|violation|ticket|speeding|statute|"
            r"law|regulation|sentence|offense|offence|infraction|motor vehicle)\b",
            question,
        )
    )


def _answer_lacks_support(answer: str) -> bool:
    return bool(_INSUFFICIENT_RE.search(answer))


def _grounded_web_question(question: str, domain_id: str) -> str:
    q = question
    try:
        from arka.agent.chat import get_live_location, ground_search_query

        if domain_id == "legal" and re.search(
            r"(?i)\b(fine|penalty|traffic|violation|ticket|speeding|infraction|motor vehicle)\b",
            question,
        ):
            ctx = get_live_location()
            city = str(ctx.get("city") or "").strip()
            if city and city.lower() not in ("unknown",) and city.lower() not in q.lower():
                q = f"{q} {city}"
        q = ground_search_query(q)
    except ImportError:
        pass
    return q


def _fallback_web(question: str, *, domain_id: str, deep: bool = False) -> int:
    q = _grounded_web_question(question, domain_id)
    skill = "deep_web_answer" if deep else "web_answer"
    print(f"Falling back to {skill}…", file=sys.stderr)
    return _dispatch_skill(f"{skill} {shlex.quote(q)}")


def _ask_from_sources(dom: Domain, question: str, *, deep: bool) -> int:
    from arka.agent.profession_sources import gather_profession_context

    print(f"Gathering sources for {dom.id}…", file=sys.stderr)
    context, sources = gather_profession_context(dom.id, question, deep=deep)

    if not context.strip():
        print("No sources returned — falling back to web_answer.", file=sys.stderr)
        return _fallback_web(question, domain_id=dom.id, deep=deep or _needs_deep_sources(dom.id, question))

    try:
        from arka.llm.cli import llm_complete
    except ImportError:
        return _dispatch_skill(f"web_answer {shlex.quote(question)}")

    src_line = ", ".join(sources) if sources else "none"
    system = (
        "Answer using ONLY the provided source material. "
        "Write plain text for the terminal: no markdown (no **, *, ###, or _italic_). "
        "Use a short opening sentence, then numbered items (1. 2. 3.) or lines starting with •. "
        "Do not append (web) or (memory) after every line — put source ids once under a final "
        "Sources: section. "
        "If the sources do not contain enough information, say so clearly — do not invent facts. "
        "Be structured and practical."
    )
    if dom.disclaimer:
        system += " " + dom.disclaimer

    user = (
        f"Domain: {dom.title}\n"
        f"Sources consulted: {src_line}\n\n"
        f"{context}\n\n"
        f"Question: {question}"
    )
    answer = llm_complete(system, user, temperature=0.2, task="default")
    if not answer.strip():
        return _fallback_web(question, domain_id=dom.id, deep=deep)

    if _answer_lacks_support(answer) or ("web" not in sources and _needs_deep_sources(dom.id, question)):
        return _fallback_web(question, domain_id=dom.id, deep=True)

    body = answer.strip()
    if sources:
        body += f"\n\nSources:\n  {src_line}"
    if dom.disclaimer and "disclaimer" not in body.lower():
        body += f"\n\nNote: {dom.disclaimer}"

    print(body)
    return 0


def _dispatch_skill(line: str) -> int:
    print(f"→ {line}", file=sys.stderr)
    try:
        from arka.fish_bridge import delegate_to_fish

        code = delegate_to_fish(line.split())
        return int(code or 0)
    except ImportError:
        pass
    print(line)
    return 0


def route_command(text: str) -> str:
    if re.search(r"(?i)\b(list professions|profession list|what professions)\b", text):
        return "profession list"
    if re.search(
        r"(?i)\b(clone|setup|install)\b.*\b(profession|professions)\b.*\b(projects?|repos?)\b"
        r"|\bprofession\s+(setup|clone)\b",
        text,
    ):
        m = re.search(
            r"(?i)\b(?:setup|clone)\s+(?:profession\s+)?(?:project\s+)?"
            r"(" + "|".join(re.escape(x) for x in _setup_domain_ids()) + r")\b",
            text,
        )
        return f"profession setup {m.group(1).lower()}" if m else "profession setup"
    if re.search(r"(?i)\bprofession\s+(status|combine|sources)\b", text):
        m = re.search(r"(?i)\bprofession\s+(status|combine|sources)(?:\s+(\S+))?", text)
        if m and m.group(1).lower() == "sources":
            dom = (m.group(2) or "").strip()
            return f"profession sources {dom}".strip()
        return f"profession {m.group(1).lower()}" if m else "profession status"

    hit = detect(text)
    if not hit:
        return ""
    dom_id, question = hit
    if re.search(r"(?i)\bopen\s+(?:my\s+)?(?:project|repo)\b", text):
        return f"profession open {dom_id}"
    return f"profession ask {dom_id} {shlex.quote(question)}"


def cmd_sources(domain_id: str | None = None) -> int:
    from arka.agent.profession_sources import list_sources

    if domain_id:
        dom = _by_id().get(domain_id)
        if not dom:
            print(f"Unknown domain: {domain_id}", file=sys.stderr)
            return 1
        tag = " [plugin]" if _is_plugin_domain(domain_id) else ""
        print(f"Sources for {dom.title} ({dom.id}){tag}:")
        for sid, label in list_sources(dom.id):
            print(f"  {sid:<24} {label}")
        return 0
    print("Profession domains use curated sources (not role prompts):\n")
    for d in all_domains():
        srcs = list_sources(d.id)
        ids = ", ".join(s[0] for s in srcs[:4])
        extra = f" +{len(srcs) - 4} more" if len(srcs) > 4 else ""
        tag = " [plugin]" if _is_plugin_domain(d.id) else ""
        print(f"  {d.id:<12} {ids}{extra}{tag}")
    print("\nDetail: profession sources <domain>")
    print("Third-party: profession install <path|git-url>  |  profession plugins list")
    return 0


def _is_plugin_domain(domain_id: str) -> bool:
    pp = _load_plugins()
    if pp is None:
        return False
    return pp.is_plugin_domain(domain_id)


def cmd_list() -> int:
    saved = user_domain_from_memory()
    if saved:
        title = _by_id().get(saved)
        label = title.title if title else saved
        print(f"Your saved profession → domain: {saved} ({label})")
        print()
    print("Domains (each has a curated source list — profession sources <id>):\n")
    for d in all_domains():
        proj = ""
        if d.project_key:
            try:
                from arka.agent.profession_projects import profession_project_path

                p = profession_project_path(d.project_key)
                if p:
                    proj = f"  ✓ {p}"
            except ImportError:
                pass
        if not proj:
            pp = _load_plugins()
            if pp is not None:
                p = pp.plugin_project_path(d.id)
                if p:
                    proj = f"  ✓ {p}"
        tag = "  [plugin]" if _is_plugin_domain(d.id) else ""
        print(f"  {d.id:<12} {d.title}{proj}{tag}")
    pp = _load_plugins()
    if pp is not None and pp.discover_professions():
        print("\nThird-party: profession plugins list  |  profession install <path|git-url>")
    print("\nUsage: profession ask <domain> <question>")
    print("       profession sources [domain]")
    print("       profession ask <question>   (uses saved profession from memory)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profession domains (strict symbolic routing)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list")
    p_sources = sub.add_parser("sources")
    p_sources.add_argument("domain", nargs="?")
    p_ask = sub.add_parser("ask")
    p_ask.add_argument("target", nargs="+")
    p_match = sub.add_parser("match")
    p_match.add_argument("text", nargs="+")
    p_route = sub.add_parser("route")
    p_route.add_argument("text", nargs="+")
    p_open = sub.add_parser("open")
    p_open.add_argument("domain")
    p_ids = sub.add_parser("list-ids")
    p_ids.add_argument("--plugins-only", action="store_true")
    p_install = sub.add_parser("install")
    p_install.add_argument("source")
    p_plugins = sub.add_parser("plugins")
    p_plugins_sub = p_plugins.add_subparsers(dest="plugins_cmd")
    p_plugins_sub.add_parser("list")
    p_plugins_sub.add_parser("refresh")

    args = parser.parse_args(argv)
    if args.cmd is None:
        return cmd_list()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "sources":
        return cmd_sources(args.domain)
    if args.cmd == "ask":
        words = args.target
        if len(words) >= 2 and _role_to_domain(words[0]):
            return profession_ask(_role_to_domain(words[0]) or words[0], " ".join(words[1:]))
        saved = user_domain_from_memory()
        if saved:
            return profession_ask(saved, " ".join(words))
        print("Specify domain: profession ask nutrition <question>", file=sys.stderr)
        print("Or tell Arka your profession first: I'm a nutritionist", file=sys.stderr)
        return 1
    if args.cmd == "match":
        hit = detect(" ".join(args.text))
        if hit:
            print(f"{hit[0]}\t{hit[1]}")
            return 0
        return 1
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1
    if args.cmd == "open":
        try:
            from arka.agent.profession_projects import profession_project_path

            dom = _by_id().get(args.domain)
            key = dom.project_key if dom else args.domain
            path = profession_project_path(key or args.domain) if key else None
            if not path:
                pp = _load_plugins()
                if pp is not None:
                    path = pp.plugin_project_path(args.domain)
            if path:
                print(path)
                return 0
        except ImportError:
            pass
        print(f"No project for domain: {args.domain}", file=sys.stderr)
        return 1
    if args.cmd == "list-ids":
        pp = _load_plugins()
        if pp is None:
            for d in BUILTIN_DOMAINS:
                print(d.id)
            return 0
        if args.plugins_only:
            for row in pp.discover_professions():
                print(row["id"])
        else:
            for dom_id in pp.list_domain_ids():
                print(dom_id)
        return 0
    if args.cmd == "install":
        pp = _load_plugins()
        if pp is None:
            print("Profession plugins module unavailable.", file=sys.stderr)
            return 1
        invalidate_profession_cache()
        return pp.install_profession(args.source)
    if args.cmd == "plugins":
        pp = _load_plugins()
        if pp is None:
            print("Profession plugins module unavailable.", file=sys.stderr)
            return 1
        if args.plugins_cmd == "list":
            pp.print_plugin_list(verbose=True)
            return 0
        if args.plugins_cmd == "refresh":
            invalidate_profession_cache()
            print("Profession plugin registry refreshed.")
            return 0
        print("Usage: profession plugins list|refresh", file=sys.stderr)
        return 1
    return 1


# Back-compat for fish orchestrate hook
def orchestrate(prof_id: str, question: str) -> str:
    dom = _role_to_domain(prof_id) or prof_id
    return f"profession ask {dom} {shlex.quote(question)}"


if __name__ == "__main__":
    raise SystemExit(main())
