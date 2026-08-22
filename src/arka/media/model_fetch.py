"""Fetch free, CC0 3D model files by text query (Poly Haven API).

Standalone module so it can be wired into model_video.py's `fetch`
subcommand, or invoked directly: `python -m arka.media.model_fetch "chair"`.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

POLYHAVEN_API = "https://api.polyhaven.com"
USER_AGENT = "arka-model-fetch/1.0"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
        fh.write(resp.read())
    return dest


def search_models(query: str, limit: int = 5) -> list[str]:
    """Return Poly Haven model slugs matching a free-text query."""
    catalog = _get_json(f"{POLYHAVEN_API}/assets?t=models")
    query_lower = query.lower()
    matches = [
        slug for slug, meta in catalog.items()
        if query_lower in slug.lower()
        or query_lower in " ".join(meta.get("categories", [])).lower()
    ]
    return matches[:limit]


def fetch_model_by_query(query: str, dest_dir: Path, fmt: str = "gltf") -> Path:
    """Search Poly Haven for `query`, download the best match, return local path."""
    matches = search_models(query)
    if not matches:
        raise RuntimeError(f"No Poly Haven models found for query: {query!r}")
    slug = matches[0]
    files_meta = _get_json(f"{POLYHAVEN_API}/files/{slug}")
    fmt_block = files_meta.get(fmt) or next(iter(files_meta.values()))
    resolution = next(iter(fmt_block.values()))
    file_info = resolution.get(fmt) or next(iter(resolution.values()))
    url = file_info["url"]
    ext = Path(url).suffix or ".glb"
    dest = dest_dir / f"{slug}{ext}"
    return _download(url, dest)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arka-model-fetch")
    p.add_argument("query", help="Text query, e.g. 'wooden chair'")
    p.add_argument("--dest", default="./downloads", help="Output directory")
    p.add_argument("--format", default="gltf", help="gltf|fbx|blend (default gltf)")
    return p


def main(argv: list[str] | None = None) -> int:
    from arka.core.output_layout import error, info, result_box, success

    args = build_parser().parse_args(argv)
    info(f"Searching Poly Haven for {args.query!r} …")
    try:
        path = fetch_model_by_query(args.query, Path(args.dest), fmt=args.format)
    except Exception as exc:  # noqa: BLE001
        error(f"Fetch failed: {exc}")
        return 1
    result_box("Model fetched", f"Query: {args.query}\nFormat: {args.format}\nPath: {path}")
    success(f"Downloaded to {path}")
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
