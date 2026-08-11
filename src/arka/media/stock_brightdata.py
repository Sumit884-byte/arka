"""Bright Data SERP fallback for stock image/video search in compose_video."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REQUEST_ENDPOINT = "https://api.brightdata.com/request"
_USER_AGENT = "arka-compose-video/1.0"

_IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
_VIDEO_EXT = frozenset({".mp4", ".webm", ".mov"})
_SKIP_HOSTS = frozenset(
    {
        "google.com",
        "gstatic.com",
        "googleusercontent.com",
        "bing.com",
        "yandex.com",
        "duckduckgo.com",
    }
)

_IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:jpe?g|png|webp|gif)(?:\?[^\s\"'<>\\]*)?",
    re.IGNORECASE,
)
_VIDEO_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:mp4|webm|mov)(?:\?[^\s\"'<>\\]*)?",
    re.IGNORECASE,
)

_last_request_at = 0.0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def api_token() -> str:
    for name in (
        "BRIGHTDATA_API_TOKEN",
        "BRIGHT_DATA_API_KEY",
        "BRIGHTDATA_TOKEN",
        "BRIGHT_DATA_API_TOKEN",
        "API_TOKEN",
    ):
        val = _env(name)
        if val and not val.lower().startswith("your_"):
            return val
    return ""


def serp_zone() -> str:
    for name in ("BRIGHTDATA_SERP_ZONE", "BRIGHT_DATA_SERP_ZONE", "BRIGHTDATA_ZONE"):
        val = _env(name)
        if val:
            return val
    return "serp_api"


def is_configured() -> bool:
    return bool(api_token())


def fallback_enabled() -> bool:
    raw = _env("VIDEO_STOCK_FALLBACK", "brightdata").lower()
    if raw in {"0", "false", "no", "off", "none", "disabled"}:
        return False
    return is_configured()


def setup_hint() -> str:
    return (
        "Bright Data fallback for stock media search.\n"
        "Set in ~/.config/arka/.env:\n"
        "  BRIGHTDATA_API_TOKEN=...     # from https://brightdata.com/cp/setting/users\n"
        "  BRIGHTDATA_SERP_ZONE=serp_api  # optional SERP zone name\n"
        "  VIDEO_STOCK_FALLBACK=brightdata  # set none to disable fallback"
    )


def _rate_limit() -> None:
    global _last_request_at
    delay = max(0.0, _env_float("BRIGHTDATA_RATE_LIMIT_SEC", 0.5))
    if delay <= 0:
        return
    elapsed = time.monotonic() - _last_request_at
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_request_at = time.monotonic()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _strip_untrusted(text: str) -> str:
    text = re.sub(
        r"SECURITY NOTICE:[\s\S]*?BEGIN=====\n?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"=====UNTRUSTED_[a-f0-9]+_(BEGIN|END)=====\n?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _extract_json(text: str) -> dict | list:
    raw = _strip_untrusted(text)
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, (dict, list)):
            return parsed
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, raw)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Bright Data response was not valid JSON")


def _serp_request(url: str) -> str:
    if not is_configured():
        raise RuntimeError("Bright Data API token not configured")
    _rate_limit()
    payload = {
        "url": url,
        "zone": serp_zone(),
        "format": "raw",
    }
    req = urllib.request.Request(
        REQUEST_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_token()}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Bright Data HTTP {exc.code}: {detail}") from exc


def _host_ok(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    return not any(host == skip or host.endswith(f".{skip}") for skip in _SKIP_HOSTS)


def _normalize_media_url(raw: object) -> str:
    url = str(raw or "").strip()
    if not url.startswith("http"):
        return ""
    if not _host_ok(url):
        return ""
    return url


def _results_list(data: dict | list) -> list[dict]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("images", "organic", "results", "items", "data", "videos"):
            val = data.get(key)
            if isinstance(val, list):
                return [row for row in val if isinstance(row, dict)]
    return []


def _image_rows_from_payload(data: dict | list) -> list[dict]:
    rows: list[dict] = []
    for item in _results_list(data):
        for key in ("original_image", "image", "url", "link", "src", "thumbnail"):
            url = _normalize_media_url(item.get(key))
            if not url:
                continue
            path = urllib.parse.urlparse(url).path.lower()
            if path and not any(path.endswith(ext) for ext in _IMAGE_EXT):
                if key not in {"original_image", "image", "thumbnail"}:
                    continue
            rows.append(
                {
                    "url": url,
                    "title": str(item.get("title") or item.get("alt") or item.get("name") or ""),
                    "width": int(item.get("original_width") or item.get("image_width") or item.get("width") or 0),
                    "height": int(item.get("original_height") or item.get("image_height") or item.get("height") or 0),
                }
            )
            break
    return rows


def _video_rows_from_payload(data: dict | list) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    def add(url: str, title: str = "", duration: float = 0.0) -> None:
        normalized = _normalize_media_url(url)
        if not normalized or normalized in seen:
            return
        path = urllib.parse.urlparse(normalized).path.lower()
        if path and not any(path.endswith(ext) for ext in _VIDEO_EXT):
            return
        seen.add(normalized)
        rows.append({"url": normalized, "title": title, "duration": duration})

    for item in _results_list(data):
        for key in ("url", "link", "video_url", "contentUrl"):
            add(str(item.get(key) or ""), str(item.get("title") or item.get("name") or ""))
        desc = json.dumps(item)
        for match in _VIDEO_URL_RE.findall(desc):
            add(match, str(item.get("title") or ""))

    if isinstance(data, dict):
        blob = json.dumps(data)
        for match in _VIDEO_URL_RE.findall(blob):
            add(match)
    elif isinstance(data, list):
        blob = json.dumps(data)
        for match in _VIDEO_URL_RE.findall(blob):
            add(match)

    return rows


def _regex_image_urls(text: str) -> list[dict]:
    seen: set[str] = set()
    rows: list[dict] = []
    for match in _IMAGE_URL_RE.findall(text):
        url = _normalize_media_url(match)
        if url and url not in seen:
            seen.add(url)
            rows.append({"url": url, "title": "", "width": 0, "height": 0})
    return rows


def _google_images_url(query: str) -> str:
    params = urllib.parse.urlencode({"q": query, "udm": "2", "brd_json": "1"})
    return f"https://www.google.com/search?{params}"


def _google_video_url(query: str) -> str:
    q = f"{query} stock video free download"
    params = urllib.parse.urlencode({"q": q, "tbm": "vid", "brd_json": "1"})
    return f"https://www.google.com/search?{params}"


def _google_stock_video_url(query: str) -> str:
    q = f"{query} site:pexels.com/video OR site:pixabay.com/videos OR site:videvo.net"
    params = urllib.parse.urlencode({"q": q, "brd_json": "1"})
    return f"https://www.google.com/search?{params}"


def search_brightdata_images(query: str, *, count: int = 10) -> list[dict]:
    """Return image candidate dicts: url, title, width, height."""
    if not fallback_enabled():
        return []
    search_q = (query or "technology").strip()
    text = _serp_request(_google_images_url(search_q))
    rows: list[dict] = []
    try:
        data = _extract_json(text)
        rows = _image_rows_from_payload(data)
    except RuntimeError:
        rows = _regex_image_urls(text)
    if not rows:
        rows = _regex_image_urls(text)
    if len(rows) < count:
        fallback_text = _serp_request(
            f"https://www.google.com/search?q={urllib.parse.quote(search_q + ' stock photo')}&brd_json=1"
        )
        try:
            rows.extend(_image_rows_from_payload(_extract_json(fallback_text)))
        except RuntimeError:
            rows.extend(_regex_image_urls(fallback_text))
    deduped: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            deduped.append(row)
        if len(deduped) >= count:
            break
    if deduped:
        print(f"  Bright Data images: {len(deduped)} hits for {search_q!r}", file=sys.stderr)
    return deduped[:count]


def search_brightdata_videos(query: str, *, count: int = 10) -> list[dict]:
    """Return video candidate dicts: url, title, duration."""
    if not fallback_enabled():
        return []
    search_q = (query or "technology motion").strip()
    rows: list[dict] = []
    for url_builder in (_google_video_url, _google_stock_video_url):
        text = _serp_request(url_builder(search_q))
        try:
            rows.extend(_video_rows_from_payload(_extract_json(text)))
        except RuntimeError:
            for match in _VIDEO_URL_RE.findall(text):
                rows.append({"url": match, "title": search_q, "duration": 0.0})
        if len(rows) >= count:
            break

    deduped: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            deduped.append(row)
        if len(deduped) >= count:
            break
    if deduped:
        print(f"  Bright Data videos: {len(deduped)} hits for {search_q!r}", file=sys.stderr)
    return deduped[:count]


def _content_kind(content_type: str, path: Path) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("image/"):
        return "image"
    suffix = path.suffix.lower()
    if suffix in _VIDEO_EXT:
        return "video"
    if suffix in _IMAGE_EXT:
        return "image"
    return ""


def download_brightdata_media(url: str, dest: Path, *, kind: str = "image") -> Path:
    """Download and validate remote media for ffmpeg/Pillow."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read()
    min_bytes = 1024 if kind == "image" else 50_000
    if len(data) < min_bytes:
        raise RuntimeError(f"Bright Data media too small ({len(data)} bytes): {url[:80]}")
    detected = _content_kind(content_type, dest)
    if detected and detected != kind:
        raise RuntimeError(f"Expected {kind}, got {detected} from {url[:80]}")
    if kind == "image" and detected != "image":
        # Some hosts omit content-type; allow if suffix looks like an image.
        suffix = urllib.parse.urlparse(url).path.lower()
        if not any(suffix.endswith(ext) for ext in _IMAGE_EXT):
            raise RuntimeError(f"URL does not look like an image: {url[:80]}")
    dest.write_bytes(data)
    return dest
