"""Router tests for conceptual comparison questions (must not route to agent_ask)."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

class RouterConceptualCompareTests(unittest.TestCase):
    def test_offline_route_prefers_web_answer(self) -> None:
        if not shutil.which("fish"):
            self.skipTest("fish not installed")
        cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"
        for query in (
            "commit vs push difference",
            "difference between git commit and push",
            "git commit versus push",
        ):
            with self.subTest(query=query):
                proc = subprocess.run(
                    [
                        "fish",
                        "-c",
                        f"source {cfg}; _agent_offline_route_cmd {subprocess.list2cmdline([query])}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                self.assertEqual(proc.stdout.strip().split()[0], "web_answer")

    def test_corrects_llm_agent_ask_to_web_answer(self) -> None:
        if not shutil.which("fish"):
            self.skipTest("fish not installed")
        cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"
        proc = subprocess.run(
            [
                "fish",
                "-c",
                "source "
                + str(cfg)
                + "; _agent_correct_interpretation "
                + subprocess.list2cmdline(["commit vs push difference"])
                + " "
                + subprocess.list2cmdline(["agent_ask commit vs push difference"]),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(proc.stdout.strip().split()[0], "web_answer")

    def test_keeps_personal_hardware_compare_on_agent_path(self) -> None:
        if not shutil.which("fish"):
            self.skipTest("fish not installed")
        cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"
        proc = subprocess.run(
            [
                "fish",
                "-c",
                f"source {cfg}; _agent_offline_route_cmd {subprocess.list2cmdline(['compare my cpu and gpu for gaming'])}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(proc.stdout.strip().split()[0], "agent_ask")

    def test_python_knowledge_detector_matches_conceptual_compare(self) -> None:
        from arka.router import _is_knowledge_question

        self.assertTrue(_is_knowledge_question("commit vs push difference"))
        self.assertTrue(_is_knowledge_question("difference between git commit and push"))
        self.assertFalse(_is_knowledge_question("compare my cpu and gpu for gaming"))


class ConceptualCompareFishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("fish"):
            raise unittest.SkipTest("fish not installed")
        cls.cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"

    def _fish_bool(self, func: str, query: str) -> bool:
        proc = subprocess.run(
            [
                "fish",
                "-c",
                f"source {self.cfg}; {func} {subprocess.list2cmdline([query])}; echo $status",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return proc.stdout.strip().endswith("0")

    def test_knowledge_question_detects_conceptual_compare(self) -> None:
        self.assertTrue(self._fish_bool("_agent_is_knowledge_question", "commit vs push difference"))
        self.assertTrue(
            self._fish_bool("_agent_is_knowledge_question", "difference between commit and push")
        )

    def test_advisory_question_rejects_conceptual_compare(self) -> None:
        self.assertFalse(self._fish_bool("_agent_is_advisory_question", "commit vs push difference"))

    def test_advisory_question_keeps_personal_hardware_compare(self) -> None:
        self.assertTrue(
            self._fish_bool("_agent_is_advisory_question", "compare my cpu and gpu for gaming")
        )


if __name__ == "__main__":
    unittest.main()
