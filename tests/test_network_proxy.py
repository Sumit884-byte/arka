"""Tests for outbound proxy and VPN helpers."""

from __future__ import annotations

import json
import os
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from arka.core import network_proxy as np
from arka.env import load_env


class NetworkProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        for key in (
            "PROXY",
            "PROXY_ENABLED",
            "PROXY_LIST",
            "PROXY_LIST_FILE",
            "PROXY_ROTATION",
            "PROXY_ROTATE_ON_FAIL",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
            "VPN_PROXY",
            "VPN_INTERFACE",
        ):
            os.environ.pop(key, None)

    def test_apply_proxy_from_single_proxy_var(self) -> None:
        os.environ["PROXY"] = "http://127.0.0.1:7890"
        applied = np.apply_proxy_env()
        self.assertEqual(os.environ["HTTP_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(os.environ["http_proxy"], "http://127.0.0.1:7890")
        self.assertIn("HTTP_PROXY", applied)

    def test_apply_respects_existing_http_proxy(self) -> None:
        os.environ["HTTP_PROXY"] = "http://corp:8080"
        os.environ["PROXY"] = "http://127.0.0.1:7890"
        np.apply_proxy_env()
        self.assertEqual(os.environ["HTTP_PROXY"], "http://corp:8080")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:7890")

    def test_disabled_skips_apply(self) -> None:
        os.environ["PROXY"] = "http://127.0.0.1:7890"
        os.environ["PROXY_ENABLED"] = "0"
        applied = np.apply_proxy_env()
        self.assertEqual(applied, {})
        self.assertNotIn("HTTP_PROXY", os.environ)

    def test_vpn_proxy_used_when_interface_active(self) -> None:
        os.environ["VPN_PROXY"] = "http://127.0.0.1:1080"
        with mock.patch.object(np, "vpn_active", return_value=True):
            np.apply_proxy_env()
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:1080")

    def test_redact_proxy_url_hides_credentials(self) -> None:
        redacted = np.redact_proxy_url("http://user:secret@proxy.local:8080/path")
        self.assertIn("***@", redacted)
        self.assertNotIn("secret", redacted)

    def test_proxy_enabled_file_toggle(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp)
            with mock.patch.object(np, "config_dir", return_value=cfg):
                np.set_proxy_enabled(False)
                self.assertFalse(np.is_proxy_enabled())
                np.set_proxy_enabled(True)
                self.assertTrue(np.is_proxy_enabled())

    def test_load_env_applies_arka_proxy_alias(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("ARKA_PROXY=http://127.0.0.1:3128\n")
            load_env(env_path)
            self.assertEqual(os.environ.get("PROXY"), "http://127.0.0.1:3128")
            self.assertEqual(os.environ.get("HTTP_PROXY"), "http://127.0.0.1:3128")

    def test_route_command(self) -> None:
        self.assertEqual(np.route_command("check my proxy status"), "proxy status")
        self.assertEqual(np.route_command("test proxy connection"), "proxy test")
        self.assertEqual(np.route_command("turn proxy off"), "proxy off")
        self.assertEqual(np.route_command("rotate proxy"), "proxy rotate")
        self.assertEqual(np.route_command("list my proxies"), "proxy list")

    def test_load_proxy_pool_from_list(self) -> None:
        os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
        pool = np.load_proxy_pool()
        self.assertEqual(pool, ["http://127.0.0.1:7890", "http://127.0.0.1:7891"])

    def test_load_proxy_pool_from_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proxies.txt"
            path.write_text("http://127.0.0.1:7890\n# comment\nhttp://127.0.0.1:7891\n")
            os.environ["PROXY_LIST_FILE"] = str(path)
            pool = np.load_proxy_pool()
        self.assertEqual(pool, ["http://127.0.0.1:7890", "http://127.0.0.1:7891"])

    def test_apply_proxy_from_pool(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with mock.patch.object(np, "cache_dir", return_value=cache):
                os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
                np.save_rotation_state(index=1, pinned=False)
                np.apply_proxy_env()
        self.assertEqual(os.environ["HTTP_PROXY"], "http://127.0.0.1:7891")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:7891")

    def test_rotate_proxy_advances_index(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with mock.patch.object(np, "cache_dir", return_value=cache):
                os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
                np.save_rotation_state(index=0, pinned=False)
                proxy, index = np.rotate_proxy()
        self.assertEqual(index, 1)
        self.assertEqual(proxy, "http://127.0.0.1:7891")
        self.assertEqual(os.environ["HTTP_PROXY"], "http://127.0.0.1:7891")

    def test_pin_proxy_by_index(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with mock.patch.object(np, "cache_dir", return_value=cache):
                os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
                proxy, index = np.pin_proxy("0")
        self.assertEqual(index, 0)
        self.assertEqual(proxy, "http://127.0.0.1:7890")
        self.assertEqual(os.environ["HTTP_PROXY"], "http://127.0.0.1:7890")
        self.assertTrue(np.load_rotation_state()["pinned"])

    def test_rotate_proxy_on_error_when_enabled(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with mock.patch.object(np, "cache_dir", return_value=cache):
                os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
                os.environ["PROXY_ROTATE_ON_FAIL"] = "1"
                np.save_rotation_state(index=0, pinned=False)
                rotated = np.rotate_proxy_on_error()
        self.assertIsNotNone(rotated)
        assert rotated is not None
        self.assertEqual(rotated[1], 1)

    def test_cmd_list_marks_active_proxy(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with mock.patch.object(np, "cache_dir", return_value=cache):
                os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
                np.save_rotation_state(index=1, pinned=False)
                buf = StringIO()
                with mock.patch("sys.stdout", buf):
                    code = np.cmd_list(argparse_namespace())
        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("* [1]", output)
        self.assertIn("[0]", output)

    def test_doctor_lines_show_pool(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with mock.patch.object(np, "cache_dir", return_value=cache):
                os.environ["PROXY_LIST"] = "http://127.0.0.1:7890,http://127.0.0.1:7891"
                np.save_rotation_state(index=0, pinned=False)
                lines = np.doctor_lines()
        self.assertTrue(any("pool:" in line and "2 proxies" in line for line in lines))

    def test_proxy_test_success(self) -> None:
        payload = json.dumps({"ip": "203.0.113.10"}).encode()
        fake_resp = mock.Mock()
        fake_resp.read.return_value = payload
        fake_resp.__enter__ = mock.Mock(return_value=fake_resp)
        fake_resp.__exit__ = mock.Mock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            result = np.proxy_test(url="https://example.test/ip")
        self.assertTrue(result["ok"])
        self.assertEqual(result["ip"], "203.0.113.10")

    def test_doctor_lines_include_proxy_section(self) -> None:
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
        lines = np.doctor_lines()
        self.assertTrue(any(line.strip().startswith("Proxy:") for line in lines))
        self.assertTrue(any("7890" in line for line in lines))

    def test_cmd_status_prints_enabled(self) -> None:
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = np.cmd_status(argparse_namespace())
        self.assertEqual(code, 0)
        self.assertIn("enabled=True", buf.getvalue())

    def test_detect_vpn_interfaces_custom(self) -> None:
        os.environ["VPN_INTERFACE"] = "wg-test0"
        with mock.patch.object(np, "_VPN_IF_RE", np._VPN_IF_RE):
            rows = np.detect_vpn_interfaces()
        self.assertTrue(any(row["name"] == "wg-test0" for row in rows))


def argparse_namespace():
    from argparse import Namespace

    return Namespace()


if __name__ == "__main__":
    unittest.main()
