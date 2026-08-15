"""Natural-language routing for safety_advice — domestic violence, harassment, etc."""

from __future__ import annotations

import re

# Fiction / media / abstract mentions — do not route to crisis advice.
_EXCLUDE = re.compile(
    r"(?i)\b("
    r"movie|film|show|series|novel|book|game|fiction|documentary|"
    r"history|historical|war\s+movie|video\s+game|"
    r"statistics|statistic|rate\s+of|news\s+article|headline|"
    r"research|study|paper|essay|thesis|"
    r"define|definition|what\s+is\s+the\s+meaning"
    r")\b"
)

_DOMESTIC = re.compile(
    r"(?i)\b("
    r"domestic\s+violence|domestic\s+abuse|intimate\s+partner|family\s+violence|"
    r"partner\s+(?:is\s+)?(?:hit|hits|hitting|beating|abusing|violent)|"
    r"(?:partner|spouse|family\s+member|relative|roommate|housemate|carer|caregiver|"
    r"parent|guardian|husband|wife|boyfriend|girlfriend)\s+(?:is\s+)?(?:hit|hits|hitting|beating|abuse|abusing|abusive|violent|threaten(?:ed|ing)?|hurting)|"
    r"abusive\s+(?:family\s+member|relative|parent|guardian|roommate|partner|spouse|carer|caregiver)|"
    r"abuse(?:d)?\s+(?:at\s+)?home|violence\s+at\s+home|"
    r"in[- ]house\s+violence|house\s+violence|"
    r"physical\s+abuse\s+(?:at\s+)?home|"
    r"scared\s+of\s+(?:my\s+)?(?:partner|spouse|family\s+member|relative|roommate|"
    r"carer|caregiver|parent|guardian|someone\s+I\s+live\s+with)"
    r")\b"
)

_SEXUAL_HARASSMENT = re.compile(
    r"(?i)\b("
    r"sexual\s+harass(?:ment|ed|ing)|"
    r"harass(?:ed|ment)\s+(?:sexually|at\s+work|at\s+school|by\s+(?:boss|colleague|manager|coworker|peer|teacher|classmate))|"
    r"(?:boss|colleague|manager|coworker|peer|teacher|classmate|someone)\s+(?:\w+\s+){0,3}(?:touched|groped|molested|assaulted)\s+me|"
    r"\b(?:groped|molested|assaulted)\s+me\b|"
    r"unwanted\s+(?:touch|touching|advances)|"
    r"rape|sexual\s+assault|"
    r"me\s+too|#metoo"
    r")\b"
)

_WORKPLACE = re.compile(
    r"(?i)\b("
    r"workplace\s+harass(?:ment|ed|ing)|"
    r"harass(?:ed|ment)\s+at\s+work|"
    r"toxic\s+workplace|hostile\s+work\s+environment|"
    r"boss\s+(?:harass|bully|threaten)|"
    r"posh\s+(?:act|complaint|committee)"
    r")\b"
)

_STALKING = re.compile(
    r"(?i)\b("
    r"stalk(?:ing|ed|er)|"
    r"following\s+me\s+everywhere|"
    r"someone\s+(?:won't|wont)\s+leave\s+me\s+alone"
    r")\b"
)

_DIGITAL = re.compile(
    r"(?i)\b("
    r"cyber\s*stalk|online\s+harass|"
    r"revenge\s+porn|non[- ]consensual\s+(?:images|photos|sharing)|"
    r"sextortion|blackmail(?:ing)?\s+(?:with\s+)?(?:photos|videos|nudes)"
    r")\b"
)

_EXPLICIT = re.compile(
    r"(?i)\b(?:safety\s+advice|crisis\s+advice|support\s+advice|"
    r"help\s+with\s+(?:domestic|sexual|workplace)\s+(?:violence|harassment|abuse))\b"
)


def is_safety_advice_request(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean or _EXCLUDE.search(clean):
        return False
    if _EXPLICIT.search(clean):
        return True
    return bool(
        _DOMESTIC.search(clean)
        or _SEXUAL_HARASSMENT.search(clean)
        or _WORKPLACE.search(clean)
        or _STALKING.search(clean)
        or _DIGITAL.search(clean)
    )


def route_command(cmd: str) -> str | None:
    clean = " ".join((cmd or "").split()).strip()
    if not is_safety_advice_request(clean):
        return None
    return f"safety_advice {clean!r}"
