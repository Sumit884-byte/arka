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


def test_supermemory_local_fallback_on_api_error(tmp_path, monkeypatch):
    import arka.integrations.supermemory as sm

    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY", "auto")
    monkeypatch.setenv("SUPERMEMORY_API_KEY", "test-key")
    monkeypatch.setattr(sm, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(sm, "_api_remember", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 503")))
    result = sm._remember_impl("fallback memory")
    assert result["backend"] == "local"
    assert "api_error" in result


if __name__ == "__main__":
    unittest.main()
