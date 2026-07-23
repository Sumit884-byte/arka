"""Tests for Gmail auto-draft on new inbound mail."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.integrations import gmail_auto_draft as gad


class GmailAutoDraftHelpersTests(unittest.TestCase):
    def test_reply_subject(self) -> None:
        self.assertEqual(gad._reply_subject("Hello"), "Re: Hello")
        self.assertEqual(gad._reply_subject("Re: Hello"), "Re: Hello")

    def test_should_skip_automated_sender(self) -> None:
        self.assertEqual(
            gad._should_skip_sender("No Reply <noreply@service.com>", account_email="me@x.com"),
            "automated sender",
        )
        self.assertIsNone(
            gad._should_skip_sender("Alice <alice@corp.com>", account_email="me@x.com"),
        )
        self.assertEqual(
            gad._should_skip_sender("Me <me@x.com>", account_email="me@x.com"),
            "self-sent",
        )

    def test_route_command(self) -> None:
        self.assertEqual(gad.route_command("enable auto draft for email"), "google auto-draft enable")
        self.assertEqual(gad.route_command("auto draft new emails"), "google auto-draft tick")
        self.assertEqual(
            gad.route_command("auto draft email replies every 5 minutes"),
            'routines add every 5m "google auto-draft tick"',
        )


class GmailAutoDraftTickTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "gmail_auto_draft.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch_state(self) -> mock._patch:
        return mock.patch.object(gad, "_state_path", lambda: self.state_path)

    def test_bootstrap_marks_seen_without_drafting(self) -> None:
        with self._patch_state():
            gad.set_enabled(True)
            with mock.patch("arka.integrations.gmail_auto_draft.oauth.credentials_configured", return_value=True):
                with mock.patch("arka.integrations.gmail_auto_draft.oauth.resolve_account_keys", return_value=["personal"]):
                    with mock.patch("arka.integrations.gmail_auto_draft.oauth.using_account"):
                        with mock.patch(
                            "arka.integrations.gmail_auto_draft.oauth.signed_in_email",
                            return_value="me@example.com",
                        ):
                            with mock.patch(
                                "arka.integrations.gmail_auto_draft._list_gmail_message_ids",
                                return_value=(["m1", "m2"], 2),
                            ):
                                result = gad.auto_draft_tick(force=True)

            self.assertEqual(result["bootstrapped"], ["personal"])
            self.assertEqual(result["drafts"], [])
            state = gad.load_state()
            self.assertTrue(state["accounts"]["personal"]["bootstrapped"])
            self.assertIn("m1", state["accounts"]["personal"]["seen_ids"])

    def test_tick_drafts_new_message(self) -> None:
        with self._patch_state():
            gad.set_enabled(True)
            state = gad.load_state()
            state["accounts"]["personal"] = {
                "seen_ids": [],
                "drafted_ids": [],
                "bootstrapped": True,
            }
            gad.save_state(state)

            row = {
                "id": "m-new",
                "subject": "Project update",
                "sender": "Alice <alice@corp.com>",
                "body": "Can we meet tomorrow?",
                "snippet": "Can we meet tomorrow?",
            }

            with mock.patch("arka.integrations.gmail_auto_draft.oauth.credentials_configured", return_value=True):
                with mock.patch("arka.integrations.gmail_auto_draft.oauth.resolve_account_keys", return_value=["personal"]):
                    with mock.patch("arka.integrations.gmail_auto_draft.oauth.using_account"):
                        with mock.patch(
                            "arka.integrations.gmail_auto_draft.oauth.signed_in_email",
                            return_value="me@example.com",
                        ):
                            with mock.patch(
                                "arka.integrations.gmail_auto_draft._list_gmail_message_ids",
                                return_value=(["m-new"], 1),
                            ):
                                with mock.patch(
                                    "arka.integrations.gmail_auto_draft._gmail_fetch_row",
                                    return_value=row,
                                ):
                                    with mock.patch(
                                        "arka.integrations.email_contacts.find_similar_draft",
                                        return_value=None,
                                    ):
                                        with mock.patch(
                                            "arka.integrations.gmail_auto_draft._compose_inbound_reply",
                                            return_value=("Re: Project update", "Sure, tomorrow works.", "test"),
                                        ):
                                            with mock.patch(
                                                "arka.integrations.gmail_auto_draft.create_gmail_draft",
                                                return_value="draft-1",
                                            ):
                                                with mock.patch(
                                                    "arka.integrations.gmail_auto_draft._notify",
                                                ):
                                                    result = gad.auto_draft_tick(force=True)

            self.assertEqual(len(result["drafts"]), 1)
            self.assertEqual(result["drafts"][0]["to"], "alice@corp.com")
            self.assertEqual(result["drafts"][0]["draft_id"], "draft-1")

    def test_tick_skips_when_disabled(self) -> None:
        with self._patch_state():
            gad.set_enabled(False)
            result = gad.auto_draft_tick()
            self.assertEqual(result.get("skipped"), "disabled")


if __name__ == "__main__":
    unittest.main()
