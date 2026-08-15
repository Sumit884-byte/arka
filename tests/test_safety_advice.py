"""Tests for safety_advice — routing, playbooks, and MCP."""

from __future__ import annotations

import json

from arka.agent.safety_advice import classify_topic, safety_advice_result
from arka.integrations.mcp_server import _handle_arka_safety_advice
from arka.routing.safety_advice import is_safety_advice_request, route_command
from arka.routing.symbolic import route_safety_advice


def test_detects_domestic_violence():
    assert is_safety_advice_request("my partner hit me what should I do")
    assert is_safety_advice_request("family member is abusive at home")
    assert is_safety_advice_request("my roommate threatened me")


def test_playbook_language_is_inclusive():
    payload = safety_advice_result("partner is violent", region="us")
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for term in ("husband", "wife", "boyfriend", "girlfriend", "women's cell", " abuser", " harasser", " stalker"):
        assert term not in blob
    assert payload.get("inclusion_note")


def test_detects_sexual_harassment():
    assert is_safety_advice_request("sexual harassment at work by my manager")


def test_excludes_fiction():
    assert not is_safety_advice_request("domestic violence in the movie plot")


def test_route_command():
    routed = route_command("I'm being abused at home")
    assert routed is not None
    assert routed.startswith("safety_advice ")


def test_symbolic_route():
    hit = route_safety_advice("help with sexual harassment")
    assert hit is not None
    assert hit.startswith("safety_advice ")


def test_classify_and_playbook():
    topic = classify_topic("someone at work groped me")
    assert topic == "sexual_harassment"
    payload = safety_advice_result("someone at work groped me", region="in")
    assert payload["region"] == "in"
    assert payload["source"] == "curated_playbook"
    assert any("112" in str(r.get("contact", "")) for r in payload["resources"])


def test_mcp_advice():
    out = _handle_arka_safety_advice({"action": "advice", "text": "partner is violent", "region": "us"})
    assert "911" in out
    assert "curated" in out.lower() or "playbook" in out.lower()


def test_mcp_parse():
    payload = json.loads(_handle_arka_safety_advice({"action": "parse", "text": "domestic abuse at home"}))
    assert payload["argv"]
