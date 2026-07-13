"""Tests for Arka flow skill — NL routing, formatting, and disambiguation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from arka.agent.flow import (
    _flow_system_prompt,
    _is_flow_request,
    _is_science_flow_request,
    format_flow_terminal,
    generate_flow,
    nl_to_argv,
)
from arka.routing.symbolic import route_flow


class TestFlowNlToArgv(unittest.TestCase):
    def test_direct_flow_command(self) -> None:
        self.assertEqual(
            nl_to_argv("flow how to install docker on mac and windows"),
            ["how to install docker on mac and windows"],
        )

    def test_arka_flow_prefix(self) -> None:
        self.assertEqual(
            nl_to_argv("arka flow setting up python venv"),
            ["setting up python venv"],
        )

    def test_give_me_a_flow(self) -> None:
        self.assertEqual(
            nl_to_argv("give me a flow for setting up python venv"),
            ["setting up python venv"],
        )

    def test_make_flow_for(self) -> None:
        self.assertEqual(
            nl_to_argv("make a flow for deploying to kubernetes"),
            ["deploying to kubernetes"],
        )

    def test_not_workflow_teams(self) -> None:
        self.assertEqual(nl_to_argv("workflow list"), [])
        self.assertEqual(nl_to_argv("workflow run review-and-ship"), [])

    def test_not_ci_workflow(self) -> None:
        self.assertEqual(nl_to_argv("why did the workflow fail"), [])
        self.assertEqual(nl_to_argv("ci failed on github actions"), [])

    def test_not_nextflow(self) -> None:
        self.assertEqual(nl_to_argv("nextflow run main.nf"), [])

    def test_not_generic_howto(self) -> None:
        self.assertEqual(nl_to_argv("how to install docker"), [])

    def test_science_pcr_protocol_steps(self) -> None:
        self.assertEqual(
            nl_to_argv("steps to run a PCR protocol"),
            ["run a PCR protocol"],
        )

    def test_science_western_blot_flow(self) -> None:
        self.assertEqual(
            nl_to_argv("flow for western blot"),
            ["western blot"],
        )

    def test_science_photosynthesis(self) -> None:
        self.assertEqual(
            nl_to_argv("how does photosynthesis work"),
            ["photosynthesis"],
        )

    def test_science_dna_replication_steps(self) -> None:
        self.assertEqual(
            nl_to_argv("explain DNA replication steps"),
            ["DNA replication"],
        )

    def test_science_not_computer_science(self) -> None:
        self.assertEqual(nl_to_argv("how does kubernetes work"), [])

    def test_science_not_life_sciences_catalog(self) -> None:
        self.assertEqual(nl_to_argv("life sciences list"), [])

    def test_route_symbolic(self) -> None:
        hit = route_flow("give me a flow for setting up python venv")
        self.assertEqual(hit, "flow 'setting up python venv'")


class TestFlowRequestDetection(unittest.TestCase):
    def test_is_flow_request_true_cases(self) -> None:
        self.assertTrue(_is_flow_request("flow install docker"))
        self.assertTrue(_is_flow_request("give me a flow for python venv"))

    def test_is_flow_request_false_cases(self) -> None:
        self.assertFalse(_is_flow_request("workflow list"))
        self.assertFalse(_is_flow_request("how to install docker"))
        self.assertFalse(_is_flow_request("how does kubernetes work"))

    def test_is_science_flow_request(self) -> None:
        self.assertTrue(_is_science_flow_request("steps to run a PCR protocol"))
        self.assertTrue(_is_science_flow_request("how does photosynthesis work"))
        self.assertFalse(_is_science_flow_request("life sciences list"))
        self.assertFalse(_is_science_flow_request("how does kubernetes work"))


class TestFlowSciencePrompt(unittest.TestCase):
    def test_science_prompt_addendum(self) -> None:
        prompt = _flow_system_prompt("PCR protocol")
        self.assertIn("Materials", prompt)
        self.assertIn("Safety", prompt)

    def test_generic_prompt_unchanged(self) -> None:
        prompt = _flow_system_prompt("install docker")
        self.assertNotIn("Reagents", prompt)


class TestFlowFormatting(unittest.TestCase):
    def test_format_flow_terminal_sections(self) -> None:
        raw = "## Install Docker on macOS\n1. Download Docker Desktop\n\n---\n\n## Install Docker on Windows\n1. Enable WSL2"
        out = format_flow_terminal(raw)
        self.assertIn("▸ Install Docker on macOS", out)
        self.assertIn("▸ Install Docker on Windows", out)
        self.assertIn("─" * 60, out)
        self.assertIn("1. Download Docker Desktop", out)

    def test_format_single_section(self) -> None:
        raw = "## Python venv\n1. python3 -m venv .venv"
        out = format_flow_terminal(raw)
        self.assertIn("▸ Python venv", out)
        self.assertNotIn("─" * 60, out)


class TestFlowGenerate(unittest.TestCase):
    def test_generate_flow_calls_llm(self) -> None:
        with patch("arka.llm.cli.llm_complete", return_value="## Topic\n1. First step") as mock_llm:
            out = generate_flow("install docker")
        self.assertEqual(out, "## Topic\n1. First step")
        mock_llm.assert_called_once()
        _args, kwargs = mock_llm.call_args
        self.assertEqual(kwargs.get("task"), "flow")
        self.assertEqual(kwargs.get("skill"), "flow")

    def test_generate_flow_science_uses_science_prompt(self) -> None:
        with patch("arka.llm.cli.llm_complete", return_value="## Photosynthesis\n1. Light") as mock_llm:
            generate_flow("photosynthesis")
        mock_llm.assert_called_once()
        system_prompt = mock_llm.call_args[0][0]
        self.assertIn("Reagents", system_prompt)

    def test_generate_flow_bundled_pcr_skips_llm(self) -> None:
        with patch("arka.llm.cli.llm_complete") as mock_llm:
            out = generate_flow("PCR protocol")
        mock_llm.assert_not_called()
        self.assertIn("*Source:", out)


if __name__ == "__main__":
    unittest.main()
