from arka.integrations.ollama_tunnel import RateLimiter, _extract_tunnel_url, ensure_token


def test_rate_limiter_blocks_after_rpm():
    limiter = RateLimiter(2)
    assert limiter.allow("client-a")
    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")
    assert limiter.allow("client-b")


def test_extract_tunnel_url_cloudflared_line():
    line = "INF | https://random-name.trycloudflare.com"
    assert _extract_tunnel_url(line) == "https://random-name.trycloudflare.com"


def test_ensure_token_generates_without_persist(monkeypatch):
    monkeypatch.delenv("OLLAMA_TUNNEL_TOKEN", raising=False)
    token = ensure_token(persist=False)
    assert len(token) > 16
