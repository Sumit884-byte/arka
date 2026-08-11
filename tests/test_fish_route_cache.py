"""fish_route_preview cache must not cross-contaminate platforms."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from arka.fish_bridge import _route_preview_cache, fish_route_preview


@pytest.fixture(autouse=True)
def _clear_preview_cache():
    _route_preview_cache.clear()
    yield
    _route_preview_cache.clear()


def test_route_preview_cache_is_platform_scoped():
    try:
        from arka.fish_bridge import _find_fish, fish_config

        if _find_fish() is None or fish_config() is None:
            pytest.skip("fish/config unavailable")
    except ImportError:
        pytest.skip("fish_bridge unavailable")

    base = {
        "CONFIG_DIR": "/tmp/arka-route-cache-test",
        "INSTALL_HOME": os.environ.get("INSTALL_HOME", ""),
    }
    with mock.patch.dict(os.environ, {**base, "PLATFORM": "linux"}, clear=False):
        linux = fish_route_preview("install fish")
    with mock.patch.dict(os.environ, {**base, "PLATFORM": "macos"}, clear=False):
        macos = fish_route_preview("install fish")

    assert linux is not None and macos is not None
    assert "Flatpak" in (linux.why or "")
    assert "Homebrew" in (macos.why or "")
