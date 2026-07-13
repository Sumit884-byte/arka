#!/usr/bin/env python3
"""Post shortened URL content to X/Twitter — fetch, LLM shorten, publish."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_DEFAULT_WORDS = 40
_MAX_TWEET_CHARS = 280

_POST_TRIGGER = re.compile(
    r"(?i)\b(?:post|share|tweet|publish)\b.*\b(?:on\s+(?:my\s+)?(?:x|twitter)|to\s+(?:my\s+)?(?:x|twitter))\b"
    r"|\b(?:shorten|summarize|trim)\b.*\b(?:linkedin|post|url|article|page|link)\b.*"
    r"(?:\band\s+)?\b(?:post|tweet|share|publish)\b.*\b(?:on\s+)?(?:my\s+)?(?:x|twitter)\b"
    r"|\b(?:post|tweet|share)\s+(?:it|this)\s+(?:on\s+)?(?:my\s+)?(?:x|twitter)\b"
)

_MONITOR_RE = re.compile(r"(?i)\b(?:monitor|watch|track|notify)\b")

_WORD_LIMIT_RE = re.compile(
    r"(?i)(?:<=?\s*(\d+)\s*words?|(?:in|under|within|at most|max(?:imum)?)\s+(\d+)\s*words?"
    r"|(\d+)[- ]words?|for\s+(\d+)\s+words?)"
)

_BIRD_NPM_PKG = "@steipete/bird"
_BIRD_TIMEOUT_GLOBAL = 60
_BIRD_TIMEOUT_NPX = 180
_BIRD_INSTALL_TIMEOUT = 180
_BIRD_STATE_NAME = "bird_install.json"
_BIRD_NPM_PREFIX_NAME = "bird-npm"
_ensure_bird_cached_prefix: list[str] | None = None

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[^\s\"'<>)\]]+", re.I)
_BARE_GITHUB_RE = re.compile(
    r"(?<![/\w])(?:www\.)?github\.com/[\w.-]+/[\w.-]+",
    re.I,
)
_HASHTAG_RE = re.compile(r"(?<!\w)#\w[\w-]*")
_LINKEDIN_HOST_RE = re.compile(r"(?i)linkedin\.com")
_ARKA_WORD_RE = re.compile(r"(?i)\barka\b")

# Known LLM-hallucinated GitHub paths — blocked unless verbatim in source text.
_BLOCKED_GITHUB_PATHS = frozenset(
    {
        "github.com/arkahq/arka",
        "www.github.com/arkahq/arka",
    }
)

_LINK_PREFIX_RE = re.compile(
    r"(?i)\b(?:check it out|read more|learn more|see more|link|repo|repository):\s*"
)


def parse_word_limit(text: str, default: int = _DEFAULT_WORDS) -> int:
    match = _WORD_LIMIT_RE.search(text or "")
    if not match:
        return default
    for group in match.groups():
        if group:
            return max(1, min(int(group), 200))
    return default


def count_words(text: str) -> int:
    return len(re.sub(r"\s+", " ", (text or "").strip()).split())


def truncate_words(text: str, max_words: int) -> str:
    words = re.sub(r"\s+", " ", (text or "").strip()).split()
    if not words or max_words <= 0:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "…"


def extract_urls_from_text(text: str) -> list[str]:
    """Return unique URLs found in *text*, preserving first-seen order."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:!?)\"']")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def normalize_url_key(url: str) -> str:
    """Normalize a URL for set membership checks."""
    url = (url or "").strip().rstrip(".,;:!?)\"']")
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").rstrip("/")
    return f"{parsed.scheme.lower()}://{host}{path}"


def collect_source_urls(source_text: str, page_url: str = "") -> list[str]:
    """Gather every URL from scraped source text plus the page URL itself."""
    seen: set[str] = set()
    urls: list[str] = []
    for raw in [page_url, *extract_urls_from_text(source_text)]:
        raw = (raw or "").strip()
        if not raw:
            continue
        key = normalize_url_key(raw)
        if key and key not in seen:
            seen.add(key)
            urls.append(raw.rstrip(".,;:!?)\"']"))
    return urls


def allowed_url_keys(urls: list[str]) -> set[str]:
    return {normalize_url_key(u) for u in urls if normalize_url_key(u)}


def _find_git_toplevel(start: str | None = None) -> str | None:
    """Return git repo root containing *start*, or None."""
    path = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def git_remote_github_url(cwd: str | None = None) -> str:
    """Symbolic ground truth: ``https://github.com/org/repo`` from ``git remote``."""
    root = _find_git_toplevel(cwd)
    if not root:
        return ""
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=root,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    remote = (proc.stdout or "").strip()
    match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s#?]+)", remote, re.I)
    if not match:
        return ""
    org, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"https://github.com/{org}/{repo}"


def github_path_key(url: str) -> str:
    """Lowercase ``github.com/org/repo`` fragment for blocklist checks."""
    key = normalize_url_key(url).lower()
    match = re.search(r"github\.com/([^/\s#?]+/[^/\s#?]+)", key)
    return f"github.com/{match.group(1)}" if match else ""


def url_in_source_verbatim(url: str, source_text: str) -> bool:
    """True when *url* appears literally in scraped source (symbolic, not fuzzy)."""
    if not url or not source_text:
        return False
    trimmed = url.rstrip(".,;:!?)\"']")
    if trimmed in source_text:
        return True
    return normalize_url_key(trimmed) in allowed_url_keys(extract_urls_from_text(source_text))


def is_blocked_github_url(url: str, source_text: str) -> bool:
    """Reject known-wrong GitHub paths unless they appear verbatim in source."""
    path = github_path_key(url)
    if not path or path not in _BLOCKED_GITHUB_PATHS:
        return False
    return not url_in_source_verbatim(url, source_text)


def strip_all_urls(text: str) -> str:
    """Remove every http(s) and bare github.com/… URL from *text*."""
    if not text:
        return ""

    def _drop_http(match: re.Match[str]) -> str:
        return ""

    cleaned = _URL_RE.sub(_drop_http, text)
    cleaned = _BARE_GITHUB_RE.sub(_drop_http, cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def strip_link_prefixes(text: str) -> str:
    """Remove marketing prefixes left after URL stripping (e.g. 'Check it out:')."""
    if not text:
        return ""
    cleaned = _LINK_PREFIX_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def build_symbolic_allowed_urls(
    source_text: str,
    page_url: str = "",
    *,
    use_git_remote_fallback: bool = True,
) -> tuple[list[str], dict[str, object]]:
    """Gather URLs allowed in output — scrape-only, plus git-remote fallback for Arka posts."""
    urls = collect_source_urls(source_text, page_url)
    meta: dict[str, object] = {
        "from_source": list(urls),
        "from_git_remote": "",
        "blocked": [],
    }

    has_github = bool(github_urls_from_source(urls))
    if use_git_remote_fallback and _ARKA_WORD_RE.search(source_text or "") and not has_github:
        remote = git_remote_github_url()
        if remote and normalize_url_key(remote) not in allowed_url_keys(urls):
            urls.append(remote)
            meta["from_git_remote"] = remote

    kept: list[str] = []
    for url in urls:
        if is_blocked_github_url(url, source_text):
            meta["blocked"].append(url)
            continue
        kept.append(url)
    return kept, meta


def symbolic_verify_urls(
    text: str,
    *,
    source_text: str,
    allowed_urls: list[str],
) -> tuple[str, list[str], list[str]]:
    """Strip all URLs from *text*; return (body, accepted, rejected) for logging."""
    allowed = allowed_url_keys(allowed_urls)
    rejected: list[str] = []
    accepted: list[str] = []
    for url in extract_urls_from_text(text):
        if is_blocked_github_url(url, source_text):
            rejected.append(url)
        elif normalize_url_key(url) in allowed and url_in_source_verbatim(url, source_text):
            accepted.append(url)
        elif normalize_url_key(url) in allowed:
            # Allowed via git-remote fallback even if not verbatim in scrape.
            accepted.append(url)
        else:
            rejected.append(url)

    cleaned = strip_link_prefixes(strip_all_urls(text))
    return cleaned, accepted, rejected


def github_urls_from_source(urls: list[str]) -> list[str]:
    return [u for u in urls if "github.com" in normalize_url_key(u)]


def pick_link_url(source_urls: list[str], page_url: str = "") -> str:
    """Prefer an exact GitHub URL from the scrape; otherwise use the page URL."""
    github = github_urls_from_source(source_urls)
    if github:
        return github[0]
    return (page_url or "").strip()


def strip_urls_not_in_source(text: str, allowed: set[str]) -> str:
    """Remove URLs from *text* that were not present in the scraped source."""
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0).rstrip(".,;:!?)\"']")
        key = normalize_url_key(raw)
        if key not in allowed:
            return ""
        return match.group(0)

    cleaned = _URL_RE.sub(_replace, text)
    cleaned = _BARE_GITHUB_RE.sub(_replace, cleaned)
    return strip_link_prefixes(cleaned)


def source_hashtags(source_text: str) -> set[str]:
    return {tag.lower() for tag in _HASHTAG_RE.findall(source_text or "")}


def strip_hashtags_not_in_source(text: str, source_text: str) -> str:
    """Drop hashtags invented by the LLM; keep only tags that appear in source."""
    allowed = source_hashtags(source_text)

    def _replace(match: re.Match[str]) -> str:
        return match.group(0) if match.group(0).lower() in allowed else ""

    return re.sub(r"\s+", " ", _HASHTAG_RE.sub(_replace, text or "")).strip()


def sanitize_shortened_post(
    text: str,
    *,
    source_text: str,
    allowed_urls: list[str],
    max_words: int,
) -> str:
    """Post-process LLM output: strip ALL URLs, drop invented hashtags, hard-cap words."""
    cleaned, _accepted, _rejected = symbolic_verify_urls(
        (text or "").strip(),
        source_text=source_text,
        allowed_urls=allowed_urls,
    )
    cleaned = strip_hashtags_not_in_source(cleaned, source_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    clipped = truncate_words(cleaned, max_words)
    if clipped.endswith("…"):
        clipped = clipped[:-1].rstrip()
    return clipped


def _meta_content(page_html: str, *names: str) -> str:
    for name in names:
        patterns = (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(name)}["\']',
        )
        for pattern in patterns:
            match = re.search(pattern, page_html, re.I | re.S)
            if match:
                value = html.unescape(match.group(1)).strip()
                if value:
                    return value
    return ""


def _jsonld_text_fields(data: object, out: list[str]) -> None:
    if isinstance(data, dict):
        for key in ("articleBody", "description", "text", "headline", "name"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
        for val in data.values():
            _jsonld_text_fields(val, out)
    elif isinstance(data, list):
        for item in data:
            _jsonld_text_fields(item, out)


def _jsonld_bodies(page_html: str) -> list[str]:
    bodies: list[str] = []
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.I | re.S,
    ):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        _jsonld_text_fields(payload, bodies)
    return bodies


def scrape_linkedin_post(url: str, timeout: int = 12) -> str:
    """Fetch LinkedIn post text via og/meta/JSON-LD before generic scraping."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; arka-chat/1.0; +https://github.com/Sumit884-byte/arka)"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page_html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""

    candidates: list[str] = []
    meta_fields = (
        "og:description",
        "twitter:description",
        "description",
        "og:title",
        "twitter:title",
        "article:description",
    )
    for name in meta_fields:
        value = _meta_content(page_html, name)
        if value:
            value = re.sub(r"\s+", " ", html.unescape(value)).strip()
            if value and count_words(value) >= 8:
                candidates.append(value)

    for body in _jsonld_bodies(page_html):
        body = re.sub(r"\s+", " ", html.unescape(body)).strip()
        if body and count_words(body) >= 8:
            candidates.append(body)

    # Prefer the candidate that contains a GitHub URL (symbolic signal from scrape).
    github_candidates = [c for c in candidates if _GITHUB_URL_RE.search(c)]
    if github_candidates:
        github_candidates.sort(key=lambda t: (count_words(t), len(t)), reverse=True)
        return github_candidates[0]

    if candidates:
        candidates.sort(key=lambda t: (count_words(t), len(t)), reverse=True)
        return candidates[0]

    try:
        from arka.agent.chat import scrape_url
    except ImportError:
        return ""
    return (scrape_url(url, timeout=timeout) or "").strip()


def parse_post_x_request(text: str) -> dict[str, str | int] | None:
    """Parse NL like ``post this https://… on my x`` or shorten-and-post follow-ups."""
    t = (text or "").strip()
    if not t or not _POST_TRIGGER.search(t):
        return None
    if _MONITOR_RE.search(t):
        return None
    url = _url_in_text(t)
    return {
        "url": url or "",
        "words": parse_word_limit(t),
        "raw": t,
    }


def _url_in_text(text: str) -> str | None:
    try:
        from arka.agent.chat import extract_urls
    except ImportError:
        return None
    urls = extract_urls(text)
    return urls[0] if urls else None


def build_post_x_argv_from_nl(text: str) -> list[str]:
    parsed = parse_post_x_request(text)
    if not parsed:
        return []
    argv = ["post"]
    if parsed.get("url"):
        argv.append(str(parsed["url"]))
    words = int(parsed.get("words") or _DEFAULT_WORDS)
    if words != _DEFAULT_WORDS:
        argv.extend(["--words", str(words)])
    if not parsed.get("url"):
        argv.append("--from-session")
    return argv


def _urls_from_session(limit: int = 12) -> list[str]:
    try:
        from arka.agent.chat import extract_urls, load_session
    except ImportError:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for msg in reversed(load_session()):
        if msg.get("role") != "user":
            continue
        for url in extract_urls(str(msg.get("content") or "")):
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                return urls
    return urls


def resolve_source_url(text: str) -> str | None:
    try:
        from arka.agent.chat import extract_urls
    except ImportError:
        extract_urls = None  # type: ignore[assignment]
    if extract_urls:
        urls = extract_urls(text)
        if urls:
            return urls[0]
    for url in _urls_from_session():
        if "linkedin.com" in url.lower():
            return url
    session_urls = _urls_from_session()
    return session_urls[0] if session_urls else None


def fetch_url_text(url: str) -> str:
    url = (url or "").strip()
    if _LINKEDIN_HOST_RE.search(url):
        body = scrape_linkedin_post(url)
        if body and count_words(body) >= 10:
            return body

    try:
        from arka.agent.chat import scrape_url
    except ImportError:
        scrape_url = None  # type: ignore[assignment]
    if scrape_url:
        body = scrape_url(url)
        if body and count_words(body) >= 15:
            return body.strip()
    try:
        from arka.media.summarize import _fetch_text

        return _fetch_text(url).strip()
    except Exception:
        return ""


def shorten_post(
    text: str,
    *,
    max_words: int = _DEFAULT_WORDS,
    source_url: str = "",
    source_urls: list[str] | None = None,
) -> str:
    """LLM-shorten article text to <= max_words, with hard word cap."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""

    urls = source_urls
    if urls is None:
        urls, _meta = build_symbolic_allowed_urls(cleaned, source_url)
    url_lines = "\n".join(f"- {u}" for u in urls) if urls else "- (none found in source)"

    if count_words(cleaned) <= max_words:
        return sanitize_shortened_post(
            cleaned,
            source_text=cleaned,
            allowed_urls=urls,
            max_words=max_words,
        )

    from arka.llm.cli import llm_complete

    system = (
        f"You write concise social posts for X/Twitter. Rewrite the source in at most {max_words} words.\n"
        "CRITICAL RULES:\n"
        f"- Hard limit: {max_words} words total.\n"
        "- Use ONLY facts explicitly stated in the source. Do not invent companies, outcomes, or links.\n"
        "- Do NOT include any URL or web link in your output (links are appended separately).\n"
        "- Do NOT include hashtags unless they appear verbatim in the source text.\n"
        "- Plain text only — no markdown, no 'Thread:', no preamble."
    )
    user = (
        f"Source page URL: {source_url or 'n/a'}\n"
        f"URLs found in source (do NOT output these; for context only):\n{url_lines}\n\n"
        f"Source text:\n{cleaned[:12000]}"
    )
    draft = llm_complete(system, user, temperature=0.2, task="summarize").strip()
    draft = re.sub(r"^[\"']|[\"']$", "", draft)
    sanitized = sanitize_shortened_post(
        draft,
        source_text=cleaned,
        allowed_urls=urls,
        max_words=max_words,
    )
    return sanitized or sanitize_shortened_post(
        truncate_words(cleaned, max_words).rstrip("…"),
        source_text=cleaned,
        allowed_urls=urls,
        max_words=max_words,
    )


def compose_tweet(
    body: str,
    url: str = "",
    *,
    allowed_urls: list[str] | None = None,
    source_text: str = "",
) -> str:
    body = (body or "").strip()
    url = (url or "").strip()
    if allowed_urls is not None:
        allowed = allowed_url_keys(allowed_urls)
        body, _accepted, rejected = symbolic_verify_urls(
            body,
            source_text=source_text,
            allowed_urls=allowed_urls,
        )
        if url:
            if is_blocked_github_url(url, source_text):
                url = ""
            elif normalize_url_key(url) not in allowed:
                url = ""
        if rejected and url:
            # Never append a link when the body still had rejected hallucinations.
            pass
    will_append_url = bool(url and url not in body)
    url_suffix = f" {url}" if will_append_url else ""
    max_body_chars = _MAX_TWEET_CHARS - len(url_suffix)

    if len(body) > max_body_chars:
        if max_body_chars <= 1:
            body = body[:max_body_chars]
        else:
            body = body[: max_body_chars - 1].rstrip() + "…"

    if will_append_url:
        body = body + url_suffix

    if len(body) > _MAX_TWEET_CHARS:
        body = body[: _MAX_TWEET_CHARS - 1].rstrip() + "…"
    return body


def log_symbolic_url_check(
    *,
    allowed_urls: list[str],
    url_meta: dict[str, object],
    body_rejected: list[str],
    link_url: str,
    verify_urls: bool = False,
) -> None:
    """Log which URLs passed symbolic validation (always brief; verbose with --verify-urls)."""
    allowed = allowed_urls or []
    git_remote = str(url_meta.get("from_git_remote") or "")
    blocked = list(url_meta.get("blocked") or [])
    print(
        f"symbolic_urls: allowed={allowed!r} link={link_url!r} rejected={body_rejected!r}",
        file=sys.stderr,
    )
    if verify_urls:
        print(f"symbolic_urls_detail: from_source={url_meta.get('from_source')!r}", file=sys.stderr)
        if git_remote:
            print(f"symbolic_urls_detail: git_remote_fallback={git_remote!r}", file=sys.stderr)
        if blocked:
            print(f"symbolic_urls_detail: blocked={blocked!r}", file=sys.stderr)


def _env_first(*names: str) -> str:
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def twitter_api_credentials() -> dict[str, str] | None:
    api_key = _env_first("TWITTER_API_KEY", "X_API_KEY", "TWITTER_CONSUMER_KEY", "X_CONSUMER_KEY")
    api_secret = _env_first(
        "TWITTER_API_SECRET",
        "X_API_SECRET",
        "TWITTER_CONSUMER_SECRET",
        "X_CONSUMER_SECRET",
    )
    access_token = _env_first("TWITTER_ACCESS_TOKEN", "X_ACCESS_TOKEN")
    access_secret = _env_first(
        "TWITTER_ACCESS_TOKEN_SECRET",
        "X_ACCESS_TOKEN_SECRET",
        "TWITTER_ACCESS_SECRET",
        "X_ACCESS_SECRET",
    )
    if api_key and api_secret and access_token and access_secret:
        return {
            "api_key": api_key,
            "api_secret": api_secret,
            "access_token": access_token,
            "access_secret": access_secret,
        }
    return None


def bird_cookie_credentials() -> dict[str, str] | None:
    auth = _env_first("X_AUTH_TOKEN", "AUTH_TOKEN", "TWITTER_AUTH_TOKEN")
    ct0 = _env_first("X_CT0", "CT0", "TWITTER_CT0")
    if auth and ct0:
        return {"auth_token": auth, "ct0": ct0}
    return None


def x_auth_configured() -> bool:
    """True when Twitter API keys or explicit bird cookie env vars are set."""
    return twitter_api_credentials() is not None or bird_cookie_credentials() is not None


_DRAFT_ONLY_HINT = (
    "Copy and post manually, or set credentials to auto-post:\n"
    "  bird: X_AUTH_TOKEN + X_CT0\n"
    "  API: TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, "
    "TWITTER_ACCESS_TOKEN_SECRET\n"
    "  Then retry with --post to publish automatically."
)

_AUTH_MISSING_HINT = (
    "X/Twitter auth not configured.\n"
    "  bird: X_AUTH_TOKEN + X_CT0\n"
    "  API: TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, "
    "TWITTER_ACCESS_TOKEN_SECRET\n"
    "  Draft shown above — copy and post manually, or set credentials and retry with --post."
)


def _oauth1_signature(
    method: str,
    url: str,
    creds: dict[str, str],
    extra_params: dict[str, str] | None = None,
) -> str:
    oauth_params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    params: dict[str, str] = {}
    if extra_params:
        params.update(extra_params)
    params.update(oauth_params)
    encoded = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(params.items())
    )
    base = "&".join(
        (
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(encoded, safe=""),
        )
    )
    key = (
        f"{urllib.parse.quote(creds['api_secret'], safe='')}"
        f"&{urllib.parse.quote(creds['access_secret'], safe='')}"
    )
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _oauth1_header(method: str, url: str, creds: dict[str, str]) -> str:
    oauth_params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    oauth_params["oauth_signature"] = _oauth1_signature(method, url, creds, oauth_params)
    parts = [
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    ]
    return "OAuth " + ", ".join(parts)


def post_via_api(text: str) -> str:
    creds = twitter_api_credentials()
    if not creds:
        raise RuntimeError("Twitter API credentials not configured")
    url = "https://api.twitter.com/2/tweets"
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": _oauth1_header("POST", url, creds),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Twitter API HTTP {exc.code}: {detail[:400]}") from exc
    tweet_id = (data.get("data") or {}).get("id") or ""
    if not tweet_id:
        raise RuntimeError(f"Unexpected Twitter API response: {data!r}")
    return tweet_id


def _bird_cache_dir() -> Path:
    try:
        from arka.paths import cache_dir

        return cache_dir()
    except ImportError:
        return Path.home() / ".cache" / "arka"


def _bird_state_path() -> Path:
    return _bird_cache_dir() / _BIRD_STATE_NAME


def _bird_local_prefix_dir() -> Path:
    return _bird_cache_dir() / _BIRD_NPM_PREFIX_NAME


def _bird_local_binary() -> Path:
    return _bird_local_prefix_dir() / "node_modules" / ".bin" / "bird"


def bird_node_npm_paths() -> tuple[str, str]:
    """Return (node, npm) executables or raise RuntimeError with install guidance."""
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node and npm:
        return node, npm
    missing = []
    if not node:
        missing.append("node")
    if not npm:
        missing.append("npm")
    raise RuntimeError(
        "Node.js and npm are required for the bird CLI (post_x).\n"
        f"  Missing: {', '.join(missing)}\n"
        "  Install Node.js 18+ from https://nodejs.org/ (includes npm)\n"
        "  Or use Twitter API keys instead: TWITTER_API_KEY, TWITTER_API_SECRET, "
        "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET"
    )


def bird_npm_missing_message() -> str:
    try:
        bird_node_npm_paths()
        return ""
    except RuntimeError as exc:
        return str(exc)


def _load_bird_install_state() -> dict[str, object]:
    path = _bird_state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_bird_install_state(state: dict[str, object]) -> None:
    path = _bird_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def verify_bird_binary(path: str, *, timeout: int = 15) -> bool:
    """True when ``bird --version`` succeeds for *path*."""
    if not path:
        return False
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def bird_version(path: str) -> str:
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0]


def _bird_binary_from_state() -> str:
    state = _load_bird_install_state()
    path = str(state.get("path") or "").strip()
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    local = _bird_local_binary()
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return ""


def _run_npm_install(args: list[str], *, quiet: bool) -> None:
    npm = bird_node_npm_paths()[1]
    cmd = [npm, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_BIRD_INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"npm install timed out after {_BIRD_INSTALL_TIMEOUT}s while installing {_BIRD_NPM_PKG}"
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"npm exited {proc.returncode}")


def install_bird(*, quiet: bool = False) -> str:
    """Install @steipete/bird globally, or locally under Arka cache. Returns bird binary path."""
    bird_node_npm_paths()
    cached = _bird_binary_from_state()
    if cached and verify_bird_binary(cached):
        return cached

    global_path = shutil.which("bird")
    if global_path and verify_bird_binary(global_path):
        _save_bird_install_state(
            {
                "path": global_path,
                "method": "global",
                "version": bird_version(global_path),
            }
        )
        return global_path

    if not quiet:
        print(f"installing bird ({_BIRD_NPM_PKG})…", file=sys.stderr)

    global_error = ""
    try:
        _run_npm_install(["install", "-g", _BIRD_NPM_PKG], quiet=quiet)
        global_path = shutil.which("bird")
        if global_path and verify_bird_binary(global_path):
            _save_bird_install_state(
                {
                    "path": global_path,
                    "method": "global",
                    "version": bird_version(global_path),
                }
            )
            if not quiet:
                print(f"✓ bird installed globally: {global_path}", file=sys.stderr)
            return global_path
    except RuntimeError as exc:
        global_error = str(exc)

    prefix = _bird_local_prefix_dir()
    prefix.mkdir(parents=True, exist_ok=True)
    try:
        _run_npm_install(
            ["install", _BIRD_NPM_PKG, "--prefix", str(prefix)],
            quiet=quiet,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if global_error:
            detail = f"{global_error}\nLocal install also failed: {detail}"
        raise RuntimeError(detail) from exc

    local_path = str(_bird_local_binary())
    if not verify_bird_binary(local_path):
        raise RuntimeError(
            f"bird install finished but verification failed for {local_path}"
            + (f"\nGlobal install error: {global_error}" if global_error else "")
        )

    _save_bird_install_state(
        {
            "path": local_path,
            "method": "local",
            "version": bird_version(local_path),
        }
    )
    if not quiet:
        print(f"✓ bird installed locally: {local_path}", file=sys.stderr)
    return local_path


def bird_exec_prefix() -> list[str] | None:
    """Return argv prefix for bird: BIRD_CLI override, then global ``bird``, then npx."""
    override = os.environ.get("BIRD_CLI", "").strip()
    if override:
        return [override]
    path = shutil.which("bird")
    if path:
        return [path]
    cached = _bird_binary_from_state()
    if cached and verify_bird_binary(cached):
        return [cached]
    if shutil.which("npx"):
        return ["npx", _BIRD_NPM_PKG]
    return None


def ensure_bird_exec_prefix(*, auto_install: bool = True, quiet: bool = False) -> list[str] | None:
    """Resolve bird CLI, auto-installing on first use when Node/npm are available."""
    global _ensure_bird_cached_prefix
    if _ensure_bird_cached_prefix is not None:
        return list(_ensure_bird_cached_prefix)

    override = os.environ.get("BIRD_CLI", "").strip()
    if override:
        _ensure_bird_cached_prefix = [override]
        return list(_ensure_bird_cached_prefix)

    path = shutil.which("bird")
    if path and verify_bird_binary(path):
        _ensure_bird_cached_prefix = [path]
        return list(_ensure_bird_cached_prefix)

    cached = _bird_binary_from_state()
    if cached and verify_bird_binary(cached):
        _ensure_bird_cached_prefix = [cached]
        return list(_ensure_bird_cached_prefix)

    if auto_install and bird_npm_missing_message() == "":
        try:
            installed = install_bird(quiet=quiet)
            _ensure_bird_cached_prefix = [installed]
            return list(_ensure_bird_cached_prefix)
        except RuntimeError:
            pass

    if shutil.which("npx"):
        _ensure_bird_cached_prefix = ["npx", _BIRD_NPM_PKG]
        return list(_ensure_bird_cached_prefix)

    _ensure_bird_cached_prefix = []
    return None


def reset_bird_install_cache() -> None:
    """Clear in-process bird prefix cache (tests)."""
    global _ensure_bird_cached_prefix
    _ensure_bird_cached_prefix = None


def bird_subprocess_timeout(prefix: list[str]) -> int:
    """Longer timeout when falling back to npx (first run may download packages)."""
    if prefix and prefix[0] == "npx":
        return _BIRD_TIMEOUT_NPX
    return _BIRD_TIMEOUT_GLOBAL


def _bird_timeout_help(prefix: list[str], timeout: int) -> str:
    using_npx = bool(prefix and prefix[0] == "npx")
    lines = [
        f"bird CLI timed out after {timeout}s.",
    ]
    if using_npx:
        lines.append(
            "  npx first-run can be slow (npm download). Install globally for faster posts:"
        )
        lines.append(f"    npm install -g {_BIRD_NPM_PKG}")
    else:
        lines.append("  Retry, or install/update bird globally:")
        lines.append(f"    npm install -g {_BIRD_NPM_PKG}")
    lines.extend(
        [
            "  Or set BIRD_CLI=/path/to/bird",
            "  Or use Twitter API keys: TWITTER_API_KEY, TWITTER_API_SECRET, "
            "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET",
        ]
    )
    return "\n".join(lines)


def post_via_bird(text: str) -> str:
    prefix = ensure_bird_exec_prefix()
    if not prefix:
        npm_msg = bird_npm_missing_message()
        if npm_msg:
            raise RuntimeError(npm_msg)
        raise RuntimeError(
            f"bird CLI not found and auto-install failed for {_BIRD_NPM_PKG}.\n"
            "  Retry: post_x install\n"
            "  Or set BIRD_CLI=/path/to/bird"
        )
    env = os.environ.copy()
    cookies = bird_cookie_credentials()
    if cookies:
        env.setdefault("AUTH_TOKEN", cookies["auth_token"])
        env.setdefault("CT0", cookies["ct0"])
    cmd = prefix + ["tweet", text]
    timeout = bird_subprocess_timeout(prefix)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(_bird_timeout_help(prefix, timeout)) from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"bird exited {proc.returncode}")
    out = (proc.stdout or "").strip()
    match = re.search(r"/status/(\d+)", out)
    if match:
        return match.group(1)
    return out or "posted"


def post_tweet(text: str) -> tuple[str, str]:
    """Return (tweet_id_or_status, backend_label). Requires configured credentials."""
    if twitter_api_credentials():
        return post_via_api(text), "twitter_api"
    if bird_cookie_credentials():
        return post_via_bird(text), "bird_cli"
    raise SystemExit(_AUTH_MISSING_HINT)


def post_url_to_x(
    url: str,
    *,
    max_words: int = _DEFAULT_WORDS,
    include_url: bool = True,
    dry_run: bool = False,
    force_post: bool = False,
    verify_urls: bool = False,
) -> tuple[str, str, str]:
    """Fetch URL, shorten, optionally post. Returns (tweet_text, tweet_id, backend)."""
    url = url.strip()
    if not url:
        raise SystemExit("URL required — include a link or run after sharing one in chat")
    print(f"Fetching {url} …", file=sys.stderr)
    article = fetch_url_text(url)
    if not article or count_words(article) < 10:
        raise SystemExit(f"Could not extract readable text from {url}")

    source_urls, url_meta = build_symbolic_allowed_urls(article, url)
    link_url = pick_link_url(source_urls, url) if include_url else ""

    shortened = shorten_post(
        article,
        max_words=max_words,
        source_url=url,
        source_urls=source_urls,
    )
    _clean_body, _accepted, body_rejected = symbolic_verify_urls(
        shortened,
        source_text=article,
        allowed_urls=source_urls,
    )
    tweet = compose_tweet(
        shortened,
        link_url,
        allowed_urls=source_urls,
        source_text=article,
    )
    if not tweet:
        raise SystemExit("Generated post was empty")

    log_symbolic_url_check(
        allowed_urls=source_urls,
        url_meta=url_meta,
        body_rejected=body_rejected,
        link_url=link_url,
        verify_urls=verify_urls,
    )

    print("━━━ Draft ━━━")
    print(tweet)
    print(f"({count_words(shortened)} words before link)", file=sys.stderr)
    if link_url and link_url not in shortened:
        print(f"link: {link_url}", file=sys.stderr)

    if dry_run:
        print("━━━ Dry run — not posted ━━━", file=sys.stderr)
        return tweet, "dry-run", "dry_run"

    if not force_post and not x_auth_configured():
        print("━━━ Draft only — not posted ━━━", file=sys.stderr)
        print(_DRAFT_ONLY_HINT, file=sys.stderr)
        return tweet, "draft", "draft_only"

    tweet_id, backend = post_tweet(tweet)
    return tweet, tweet_id, backend


def cmd_parse(args: argparse.Namespace) -> int:
    argv = build_post_x_argv_from_nl(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    url = (args.url or "").strip()
    max_words = int(args.words or _DEFAULT_WORDS)
    if not url and args.from_session:
        url = resolve_source_url("") or ""
    if not url:
        nl = " ".join(getattr(args, "nl_text", []) or []).strip()
        if nl:
            url = resolve_source_url(nl) or ""
    if not url:
        raise SystemExit(
            "No URL found. Include https://… in your message or share a link in chat first."
        )
    force_post = bool(getattr(args, "force_post", False))
    tweet, tweet_id, backend = post_url_to_x(
        url,
        max_words=max_words,
        include_url=not args.no_url,
        dry_run=bool(args.dry_run),
        force_post=force_post,
        verify_urls=bool(args.verify_urls),
    )
    if args.dry_run or backend == "draft_only":
        return 0
    print("━━━ Posted ━━━")
    print(f"backend: {backend}")
    print(f"id: {tweet_id}")
    print(tweet)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    api = twitter_api_credentials()
    cookies = bird_cookie_credentials()
    npm_msg = bird_npm_missing_message()
    bird = bird_exec_prefix()
    bird_ready = bool(bird) and bird[0] != "npx"
    bird_method = ""
    if bird_ready:
        if os.environ.get("BIRD_CLI", "").strip():
            bird_method = "override"
        elif shutil.which("bird"):
            bird_method = "global"
        else:
            bird_method = str(_load_bird_install_state().get("method") or "cached")
    elif bird and bird[0] == "npx":
        bird_method = "npx"
        if npm_msg == "":
            print("installing bird…", file=sys.stderr)
            ensured = ensure_bird_exec_prefix(auto_install=True, quiet=False)
            if ensured and ensured[0] != "npx":
                bird = ensured
                bird_ready = True
                bird_method = str(_load_bird_install_state().get("method") or "installed")

    print("post_x\tavailable")
    print(f"twitter_api\t{'yes' if api else 'no'}")
    print(f"bird_cli\t{'yes' if bird_ready else ('npx' if bird else 'no')}")
    if bird:
        print(f"bird_invoke\t{' '.join(bird)}")
    if bird_method:
        print(f"bird_method\t{bird_method}")
    state = _load_bird_install_state()
    if state.get("version"):
        print(f"bird_version\t{state['version']}")
    if npm_msg:
        print("node_npm\tmissing")
        print(f"bird_install_hint\t{npm_msg.replace(chr(10), ' ')}")
    else:
        print("node_npm\tyes")
    print(f"bird_cookies\t{'yes' if cookies else 'no'}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    if bird_npm_missing_message():
        raise SystemExit(bird_npm_missing_message())
    try:
        path = install_bird(quiet=bool(args.quiet))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if not args.quiet:
        print("bird_install\tok")
        print(f"bird_path\t{path}")
        version = bird_version(path)
        if version:
            print(f"bird_version\t{version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(description="Fetch URL, shorten, post to X/Twitter")
    sub = parser.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse NL into post_x argv")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(handler=cmd_parse)

    p_post = sub.add_parser("post", help="Fetch URL, shorten, and post")
    p_post.add_argument("url", nargs="?", default="")
    p_post.add_argument("--words", type=int, default=_DEFAULT_WORDS)
    p_post.add_argument("--from-session", action="store_true")
    p_post.add_argument("--no-url", action="store_true", help="Omit source URL from tweet")
    p_post.add_argument(
        "--dry-run",
        action="store_true",
        help="Print draft only; do not post to X/Twitter",
    )
    p_post.add_argument(
        "--post",
        "--send",
        dest="force_post",
        action="store_true",
        help="Attempt to post (requires X/Twitter credentials)",
    )
    p_post.add_argument(
        "--verify-urls",
        action="store_true",
        help="Log symbolic URL validation details to stderr",
    )
    p_post.add_argument("nl_text", nargs="*", help=argparse.SUPPRESS)
    p_post.set_defaults(handler=cmd_post)

    p_status = sub.add_parser("status", help="Show auth/backend status")
    p_status.set_defaults(handler=cmd_status)

    p_install = sub.add_parser("install", help="Install @steipete/bird CLI (Node.js/npm)")
    p_install.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Less output when already installed",
    )
    p_install.set_defaults(handler=cmd_install)

    if raw and raw[0] in ("-h", "--help", "help"):
        parser.print_help()
        return 0

    if raw and raw[0] == "parse":
        return cmd_parse(argparse.Namespace(text=raw[1:]))
    if raw and raw[0] == "status":
        return cmd_status(argparse.Namespace())
    if raw and raw[0] == "install":
        quiet = "--quiet" in raw or "-q" in raw
        return cmd_install(argparse.Namespace(quiet=quiet))

    # Default: treat argv as post command (URL or NL via fish)
    ns = argparse.Namespace(
        url=raw[0] if raw and raw[0].startswith("http") else "",
        words=_DEFAULT_WORDS,
        from_session="--from-session" in raw,
        no_url="--no-url" in raw,
        dry_run="--dry-run" in raw,
        force_post="--post" in raw or "--send" in raw,
        verify_urls="--verify-urls" in raw,
        nl_text=[a for a in raw if not a.startswith("-") and not a.startswith("http")],
    )
    for i, tok in enumerate(raw):
        if tok == "--words" and i + 1 < len(raw):
            try:
                ns.words = int(raw[i + 1])
            except ValueError:
                pass
        if tok.startswith("http"):
            ns.url = tok
    if ns.url or ns.from_session or ns.nl_text:
        return cmd_post(ns)

    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    raise SystemExit(main())
