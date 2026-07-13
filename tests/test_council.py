"""Tests for Arka Council — routing, personas, synthesis, and memory."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent.council import (
    DEFAULT_COUNCIL_MEMBERS,
    format_chamber,
    is_duplicate,
    list_sessions,
    member_system_prompt,
    nl_to_argv,
    normalize_question,
    record_session,
    resolve_council_members,
    run_council,
    synthesize_deliberation,
)
from arka.agent.personas.schema import Persona
from arka.routing.council import extract_question, is_council_request
from arka.routing.symbolic import route_council
from arka.router import route


class CouncilDetectionTests(unittest.TestCase):
    def test_detects_arka_council(self) -> None:
        self.assertTrue(is_council_request("arka council should I learn Rust?"))

    def test_detects_bare_council(self) -> None:
        self.assertTrue(is_council_request("council should I quit my job"))

    def test_detects_deliberate_with_arka(self) -> None:
        self.assertTrue(
            is_council_request("deliberate with arka on whether remote work is better")
        )

    def test_detects_ask_the_council(self) -> None:
        self.assertTrue(is_council_request("ask the council about learning Go"))

    def test_detects_council_of_experts(self) -> None:
        self.assertTrue(is_council_request("council of experts on startup risk"))

    def test_detects_list(self) -> None:
        self.assertTrue(is_council_request("council list"))

    def test_rejects_unrelated(self) -> None:
        self.assertFalse(is_council_request("what is Rust?"))

    def test_rejects_security_council(self) -> None:
        self.assertFalse(is_council_request("tell me about the UN security council"))


class CouncilExtractTests(unittest.TestCase):
    def test_extracts_from_council(self) -> None:
        self.assertEqual(extract_question("council should I learn Rust?"), "should I learn Rust?")

    def test_extracts_from_deliberate(self) -> None:
        self.assertEqual(
            extract_question("deliberate with arka on whether remote work is better"),
            "whether remote work is better",
        )

    def test_extracts_from_ask_the_council(self) -> None:
        self.assertEqual(
            extract_question("ask the council about switching careers"),
            "switching careers",
        )


class CouncilNlToArgvTests(unittest.TestCase):
    def test_nl_to_argv_question(self) -> None:
        self.assertEqual(nl_to_argv("council should I learn Rust?"), ["should I learn Rust?"])

    def test_nl_to_argv_list(self) -> None:
        self.assertEqual(nl_to_argv("council list"), ["list"])

    def test_nl_to_argv_empty_for_generic(self) -> None:
        self.assertEqual(nl_to_argv("what is Python"), [])

    def test_route_symbolic(self) -> None:
        hit = route_council("deliberate with arka on startup equity")
        self.assertEqual(hit, "council 'startup equity'")


class CouncilRouterTests(unittest.TestCase):
    def test_routes_council_offline(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("council should I learn Rust?")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "council")


class CouncilPersonaTests(unittest.TestCase):
    def test_default_members(self) -> None:
        self.assertEqual(DEFAULT_COUNCIL_MEMBERS, ("socrates", "elon", "feynman"))

    def test_resolve_default_personas(self) -> None:
        with mock.patch("arka.agent.council.resolve_persona") as resolve:
            resolve.side_effect = lambda name: Persona(
                name=name,
                display_name=f"{name.title()} (simulated)",
                system_prompt=f"You are {name}.",
            )
            members = resolve_council_members()
        self.assertEqual(len(members), 3)
        self.assertEqual([m.name for m in members], ["socrates", "elon", "feynman"])

    def test_member_prompt_includes_persona_lens(self) -> None:
        persona = Persona(name="socrates", system_prompt="Ask questions.")
        prompt = member_system_prompt(persona)
        self.assertIn("Persona lens", prompt)
        self.assertIn("Arka Council", prompt)


class CouncilMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mem = Path(self.tmp.name) / "council-memory.json"

    def _patch_mem(self):
        return mock.patch("arka.agent.council.memory_path", return_value=self.mem)

    def test_normalize_and_duplicate(self) -> None:
        a = normalize_question("Should I learn Rust?")
        b = normalize_question("should i learn rust")
        self.assertEqual(a, b)
        self.assertTrue(is_duplicate("Should I learn Rust?", [{"question": "should i learn rust"}]))

    def test_record_skips_duplicate(self) -> None:
        with self._patch_mem():
            self.assertTrue(record_session("Should I learn Rust?", ["socrates", "elon", "feynman"]))
            self.assertFalse(record_session("should i learn rust", ["socrates", "elon", "feynman"]))
            data = json.loads(self.mem.read_text(encoding="utf-8"))
            self.assertEqual(len(data["sessions"]), 1)

    def test_list_sessions_newest_first(self) -> None:
        with self._patch_mem():
            record_session("First question?", ["socrates"])
            record_session("Second question?", ["elon"])
            items = list_sessions()
        self.assertEqual(items[0]["question"], "Second question?")


class CouncilSynthesisTests(unittest.TestCase):
    def test_synthesis_mock(self) -> None:
        persona = Persona(name="socrates", display_name="Socrates (simulated)", system_prompt="x")
        answers = [(persona, "Know thy purpose first.")]
        with mock.patch(
            "arka.agent.council._llm_complete",
            return_value=(
                "CONSENSUS: Learning takes discipline.\n"
                "TENSION: Time cost vs payoff.\n"
                "VERDICT: Start small if curiosity is real."
            ),
        ):
            result = synthesize_deliberation("Should I learn Rust?", answers)
        self.assertIn("discipline", result["consensus"].lower())
        self.assertIn("payoff", result["tension"].lower())
        self.assertIn("Start small", result["verdict"])

    def test_format_chamber(self) -> None:
        persona = Persona(name="elon", display_name="Elon (simulated)", system_prompt="x")
        text = format_chamber(
            "Should I learn Rust?",
            [(persona, "Rust is great for systems work.")],
            {"consensus": "Systems skills matter.", "tension": "Steep curve.", "verdict": "Try it."},
        )
        self.assertIn("━━━ Arka Council ━━━", text)
        self.assertIn("Elon (simulated)", text)
        self.assertIn("Consensus:", text)
        self.assertIn("Verdict:", text)

    def test_run_council_end_to_end_mock(self) -> None:
        def fake_resolve(name: str) -> Persona:
            return Persona(
                name=name,
                display_name=f"{name.title()} (simulated)",
                system_prompt=f"You are {name}.",
            )

        llm_side_effect = [
            "I would examine your motives first.",
            "First principles say learn what you will ship.",
            "Try building something tiny and see if you enjoy the struggle.",
            "CONSENSUS: Hands-on learning wins.\nTENSION: Time vs depth.\nVERDICT: Build a small project.",
        ]

        with (
            mock.patch("arka.agent.council.resolve_persona", side_effect=fake_resolve),
            mock.patch("arka.agent.council._llm_complete", side_effect=llm_side_effect),
            mock.patch("arka.agent.council.record_session", return_value=True),
        ):
            output = run_council("Should I learn Rust?")

        self.assertIn("Socrates (simulated)", output)
        self.assertIn("Synthesis", output)
        self.assertIn("Verdict:", output)


if __name__ == "__main__":
    unittest.main()
