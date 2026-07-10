"""Tests for Supermemory OpenTelemetry helpers."""

from __future__ import annotations

import os
import unittest
from unittest import mock


class SupermemoryObsTests(unittest.TestCase):
    def test_supermemory_api_attrs(self) -> None:
        from arka.telemetry.supermemory_obs import supermemory_api_attrs

        attrs = supermemory_api_attrs("POST", "/v4/profile", container="arka")
        self.assertEqual(attrs["http.method"], "POST")
        self.assertIn("api.supermemory.ai", attrs["http.url"])
        self.assertEqual(attrs["arka.supermemory.operation"], "v4.profile")
        self.assertEqual(attrs["arka.supermemory.container"], "arka")

    def test_supermemory_status_lines_without_key(self) -> None:
        from arka.telemetry.supermemory_obs import supermemory_status_lines

        with mock.patch.dict(os.environ, {"MEMORY": "auto"}, clear=False):
            os.environ.pop("SUPERMEMORY_API_KEY", None)
            lines = dict(supermemory_status_lines())
        self.assertIn("supermemory_mode", lines)
        self.assertEqual(lines["supermemory_api_key"], "not_set")
        self.assertIn("supermemory_backend", lines)

    def test_record_supermemory_op_no_crash(self) -> None:
        from arka.telemetry.metrics import record_supermemory_op

        record_supermemory_op(operation="context", backend="local", success=True, hits=1)


if __name__ == "__main__":
    unittest.main()
