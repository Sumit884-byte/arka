"""Tests for Gmail draft parsing and creation."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.integrations.google_workspace import (
    _encode_draft_raw,
    _gmail_draft_error_hint,
    _parse_compose_output,
    build_gmail_draft_argv_from_nl,
    compose_draft_email,
    create_gmail_draft,
    parse_gmail_draft_request,
)


class GmailDraftParseTests(unittest.TestCase):
    def test_parse_draft_email_to_about(self) -> None:
        text = (
            "draft an email to contact@wemakedevs.org about i want to claim my "
            "100 aws credits my username at aws builder center is supersumit"
        )
        parsed = parse_gmail_draft_request(text)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["to"], "contact@wemakedevs.org")
        self.assertIn("aws credits", parsed["about"].lower())
        self.assertIn("supersumit", parsed["about"])

    def test_parse_compose_email(self) -> None:
        parsed = parse_gmail_draft_request(
            "compose email to alice@example.com regarding project timeline update"
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["to"], "alice@example.com")
        self.assertIn("project timeline", parsed["about"])

    def test_rejects_inbox_read(self) -> None:
        self.assertIsNone(parse_gmail_draft_request("check my unread gmail"))
        self.assertIsNone(parse_gmail_draft_request("summarize emails from today"))

    def test_build_argv_from_nl(self) -> None:
        argv = build_gmail_draft_argv_from_nl(
            "write email to bob@test.com about meeting next week"
        )
        self.assertEqual(
            argv,
            ["gmail", "--draft", "--to", "bob@test.com", "--about", "meeting next week"],
        )

    def test_parse_send_to_email(self) -> None:
        parsed = parse_gmail_draft_request(
            "send to s21226905@gmail.com happy birthday"
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["to"], "s21226905@gmail.com")
        self.assertEqual(parsed["about"], "happy birthday")

    def test_build_argv_send_to_email(self) -> None:
        argv = build_gmail_draft_argv_from_nl(
            "send to s21226905@gmail.com happy birthday"
        )
        self.assertEqual(
            argv,
            [
                "gmail",
                "--draft",
                "--to",
                "s21226905@gmail.com",
                "--about",
                "happy birthday",
            ],
        )


class GmailDraftComposeTests(unittest.TestCase):
    def test_parse_compose_output(self) -> None:
        raw = "Subject: AWS credits\nBody:\nHi team,\n\nPlease process my credits.\n\nThanks"
        subject, body = _parse_compose_output(raw)
        self.assertEqual(subject, "AWS credits")
        self.assertIn("Please process", body)

    def test_compose_draft_email_mocked(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete") as llm:
            llm.return_value = (
                "Subject: AWS credits claim\nBody:\nHi,\n\nMy Builder Center username is supersumit.\n\nThanks"
            )
            subject, body, composer = compose_draft_email(
                to="contact@wemakedevs.org",
                about="claim 100 AWS credits, username supersumit",
                sender_email="me@example.com",
            )
        self.assertEqual(subject, "AWS credits claim")
        self.assertIn("supersumit", body)
        self.assertIn("/", composer)  # provider/model label
        llm.assert_called_once()

    def test_compose_happy_birthday_uses_template_without_llm(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete") as llm:
            subject, body, composer = compose_draft_email(
                to="s21226905@gmail.com",
                about="happy birthday",
                sender_email="me@example.com",
            )
        llm.assert_not_called()
        self.assertEqual(subject, "Happy Birthday!")
        self.assertIn("happy birthday", body.lower())
        self.assertEqual(composer, "built-in template (no LLM)")

    def test_normalize_truncated_happy_about(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete") as llm:
            subject, body, composer = compose_draft_email(
                to="s21226905@gmail.com",
                about="happy",
                sender_email="me@example.com",
            )
        llm.assert_not_called()
        self.assertEqual(subject, "Happy Birthday!")
        self.assertEqual(composer, "built-in template (no LLM)")

    def test_create_gmail_draft_mocked(self) -> None:
        with mock.patch("arka.integrations.google_workspace.oauth.api_request") as api:
            api.return_value = {"id": "draft-123"}
            draft_id = create_gmail_draft(
                to="contact@wemakedevs.org",
                subject="Test",
                body="Hello",
                sender="me@example.com",
            )
        self.assertEqual(draft_id, "draft-123")
        call = api.call_args
        self.assertEqual(call.kwargs.get("method"), "POST")
        body = call.kwargs.get("body") or {}
        self.assertIn("raw", body.get("message", {}))

    def test_encode_draft_raw_includes_headers(self) -> None:
        raw = _encode_draft_raw(
            to="a@b.com",
            subject="Hi",
            body="Body text",
            sender="me@b.com",
        )
        self.assertTrue(raw)

    def test_create_gmail_draft_403_hint(self) -> None:
        with mock.patch("arka.integrations.google_workspace.oauth.api_request") as api:
            api.side_effect = RuntimeError(
                'Google API HTTP 403: {"error":{"message":"Insufficient Permission"}}'
            )
            with self.assertRaises(RuntimeError) as ctx:
                create_gmail_draft(to="a@b.com", subject="Hi", body="Hello")
        self.assertIn("arka google login", str(ctx.exception))
        self.assertIn(
            "arka google login",
            _gmail_draft_error_hint(RuntimeError("Google API HTTP 403: insufficient scope")),
        )


class GmailDraftRoutingTests(unittest.TestCase):
    def test_fish_route_preview_draft_email(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        cmd = (
            "draft an email to contact@wemakedevs.org about claiming AWS credits, "
            "username supersumit"
        )
        preview = fish_route_preview(cmd)
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertIn("gmail --draft", preview.action)
        self.assertIn("contact@wemakedevs.org", preview.action)

    def test_fish_route_preview_send_to_email(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        preview = fish_route_preview("send to s21226905@gmail.com happy birthday")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertIn("gmail --draft", preview.action)
        self.assertIn("s21226905@gmail.com", preview.action)
        self.assertNotEqual(preview.action.split()[0], "web_answer")


if __name__ == "__main__":
    unittest.main()
