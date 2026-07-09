"""Tests for product_reviewer skill routing and core logic."""

from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from unittest import mock

from arka.agent.core import product_reviewer
from arka.agent.professions import detect, profession_ask
from arka.router import route
from arka.routing.symbolic import route_product_reviewer


class ProductReviewerRoutingTests(unittest.TestCase):
    def test_route_product_reviewer_explicit_phrases(self) -> None:
        cases = {
            "product reviewer CeraVe cleanser ingredients": "product_reviewer",
            "review this product Head & Shoulders": "product_reviewer",
            "check ingredients water, glycerin, niacinamide": "product_reviewer",
            "ingredient check for this sunscreen": "product_reviewer",
            "analyze ingredients of this lotion": "product_reviewer",
        }
        for query, skill in cases.items():
            with self.subTest(query=query):
                hit = route_product_reviewer(query)
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit.split()[0], skill)

    def test_route_product_reviewer_natural_questions(self) -> None:
        for query in (
            "is this shampoo good for dry hair",
            "is CeraVe moisturizer vegan",
            "is this serum safe for sensitive skin",
        ):
            with self.subTest(query=query):
                hit = route_product_reviewer(query)
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertTrue(hit.startswith("product_reviewer"))

    def test_router_symbolic_routes_to_product_reviewer(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("check ingredients water, glycerin — is it vegan?")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "product_reviewer")


class ProductReviewerCoreTests(unittest.TestCase):
    def test_product_reviewer_calls_research_with_product_mode(self) -> None:
        with mock.patch("arka.agent.core.research") as research:
            product_reviewer("CeraVe cleanser — safe for sensitive skin?")
        research.assert_called_once_with(
            "CeraVe cleanser — safe for sensitive skin?",
            deep=True,
            force_mode="product",
        )

    def test_product_reviewer_empty_query_prints_usage(self) -> None:
        with mock.patch("arka.agent.core.research") as research:
            with mock.patch("builtins.print") as print_mock:
                product_reviewer("   ")
        research.assert_not_called()
        print_mock.assert_called_once()
        self.assertIn("Usage", print_mock.call_args[0][0])


class ProductProfessionTests(unittest.TestCase):
    def _builtin_domains_ctx(self) -> ExitStack:
        from arka.agent.professions import BUILTIN_DOMAINS

        stack = ExitStack()
        stack.enter_context(mock.patch("arka.agent.professions._load_plugins", return_value=None))
        stack.enter_context(mock.patch("arka.agent.professions.all_domains", return_value=BUILTIN_DOMAINS))
        return stack

    def test_detect_product_reviewer_role(self) -> None:
        from arka.agent.professions import detect, invalidate_profession_cache

        with self._builtin_domains_ctx():
            invalidate_profession_cache()
            hit = detect("as a product reviewer, is this sunscreen reef-safe?")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0], "product")

    def test_profession_ask_dispatches_product_reviewer(self) -> None:
        with self._builtin_domains_ctx():
            with mock.patch("arka.agent.professions._dispatch_skill", return_value=0) as dispatch:
                code = profession_ask("product", "niacinamide serum — pregnancy safe?")
        self.assertEqual(code, 0)
        dispatch.assert_called_once()
        self.assertTrue(dispatch.call_args[0][0].startswith("product_reviewer "))


if __name__ == "__main__":
    unittest.main()
