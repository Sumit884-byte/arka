"""Tests for arka personalize onboarding and skill recommendations."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from arka.core.personalize import (
    SKILL_CATALOG,
    _parse_interest_input,
    format_profile_summary,
    is_personalize_query,
    load_profile,
    nl_to_argv,
    profile_path,
    reset_profile,
    run_wizard,
    save_profile,
    score_skills,
)
from arka.routing.symbolic import route_offline_extras, route_personalize


class PersonalizeProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    def test_save_and_load_profile(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        profile = {
            "interests": ["finance", "pdf"],
            "experience": "beginner",
            "platforms": ["mac"],
            "has_api_keys": True,
            "uses_fish": False,
            "completed_at": "2026-07-11T00:00:00Z",
            "onboarding_done": True,
        }
        save_profile(profile)
        loaded = load_profile()
        self.assertEqual(loaded["interests"], ["finance", "pdf"])
        self.assertEqual(loaded["experience"], "beginner")
        self.assertTrue(loaded["onboarding_done"])

    @mock.patch("arka.core.personalize.config_dir")
    def test_reset_clears_profile(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        save_profile({"interests": ["dev"], "experience": "intermediate", "platforms": ["linux"]})
        self.assertTrue(profile_path().is_file())
        reset_profile()
        self.assertFalse(profile_path().is_file())


class PersonalizeScoringTests(unittest.TestCase):
    def test_finance_profile_ranks_stocks(self) -> None:
        profile = {"interests": ["finance"], "experience": "beginner", "platforms": ["mac"]}
        recs = score_skills(profile, limit=5)
        names = [r.name for r in recs]
        self.assertIn("stocks", names)
        self.assertIn("currency_convert", names)

    def test_pdf_profile_ranks_pdf_tools(self) -> None:
        profile = {"interests": ["pdf"], "experience": "beginner", "platforms": ["linux"]}
        recs = score_skills(profile, limit=5)
        names = [r.name for r in recs]
        self.assertIn("pdf_tools", names[:3])

    def test_beginner_bonus_prefers_beginner_skills(self) -> None:
        profile = {"interests": ["productivity"], "experience": "beginner", "platforms": ["mac"]}
        recs = score_skills(profile, limit=10)
        beginner_hits = [r for r in recs if SKILL_CATALOG[r.name].get("beginner")]
        self.assertTrue(len(beginner_hits) >= 2)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_gated_skill_shows_env_label(self) -> None:
        profile = {"interests": ["finance"], "experience": "beginner", "platforms": ["mac"]}
        recs = score_skills(profile, limit=10)
        stocks = next(r for r in recs if r.name == "stocks")
        self.assertFalse(stocks.gate_ok)
        self.assertIn("GROQ_API_KEY", stocks.gate_label)


class PersonalizeInterestParsingTests(unittest.TestCase):
    def test_parse_consecutive_digits_123(self) -> None:
        self.assertEqual(
            _parse_interest_input("123"),
            ["dev", "finance", "google"],
        )

    def test_parse_comma_separated_digits(self) -> None:
        self.assertEqual(
            _parse_interest_input("1,2,3"),
            ["dev", "finance", "google"],
        )

    def test_parse_space_separated_digits(self) -> None:
        self.assertEqual(
            _parse_interest_input("1 2 3"),
            ["dev", "finance", "google"],
        )

    def test_parse_interest_names(self) -> None:
        self.assertEqual(
            _parse_interest_input("dev,finance,google"),
            ["dev", "finance", "google"],
        )

    def test_parse_single_digit(self) -> None:
        self.assertEqual(_parse_interest_input("1"), ["dev"])

    def test_parse_deduplicates_repeated_digits(self) -> None:
        self.assertEqual(_parse_interest_input("112"), ["dev", "finance"])


class PersonalizeWizardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    def test_wizard_flags_non_interactive(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        profile = run_wizard(
            interests=["finance", "pdf"],
            experience="beginner",
            platforms=["mac"],
            non_interactive=True,
        )
        self.assertEqual(profile["interests"], ["finance", "pdf"])
        self.assertTrue(profile["onboarding_done"])
        data = json.loads((self.config / "personalize.json").read_text(encoding="utf-8"))
        self.assertEqual(data["interests"], ["finance", "pdf"])

    @mock.patch("arka.core.personalize.config_dir")
    @mock.patch("arka.core.personalize.sys.stdin")
    def test_wizard_interactive_digits_123(
        self, stdin: mock.MagicMock, config_dir: mock.MagicMock
    ) -> None:
        config_dir.return_value = self.config
        stdin.isatty.return_value = True
        with mock.patch("builtins.input", side_effect=["123", "1"]):
            profile = run_wizard(non_interactive=False)
        self.assertEqual(profile["interests"], ["dev", "finance", "google"])
        self.assertEqual(
            format_profile_summary(profile),
            "dev, finance, google (beginner)",
        )
        data = json.loads((self.config / "personalize.json").read_text(encoding="utf-8"))
        self.assertEqual(data["interests"], ["dev", "finance", "google"])

    @mock.patch("arka.core.personalize.config_dir")
    def test_wizard_cli_interests_flag_123(self, config_dir: mock.MagicMock) -> None:
        from arka.core.personalize import main

        config_dir.return_value = self.config
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = main(["wizard", "--interests", "123", "--experience", "beginner", "-y"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("dev, finance, google (beginner)", out)
        data = json.loads((self.config / "personalize.json").read_text(encoding="utf-8"))
        self.assertEqual(data["interests"], ["dev", "finance", "google"])


class PersonalizeDevFinanceGoogleScoringTests(unittest.TestCase):
    def test_dev_finance_google_profile_ranks_relevant_skills(self) -> None:
        profile = {
            "interests": ["dev", "finance", "google"],
            "experience": "beginner",
            "platforms": ["mac"],
        }
        recs = score_skills(profile, limit=10)
        names = [r.name for r in recs]
        self.assertIn("github_repo", names)
        self.assertIn("stocks", names)
        self.assertIn("google", names)
        self.assertNotIn("ascii_art", names[:5])
        self.assertNotIn("bookmarks", names[:5])


class PersonalizeOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    def test_recommend_output_format(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        save_profile(
            {
                "interests": ["finance", "pdf"],
                "experience": "beginner",
                "platforms": ["mac"],
                "onboarding_done": True,
            }
        )
        from arka.core.personalize import print_recommendations

        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = print_recommendations()
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("Your profile: finance, pdf (beginner)", out)
        self.assertIn("Recommended skills:", out)
        self.assertIn("pdf_tools", out)
        self.assertIn("Try:", out)


class PersonalizeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    @mock.patch("arka.core.personalize.sys.stdin")
    def test_main_empty_argv_defaults_to_wizard(
        self, stdin: mock.MagicMock, config_dir: mock.MagicMock
    ) -> None:
        from arka.core.personalize import main

        config_dir.return_value = self.config
        stdin.isatty.return_value = False
        with mock.patch("sys.argv", ["arka", "personalize"]):
            buf = StringIO()
            with mock.patch("sys.stdout", buf):
                code = main([])
        self.assertEqual(code, 0)
        self.assertIn("Profile saved", buf.getvalue())
        self.assertTrue((self.config / "personalize.json").is_file())

    @mock.patch("arka.core.personalize.config_dir")
    def test_main_recommend_subcommand(self, config_dir: mock.MagicMock) -> None:
        from arka.core.personalize import main

        config_dir.return_value = self.config
        save_profile(
            {
                "interests": ["finance"],
                "experience": "beginner",
                "platforms": ["mac"],
                "onboarding_done": True,
            }
        )
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = main(["recommend"])
        self.assertEqual(code, 0)
        self.assertIn("Recommended skills:", buf.getvalue())

    @mock.patch("arka.core.personalize.config_dir")
    def test_main_status_subcommand(self, config_dir: mock.MagicMock) -> None:
        from arka.core.personalize import main

        config_dir.return_value = self.config
        save_profile(
            {
                "interests": ["dev"],
                "experience": "intermediate",
                "platforms": ["linux"],
                "onboarding_done": True,
            }
        )
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Interests:    dev", buf.getvalue())

    @mock.patch("arka.core.personalize.config_dir")
    @mock.patch("arka.core.personalize.sys.stdin")
    def test_cli_personalize_no_subcommand(
        self, stdin: mock.MagicMock, config_dir: mock.MagicMock
    ) -> None:
        from arka.cli import main as cli_main

        config_dir.return_value = self.config
        stdin.isatty.return_value = False
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = cli_main(["personalize"])
        self.assertEqual(code, 0)
        self.assertIn("Profile saved", buf.getvalue())

    @mock.patch("arka.core.personalize.config_dir")
    def test_dispatch_personalize_skill(self, config_dir: mock.MagicMock) -> None:
        from arka.dispatch import run_skill

        config_dir.return_value = self.config
        save_profile(
            {
                "interests": ["pdf"],
                "experience": "beginner",
                "platforms": ["mac"],
                "onboarding_done": True,
            }
        )
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = run_skill("personalize recommend")
        self.assertEqual(code, 0)
        self.assertIn("pdf_tools", buf.getvalue())


class PersonalizeRoutingTests(unittest.TestCase):
    def test_is_personalize_query(self) -> None:
        self.assertTrue(is_personalize_query("personalize me"))
        self.assertTrue(is_personalize_query("recommend skills for me"))
        self.assertTrue(is_personalize_query("what skills should I use"))
        self.assertTrue(is_personalize_query("get started with arka"))
        self.assertFalse(is_personalize_query("what is Python"))

    def test_nl_to_argv_recommend(self) -> None:
        self.assertEqual(nl_to_argv("recommend skills"), ["recommend"])

    def test_nl_to_argv_quickstart(self) -> None:
        self.assertEqual(nl_to_argv("get started with arka quickstart"), ["quickstart"])

    def test_route_personalize(self) -> None:
        self.assertEqual(route_personalize("personalize me"), "personalize recommend")
        self.assertEqual(route_personalize("get started with arka"), "personalize recommend")

    def test_offline_extras_routes_personalize(self) -> None:
        hit = route_offline_extras("recommend skills for finance and pdf")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "personalize")


if __name__ == "__main__":
    unittest.main()
