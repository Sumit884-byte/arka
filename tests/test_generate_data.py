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
        self.assertFalse(gd.wants_generate_data("generate an image of a cat"))
        self.assertFalse(gd.wants_generate_data("generate password for wifi"))

    def test_route_command(self) -> None:
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
