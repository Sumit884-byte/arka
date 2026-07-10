"""Tests for generate_data skill."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import generate_data as gd
from arka.router import route
from arka.routing.symbolic import route_generate_data


class GenerateDataTests(unittest.TestCase):
    def test_wants_generate_data(self) -> None:
        self.assertTrue(gd.wants_generate_data("generate 100 users as csv"))
        self.assertTrue(gd.wants_generate_data("create sample json data"))
        self.assertTrue(gd.wants_generate_data("fake emails tsv"))
        self.assertTrue(gd.wants_generate_data("generate real world bank gdp india as csv"))
        self.assertTrue(gd.wants_generate_data("generate 20 pubmed papers on mRNA vaccines as csv"))
        self.assertFalse(gd.wants_generate_data("generate an image of a cat"))
        self.assertFalse(gd.wants_generate_data("generate password for wifi"))

    def test_wants_real_vs_fake(self) -> None:
        self.assertFalse(gd._wants_real_source("generate fake users as csv"))
        self.assertTrue(gd._wants_real_source("generate real GDP data for India"))

    def test_detect_source(self) -> None:
        self.assertEqual(gd._detect_source("generate real world bank gdp india"), "worldbank")
        self.assertEqual(gd._detect_source("generate 20 pubmed papers on cancer"), "pubmed")
        self.assertEqual(
            gd._detect_source("generate data from https://example.com/data.json"),
            "url",
        )

    def test_route_command_synthetic(self) -> None:
        self.assertEqual(
            gd.route_command("generate 100 users as csv"),
            "generate_data users --count 100 --format csv",
        )
        self.assertEqual(
            gd.route_command("generate sample sales data json --rows 50"),
            "generate_data sales --count 50 --format json",
        )
        self.assertEqual(
            gd.route_command("data_gen --schema name,email,age --format json --count 20"),
            "generate_data --count 20 --format json --fields name,email,age",
        )

    def test_route_command_real_world(self) -> None:
        route = gd.route_command("generate real world bank gdp india 2010-2024 as csv")
        self.assertIn("--source worldbank", route)
        self.assertIn("--indicator gdp", route)
        self.assertIn("--country IN", route)
        self.assertIn("--year-from 2010", route)
        self.assertIn("--year-to 2024", route)
        self.assertIn("--format csv", route)

        route = gd.route_command('generate 20 pubmed papers on "mRNA vaccines" as csv')
        self.assertIn("--source pubmed", route)
        self.assertIn("--count 20", route)
        self.assertIn("mRNA vaccines", route)

    def test_route_command_fake_over_real(self) -> None:
        route = gd.route_command("generate fake users as csv")
        self.assertNotIn("--source", route)
        self.assertIn("users", route)

    def test_generate_csv(self) -> None:
        rows = gd.generate_rows(["name", "email", "age"], 3, seed=42)
        text = gd.format_rows(rows, "csv")
        reader = csv.DictReader(io.StringIO(text))
        parsed = list(reader)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(set(parsed[0].keys()), {"name", "email", "age"})

    def test_generate_json(self) -> None:
        rows = gd.generate_rows(["id", "name", "price"], 2, seed=1)
        text = gd.format_rows(rows, "json")
        parsed = json.loads(text)
        self.assertEqual(len(parsed), 2)
        self.assertIn("name", parsed[0])

    def test_generate_tsv(self) -> None:
        rows = gd.generate_rows(["email"], 2, seed=5)
        text = gd.format_rows(rows, "tsv")
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "email")
        self.assertEqual(len(lines), 3)

    def test_fetch_worldbank_rows_mocked(self) -> None:
        wb_data = {"India": {2010: 100.0, 2011: 110.0}}
        with mock.patch("arka.charts.data.fetch_worldbank", return_value=wb_data):
            rows = gd.fetch_worldbank_rows(
                indicator="gdp",
                country="IN",
                year_from=2010,
                year_to=2011,
            )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["country"], "India")
        self.assertEqual(rows[0]["indicator"], "gdp")
        self.assertIn("value", rows[0])

    def test_fetch_pubmed_rows_mocked(self) -> None:
        hits = [
            {
                "pmid": "1",
                "title": "Paper A",
                "journal": "Science",
                "year": "2024",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
            }
        ]
        with mock.patch("arka.agent.generate_data._load_search_pubmed") as load_mock:
            load_mock.return_value = lambda *_a, **_k: hits
            rows = gd.fetch_pubmed_rows("mRNA vaccines", max_rows=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Paper A")

    def test_fetch_url_rows_json_mocked(self) -> None:
        payload = json.dumps([{"name": "bulbasaur", "url": "https://example.com/1"}]).encode()
        fake_resp = mock.MagicMock()
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.headers.get.return_value = "application/json"
        fake_resp.read.return_value = payload
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            rows = gd.fetch_url_rows("https://pokeapi.co/api/v2/pokemon?limit=1")
        self.assertEqual(rows[0]["name"], "bulbasaur")

    def test_cmd_generate_real_source_mocked(self) -> None:
        wb_data = {"India": {2020: 200.0}}
        with mock.patch("arka.charts.data.fetch_worldbank", return_value=wb_data):
            code = gd.main(
                [
                    "--source",
                    "worldbank",
                    "--indicator",
                    "gdp",
                    "--country",
                    "IN",
                    "--format",
                    "json",
                    "--count",
                    "50",
                ]
            )
        self.assertEqual(code, 0)

    def test_cli_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "products.csv"
            code = gd.main([str(out), "--fields", "id,name,price,category", "--count", "5"])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            text = out.read_text(encoding="utf-8")
            self.assertIn("name", text)

    def test_route_symbolic(self) -> None:
        hit = route_generate_data("generate 50 rows of user data as csv")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("generate_data"))

    def test_route_symbolic_real(self) -> None:
        hit = route_generate_data("generate real world bank gdp india as csv")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("--source worldbank", hit)

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("generate fake emails tsv")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "generate_data")

    def test_generate_image_not_data(self) -> None:
        self.assertFalse(gd.wants_generate_data("generate an image of a sunset"))


if __name__ == "__main__":
    unittest.main()
