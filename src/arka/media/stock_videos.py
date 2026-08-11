"""Stock video search — Pexels and Pixabay with photo-search fallback helpers."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from arka.media.stock_brightdata import fallback_enabled as brightdata_enabled
from arka.media.stock_brightdata import search_brightdata_videos
from arka.media.stock_photos import (
    compact_photo_query,
    diverse_photo_queries,
    pexels_key,
    photo_query_variants,
    pixabay_key,
    score_photo_relevance,
)


@dataclass(frozen=True)
class StockVideo:
    id: str
    url: str
    download_url: str
    photographer: str
    photographer_url: str
    description: str
    source: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    tags: tuple[str, ...] = ()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured_video_sources() -> list[str]:
    raw = _env("VIDEO_VIDEO_SOURCES", "pexels,pixabay,brightdata")
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def any_video_source_available() -> bool:
    for source in configured_video_sources():
        if source == "pexels" and pexels_key():
            return True
        if source == "pixabay" and pixabay_key():
            return True
        if source == "brightdata" and brightdata_enabled():
            return True
    return False


def video_uid(video: StockVideo) -> str:
    return f"{video.source}:{video.id}"


def stock_video_search_query(query: str) -> str:
    """Prefer compact visual terms; avoid office-desk bias used for photo explainers."""
    compact = compact_photo_query(query)
    if compact == "technology":
        return "technology motion"
    return compact


def _pick_pexels_file(files: list[dict], *, min_width: int = 1280) -> str:
    candidates: list[tuple[int, str]] = []
    for row in files or []:
        link = str(row.get("link") or "").strip()
        if not link or not link.startswith("http"):
            continue
        width = int(row.get("width") or 0)
        quality = str(row.get("quality") or "").lower()
        score = width
        if quality == "hd":
            score += 500
        elif quality == "sd":
            score += 100
        if width >= min_width:
            score += 200
        candidates.append((score, link))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _search_pexels_videos(query: str, *, count: int, orientation: str) -> list[StockVideo]:
    key = pexels_key()
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "query": stock_video_search_query(query),
            "per_page": max(1, min(count, 30)),
            "orientation": orientation if orientation in {"landscape", "portrait", "square"} else "landscape",
        }
    )
    req = urllib.request.Request(
        f"https://api.pexels.com/videos/search?{params}",
        headers={"Authorization": key, "User-Agent": "arka-compose-video/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    out: list[StockVideo] = []
    for row in payload.get("videos") or []:
        url = _pick_pexels_file(row.get("video_files") or [])
        if not url:
            continue
        user = row.get("user") or {}
        out.append(
            StockVideo(
                id=str(row.get("id") or ""),
                url=url,
                download_url=url,
                photographer=str(user.get("name") or "Pexels"),
                photographer_url=str(user.get("url") or "https://www.pexels.com"),
                description=stock_video_search_query(query),
                source="pexels",
                duration=float(row.get("duration") or 0),
                width=int(row.get("width") or 0),
                height=int(row.get("height") or 0),
            )
        )
    return out


def _pick_pixabay_video(videos: dict) -> tuple[str, int, int]:
    for key in ("large", "medium", "small", "tiny"):
        row = videos.get(key) or {}
        url = str(row.get("url") or "").strip()
        if url:
            return url, int(row.get("width") or 0), int(row.get("height") or 0)
    return "", 0, 0


def _search_pixabay_videos(query: str, *, count: int, orientation: str) -> list[StockVideo]:
    key = pixabay_key()
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "key": key,
            "q": stock_video_search_query(query),
            "video_type": "film",
            "orientation": "horizontal" if orientation != "portrait" else "vertical",
            "per_page": max(3, min(count, 30)),
            "safesearch": "true",
        }
    )
    req = urllib.request.Request(
        f"https://pixabay.com/api/videos/?{params}",
        headers={"User-Agent": "arka-compose-video/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    out: list[StockVideo] = []
    for row in payload.get("hits") or []:
        url, width, height = _pick_pixabay_video(row.get("videos") or {})
        if not url:
            continue
        tags = tuple(tag.strip().lower() for tag in str(row.get("tags") or "").split(",") if tag.strip())
        out.append(
            StockVideo(
                id=str(row.get("id") or ""),
                url=url,
                download_url=url,
                photographer=str(row.get("user") or "Pixabay"),
                photographer_url=str(row.get("pageURL") or "https://pixabay.com"),
                description=str(row.get("tags") or query),
                source="pixabay",
                duration=float(row.get("duration") or 0),
                width=width,
                height=height,
                tags=tags,
            )
        )
    return out


def _search_brightdata_videos(query: str, *, count: int, orientation: str) -> list[StockVideo]:
    if not brightdata_enabled():
        return []
    rows = search_brightdata_videos(query, count=max(count * 2, 10))
    out: list[StockVideo] = []
    for row in rows:
        url = str(row.get("url") or "")
        if not url:
            continue
        title = str(row.get("title") or query)
        out.append(
            StockVideo(
                id=url,
                url=url,
                download_url=url,
                photographer="Bright Data",
                photographer_url="https://brightdata.com",
                description=title,
                source="brightdata",
                duration=float(row.get("duration") or 0),
            )
        )
        if len(out) >= count:
            break
    return out


def _search_source_videos(
    source: str,
    query: str,
    *,
    count: int,
    orientation: str,
) -> list[StockVideo]:
    if source == "pexels" and pexels_key():
        return _search_pexels_videos(query, count=count, orientation=orientation)
    if source == "pixabay" and pixabay_key():
        return _search_pixabay_videos(query, count=count, orientation=orientation)
    if source == "brightdata" and brightdata_enabled():
        return _search_brightdata_videos(query, count=count, orientation=orientation)
    return []


def _video_as_photo_score(video: StockVideo, query: str, *, context_terms: list[str] | None = None) -> int:
    from arka.media.stock_photos import StockPhoto

    pseudo = StockPhoto(
        id=video.id,
        url=video.url,
        download_url=video.download_url,
        photographer=video.photographer,
        photographer_url=video.photographer_url,
        description=video.description,
        source=video.source,
        tags=video.tags,
    )
    return score_photo_relevance(pseudo, query, context_terms=context_terms)


def search_stock_videos(
    query: str,
    *,
    count: int = 1,
    orientation: str = "landscape",
    context_terms: list[str] | None = None,
    exclude_ids: set[str] | None = None,
) -> list[StockVideo]:
    if not any_video_source_available():
        return []
    errors: list[str] = []
    variants = photo_query_variants(query)
    fetch_count = max(count * 4, 12)
    excluded = exclude_ids or set()
    for variant in variants:
        search_q = stock_video_search_query(variant)
        for source in configured_video_sources():
            try:
                videos = _search_source_videos(source, search_q, count=fetch_count, orientation=orientation)
                if not videos:
                    continue
                ranked = sorted(
                    videos,
                    key=lambda video: _video_as_photo_score(video, variant, context_terms=context_terms),
                    reverse=True,
                )
                if excluded:
                    fresh = [video for video in ranked if video_uid(video) not in excluded]
                    if not fresh:
                        continue
                    ranked = fresh
                if _video_as_photo_score(ranked[0], variant, context_terms=context_terms) <= 0:
                    print(
                        f"  Video source {source}: weak match for {search_q!r}, trying next …",
                        file=sys.stderr,
                    )
                    continue
                picked = ranked[:count]
                print(f"  Video: {source} ({search_q!r}) — id={picked[0].id}", file=sys.stderr)
                return picked
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                print(f"  Video source {source} failed: {exc}", file=sys.stderr)
    if errors:
        print(f"  No stock videos for {query!r} ({'; '.join(errors[-2:])})", file=sys.stderr)
    return []


def download_stock_video(video: StockVideo, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if video.source == "brightdata":
        from arka.media.stock_brightdata import download_brightdata_media

        return download_brightdata_media(video.download_url, dest, kind="video")
    req = urllib.request.Request(video.download_url, headers={"User-Agent": "arka-compose-video/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest


def diverse_video_queries(query: str, *, limit: int = 6) -> list[str]:
    """Reuse photo query expansion for varied B-roll video searches."""
    out: list[str] = []
    seen: set[str] = set()
    for item in diverse_photo_queries(query, limit=limit):
        normalized = stock_video_search_query(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out or [stock_video_search_query(query)]
