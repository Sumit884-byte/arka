#!/usr/bin/env python3
"""Structured multi-block step-by-step answers (Arka flow)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
import sys
from pathlib import Path
from typing import Any

FLOW_SYSTEM_PROMPT = """You answer how-to and setup questions with a flow structure.

Output markdown with one or more sections. Each section covers ONE topic, platform, or sub-task.

Format rules:
- Use ## for section headers (e.g. "## Install Docker on macOS")
- Under each section use numbered steps: 1. step text
- Keep steps actionable and concise (1-2 sentences each)
- 3-8 steps per section typical
- Put --- on its own line between sections when there are multiple sections
- No intro paragraph before the first section unless one brief sentence is needed
- Commands may appear inline in steps; avoid large code blocks
- No tables, no nested lists
- TTS-friendly: plain language, minimal symbols
"""

SCIENCE_FLOW_ADDENDUM = """
For science, lab, protocol, or natural-process topics:
- Use precise scientific terminology; keep steps in standard lab order (prep, procedure, analysis, cleanup)
- Add a ## Materials or ## Reagents section when wet-lab supplies matter
- Add a ## Safety section when hazardous chemicals, biohazards, heat, or sharps are involved
- For conceptual processes (e.g. photosynthesis, replication), use ## Overview then ## Steps
- Note critical temperatures, timings, concentrations, and controls inline in steps
"""

_SCIENCE_FLOW_EXCLUDE = re.compile(
    r"(?i)\b(?:"
    r"computer\s+science|"
    r"life[- ]sciences?\s+(?:list|install|info|doctor)|"
    r"(?:install|setup)\s+(?:pubmed|single[- ]cell|nextflow|scvi)|"
    r"model\s+context\s+protocol|"
    r"\bmcp\b.*\bprotocol\b|"
    r"how\s+to\s+(?:install|download|setup|set\s+up|uninstall|upgrade|update|deploy|configure)\b|"
    r"astronomy|moon\s+phase|iss\s+pass|"
    r"metallurgy|alloy\s+composition|steel\s+grade|heat\s+treat"
    r")\b"
)

_METALLURGY_HEAT = re.compile(r"(?i)\bheat\s*treat")

_SCIENCE_DOMAIN = re.compile(
    r"(?i)\b(?:"
    r"biology|chemistry|physics|biochemistry|molecular|cellular|genetic|genomic|microbiology|"
    r"lab(?:oratory)?|protocol|experiment|assay|reagent|specimen|sample|"
    r"pcr|polymerase\s+chain\s+reaction|western\s+blot|elisa|chromatography|"
    r"electrophoresis|centrifug|spectroscop|titration|distillation|electrolysis|"
    r"dna|rna|protein|enzyme|antibody|antigen|plasmid|vector|cloning|sequencing|crispr|"
    r"mitosis|meiosis|photosynthesis|respiration|replication|transcription|translation|"
    r"metabolism|osmosis|diffusion|fermentation|catalyst|isotope|molecule|atom|ion|"
    r"bacteria|virus|cell\s+culture|organism|microscope|petri\s+dish|pipette|incubator|"
    r"gel|buffer|blot|immunol|spectrophotometer|bunsen|beaker|flask|stoichiometry|"
    r"periodic\s+table|thermodynamics|kinematics|optics|magnetism|ecosystem|evolution|"
    r"anatomy|physiology|pathology|immunol|vaccine|antibiotic|hormone|neuron|synapse"
    r")\b"
)

_SCIENCE_STEPS = re.compile(
    r"(?i)(?:"
    r"\bsteps?\s+(?:to|for|of)\s+"
    r"|\bstep[- ]by[- ]step\s+"
    r"|\b(?:explain|describe|outline)\s+(?:the\s+)?(?:steps?\s+(?:of|for)\s+|\S.+\s+steps?)\b"
    r"|\b(?:procedure|protocol)\s+(?:for|to|of)\s+"
    r"|\bhow\s+does\s+.+\s+work\b"
    r"|\bhow\s+to\s+(?:run|perform|conduct|carry\s+out)\s+"
    r")"
)


def _is_science_flow_request(text: str) -> bool:
    t = text.strip()
    if not t or _SCIENCE_FLOW_EXCLUDE.search(t):
        return False
    if not _SCIENCE_DOMAIN.search(t):
        return False
    return bool(_SCIENCE_STEPS.search(t) or re.search(r"(?i)\b(?:lab|protocol|experiment|assay)\b", t))


def _extract_science_topic(text: str) -> str:
    t = text.strip()
    m = re.match(r"(?i)^how\s+does\s+(.+?)\s+work\s*$", t)
    if m:
        return m.group(1).strip()
    m = re.match(r"(?i)^(?:explain|describe|outline)\s+(?:the\s+)?(.+?)\s+steps?\s*$", t)
    if m:
        return m.group(1).strip()
    for pat in (
        r"(?i)^steps?\s+(?:to|for|of)\s+",
        r"(?i)^step[- ]by[- ]step\s+",
        r"(?i)^(?:explain|describe|outline)\s+(?:the\s+)?steps?\s+(?:of|for)\s+",
        r"(?i)^(?:procedure|protocol)\s+(?:for|to|of)\s+",
        r"(?i)^how\s+to\s+(?:run|perform|conduct|carry\s+out)\s+",
        r"(?i)^how\s+do(?:es)?\s+",
    ):
        t = re.sub(pat, "", t).strip()
    return t.strip("'\"")


def _flow_system_prompt(topic: str) -> str:
    if _SCIENCE_DOMAIN.search(topic):
        return FLOW_SYSTEM_PROMPT + SCIENCE_FLOW_ADDENDUM
    return FLOW_SYSTEM_PROMPT


def _is_flow_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(
        r"(?i)\b(?:nextflow|github\s+actions?\s+workflow|workflow\s+(?:list|run|create|show|failed)|"
        r"why did (?:the )?ci fail|ci failed|failed checks)\b",
        t,
    ):
        return False
    if re.match(r"(?i)^workflow\s+", t):
        return False
    if re.match(r"(?i)^(?:arka\s+)?flow\s+\S", t):
        return True
    if re.search(
        r"(?i)(?:give\s+me\s+(?:a\s+)?(?:arka\s+)?flow\s+(?:for|on|about|to)\s+\S"
        r"|(?:create|make|show|get|generate)\s+(?:a\s+)?(?:arka\s+)?flow\s+(?:for|on|about|to)\s+\S"
        r"|(?:i\s+)?(?:want|need)\s+(?:a\s+)?flow\s+(?:for|on|about|to)\s+\S)",
        t,
    ):
        return True
    return _is_science_flow_request(t)


def _extract_topic(text: str) -> str:
    t = text.strip()
    if _is_science_flow_request(t):
        sci = _extract_science_topic(t)
        if sci:
            return sci
    for pat in (
        r"(?i)^(?:arka\s+)?flow\s+(?:for|on|about|to)\s+",
        r"(?i)^(?:arka\s+)?flow\s+",
        r"(?i)^(?:give\s+me\s+(?:a\s+)?(?:arka\s+)?flow\s+(?:for|on|about|to)\s+)",
        r"(?i)^(?:(?:create|make|show|get|generate)\s+(?:a\s+)?(?:arka\s+)?flow\s+(?:for|on|about|to)\s+)",
        r"(?i)^(?:i\s+)?(?:want|need)\s+(?:a\s+)?flow\s+(?:for|on|about|to)\s+",
    ):
        t = re.sub(pat, "", t).strip()
    return t.strip("'\"")


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_flow_request(t):
        return []
    topic = _extract_topic(t)
    if not topic:
        return []
    return [topic]


def _load_protocol_sources() -> Any | None:
    """Import life_sciences protocol_sources (skills/ is not a Python package)."""
    lib_path = Path(__file__).resolve().parents[1] / "skills" / "life_sciences" / "protocol_sources.py"
    if not lib_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_protocol_sources", lib_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_metallurgy_sources() -> Any | None:
    """Import metallurgy heat-treatment sources for bundled flow answers."""
    lib_path = Path(__file__).resolve().parents[1] / "skills" / "metallurgy" / "metallurgy_sources.py"
    if not lib_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_metallurgy_sources", lib_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _llm_flow(system_prompt: str, user: str) -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system_prompt,
            user,
            temperature=0.3,
            task="flow",
            skill="flow",
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system_prompt, user, temperature=0.3, task="flow").strip()


_PUBMED_FLOW_ADDENDUM = """
You are structuring a lab protocol flow from a PubMed abstract.
- Use ONLY information present in the provided abstract; do not invent steps or reagents.
- If the abstract lacks procedural detail, state what is known and note gaps briefly in a final step.
- End with a line: *Source: PubMed [URL]*
"""


def format_flow_terminal(markdown: str) -> str:
    """Render flow markdown with visual block separators for direct terminal use."""
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


def generate_flow(topic: str) -> str:
    topic = " ".join((topic or "").split()).strip()
    if not topic:
        return ""

    if _METALLURGY_HEAT.search(topic):
        ms = _load_metallurgy_sources()
        if ms is not None:
            try:
                sourced, source_kind = ms.try_metallurgy_flow_from_sources(topic)
            except Exception:
                sourced, source_kind = None, "none"
            else:
                if sourced and source_kind == "bundled":
                    return sourced

    if _SCIENCE_DOMAIN.search(topic):
        ps = _load_protocol_sources()
        if ps is not None:
            try:
                sourced, source_kind = ps.try_science_flow_from_sources(topic)
            except Exception:
                sourced, source_kind = None, "none"
            else:
                if sourced and source_kind == "bundled":
                    return sourced
                if sourced and source_kind == "pubmed":
                    system_prompt = (
                        FLOW_SYSTEM_PROMPT + SCIENCE_FLOW_ADDENDUM + _PUBMED_FLOW_ADDENDUM
                    )
                    user = f"Topic: {topic}\n\n{sourced}"
                    return _llm_flow(system_prompt, user)

    user = f"Request: {topic}"
    system_prompt = _flow_system_prompt(topic)
    return _llm_flow(system_prompt, user)


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Structured multi-block step-by-step answers")
    sub = p.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse natural language → flow args")
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
        print("  flow how to install docker on mac and windows", file=sys.stderr)
        print("  flow setting up python venv", file=sys.stderr)
        return 0

    topic = " ".join(argv).strip()
    nl = nl_to_argv(topic)
    if nl:
        topic = nl[0]

    if not topic:
        print("Usage: flow <topic or how-to question>", file=sys.stderr)
        print("Example: flow how to install docker on mac and windows", file=sys.stderr)
        return 1

    answer = generate_flow(topic)
    if not answer:
        print("Could not generate a flow (check LLM API keys)", file=sys.stderr)
        return 1

    if sys.stdout.isatty():
        print(format_flow_terminal(answer), end="")
    else:
        print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
