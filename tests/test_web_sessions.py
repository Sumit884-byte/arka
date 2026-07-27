"""Web dashboard session persistence via message_sessions."""

from __future__ import annotations

import os
import tempfile
import unittest


class WebSessionBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["MESSAGE_SESSIONS_DIR"] = self.tmp.name
        os.environ["MESSAGE_SESSIONS"] = "1"
        os.environ["MESSAGE_SESSION_IDLE_MINUTES"] = "0"

    def test_web_channel_push_and_resume(self) -> None:
        from arka.integrations.message_sessions import push, resume_payload

        chat_id = "browser-test-1"
        self.assertEqual(push("web", chat_id, "user", "Hello Arka"), (0, None))
        self.assertEqual(push("web", chat_id, "assistant", "Hi there"), (0, None))
        payload = resume_payload("web", chat_id, limit=10)
        self.assertEqual(payload["channel"], "web")
        self.assertEqual(payload["chat_id"], chat_id)
        texts = [turn["text"] for turn in payload["turns"]]
        self.assertIn("Hello Arka", texts)
        self.assertIn("Hi there", texts)

    def test_bridge_session_helpers(self) -> None:
        from web.bridge import WEB_SESSION_CHANNEL, _sessions_push, _sessions_reset, _sessions_resume

        chat_id = "bridge-test"
        push_result = _sessions_push(WEB_SESSION_CHANNEL, chat_id, "user", "ping")
        self.assertTrue(push_result["ok"])
        resume = _sessions_resume(WEB_SESSION_CHANNEL, chat_id)
        self.assertTrue(resume["ok"])
        self.assertEqual(len(resume["turns"]), 1)
        reset = _sessions_reset(WEB_SESSION_CHANNEL, chat_id)
        self.assertTrue(reset["ok"])
        cleared = _sessions_resume(WEB_SESSION_CHANNEL, chat_id)
        self.assertEqual(cleared.get("turns"), [])
