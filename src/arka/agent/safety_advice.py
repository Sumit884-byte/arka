#!/usr/bin/env python3
"""Curated safety advice for domestic violence, sexual harassment, and related crises.

Uses vetted static playbooks and hotlines — not free-form LLM legal/medical advice.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from typing import Any

INCLUSION_NOTE = (
    "This guidance applies regardless of your gender, age, background, or relationship to the person causing harm."
)

DISCLAIMER = (
    "This is general supportive information, not legal, medical, or therapeutic advice. "
    "If you are in immediate danger, contact local emergency services now."
)

EMERGENCY = {
    "us": "911 (US emergency)",
    "in": "112 (India emergency — also try 100 police, 108 ambulance)",
    "intl": "Your local emergency number (112 in many countries)",
}

RESOURCES: dict[str, dict[str, list[dict[str, str]]]] = {
    "us": {
        "all": [
            {"name": "Emergency", "contact": "911"},
            {"name": "988 Suicide & Crisis Lifeline", "contact": "988 (call or text)"},
        ],
        "domestic_violence": [
            {"name": "National Domestic Violence Hotline", "contact": "1-800-799-7233 — serves all genders (call) / thehotline.org chat"},
        ],
        "sexual_harassment": [
            {"name": "RAINN National Sexual Assault Hotline", "contact": "1-800-656-4673 (HOPE) / rainn.org chat"},
        ],
        "workplace_harassment": [
            {"name": "EEOC (workplace discrimination/harassment)", "contact": "eeoc.gov — file charges info; not emergency line"},
        ],
        "stalking": [
            {"name": "National Domestic Violence Hotline", "contact": "1-800-799-7233 — can help with safety planning"},
            {"name": "VictimConnect", "contact": "1-855-484-2846"},
        ],
        "digital_harassment": [
            {"name": "Cyber Civil Rights Initiative", "contact": "cybercivilrights.org — non-consensual image abuse"},
            {"name": "RAINN", "contact": "1-800-656-4673"},
        ],
    },
    "in": {
        "all": [
            {"name": "Emergency", "contact": "112 (or 100 police / 108 ambulance)"},
            {
                "name": "National Women Helpline",
                "contact": "181 (many states) or 1091 — name says 'women' but often helps anyone facing abuse",
            },
        ],
        "domestic_violence": [
            {
                "name": "National Commission for Women",
                "contact": "7827170170 / 14440 — also routes many non-women callers to local support",
            },
            {"name": "Domestic violence — one-stop centres", "contact": "Search 'OSC near me' or ask 181"},
        ],
        "sexual_harassment": [
            {"name": "National Commission for Women", "contact": "7827170170 / ncwapps.nic.in"},
            {"name": "Police", "contact": "100 or 112 for immediate danger"},
        ],
        "workplace_harassment": [
            {"name": "Internal POSH committee", "contact": "Every workplace with 10+ staff must have one — ask HR in writing"},
            {
                "name": "Local labour / victim-support desk",
                "contact": "District labour office or police victim-support desk (names vary by state)",
            },
        ],
        "stalking": [
            {"name": "Police helpline", "contact": "1091 / 112"},
            {"name": "National Commission for Women", "contact": "7827170170"},
        ],
        "digital_harassment": [
            {"name": "Cyber crime portal", "contact": "cybercrime.gov.in — report online abuse / image abuse"},
            {"name": "National Commission for Women", "contact": "7827170170"},
        ],
    },
    "intl": {
        "all": [
            {"name": "Local emergency", "contact": "112 in EU/India and many countries; 911 in US/Canada; 999 UK"},
            {"name": "findahelpline.com", "contact": "Directory of crisis lines by country"},
        ],
        "domestic_violence": [
            {"name": "UN Women — global resources", "contact": "unwomen.org/en/what-we-do/ending-violence-against-women"},
        ],
        "sexual_harassment": [
            {"name": "RAINN (US, English)", "contact": "1-800-656-4673"},
            {"name": "findahelpline.com", "contact": "Country-specific sexual violence lines"},
        ],
        "workplace_harassment": [
            {"name": "ILO guidance", "contact": "ilo.org — workplace violence and harassment standards"},
        ],
        "stalking": [
            {"name": "Local victim support", "contact": "Search 'stalking helpline' + your country"},
        ],
        "digital_harassment": [
            {"name": "Without My Consent", "contact": "withoutmyconsent.org — online abuse resources"},
        ],
    },
}

TOPICS: dict[str, dict[str, Any]] = {
    "domestic_violence": {
        "title": "Domestic or household violence",
        "summary": (
            "Abuse at home can be physical, sexual, emotional, financial, or coercive control. "
            "It can involve a partner, spouse, family member, roommate, caregiver, or anyone you live with — "
            "regardless of gender, age, or background. It is not your fault. Your safety comes first."
        ),
        "immediate": [
            "If you are in immediate danger, call emergency services and get to a safe place if you can.",
            "If you cannot speak safely, use text/chat lines where available.",
            "Tell a trusted person where you are if you can do so without increasing risk.",
        ],
        "steps": [
            "Safety planning: identify exits, a bag with essentials (ID, phone, medication, cash), and a safe place to go.",
            "Keep evidence only if it is safe — photos, messages, medical records stored where the other person cannot access them.",
            "Contact a confidential domestic violence advocate before confronting the person causing harm or announcing you are leaving.",
            "Avoid sharing your plan on devices someone else monitors.",
        ],
        "avoid": [
            "Do not assume you must stay to 'fix' the situation — trained advocates can help you weigh options.",
            "Do not rely on this chat for legal strategy; speak with a qualified lawyer or legal aid when safe.",
        ],
    },
    "sexual_harassment": {
        "title": "Sexual harassment or assault",
        "summary": (
            "Unwanted sexual conduct — comments, touching, pressure, or assault — is never okay, "
            "whether it happens at work, school, online, or in private. "
            "What happened is not your fault, regardless of who harmed you or your gender or age."
        ),
        "immediate": [
            "If you are in immediate danger or were just assaulted, call emergency services or go to a hospital if you can.",
            "You can decline to be alone with the person who harmed you.",
            "A sexual assault forensic exam (rape kit) is time-sensitive; a hospital or hotline can explain options.",
        ],
        "steps": [
            "If you feel safe, write what happened while memory is fresh (date, time, location, witnesses).",
            "Save messages, emails, or recordings in a secure account the other person cannot access.",
            "You choose whether to report to an employer, school, or police — advocates can explain pros and cons without pressure.",
            "Ask about confidential counseling through hotlines; many are free and serve all genders and ages.",
        ],
        "avoid": [
            "Do not let anyone pressure you to confront the person who harmed you alone.",
            "Do not assume reporting is required to get support — hotlines help regardless.",
        ],
    },
    "workplace_harassment": {
        "title": "Workplace or school harassment",
        "summary": (
            "Harassment can include sexual conduct, bullying, retaliation, or a hostile environment — "
            "at work, school, or training. Document and use official channels when you can."
        ),
        "immediate": [
            "If you are in physical danger, call emergency services.",
            "If your organization has a harassment/POSH/HR policy, note reporting deadlines in writing.",
        ],
        "steps": [
            "Document incidents: dates, times, what was said or done, witnesses, and your responses.",
            "Report in writing (email) to HR, a school office, or the internal committee when safe — keeps a paper trail.",
            "Keep copies of performance or attendance records and communications that show retaliation.",
            "Ask a labour lawyer or local victim-support office about protections in your jurisdiction — laws vary.",
        ],
        "avoid": [
            "Do not delete evidence or leave without advice if you may need to file a complaint.",
            "Do not assume HR or school staff always act neutrally — external advocates can help you prepare.",
        ],
    },
    "stalking": {
        "title": "Stalking or persistent unwanted contact",
        "summary": (
            "Repeated following, monitoring, threats, or unwanted contact can be stalking — "
            "from anyone, regardless of relationship, gender, or age. Take patterns seriously and document them."
        ),
        "immediate": [
            "If threatened with harm now, call emergency services.",
            "Vary routes and routines if someone is following you; stay in public places when possible.",
        ],
        "steps": [
            "Log every incident with date/time — photos, screenshots, license plates if safe.",
            "Tell trusted people about the situation; do not meet the person alone to 'talk it out'.",
            "Review phone/app security; change passwords from a device the other person cannot access.",
            "Ask advocates or police about protective or restraining orders where available.",
        ],
        "avoid": [
            "Do not engage to 'reason' with someone who ignores boundaries — it often escalates contact.",
        ],
    },
    "digital_harassment": {
        "title": "Online harassment or image abuse",
        "summary": (
            "Cyberstalking, threats, or sharing intimate images without consent are serious. "
            "Preserve evidence before blocking."
        ),
        "immediate": [
            "Screenshot posts, messages, and profile URLs with timestamps before deleting or blocking.",
            "If images are being shared, report to the platform and seek specialized hotlines (see resources).",
        ],
        "steps": [
            "Do not pay sextortion demands — report to police and cyber-crime portals.",
            "Secure accounts: new passwords, 2FA, review logged-in devices.",
            "Platform abuse forms + police/cybercrime reports create official records.",
        ],
        "avoid": [
            "Do not delete evidence before advocates or law enforcement advise you.",
        ],
    },
}


def default_region() -> str:
    raw = (os.environ.get("ARKA_SAFETY_REGION") or os.environ.get("ARKA_REGION") or "").strip().lower()
    if raw in {"us", "usa", "united states"}:
        return "us"
    if raw in {"in", "india", "ind"}:
        return "in"
    if raw in RESOURCES:
        return raw
    tz = (os.environ.get("TZ") or "").strip()
    if "Kolkata" in tz or "India" in tz:
        return "in"
    return "intl"


def classify_topic(text: str) -> str:
    from arka.routing.safety_advice import (
        _DIGITAL,
        _DOMESTIC,
        _SEXUAL_HARASSMENT,
        _STALKING,
        _WORKPLACE,
    )

    clean = " ".join((text or "").split()).strip()
    if _SEXUAL_HARASSMENT.search(clean):
        return "sexual_harassment"
    if _WORKPLACE.search(clean):
        return "workplace_harassment"
    if _DOMESTIC.search(clean):
        return "domestic_violence"
    if _STALKING.search(clean):
        return "stalking"
    if _DIGITAL.search(clean):
        return "digital_harassment"
    return "domestic_violence"


def _resources_for(topic: str, region: str) -> list[dict[str, str]]:
    reg = region if region in RESOURCES else "intl"
    bucket = RESOURCES[reg]
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for key in ("all", topic):
        for item in bucket.get(key) or []:
            sig = (item.get("name", ""), item.get("contact", ""))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(item)
    return out


def safety_advice_result(
    text: str,
    *,
    topic: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    reg = (region or default_region()).lower()
    if reg not in RESOURCES:
        reg = "intl"
    topic_id = topic or classify_topic(text)
    if topic_id not in TOPICS:
        topic_id = "domestic_violence"
    playbook = TOPICS[topic_id]
    return {
        "topic": topic_id,
        "title": playbook["title"],
        "region": reg,
        "emergency": EMERGENCY.get(reg, EMERGENCY["intl"]),
        "disclaimer": DISCLAIMER,
        "inclusion_note": INCLUSION_NOTE,
        "summary": playbook["summary"],
        "immediate": list(playbook["immediate"]),
        "steps": list(playbook["steps"]),
        "avoid": list(playbook["avoid"]),
        "resources": _resources_for(topic_id, reg),
        "source": "curated_playbook",
    }


def format_advice(payload: dict[str, Any]) -> str:
    lines = [
        f"⚠️  {payload.get('emergency', '')}",
        f"    {payload.get('disclaimer', DISCLAIMER)}",
        "",
        f"_{payload.get('inclusion_note', INCLUSION_NOTE)}_",
        "",
        f"## {payload.get('title', 'Safety information')}",
        "",
        str(payload.get("summary") or ""),
        "",
        "### If you are unsafe right now",
    ]
    for item in payload.get("immediate") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### Practical steps (when you can)"])
    for item in payload.get("steps") or []:
        lines.append(f"- {item}")
    avoid = payload.get("avoid") or []
    if avoid:
        lines.extend(["", "### Please avoid"])
        for item in avoid:
            lines.append(f"- {item}")
    lines.extend(["", "### Confidential resources"])
    for res in payload.get("resources") or []:
        lines.append(f"- **{res.get('name', 'Resource')}**: {res.get('contact', '')}")
    lines.extend(
        [
            "",
            "_Arka uses a fixed safety playbook for this topic — not improvised legal or medical advice._",
        ]
    )
    return "\n".join(lines)


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    from arka.routing.safety_advice import is_safety_advice_request

    if not is_safety_advice_request(t):
        return []
    return [t]


def cmd_advice(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip() if args.text else ""
    if not text and not args.topic:
        raise SystemExit("Provide a question or --topic")
    payload = safety_advice_result(
        text,
        topic=str(args.topic).strip() if args.topic else None,
        region=str(args.region).strip() if args.region else None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_advice(payload))
    return 0


def cmd_resources(args: argparse.Namespace) -> int:
    topic = str(args.topic or "domestic_violence").strip()
    region = str(args.region or default_region()).strip()
    payload = {
        "topic": topic,
        "region": region,
        "emergency": EMERGENCY.get(region, EMERGENCY["intl"]),
        "resources": _resources_for(topic, region),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_topics(_args: argparse.Namespace) -> int:
    for key, val in TOPICS.items():
        print(f"{key}\t{val['title']}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Curated safety advice — domestic violence, harassment, stalking (not LLM legal advice)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  safety_advice \"my partner hit me what do I do\"\n"
            "  safety_advice \"sexual harassment at work\" --region in\n"
            "  safety_advice resources --topic domestic_violence --region us\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_advice = sub.add_parser("advice", help="Show curated advice for a situation")
    p_advice.add_argument("text", nargs="*", help="Describe your situation")
    p_advice.add_argument("--topic", choices=sorted(TOPICS.keys()))
    p_advice.add_argument("--region", choices=sorted(RESOURCES.keys()))
    p_advice.add_argument("--json", action="store_true")
    p_advice.set_defaults(func=cmd_advice)

    p_res = sub.add_parser("resources", help="List hotlines for a topic/region")
    p_res.add_argument("--topic", default="domestic_violence", choices=sorted(TOPICS.keys()))
    p_res.add_argument("--region", choices=sorted(RESOURCES.keys()))
    p_res.set_defaults(func=cmd_resources)

    p_topics = sub.add_parser("topics", help="List supported topics")
    p_topics.set_defaults(func=cmd_topics)

    p_parse = sub.add_parser("parse", help="Parse natural language → safety_advice args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        build_parser().print_help()
        return 0
    if args[0] in {"-h", "--help"}:
        build_parser().parse_args(["advice", "--help"])
        return 0
    if args[0] not in {"advice", "resources", "topics", "parse"}:
        args = ["advice", *args]
    try:
        ns = build_parser().parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(ns, "command", None):
        build_parser().print_help()
        return 0
    try:
        return int(ns.func(ns))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
