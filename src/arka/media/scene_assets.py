"""Free/local asset resolution for 3D scene composition."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Verified free GLB assets from three.js examples (Khronos / three.js project).
CURATED_CATALOG: list[dict[str, Any]] = [
    {
        "name": "RobotExpressive",
        "url": "https://threejs.org/examples/models/gltf/RobotExpressive/RobotExpressive.glb",
        "keywords": ["robot", "animated", "character", "gallery", "expressive"],
        "roles": ["primary character", "robot", "character"],
    },
    {
        "name": "Flamingo",
        "url": "https://threejs.org/examples/models/gltf/Flamingo/glTF-Binary/Flamingo.glb",
        "keywords": ["flamingo", "bird", "animal"],
        "roles": ["animal", "character"],
    },
    {
        "name": "Parrot",
        "url": "https://threejs.org/examples/models/gltf/Parrot/glTF-Binary/Parrot.glb",
        "keywords": ["parrot", "bird", "animal"],
        "roles": ["animal", "character"],
    },
    {
        "name": "Stork",
        "url": "https://threejs.org/examples/models/gltf/Stork/glTF-Binary/Stork.glb",
        "keywords": ["stork", "bird", "animal"],
        "roles": ["animal", "character"],
    },
    {
        "name": "LittlestTokyo",
        "url": "https://threejs.org/examples/models/gltf/LittlestTokyo.glb",
        "keywords": ["city", "tokyo", "environment", "animated", "scene"],
        "roles": ["environment", "environment markers"],
    },
    {
        "name": "Soldier",
        "url": "https://threejs.org/examples/models/gltf/Soldier.glb",
        "keywords": ["soldier", "human", "character", "person", "animated"],
        "roles": ["primary character", "character", "seated character", "sleeping character"],
    },
    {
        "name": "Horse",
        "url": "https://threejs.org/examples/models/gltf/Horse.glb",
        "keywords": ["horse", "animal"],
        "roles": ["animal", "character"],
    },
    {
        "name": "Fox",
        "url": "https://threejs.org/examples/models/gltf/Fox/glTF-Binary/Fox.glb",
        "keywords": ["fox", "animal"],
        "roles": ["animal", "character"],
    },
]


def _text_blob(title: str, intent: str, plan: dict[str, Any] | None = None) -> str:
    parts = [title, intent]
    if plan:
        parts.extend(str(plan.get("context") or ""))
        parts.extend(plan.get("roles") or [])
    return " ".join(parts).lower()


def match_catalog(text: str, role: str = "") -> dict[str, Any] | None:
    """Return best curated catalog entry for text/role."""
    blob = f"{text} {role}".lower()
    role_norm = role.lower().strip()
    best: dict[str, Any] | None = None
    best_score = 0
    for entry in CURATED_CATALOG:
        score = 0
        for kw in entry.get("keywords") or []:
            if kw in blob:
                score += 3
        for r in entry.get("roles") or []:
            if r in role_norm or role_norm in r:
                score += 5
        if score > best_score:
            best_score = score
            best = entry
    if best_score > 0:
        return best
    # Default for generic character/robot gallery prompts
    if any(w in blob for w in ("robot", "gallery", "animated")):
        return CURATED_CATALOG[0]
    if any(w in blob for w in ("character", "person", "human")):
        return next(e for e in CURATED_CATALOG if e["name"] == "Soldier")
    return CURATED_CATALOG[0]


def _search_mcp(query: str) -> str | None:
    try:
        from arka.agent.three_js_model import search_models

        candidates, _source = search_models(query, use_mcp=True)
        for candidate in candidates:
            if not candidate.has_threejs_format or not candidate.viewer_url:
                continue
            url = candidate.viewer_url
            if url.lower().endswith((".glb", ".gltf")):
                return url
        return None
    except Exception:
        return None


def _generate_local(prompt: str, name: str) -> Path | None:
    try:
        from arka.media.compose_3d import main as compose_main, output_dir

        out = output_dir()
        before = {p.resolve() for p in out.glob("*.glb")}
        code = compose_main(["compose", prompt, "--backend", "auto", "--format", "glb", "--name", name])
        if code != 0:
            return None
        after = {p.resolve() for p in out.glob("*.glb")}
        new_files = after - before
        if new_files:
            return max(new_files, key=lambda p: p.stat().st_mtime)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "model"
        matches = sorted(out.glob(f"*{slug}*.glb"), key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0] if matches else None
    except Exception:
        return None


def _is_url(path: str) -> bool:
    parsed = urlparse(path)
    return parsed.scheme in ("http", "https")


def localize_asset(url: str, output_dir: Path) -> str:
    """Copy local GLB into scene output and return relative URL for HTML."""
    if _is_url(url):
        return url
    src = Path(url).expanduser().resolve()
    if not src.is_file():
        return url
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    dest = assets_dir / src.name
    if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dest)
    return f"assets/{src.name}"


def resolve_assets(
    plan: dict[str, Any],
    *,
    title: str = "",
    intent: str = "",
    user_models: list[str] | None = None,
    allow_generate: bool = True,
    output_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve scene assets from user input, catalog, search, and optional generation.

    Returns (assets, warnings).
    """
    warnings: list[str] = []
    text = _text_blob(title, intent, plan)
    roles = list(plan.get("roles") or ["primary character"])
    assets: list[dict[str, Any]] = []

    user_models = user_models or []
    for i, model in enumerate(user_models):
        role = roles[i] if i < len(roles) else f"asset_{i}"
        url = model
        if output_dir is not None:
            url = localize_asset(model, output_dir)
        assets.append({"url": url, "role": role, "animate": True})

    if assets:
        return assets, warnings

    # Auto-resolve one asset per primary role (cap at 3 for performance)
    target_roles = [r for r in roles if "camera" not in r.lower()][:3]
    if not target_roles:
        target_roles = ["primary character"]

    used_urls: set[str] = set()
    for role in target_roles:
        entry = match_catalog(text, role)
        if entry and entry["url"] not in used_urls:
            assets.append({
                "url": entry["url"],
                "role": role,
                "animate": True,
                "source": f"curated:{entry['name']}",
            })
            used_urls.add(entry["url"])
            continue

        mcp_url = _search_mcp(f"{role} {text}")
        if mcp_url and mcp_url not in used_urls:
            assets.append({"url": mcp_url, "role": role, "animate": True, "source": "threejs-mcp"})
            used_urls.add(mcp_url)
            continue

        if allow_generate:
            slug = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-") or "model"
            path = _generate_local(f"{role} for {title or 'scene'}", slug)
            if path:
                url = str(path)
                if output_dir is not None:
                    url = localize_asset(url, output_dir)
                assets.append({"url": url, "role": role, "animate": False, "source": "generated"})
                used_urls.add(url)
                continue

        warnings.append(f"No asset resolved for role: {role}")

    if not assets:
        fallback = CURATED_CATALOG[0]
        assets.append({
            "url": fallback["url"],
            "role": "primary character",
            "animate": True,
            "source": f"curated:{fallback['name']}",
        })
        warnings.append("Using default RobotExpressive curated asset")

    return assets, warnings
