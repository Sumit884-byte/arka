"""Tests for auto-refetch TTL logic."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from arka.core import auto_refetch as ar


class AutoRefetchTests(unittest.TestCase):
    def test_stamp_stale_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stamp = Path(tmp) / "last-refetch"
            with mock.patch.object(ar, "_stamp_file", return_value=stamp):
                self.assertTrue(ar._stamp_stale(ttl=3600))

    def test_stamp_fresh_within_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stamp = Path(tmp) / "last-refetch"
            stamp.write_text(str(time.time()), encoding="utf-8")
            with mock.patch.object(ar, "_stamp_file", return_value=stamp):
                self.assertFalse(ar._stamp_stale(ttl=3600))

    def test_maybe_auto_refetch_skips_when_fresh(self) -> None:
        with mock.patch.object(ar, "_stamp_stale", return_value=False):
            self.assertFalse(ar.maybe_auto_refetch())

    def test_maybe_auto_refetch_runs_when_behind(self) -> None:
        root = Path("/tmp/arka")
        with mock.patch.object(ar, "_stamp_stale", return_value=True):
            with mock.patch.object(ar, "_touch_stamp"):
                with mock.patch("arka.paths.checkout_root", return_value=root):
                    with mock.patch.object(Path, "is_dir", return_value=True):
                        fetch = mock.Mock(returncode=0, stdout="", stderr="")
                        behind = mock.Mock(returncode=0, stdout="2\n", stderr="")
                        with mock.patch("subprocess.run", side_effect=[fetch, behind]):
                            with mock.patch.object(ar, "_run_refetch", return_value=0) as refetch:
                                self.assertTrue(ar.maybe_auto_refetch(quiet=True))
                                refetch.assert_called_once()

    def test_run_refetch_falls_back_when_ff_only_blocked(self) -> None:
        root = Path("/tmp/arka")
        ff_fail = mock.Mock(returncode=128, stdout="", stderr="fatal: Not possible to fast-forward, aborting.\n")
        merge_ok = mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("arka.paths.checkout_root", return_value=root):
            with mock.patch("arka.core.auto_refetch.subprocess.run", side_effect=[ff_fail, merge_ok]) as run:
                with mock.patch.object(Path, "is_file", autospec=True, return_value=False):
                    rc = ar._run_refetch(quiet=True)
        self.assertEqual(rc, 1)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0], ["git", "pull", "--no-rebase"])


if __name__ == "__main__":
    unittest.main()
