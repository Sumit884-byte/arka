"""Tests for meme template compositor — layouts, CLI, and NL routing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from arka.agent.meme_templates import (
    caption,
    comparison,
    drake,
    expanding_brain,
    main,
    nl_to_argv,
    two_button,
    vibe_coding_comparison,
)
from arka.agent.symbolic_image import comparison as symbolic_comparison
from arka.routing.symbolic import route_meme, route_symbolic_image


class TestComparison(unittest.TestCase):
    def test_image_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.png"
            right = root / "right.png"
            Image.new("RGB", (40, 30), "blue").save(left)
            Image.new("RGB", (40, 30), "green").save(right)
            out = root / "out.png"
            result = comparison(
                left=str(left),
                right=str(right),
                left_title="AI FIRST",
                right_title="DATA FIRST",
                output=str(out),
            )
            self.assertEqual(result["token_cost"], "local-only")
            self.assertTrue(out.is_file())

    def test_text_panel_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "text-comparison.png"
            result = comparison(
                left_label="Fast hacks",
                right_label="Solid engineering",
                left_title="VIBE",
                right_title="CRAFT",
                output=str(out),
            )
            self.assertEqual(result["template"], "comparison")
            self.assertTrue(out.is_file())

    def test_symbolic_image_backward_compat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.png"
            right = root / "right.png"
            Image.new("RGB", (40, 30), "blue").save(left)
            Image.new("RGB", (40, 30), "green").save(right)
            out = root / "out.png"
            result = symbolic_comparison(
                str(left),
                str(right),
                left_title="BEFORE",
                right_title="AFTER",
                output=str(out),
            )
            self.assertTrue(out.is_file())
            self.assertEqual(result["template"], "comparison")


class TestTemplates(unittest.TestCase):
    def test_drake(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "drake.png"
            result = drake(reject="Manual deploys", accept="CI/CD pipeline", output=str(out))
            self.assertEqual(result["template"], "drake")
            self.assertTrue(out.is_file())

    def test_caption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.png"
            Image.new("RGB", (120, 80), "orange").save(image)
            out = root / "caption.png"
            result = caption(
                image=str(image),
                top="WHEN TESTS PASS",
                bottom="ON THE FIRST TRY",
                output=str(out),
            )
            self.assertEqual(result["template"], "caption")
            self.assertTrue(out.is_file())

    def test_expanding_brain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "brain.png"
            result = expanding_brain(
                ["Use print()", "Use a debugger", "Write tests", "Observability"],
                output=str(out),
            )
            self.assertEqual(result["template"], "expanding_brain")
            self.assertTrue(out.is_file())

    def test_two_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "buttons.png"
            result = two_button(
                dilemma="Production is down",
                left="Rollback",
                right="Deploy a fix",
                highlight="left",
                output=str(out),
            )
            self.assertEqual(result["template"], "two_button")
            self.assertTrue(out.is_file())

    def test_vibe_coding_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "vibe.png"
            result = vibe_coding_comparison(output=str(out))
            self.assertTrue(out.is_file())
            self.assertEqual(result["template"], "comparison")


class TestRouting(unittest.TestCase):
    def test_route_explicit_meme_vibe_coding(self) -> None:
        hit = route_meme("meme vibe-coding")
        self.assertEqual(hit, "meme vibe-coding")

    def test_route_explicit_meme_drake_flags(self) -> None:
        hit = route_meme("meme drake --reject X --accept Y")
        self.assertEqual(hit, "meme drake --reject X --accept Y")

    def test_route_drake_meme(self) -> None:
        hit = route_meme('make a drake meme reject "skip tests" accept "write tests"')
        self.assertIsNotNone(hit)
        self.assertTrue(hit.startswith("meme drake"))

    def test_route_bare_drake_meme(self) -> None:
        hit = route_meme("make a drake meme")
        self.assertEqual(hit, "meme drake")

    def test_route_vibe_coding(self) -> None:
        hit = route_meme("vibe coding vs software engineering meme")
        self.assertEqual(hit, "meme vibe-coding")

    def test_route_comparison_not_symbolic_when_meme(self) -> None:
        self.assertIsNone(
            route_symbolic_image("make a comparison meme about vibe coding")
        )
        hit = route_meme("make a comparison meme about vibe coding")
        self.assertIsNotNone(hit)

    def test_nl_to_argv_expanding_brain(self) -> None:
        argv = nl_to_argv(
            'expanding brain meme "print" "debugger" "tests" "observability"'
        )
        self.assertEqual(argv[0], "expanding-brain")
        self.assertEqual(argv.count("--label"), 4)


class TestCli(unittest.TestCase):
    def test_cli_vibe_coding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cli-vibe.png"
            code = main(["vibe-coding", "--output", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())

    def test_nl_to_argv_explicit(self) -> None:
        self.assertEqual(nl_to_argv("meme vibe-coding"), ["vibe-coding"])
        self.assertEqual(
            nl_to_argv("meme drake --reject X --accept Y"),
            ["drake", "--reject", "X", "--accept", "Y"],
        )


class TestRouterIntegration(unittest.TestCase):
    def test_router_meme_not_web_answer(self) -> None:
        from arka.router import route

        hit = route("meme vibe-coding")
        self.assertIsNotNone(hit)
        self.assertTrue(hit.skill.startswith("meme "))
        self.assertNotIn("web_answer", hit.skill)

    def test_route_preview_explicit_meme(self) -> None:
        from arka.router import route_preview

        hit = route_preview("meme vibe-coding")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.skill, "meme vibe-coding")
        self.assertNotIn("web_answer", hit.skill)

    def test_cli_meme_vibe_coding(self) -> None:
        from io import StringIO
        from unittest.mock import patch

        from arka import cli

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cli-route.png"
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = cli.main(["meme", "vibe-coding", "--output", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertIn("Created meme", buf.getvalue())

    def test_cli_meme_before_fish_delegation(self) -> None:
        from io import StringIO
        from unittest.mock import patch

        from arka import cli

        def _fish_should_not_run(_argv: list[str]) -> int:
            raise AssertionError("delegate_to_fish must not run for explicit meme subcommands")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cli-fish-bypass.png"
            buf = StringIO()
            with patch("sys.stdout", buf):
                with patch("arka.platform_info.has_full_fish_agent", return_value=True):
                    with patch("arka.fish_bridge.delegate_to_fish", side_effect=_fish_should_not_run):
                        code = cli.main(["meme", "vibe-coding", "--output", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())

    def test_delegate_to_fish_intercepts_meme(self) -> None:
        from io import StringIO
        from unittest.mock import patch

        from arka.fish_bridge import delegate_to_fish

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bridge-meme.png"
            buf = StringIO()
            with patch("sys.stdout", buf):
                with patch("subprocess.run", side_effect=AssertionError("fish must not run")):
                    code = delegate_to_fish(["meme", "vibe-coding", "--output", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertIn("Created meme", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
