"""Tests for product_reviewer skill routing and core logic."""

from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from unittest import mock

from arka.agent.core import product_reviewer
from arka.agent.product_sources import (
    build_product_search_queries,
    detect_product_category,
    list_product_sources,
)
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

    def test_research_product_mode_uses_authoritative_sources(self) -> None:
        from arka.agent.core import research

        with mock.patch(
            "arka.agent.product_sources.fetch_product_web_context",
            return_value=("incidecoder page", ["INCIDecoder", "EWG Skin Deep"]),
        ) as fetch:
            with mock.patch("arka.agent.core._llm", return_value="review"):
                with mock.patch("arka.output.print_block"):
                    research("niacinamide serum safety", force_mode="product")
        fetch.assert_called_once_with("niacinamide serum safety", deep=True)


class ProductSourceQueryTests(unittest.TestCase):
    def test_detect_cosmetics_category(self) -> None:
        self.assertEqual(detect_product_category("CeraVe cleanser for sensitive skin"), "cosmetics")
        self.assertEqual(detect_product_category("niacinamide serum SPF 30"), "cosmetics")

    def test_detect_food_category(self) -> None:
        self.assertEqual(detect_product_category("Kind bar nutrition label calories"), "food")

    def test_detect_supplement_category(self) -> None:
        self.assertEqual(detect_product_category("vitamin D3 supplement 5000 IU"), "supplement")

    def test_build_queries_target_cosmetic_domains(self) -> None:
        queries = build_product_search_queries("CeraVe Hydrating Cleanser ingredients")
        combined = queries[0].query
        self.assertIn("site:incidecoder.com", combined)
        self.assertIn("site:ewg.org", combined)
        self.assertIn("site:paulaschoice.com", combined)
        self.assertIn("CeraVe Hydrating Cleanser ingredients", combined)
        ids = {q.source_id for q in queries}
        self.assertIn("incidecoder", ids)
        self.assertIn("brand", ids)

    def test_build_queries_target_food_domains(self) -> None:
        queries = build_product_search_queries("Clif Bar chocolate chip food label")
        combined = queries[0].query
        self.assertIn("site:fdc.nal.usda.gov", combined)
        self.assertIn("site:openfoodfacts.org", combined)
        self.assertIn("site:fda.gov/food", combined)

    def test_build_queries_include_pubmed_for_safety(self) -> None:
        queries = build_product_search_queries("retinol serum pregnancy safe")
        combined = queries[0].query
        self.assertIn("site:pubmed.ncbi.nlm.nih.gov", combined)

    def test_list_product_sources_cosmetics(self) -> None:
        labels = [label for _, label in list_product_sources("cosmetics")]
        self.assertIn("INCIDecoder", labels)
        self.assertIn("EWG Skin Deep", labels)
        self.assertIn("PubMed", labels)


class ProductProfessionTests(unittest.TestCase):
    def _builtin_domains_ctx(self) -> ExitStack:
        from arka.agent.professions import BUILTIN_DOMAINS

        stack = ExitStack()
        stack.enter_context(mock.patch("arka.agent.professions._load_plugins", return_value=None))
        stack.enter_context(mock.patch("arka.agent.professions.all_domains", return_value=BUILTIN_DOMAINS))
        return stack

    def test_detect_product_reviewer_role(self) -> None:
        from arka.agent.professions import invalidate_profession_cache

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
