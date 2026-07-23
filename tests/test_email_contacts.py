"""Tests for named email contacts and draft history."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.integrations import email_contacts as ec


class EmailContactsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.contacts = self.root / "email_contacts.json"
        self.history = self.root / "email_draft_history.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch_paths(self) -> mock._patch:
        def contacts_path() -> Path:
            self.contacts.parent.mkdir(parents=True, exist_ok=True)
            return self.contacts

        def history_path() -> Path:
            self.history.parent.mkdir(parents=True, exist_ok=True)
            return self.history

        return mock.patch.multiple(
            ec,
            _contacts_path=contacts_path,
            _history_path=history_path,
        )

    def test_add_and_resolve_contact(self) -> None:
        with self._patch_paths():
            row = ec.add_contact("ceo", "ceo@company.com", display="Jane CEO")
            self.assertEqual(row["email"], "ceo@company.com")
            self.assertEqual(ec.resolve_contact("ceo"), "ceo@company.com")
            self.assertEqual(ec.resolve_contact("CEO"), "ceo@company.com")
            self.assertIsNone(ec.resolve_contact("painter"))

    def test_update_existing_contact(self) -> None:
        with self._patch_paths():
            ec.add_contact("painter", "old@paint.co")
            ec.add_contact("painter", "new@paint.co")
            self.assertEqual(ec.resolve_contact("painter"), "new@paint.co")
            self.assertEqual(len(ec.list_contacts()), 1)

    def test_parse_contact_remember_request(self) -> None:
        parsed = ec.parse_contact_remember_request("ceo's email is boss@corp.com")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["name"], "ceo")
        self.assertEqual(parsed["email"], "boss@corp.com")

        parsed2 = ec.parse_contact_remember_request("remember painter email is bob@paint.co")
        self.assertIsNotNone(parsed2)
        assert parsed2 is not None
        self.assertEqual(parsed2["name"], "painter")

    def test_route_command(self) -> None:
        self.assertEqual(
            ec.route_command("remember ceo email is ceo@company.com"),
            "email_contacts add ceo ceo@company.com",
        )
        self.assertEqual(ec.route_command("list my email contacts"), "email_contacts list")

    def test_record_and_find_similar_draft(self) -> None:
        with self._patch_paths():
            ec.record_draft_history(
                to="ceo@company.com",
                subject="Happy Birthday!",
                about="happy birthday",
                body="Wishing you a great day",
                contact_name="ceo",
            )
            hit = ec.find_similar_draft(to="ceo@company.com", about="happy birthday")
            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertEqual(hit["contact_name"], "ceo")
            miss = ec.find_similar_draft(to="ceo@company.com", about="quarterly report")
            self.assertIsNone(miss)

    def test_compose_history_context(self) -> None:
        with self._patch_paths():
            ec.record_draft_history(
                to="ceo@company.com",
                subject="Project update",
                about="project timeline",
                body="Here is the latest timeline for phase two.",
                contact_name="ceo",
            )
            ctx = ec.compose_history_context(to="ceo@company.com", about="project timeline")
            self.assertIn("project timeline", ctx)
            self.assertIn("avoid repeating", ctx.lower())


class GmailDraftContactParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.contacts = self.root / "email_contacts.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_draft_with_contact_alias(self) -> None:
        self.contacts.write_text(
            '[{"name": "ceo", "email": "ceo@company.com", "display": "CEO", "updated": "2026-01-01T00:00:00+00:00"}]',
            encoding="utf-8",
        )

        def contacts_path() -> Path:
            return self.contacts

        with mock.patch.object(ec, "_contacts_path", contacts_path):
            from arka.integrations.google_workspace import (
                build_gmail_draft_argv_from_nl,
                parse_gmail_draft_request,
            )

            parsed = parse_gmail_draft_request("send to ceo happy birthday")
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed["to"], "ceo@company.com")
            self.assertEqual(parsed["about"], "happy birthday")
            self.assertEqual(parsed.get("contact_name"), "ceo")

            argv = build_gmail_draft_argv_from_nl("email ceo about project timeline update")
            self.assertEqual(
                argv,
                [
                    "gmail",
                    "--draft",
                    "--to",
                    "ceo@company.com",
                    "--about",
                    "project timeline update",
                ],
            )


if __name__ == "__main__":
    unittest.main()
