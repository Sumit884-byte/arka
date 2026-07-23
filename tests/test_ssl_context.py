"""Tests for urllib SSL context helper."""

from __future__ import annotations

import ssl


def test_urllib_ssl_context_uses_certifi_when_enabled(monkeypatch):
    from arka.core import ssl_context as sc

    sc.urllib_ssl_context.cache_clear()
    monkeypatch.delenv("ARKA_SSL_VERIFY", raising=False)
    monkeypatch.delenv("GITHUB_SSL_VERIFY", raising=False)

    ctx = sc.urllib_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode != ssl.CERT_NONE

    import certifi

    assert ctx.get_ca_certs() or certifi.where()


def test_urllib_ssl_context_respects_disable_flag(monkeypatch):
    from arka.core import ssl_context as sc

    sc.urllib_ssl_context.cache_clear()
    monkeypatch.setenv("GITHUB_SSL_VERIFY", "0")

    ctx = sc.urllib_ssl_context()
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False
