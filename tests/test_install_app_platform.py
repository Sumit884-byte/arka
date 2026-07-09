"""Platform-aware install_app / install_brew routing and execution."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.fish_bridge import fish_route_preview
from arka.paths import bundled_dir


def _fish_available() -> bool:
    return shutil.which("fish") is not None


def _bundled_config() -> Path:
    cfg = bundled_dir() / "config.fish"
    if not cfg.is_file():
        raise unittest.SkipTest("bundled config.fish missing")
    return cfg


def _run_fish_skill(
    skill_line: str,
    *,
    platform: str,
    path_prefix: Path | None = None,
    path_only: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cfg = _bundled_config()
    env = os.environ.copy()
    env["INSTALL_HOME"] = str(bundled_dir())
    env["PLATFORM"] = platform
    if path_only is not None:
        env["PATH"] = str(path_only)
    elif path_prefix is not None:
        env["PATH"] = f"{path_prefix}:{env.get('PATH', '')}"
    if env_extra:
        env.update(env_extra)
    inner = f"source {shlex_quote(str(cfg))}; {skill_line}"
    return subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _path_without_brew() -> str:
    parts = os.environ.get("PATH", "").split(":")
    kept = [
        p
        for p in parts
        if p
        and "homebrew" not in p.lower()
        and p not in {"/opt/homebrew/bin", "/usr/local/bin"}
    ]
    return ":".join(kept) or "/usr/bin:/bin:/usr/sbin:/sbin"


def shlex_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


@unittest.skipUnless(_fish_available(), "fish shell not installed")
class InstallAppRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._env = {
            "INSTALL_HOME": str(bundled_dir()),
            "CONFIG_DIR": self._tmpdir,
        }

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _preview(self, query: str, platform: str):
        with mock.patch.dict(os.environ, {**self._env, "PLATFORM": platform}, clear=False):
            return fish_route_preview(query)

    def test_macos_install_fish_routes_to_install_app(self) -> None:
        preview = self._preview("install fish", "macos")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "install_app fish")
        self.assertIn("Homebrew", preview.why)

    def test_macos_install_fish_with_brew_routes_to_install_brew(self) -> None:
        preview = self._preview("install fish with brew", "macos")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "install_brew fish")

    def test_macos_brew_install_syntax_routes_to_install_brew(self) -> None:
        preview = self._preview("brew install fish", "macos")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "install_brew fish")

    def test_linux_install_fish_keeps_linux_stores(self) -> None:
        preview = self._preview("install fish", "linux")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "install_app fish")
        self.assertIn("Flatpak", preview.why)
        self.assertIn("apt", preview.why)


@unittest.skipUnless(_fish_available(), "fish shell not installed")
class InstallAppExecutionTests(unittest.TestCase):
    def test_macos_install_app_delegates_to_brew(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log = tmp / "brew.log"
            brew = tmp / "brew"
            brew.write_text(
                "#!/bin/sh\n"
                'case "$1" in\n'
                "  info) exit 0 ;;\n"
                '  search) echo fish ;;\n'
                f'  install) echo "BREW_INSTALL:$2" >> "{log}" ; exit 0 ;;\n'
                "esac\n"
                "exit 1\n",
                encoding="utf-8",
            )
            brew.chmod(brew.stat().st_mode | stat.S_IXUSR)

            proc = _run_fish_skill("install_app fish", platform="macos", path_prefix=tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertTrue(log.is_file())
            self.assertIn("BREW_INSTALL:fish", log.read_text(encoding="utf-8"))

    def test_macos_install_brew_without_brew_points_to_brew_sh(self) -> None:
        proc = _run_fish_skill(
            "install_brew fish",
            platform="macos",
            env_extra={
                "CONFIG_DIR": tempfile.mkdtemp(),
                "PATH": _path_without_brew(),
            },
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("https://brew.sh", combined)
        self.assertRegex(combined, r"(?i)homebrew is not installed|install homebrew from")


if __name__ == "__main__":
    unittest.main()
