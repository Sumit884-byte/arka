"""Unsplash photo search for Arka video slides (requires free API key)."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UnsplashPhoto:
    id: str
    url: str
    download_url: str
    photographer: str
    photographer_url: str
    description: str


def access_key() -> str:
    for name in ("UNSPLASH_ACCESS_KEY", "UNSPLASH_KEY", "UNSPLASH_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def setup_hint() -> str:
    return (
        "Unsplash API key required for stock photos.\n"
        "  1. Create a free app: https://unsplash.com/developers\n"
        "  2. Add to ~/.config/arka/.env:\n"
        "       UNSPLASH_ACCESS_KEY=your_access_key"
    )


def search_photos(
    query: str, *, count: int = 1, orientation: str = "landscape", size: str = "regular"
) -> list[UnsplashPhoto]:
    key = access_key()
    if not key:
        raise SystemExit(setup_hint())

    params = urllib.parse.urlencode(
        {
            "query": query.strip() or "technology",
            "per_page": max(1, min(count, 30)),
            "orientation": orientation,
            "content_filter": "high",
        }
    )
    url = f"https://api.unsplash.com/search/photos?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Client-ID {key}",
            "Accept-Version": "v1",
            "User-Agent": "arka-compose-video/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:
        raise SystemExit(f"Unsplash search failed: {exc}") from exc

    results: list[UnsplashPhoto] = []
    for row in payload.get("results") or []:
        urls = row.get("urls") or {}
        user = row.get("user") or {}
        links = row.get("links") or {}
        if size == "full":
            photo_url = urls.get("full") or urls.get("regular") or ""
        else:
            photo_url = urls.get("regular") or urls.get("full") or ""
        if not photo_url:
            continue
        results.append(
            UnsplashPhoto(
                id=str(row.get("id") or ""),
                url=photo_url,
                download_url=str(links.get("download_location") or photo_url),
                photographer=str(user.get("name") or "Unknown"),
                photographer_url=str(user.get("links", {}).get("html") or "https://unsplash.com"),
                description=str(row.get("description") or row.get("alt_description") or query),
            )
        )
    if not results:
        raise SystemExit(f"No Unsplash photos found for: {query!r}")
    return results


def trigger_download(photo: UnsplashPhoto) -> None:
    """Required by Unsplash API guidelines when using a photo."""
    key = access_key()
    if not key or not photo.download_url:
        return
    req = urllib.request.Request(
        photo.download_url,
        headers={"Authorization": f"Client-ID {key}", "User-Agent": "arka-compose-video/1.0"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def download_photo(photo: UnsplashPhoto, dest: Path) -> Path:
    trigger_download(photo)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(photo.url, headers={"User-Agent": "arka-compose-video/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest
