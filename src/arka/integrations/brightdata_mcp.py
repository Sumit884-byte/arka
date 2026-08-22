"""Bright Data MCP — web search and scraping for real-world questions in Arka."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

BRIGHTDATA_MCP_SERVER_KEY = "brightdata"
BRIGHTDATA_MCP_ALIASES = frozenset({
    "brightdata",
    "bright data",
    "bright-data",
    "bright_data",
})
BRIGHTDATA_MCP_BASE_URL = "https://mcp.brightdata.com/mcp"
BRIGHTDATA_ENV_VARS = (
    "BRIGHTDATA_API_TOKEN",
    "BRIGHT_DATA_API_KEY",
    "BRIGHTDATA_TOKEN",
    "BRIGHT_DATA_API_TOKEN",
)
BRIGHTDATA_SEARCH_TOOL = "search_engine"
_UNTRUSTED_BLOCK_RE = re.compile(
    r"=====UNTRUSTED_[a-f0-9]+_BEGIN=====\s*(.*?)\s*=====UNTRUSTED_[a-f0-9]+_END=====",
    re.DOTALL,
)
_SETUP_HINT = (
    "Bright Data MCP powers real-world web search for arka_ask.\n"
    "  BRIGHTDATA_API_TOKEN=...   # https://brightdata.com/cp/setting/users\n"
    "  Optional: ARKA_WEB_SEARCH=brightdata|duckduckgo|auto (default auto)"
)


def brightdata_api_token() -> str:
    from arka.paths import load_env_file

    load_env_file()
    for name in BRIGHTDATA_ENV_VARS:
        token = os.environ.get(name, "").strip()
        if token:
            return token
    return ""


def brightdata_configured() -> bool:
    return bool(brightdata_api_token())


def brightdata_mcp_url() -> str:
    token = brightdata_api_token()
    if not token:
        return ""
    return f"{BRIGHTDATA_MCP_BASE_URL}?token={token}"


def brightdata_mcp_launch_spec() -> dict[str, Any]:
    return {
        "url": f"{BRIGHTDATA_MCP_BASE_URL}?token=${{env:BRIGHTDATA_API_TOKEN}}",
    }


def ensure_brightdata_in_config() -> bool:
    """Add Bright Data MCP entry to mcp.json if missing."""
    from arka.integrations.mcp_manager import load_mcp_config, save_mcp_config

    data = load_mcp_config()
    servers = data.setdefault("mcpServers", {})
    if BRIGHTDATA_MCP_SERVER_KEY in servers:
        return False
    servers[BRIGHTDATA_MCP_SERVER_KEY] = brightdata_mcp_launch_spec()
    save_mcp_config(data)
    return True


def web_search_backend() -> str:
    """Return configured web search backend: auto, brightdata, or duckduckgo."""
    from arka.paths import load_env_file

    load_env_file()
    raw = os.environ.get("ARKA_WEB_SEARCH", "auto").strip().lower()
    if raw in {"brightdata", "bright-data", "bright_data"}:
        return "brightdata"
    if raw in {"duckduckgo", "ddg", "duck"}:
        return "duckduckgo"
    return "auto"


def prefer_brightdata_search() -> bool:
    backend = web_search_backend()
    if backend == "duckduckgo":
        return False
    if backend == "brightdata":
        return True
    return brightdata_configured()


def _extract_untrusted_payload(text: str) -> str:
    match = _UNTRUSTED_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()
    if "SECURITY NOTICE:" in text:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                return stripped
    return text.strip()


def _parse_search_payload(raw: str) -> list[dict[str, str]]:
    payload = _extract_untrusted_payload(raw)
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return _parse_markdown_results(payload)

    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        organic = data.get("organic")
        if isinstance(organic, list):
            rows.extend(organic)
        for key in ("results", "items", "data"):
            extra = data.get(key)
            if isinstance(extra, list):
                rows.extend(extra)
    elif isinstance(data, list):
        rows.extend(data)

    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = str(row.get("link") or row.get("url") or row.get("href") or "").strip()
        if not link:
            continue
        title = str(row.get("title") or row.get("name") or link).strip()
        snippet = str(
            row.get("description")
            or row.get("snippet")
            or row.get("text")
            or row.get("body")
            or ""
        ).strip()
        out.append({"title": title, "link": link, "snippet": snippet})
    return out


def _parse_markdown_results(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("["):
            continue
        match = re.match(r"^\[(?P<title>[^\]]+)\]\((?P<link>[^)]+)\)(?:\s*[-–—]\s*(?P<snippet>.*))?$", stripped)
        if not match:
            continue
        out.append(
            {
                "title": match.group("title").strip(),
                "link": match.group("link").strip(),
                "snippet": (match.group("snippet") or "").strip(),
            }
        )
    return out


def call_brightdata_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """Call a Bright Data MCP tool over HTTP."""
    from arka.integrations.mcp_client import McpHttpClient, _tool_result_text

    url = brightdata_mcp_url()
    if not url:
        raise RuntimeError("Bright Data API token not configured")
    client = McpHttpClient(server=BRIGHTDATA_MCP_SERVER_KEY, url=url, timeout=60.0)
    try:
        client.connect()
        result = client.call_tool(tool_name, dict(arguments or {}))
        return _tool_result_text(result)
    finally:
        client.close()


BRIGHTDATA_SCRAPE_TOOL = "scrape_as_markdown"


def brightdata_scrape_url(url: str, *, max_chars: int = 4000) -> str:
    """Fetch a page as markdown via Bright Data MCP."""
    url = str(url or "").strip()
    if not url or not brightdata_configured():
        return ""
    try:
        raw = call_brightdata_tool(BRIGHTDATA_SCRAPE_TOOL, {"url": url})
    except Exception as exc:
        print(f"Bright Data scrape error: {exc}", file=sys.stderr)
        return ""
    text = _extract_untrusted_payload(raw).strip()
    if not text:
        return ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "…"
    return text


def brightdata_scrape_urls(urls: list[str], *, max_chars: int = 2500) -> dict[str, str]:
    """Scrape multiple URLs; returns {url: markdown} for successful fetches."""
    out: dict[str, str] = {}
    for url in urls:
        url = str(url or "").strip()
        if not url or url in out:
            continue
        text = brightdata_scrape_url(url, max_chars=max_chars)
        if text:
            out[url] = text
    return out


def brightdata_search(
    query: str,
    *,
    max_results: int = 5,
    engine: str = "google",
    geo_location: str = "",
) -> list[dict]:
    """Run Bright Data search_engine and normalize to Arka search result rows."""
    query = str(query or "").strip()
    if not query or not brightdata_configured():
        return []
    args: dict[str, Any] = {"query": query, "engine": engine}
    geo = (geo_location or "").strip().lower()[:2]
    if geo:
        args["geo_location"] = geo
    try:
        raw = call_brightdata_tool(BRIGHTDATA_SEARCH_TOOL, args)
    except Exception as exc:
        print(f"Bright Data search error: {exc}", file=sys.stderr)
        return []
    rows = _parse_search_payload(raw)
    if rows:
        geo_note = f" geo={geo}" if geo else ""
        print(
            f"Bright Data: {len(rows[:max_results])} results for {query!r}{geo_note}",
            file=sys.stderr,
        )
    return rows[: max(1, max_results)]


def setup_brightdata(*, quiet: bool = False) -> dict[str, Any]:
    """Default Bright Data setup for `arka setup`."""
    result: dict[str, Any] = {"mcp_added": False, "configured": False}
    result["mcp_added"] = ensure_brightdata_in_config()
    result["configured"] = brightdata_configured()
    if not quiet:
        if result["mcp_added"]:
            print("  ✓ Bright Data MCP added to mcp.json")
        if result["configured"]:
            print("  ✓ Bright Data token ready (real-world web search via MCP)")
        else:
            print(f"  → Bright Data: set BRIGHTDATA_API_TOKEN in .env\n{_SETUP_HINT}")
    return result


def doctor_checks() -> list[dict[str, Any]]:
    from arka.integrations.mcp_manager import load_mcp_config, mcp_config_path

    data = load_mcp_config()
    servers = data.get("mcpServers") or {}
    in_config = BRIGHTDATA_MCP_SERVER_KEY in servers
    configured = brightdata_configured()
    return [
        {
            "name": "brightdata_mcp_config",
            "ok": in_config,
            "detail": str(mcp_config_path()) if in_config else "run: arka setup",
        },
        {
            "name": "brightdata_credentials",
            "ok": configured,
            "detail": (
                "BRIGHTDATA_API_TOKEN set"
                if configured
                else "set BRIGHTDATA_API_TOKEN in .env"
            ),
        },
    ]


__all__ = [
    "BRIGHTDATA_MCP_SERVER_KEY",
    "BRIGHTDATA_SCRAPE_TOOL",
    "brightdata_api_token",
    "brightdata_configured",
    "brightdata_mcp_launch_spec",
    "brightdata_mcp_url",
    "brightdata_scrape_url",
    "brightdata_scrape_urls",
    "brightdata_search",
    "call_brightdata_tool",
    "doctor_checks",
    "ensure_brightdata_in_config",
    "prefer_brightdata_search",
    "setup_brightdata",
    "web_search_backend",
]
