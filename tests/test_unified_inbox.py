"""Tests for unified Gmail inbox across multiple Google accounts."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest import mock

from arka.integrations import google_oauth as oauth
from arka.integrations.gmail_unified import (
    _gmail_dedupe_key,
    build_unified_inbox_argv_from_nl,
    fetch_unified_gmail_rows,
    is_unified_inbox_request,
)
from arka.routing.symbolic import route_unified_inbox


class UnifiedInboxParseTests(unittest.TestCase):
    def test_detect_unified_phrases(self) -> None:
        self.assertTrue(is_unified_inbox_request("unified inbox summary for unread mail"))
        self.assertTrue(is_unified_inbox_request("summarize unread emails across all google accounts"))
        self.assertTrue(is_unified_inbox_request("all my google accounts unread emails"))
        self.assertFalse(is_unified_inbox_request("summarize unread emails"))

    def test_build_argv_defaults(self) -> None:
        argv = build_unified_inbox_argv_from_nl("summarize unread emails across all google accounts")
        self.assertEqual(argv, ["inbox", "--summarize", "--unread", "--all"])

    def test_build_argv_with_days(self) -> None:
        argv = build_unified_inbox_argv_from_nl(
            "summarize unread emails across all google accounts within 3 days"
        )
        self.assertIn("--days", argv)
        self.assertIn("3", argv)
        self.assertIn("--summarize", argv)
        self.assertIn("--unread", argv)

    def test_route_unified_inbox(self) -> None:
        routed = route_unified_inbox("give me a unified inbox summary of unread email")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertIn("google inbox", routed)
        self.assertIn("--summarize", routed)


class UnifiedInboxDedupeTests(unittest.TestCase):
    def test_dedupe_same_message_shape(self) -> None:
        row_a = {
            "subject": "Hello World",
            "sender": "Alice <alice@example.com>",
            "date": "Mon, 1 Jan 2024 10:00:00 +0000",
        }
        row_b = {
            "subject": "hello   world",
            "sender": "alice@example.com",
            "date": "Mon, 1 Jan 2024 10:00:00 +0000",
        }
        self.assertEqual(_gmail_dedupe_key(row_a), _gmail_dedupe_key(row_b))


class UnifiedInboxFetchTests(unittest.TestCase):
    def test_fetch_merges_accounts(self) -> None:
        args = argparse.Namespace(
            unread=True,
            today=False,
            days=0,
            hours=0,
            rolling=False,
            query=None,
            all=True,
            limit=10,
            summarize=False,
            snippet=False,
        )

        def fake_list(query: str, *, max_results: int) -> tuple[list[str], int | None]:
            if oauth._account_override.get() == "personal":
                return ["m1", "m2"], 2
            return ["m3"], 1

        def fake_row(mid: str, *, include_body: bool = False) -> dict:
            account = oauth._account_override.get() or "unknown"
            return {
                "id": mid,
                "subject": f"Subject {mid}",
                "sender": f"{account}@example.com",
                "date": "Mon, 1 Jan 2024 10:00:00 +0000",
                "unread": True,
                "snippet": "hi",
            }

        linked = [
            {"key": "personal", "email": "personal@gmail.com", "alias": "", "legacy": True, "path": "/p"},
            {"key": "student", "email": "student@school.edu", "alias": "student", "legacy": False, "path": "/s"},
        ]

        with (
            mock.patch("arka.integrations.gmail_unified.oauth.resolve_account_keys", return_value=["personal", "student"]),
            mock.patch("arka.integrations.gmail_unified.oauth.list_linked_accounts", return_value=linked),
            mock.patch("arka.integrations.gmail_unified._list_gmail_message_ids", side_effect=fake_list),
            mock.patch("arka.integrations.gmail_unified._gmail_fetch_row", side_effect=fake_row),
        ):
            rows, accounts, _query, _range, total_unread, errors = fetch_unified_gmail_rows(args)

        self.assertEqual(len(rows), 3)
        self.assertEqual(total_unread, 3)
        self.assertEqual(len(accounts), 2)
        self.assertEqual(errors, [])


class GoogleOAuthAccountsTests(unittest.TestCase):
    def test_list_linked_accounts_legacy_and_named(self) -> None:
        legacy_path = Path("/tmp/arka-test-cache/google_oauth.json")
        student_path = Path("/tmp/arka-test-cache/google_accounts/student.json")

        def fake_read(path: Path):
            if path == legacy_path:
                return {"email": "personal@gmail.com", "refresh_token": "r1"}
            if path == student_path:
                return {
                    "email": "student@school.edu",
                    "account_alias": "student",
                    "refresh_token": "r2",
                }
            return None

        accounts_dir = mock.Mock()
        accounts_dir.glob.return_value = [student_path]

        with (
            mock.patch.object(oauth, "_read_token_file", side_effect=fake_read),
            mock.patch.object(oauth, "_legacy_token_file", return_value=legacy_path),
            mock.patch.object(oauth, "_accounts_dir", return_value=accounts_dir),
        ):
            rows = oauth.list_linked_accounts()

        self.assertEqual(len(rows), 2)
        emails = {row["email"] for row in rows}
        self.assertIn("personal@gmail.com", emails)
        self.assertIn("student@school.edu", emails)

    def test_resolve_account_keys_filters_env(self) -> None:
        linked = [
            {"key": "personal@gmail.com", "email": "personal@gmail.com", "alias": "", "legacy": True, "path": "/p"},
            {"key": "student", "email": "student@school.edu", "alias": "student", "legacy": False, "path": "/s"},
        ]
        with (
            mock.patch.object(oauth, "list_linked_accounts", return_value=linked),
            mock.patch.object(oauth, "_getenv", return_value="student@school.edu"),
        ):
            keys = oauth.resolve_account_keys()
        self.assertEqual(keys, ["student"])


if __name__ == "__main__":
    unittest.main()
