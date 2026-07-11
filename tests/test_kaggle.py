"""Tests for kaggle skill: parsing, routing, credentials, and mocked downloads."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from arka.integrations.kaggle import (
    credential_status,
    download_dataset,
    format_search_results,
    format_status,
    nl_to_argv,
    route_command,
    sanitize_dataset_slug,
    sanitize_search_query,
    search_datasets,
    wants_kaggle,
)
from arka.routing.symbolic import route_kaggle, route_offline_extras


class KaggleSanitizeTests(unittest.TestCase):
    def test_sanitize_dataset_slug(self) -> None:
        self.assertEqual(sanitize_dataset_slug("heptapod/titanic"), "heptapod/titanic")

    def test_sanitize_dataset_slug_from_url(self) -> None:
        slug = sanitize_dataset_slug("https://www.kaggle.com/datasets/heptapod/titanic")
        self.assertEqual(slug, "heptapod/titanic")

    def test_sanitize_dataset_slug_rejects_shell(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_dataset_slug("foo; rm -rf /")

    def test_sanitize_search_query(self) -> None:
        self.assertEqual(sanitize_search_query("housing prices"), "housing prices")

    def test_sanitize_search_rejects_metacharacters(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_search_query("housing; curl evil")


class KaggleParseTests(unittest.TestCase):
    def test_nl_download_slug(self) -> None:
        self.assertEqual(
            nl_to_argv("download kaggle dataset heptapod/titanic"),
            ["download", "heptapod/titanic"],
        )

    def test_nl_download_with_unzip(self) -> None:
        self.assertEqual(
            nl_to_argv("kaggle download heptapod/titanic and unzip"),
            ["download", "heptapod/titanic", "--unzip"],
        )

    def test_nl_search(self) -> None:
        self.assertEqual(nl_to_argv("kaggle search titanic"), ["search", "titanic"])

    def test_nl_status(self) -> None:
        self.assertEqual(nl_to_argv("kaggle status"), ["status"])

    def test_route_command(self) -> None:
        self.assertEqual(
            route_command("download kaggle dataset heptapod/titanic"),
            "kaggle download heptapod/titanic",
        )

    def test_no_match(self) -> None:
        self.assertEqual(nl_to_argv("what is the weather"), [])

    def test_competitions_not_kaggle(self) -> None:
        self.assertEqual(nl_to_argv("search kaggle competitions"), [])
        self.assertFalse(wants_kaggle("search kaggle competitions"))


class KaggleCredentialTests(unittest.TestCase):
    def test_env_credentials(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"KAGGLE_USERNAME": "alice", "KAGGLE_KEY": "secret"},
            clear=False,
        ):
            cred = credential_status()
        self.assertTrue(cred["configured"])
        self.assertEqual(cred["username"], "alice")
        self.assertEqual(cred["source"], "environment")

    def test_kaggle_json_credentials(self) -> None:
        with mock.patch.dict("os.environ", {"KAGGLE_USERNAME": "", "KAGGLE_KEY": ""}, clear=False):
            with mock.patch.object(Path, "is_file", return_value=True):
                with mock.patch.object(
                    Path,
                    "read_text",
                    return_value=json.dumps({"username": "bob", "key": "token"}),
                ):
                    cred = credential_status()
        self.assertTrue(cred["configured"])
        self.assertEqual(cred["username"], "bob")
        self.assertEqual(cred["source"], "kaggle.json")

    def test_missing_credentials(self) -> None:
        with mock.patch.dict("os.environ", {"KAGGLE_USERNAME": "", "KAGGLE_KEY": ""}, clear=False):
            with mock.patch.object(Path, "is_file", return_value=False):
                cred = credential_status()
        self.assertFalse(cred["configured"])

    def test_format_status_configured(self) -> None:
        with mock.patch(
            "arka.integrations.kaggle.credential_status",
            return_value={
                "configured": True,
                "username": "alice",
                "source": "environment",
                "detail": "KAGGLE_USERNAME + KAGGLE_KEY",
            },
        ):
            with mock.patch("arka.integrations.kaggle.find_kaggle_cli", return_value="/usr/bin/kaggle"):
                text = format_status()
        self.assertIn("Configured: yes", text)
        self.assertIn("alice", text)

    def test_format_status_missing(self) -> None:
        with mock.patch(
            "arka.integrations.kaggle.credential_status",
            return_value={"configured": False, "username": "", "source": "", "detail": ""},
        ):
            with mock.patch("arka.integrations.kaggle.find_kaggle_cli", return_value=None):
                with mock.patch("arka.integrations.kaggle._python_api_available", return_value=False):
                    text = format_status()
        self.assertIn("Configured: no", text)


class KaggleDownloadTests(unittest.TestCase):
    @mock.patch("arka.integrations.kaggle.credential_status")
    @mock.patch("arka.integrations.kaggle.find_kaggle_cli")
    @mock.patch("arka.integrations.kaggle._download_via_cli")
    def test_download_via_cli(
        self,
        download_cli: mock.MagicMock,
        find_cli: mock.MagicMock,
        cred: mock.MagicMock,
    ) -> None:
        cred.return_value = {"configured": True}
        find_cli.return_value = "/usr/bin/kaggle"
        download_cli.return_value = "OK"
        out = Path("/tmp/kaggle-test")
        with mock.patch("arka.integrations.kaggle._ensure_output_dir", return_value=out):
            message = download_dataset("heptapod/titanic", output_dir=out, unzip=False)
        self.assertIn("Saved to:", message)
        download_cli.assert_called_once_with("heptapod/titanic", output_dir=out, unzip=False)

    @mock.patch("arka.integrations.kaggle.credential_status")
    @mock.patch("arka.integrations.kaggle.find_kaggle_cli", return_value=None)
    @mock.patch("arka.integrations.kaggle._python_api_available", return_value=True)
    @mock.patch("arka.integrations.kaggle._download_via_python")
    def test_download_via_python(
        self,
        download_py: mock.MagicMock,
        _py_avail: mock.MagicMock,
        _find_cli: mock.MagicMock,
        cred: mock.MagicMock,
    ) -> None:
        cred.return_value = {"configured": True}
        download_py.return_value = "Downloaded"
        out = Path("/tmp/kaggle-test")
        with mock.patch("arka.integrations.kaggle._ensure_output_dir", return_value=out):
            message = download_dataset("heptapod/titanic", output_dir=out, unzip=True)
        self.assertIn("Saved to:", message)

    def test_download_requires_credentials(self) -> None:
        with mock.patch(
            "arka.integrations.kaggle.credential_status",
            return_value={"configured": False},
        ):
            with self.assertRaises(RuntimeError):
                download_dataset("heptapod/titanic")


class KaggleSearchTests(unittest.TestCase):
    @mock.patch("arka.integrations.kaggle.credential_status")
    @mock.patch("arka.integrations.kaggle.find_kaggle_cli")
    @mock.patch("arka.integrations.kaggle._search_via_cli")
    def test_search_via_cli(
        self,
        search_cli: mock.MagicMock,
        find_cli: mock.MagicMock,
        cred: mock.MagicMock,
    ) -> None:
        cred.return_value = {"configured": True}
        find_cli.return_value = "/usr/bin/kaggle"
        search_cli.return_value = [
            {"ref": "heptapod/titanic", "title": "Titanic", "size": "60KB", "downloads": "1000"}
        ]
        hits = search_datasets("titanic")
        self.assertEqual(hits[0]["ref"], "heptapod/titanic")

    def test_format_search_results_empty(self) -> None:
        text = format_search_results("missing", [])
        self.assertIn("No datasets matched", text)


class KaggleRoutingTests(unittest.TestCase):
    def test_route_kaggle(self) -> None:
        hit = route_kaggle("download kaggle dataset heptapod/titanic")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("kaggle download"))

    def test_route_offline_extras(self) -> None:
        hit = route_offline_extras("kaggle search titanic")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("kaggle", hit)

    def test_weather_not_kaggle(self) -> None:
        self.assertIsNone(route_kaggle("what is the weather today"))


if __name__ == "__main__":
    unittest.main()
