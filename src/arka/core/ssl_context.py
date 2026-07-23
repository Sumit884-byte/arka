"""SSL context helpers for urllib (macOS / minimal Python installs)."""

from __future__ import annotations

import ssl
from functools import lru_cache

from arka.env import env_get

_SSL_VERIFY_KEYS = ("ARKA_SSL_VERIFY", "GITHUB_SSL_VERIFY")
_FALSE = frozenset({"0", "false", "no", "off"})


def ssl_verify_enabled(*, extra_keys: tuple[str, ...] = ()) -> bool:
    """Return False when ARKA_SSL_VERIFY or GITHUB_SSL_VERIFY is disabled."""
    for key in _SSL_VERIFY_KEYS + extra_keys:
        raw = env_get(key, "")
        if raw:
            return raw.strip().lower() not in _FALSE
    return True


@lru_cache(maxsize=1)
def urllib_ssl_context() -> ssl.SSLContext:
    """Build an SSL context for urllib.request.urlopen."""
    if not ssl_verify_enabled():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
