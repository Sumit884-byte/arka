"""Tests for science protocol sources used by Arka flow."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from arka.agent.flow import generate_flow


def _load_protocol_sources():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "arka"
        / "skills"
        / "life_sciences"
        / "protocol_sources.py"
    )
    spec = importlib.util.spec_from_file_location("_protocol_sources_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ps = _load_protocol_sources()


class TestBundledProtocolMatch(unittest.TestCase):
    def test_match_pcr_aliases(self) -> None:
        entry = ps.match_bundled_protocol("run a PCR protocol")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["id"], "pcr")

    def test_match_western_blot(self) -> None:
        entry = ps.match_bundled_protocol("western blot")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["id"], "western_blot")

    def test_no_match_unrelated(self) -> None:
        self.assertIsNone(ps.match_bundled_protocol("install docker"))


class TestProtocolFormatting(unittest.TestCase):
    def test_format_includes_source(self) -> None:
        out = ps.format_protocol_flow(
            title="PCR",
            steps=["Mix reagents on ice.", "Run thermal cycler."],
            source="Arka protocol index",
            materials=["Primers"],
        )
        self.assertIn("## PCR", out)
        self.assertIn("## Materials", out)
        self.assertIn("## Steps", out)
        self.assertIn("1. Mix reagents on ice.", out)
        self.assertIn("*Source: Arka protocol index*", out)


class TestProtocolsIoParser(unittest.TestCase):
    def test_parse_components_format(self) -> None:
        data = {
            "title": "Sample Protocol",
            "doi": "dx.doi.org/10.17504/protocols.io.test",
            "steps": [
                {
                    "components": [
                        {"name": "Description", "data": "Prepare samples on ice."},
                        {"name": "Duration / Timer", "data": "5 min"},
                    ]
                },
                {"components": [{"name": "Description", "data": "Run gel electrophoresis."}]},
            ],
        }
        parsed = ps.parse_protocols_io_json(data)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "Sample Protocol")
        self.assertEqual(len(parsed["steps"]), 2)
        self.assertIn("protocols.io", parsed["source"])


class TestNetworkSources(unittest.TestCase):
    def test_fetch_protocols_io_mirror_mocked(self) -> None:
        payload = {
            "title": "Mirror PCR",
            "steps": [{"components": [{"name": "Description", "data": "Denature at 95C."}]}],
        }
        body = json.dumps(payload).encode("utf-8")

        class FakeResp:
            def read(self) -> bytes:
                return body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("urllib.request.urlopen", return_value=FakeResp()):
            parsed = ps.fetch_protocols_io_mirror("test-pcr.json")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["steps"], ["Denature at 95C."])

    def test_search_pubmed_protocol_mocked(self) -> None:
        search_json = json.dumps({"esearchresult": {"idlist": ["12345"]}}).encode()
        summary_xml = b"""<?xml version="1.0"?>
        <eSummaryResult><DocSum><Id>12345</Id>
        <Item Name="Title">PCR methods paper</Item></DocSum></eSummaryResult>"""
        abstract_xml = b"""<?xml version="1.0"?>
        <PubmedArticleSet><PubmedArticle><MedlineCitation>
        <Article><Abstract><AbstractText>Step one mix. Step two cycle.</AbstractText></Abstract></Article>
        </MedlineCitation></PubmedArticle></PubmedArticleSet>"""

        def fake_urlopen(url, timeout=20):
            url_s = url if isinstance(url, str) else url.full_url
            if "esearch" in url_s:
                return type("R", (), {"read": lambda self: search_json, "__enter__": lambda s: s, "__exit__": lambda *a: False})()
            if "esummary" in url_s:
                return type("R", (), {"read": lambda self: summary_xml, "__enter__": lambda s: s, "__exit__": lambda *a: False})()
            if "efetch" in url_s:
                return type("R", (), {"read": lambda self: abstract_xml, "__enter__": lambda s: s, "__exit__": lambda *a: False})()
            raise AssertionError(url_s)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            hit = ps.search_pubmed_protocol("PCR")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["pmid"], "12345")
        self.assertIn("Step one", hit["abstract"])


class TestFlowBundledIntegration(unittest.TestCase):
    def test_generate_flow_uses_bundled_without_llm(self) -> None:
        with patch("arka.llm.cli.llm_complete") as mock_llm:
            out = generate_flow("PCR protocol")
        mock_llm.assert_not_called()
        self.assertIn("## PCR", out)
        self.assertIn("*Source:", out)
        self.assertIn("thermal cycler", out.lower())

    def test_generate_flow_pubmed_fallback_mocked(self) -> None:
        pubmed_ctx = (
            "PubMed paper: Novel assay\n"
            "URL: https://pubmed.ncbi.nlm.nih.gov/99/\n\n"
            "Abstract:\nMix buffer and enzyme."
        )
        with patch(
            "arka.agent.flow._load_protocol_sources"
        ) as load_mock:
            mod = mock.MagicMock()
            mod.try_science_flow_from_sources.return_value = (pubmed_ctx, "pubmed")
            load_mock.return_value = mod
            with patch("arka.llm.cli.llm_complete", return_value="## Assay\n1. Mix buffer") as mock_llm:
                out = generate_flow("obscure assay xyz123")
        mock_llm.assert_called_once()
        system_prompt = mock_llm.call_args[0][0]
        self.assertIn("PubMed", system_prompt)
        self.assertEqual(out, "## Assay\n1. Mix buffer")


if __name__ == "__main__":
    unittest.main()
