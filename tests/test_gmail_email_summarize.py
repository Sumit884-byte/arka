"""Tests for single-email Gmail summarize."""

from __future__ import annotations

import argparse
import io
import unittest
from unittest import mock

from arka.integrations import google_oauth as oauth
from arka.integrations.gmail_email_summarize import (
    build_gmail_email_summarize_argv_from_nl,
    cmd_gmail_email_summarize,
    is_single_email_summarize_request,
    parse_single_email_summarize_request,
    resolve_single_gmail_row,
    summarize_single_gmail_row,
)
from arka.integrations.gmail_unified import is_unified_inbox_request
from arka.routing.symbolic import route_gmail_email_summarize, route_unified_inbox


class GmailEmailSummarizeParseTests(unittest.TestCase):
    def test_detect_single_email_phrases(self) -> None:
        self.assertTrue(is_single_email_summarize_request("summarize this email"))
        self.assertTrue(is_single_email_summarize_request("summarize my latest email"))
        self.assertTrue(is_single_email_summarize_request("what does this email say"))
        self.assertTrue(
            is_single_email_summarize_request("summarize email from john about the project")
        )
        self.assertFalse(is_single_email_summarize_request("summarize unread emails"))
        self.assertFalse(is_single_email_summarize_request("summarize unread emails within 2 days"))

    def test_single_email_not_unified_inbox(self) -> None:
        self.assertFalse(is_unified_inbox_request("summarize my latest email"))

    def test_parse_latest(self) -> None:
        parsed = parse_single_email_summarize_request("summarize my latest email")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("latest"), "1")

    def test_parse_latest_unread(self) -> None:
        parsed = parse_single_email_summarize_request("summarize my latest unread email")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("latest_unread"), "1")

    def test_parse_from_and_about(self) -> None:
        parsed = parse_single_email_summarize_request(
            "summarize email from john about the project timeline"
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("john", parsed.get("from", "").lower())
        self.assertIn("project timeline", parsed.get("about", "").lower())

    def test_build_argv_latest(self) -> None:
        argv = build_gmail_email_summarize_argv_from_nl("summarize this email")
        self.assertEqual(argv, ["summarize", "--latest"])

    def test_build_argv_search(self) -> None:
        argv = build_gmail_email_summarize_argv_from_nl(
            "summarize email from alice@example.com about invoice"
        )
        self.assertEqual(argv[0], "summarize")
        self.assertIn("--from", argv)
        self.assertIn("alice@example.com", argv)
        self.assertIn("--about", argv)
        self.assertIn("invoice", argv)

    def test_route_gmail_email_summarize(self) -> None:
        routed = route_gmail_email_summarize("what does this email say")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertIn("google summarize", routed)
        self.assertIn("--latest", routed)

    def test_route_unified_inbox_still_batch(self) -> None:
        routed = route_unified_inbox("summarize unread emails across all google accounts")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertIn("google inbox", routed)


class GmailEmailSummarizeResolveTests(unittest.TestCase):
    def test_resolve_latest_across_accounts(self) -> None:
        args = argparse.Namespace(
            message_id=None,
            thread=None,
            latest=True,
            latest_unread=False,
            sender=None,
            about=None,
            query=None,
            account=None,
        )

        def fake_list(query: str, *, max_results: int) -> tuple[list[str], int | None]:
            if oauth._account_override.get() == "personal":
                return ["m-old"], 1
            return ["m-new"], 1

        def fake_row(mid: str, *, include_body: bool = False) -> dict:
            rows = {
                "m-old": {
                    "id": mid,
                    "subject": "Old",
                    "sender": "old@example.com",
                    "date": "Mon, 1 Jan 2024 10:00:00 +0000",
                    "unread": False,
                    "snippet": "old",
                    "body": "old body",
                },
                "m-new": {
                    "id": mid,
                    "subject": "New",
                    "sender": "new@example.com",
                    "date": "Tue, 2 Jan 2024 10:00:00 +0000",
                    "unread": True,
                    "snippet": "new",
                    "body": "new body",
                },
            }
            return rows[mid]

        linked = [
            {"key": "personal", "email": "personal@gmail.com", "alias": "", "legacy": True, "path": "/p"},
            {"key": "student", "email": "student@school.edu", "alias": "student", "legacy": False, "path": "/s"},
        ]

        with (
            mock.patch("arka.integrations.gmail_email_summarize.oauth.resolve_account_keys", return_value=["personal", "student"]),
            mock.patch("arka.integrations.gmail_email_summarize.oauth.list_linked_accounts", return_value=linked),
            mock.patch("arka.integrations.gmail_email_summarize._list_gmail_message_ids", side_effect=fake_list),
            mock.patch("arka.integrations.gmail_email_summarize._gmail_fetch_row", side_effect=fake_row),
        ):
            row = resolve_single_gmail_row(args)

        self.assertEqual(row["subject"], "New")
        self.assertIn("student", str(row.get("account") or "").lower())

    def test_resolve_by_message_id(self) -> None:
        args = argparse.Namespace(
            message_id="abc123def456",
            thread=None,
            latest=False,
            latest_unread=False,
            sender=None,
            about=None,
            query=None,
            account=None,
        )

        with (
            mock.patch("arka.integrations.gmail_email_summarize.oauth.resolve_account_keys", return_value=["personal"]),
            mock.patch(
                "arka.integrations.gmail_email_summarize._gmail_fetch_row",
                return_value={
                    "id": "abc123def456",
                    "subject": "Hello",
                    "sender": "a@b.com",
                    "date": "Mon, 1 Jan 2024 10:00:00 +0000",
                    "unread": True,
                    "snippet": "hi",
                    "body": "full body",
                },
            ),
            mock.patch("arka.integrations.gmail_email_summarize.oauth.using_account"),
            mock.patch("arka.integrations.gmail_email_summarize._account_label", return_value="personal@gmail.com"),
        ):
            row = resolve_single_gmail_row(args)

        self.assertEqual(row["id"], "abc123def456")
        self.assertEqual(row["body"], "full body")


class GmailEmailSummarizeCommandTests(unittest.TestCase):
    def test_summarize_single_email_mocked(self) -> None:
        args = argparse.Namespace(
            message_id=None,
            thread=None,
            latest=True,
            latest_unread=False,
            sender=None,
            about=None,
            query=None,
            account=None,
            focus="",
        )
        row = {
            "subject": "Project update",
            "sender": "john@example.com",
            "date": "Mon, 1 Jan 2024 10:00:00 +0000",
            "account": "personal@gmail.com",
            "body": "We need your review by Friday.",
        }
        with (
            mock.patch("arka.integrations.gmail_email_summarize.resolve_single_gmail_row", return_value=row),
            mock.patch("arka.integrations.gmail_email_summarize.summarize_single_gmail_row", return_value="### Summary\nReview needed by Friday."),
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            code = cmd_gmail_email_summarize(args)
        self.assertEqual(code, 0)
        self.assertIn("Email summary", out.getvalue())
        self.assertIn("Project update", out.getvalue())

    def test_summarize_single_gmail_row_calls_llm(self) -> None:
        row = {
            "subject": "Invoice",
            "sender": "billing@example.com",
            "date": "Mon, 1 Jan 2024 10:00:00 +0000",
            "account": "me@example.com",
            "body": "Amount due: $42",
        }
        with mock.patch("arka.llm.cli.llm_complete", return_value="### Summary\nPay $42.") as llm:
            summary = summarize_single_gmail_row(row)
        self.assertIn("Pay $42", summary)
        llm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
