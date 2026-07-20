from urllib.error import URLError


def test_route_site_summary_requires_whole_site_intent():
    from arka.integrations.site_summary import route_site_summary
    from arka.routing.symbolic import route_offline_extras

    assert route_site_summary("summarize entire site https://example.com") == "site_summary https://example.com"
    assert route_site_summary("summarize website example.com/docs") == "site_summary example.com/docs"
    assert route_site_summary("summarize https://example.com") is None
    assert route_offline_extras("summarize entire site https://example.com").startswith("site_summary ")


def test_summarize_site_crawls_same_site_and_skips_social(monkeypatch):
    from arka.integrations import site_summary

    pages = {
        "https://example.com/": """
          <html><title>Home</title><body>
            <p>Example builds tools for developers. The product helps teams test code quickly. It also documents workflows clearly.</p>
            <a href="/docs">Docs</a>
            <a href="https://x.com/example">X</a>
            <a href="https://other.com/page">Other</a>
          </body></html>
        """,
        "https://example.com/docs": """
          <html><title>Docs</title><body>
            <p>Docs explain installation, configuration, and deployment. They include examples for terminal users. The guide avoids social links.</p>
          </body></html>
        """,
    }
    fetched = []

    def fake_fetch(url, *, timeout):
        fetched.append(url)
        if url not in pages:
            raise URLError("not found")
        return pages[url]

    monkeypatch.setattr(site_summary, "fetch_html", fake_fetch)

    summary = site_summary.summarize_site("https://example.com", max_pages=5, max_depth=1)

    assert fetched == ["https://example.com/", "https://example.com/docs"]
    assert summary.pages_summarized == 2
    assert summary.skipped_social == 1
    assert summary.skipped_offsite == 1
    assert [p.title for p in summary.pages] == ["Home", "Docs"]
    assert "Example builds tools" in summary.overview


def test_summarize_site_does_not_follow_social_even_same_depth(monkeypatch):
    from arka.integrations import site_summary

    fetched = []

    def fake_fetch(url, *, timeout):
        fetched.append(url)
        return """
          <html><title>Home</title><body>
            <p>This site has enough content to summarize. It should not crawl social networks.</p>
            <a href="https://linkedin.com/company/example">LinkedIn</a>
            <a href="https://youtube.com/watch?v=abc">YouTube</a>
          </body></html>
        """

    monkeypatch.setattr(site_summary, "fetch_html", fake_fetch)

    summary = site_summary.summarize_site("https://example.com", max_pages=5, max_depth=2)

    assert fetched == ["https://example.com/"]
    assert summary.skipped_social == 2


def test_render_text_lists_sources(monkeypatch):
    from arka.integrations import site_summary

    monkeypatch.setattr(
        site_summary,
        "fetch_html",
        lambda url, *, timeout: "<html><title>Only</title><body><p>Arka summarizes the whole website. It lists sources. It skips social media.</p></body></html>",
    )

    text = site_summary.render_text(site_summary.summarize_site("example.com", max_pages=1))

    assert "━━━ Site summary ━━━" in text
    assert "Pages summarized: 1" in text
    assert "https://example.com/" in text
