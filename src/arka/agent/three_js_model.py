"""Three.js model preference guidance for web/3D builds."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

GUIDANCE = (
    "For a web 3D request, first check Three.js examples, @react-three/drei, "
    "the configured `threejs` MCP server, and the project's existing assets for a suitable model. "
    "If `threejs` MCP is missing, run `arka mcp preset threejs --apply` to configure "
    "baryhuang/mcp-threejs, the Sketchfab-backed Three.js model server. For satellites, "
    "spacecraft, planets, and other recognizable objects, prefer a realistic "
    "verified Three.js-compatible GLTF/GLB asset with material and texture maps; "
    "do not substitute boxes, spheres, or cylinders when a suitable asset exists. "
    "Use `arka three_js_model search <object>` to normalize candidates and confirm "
    "license, attribution, scale, and performance before integrating it."
)

_REAL_WORLD_HINTS = frozenset({
    "satellite", "spacecraft", "rocket", "airplane", "car", "truck", "ship",
    "tree", "house", "person", "boy", "girl", "animal", "bird", "robot",
    "earth", "moon", "mars", "sun", "planet", "building", "chair", "table",
    "desk", "keyboard", "monitor", "bed", "lamp", "plate",
})


@dataclass(frozen=True)
class ModelCandidate:
    """Normalized Three.js-compatible asset candidate.

    Inspired by mcp-threejs' useful contract: search downloadable models, keep
    format metadata, and preserve source/attribution details instead of asking
    the LLM to invent URLs.
    """

    name: str
    uid: str = ""
    source: str = "unknown"
    viewer_url: str = ""
    thumbnail_url: str = ""
    formats: dict[str, int] | None = None
    license: str = ""
    attribution: str = ""
    downloadable: bool = False

    @property
    def has_threejs_format(self) -> bool:
        formats = {k.lower() for k in (self.formats or {})}
        return bool(formats & {"glb", "gltf"})

    @property
    def score(self) -> int:
        score = 0
        if self.downloadable:
            score += 4
        if self.has_threejs_format:
            score += 4
        if self.license:
            score += 1
        if self.viewer_url:
            score += 1
        return score


def symbolic_real_world_entity(text: str) -> bool | None:
    """Return True/False when symbolic vocabulary is decisive, else None."""
    words = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    if words & _REAL_WORLD_HINTS:
        return True
    if re.search(r"(?i)\b(?:fictional|imaginary|abstract|procedural|geometric)\b", text or ""):
        return False
    return None


def asset_query(text: str) -> str:
    """Extract a compact 3D asset search query from natural language."""
    clean = re.sub(r"https?://\S+", " ", text or "")
    words = re.findall(r"[a-zA-Z0-9]+", clean.lower())
    stop = {
        "add", "build", "create", "make", "use", "find", "search", "model", "models",
        "3d", "three", "js", "threejs", "scene", "realistic", "real", "looking",
        "gltf", "glb", "asset", "assets", "to", "for", "in", "with", "the", "a", "an",
    }
    important = [word for word in words if word not in stop]
    for word in important:
        if word in _REAL_WORLD_HINTS:
            return word
    return " ".join(important[:4]).strip() or clean.strip() or "model"


def normalize_candidate(raw: dict[str, Any], *, source: str = "threejs-mcp") -> ModelCandidate:
    """Normalize Sketchfab/mcp-threejs style records into Arka's asset shape."""
    formats = raw.get("formats") or {}
    if isinstance(formats, list):
        formats = {str(item).lower(): 0 for item in formats}
    if not isinstance(formats, dict):
        formats = {}
    return ModelCandidate(
        name=str(raw.get("name") or raw.get("title") or raw.get("uid") or "Untitled model"),
        uid=str(raw.get("uid") or raw.get("model_id") or raw.get("id") or ""),
        source=str(raw.get("source") or source),
        viewer_url=str(raw.get("viewerUrl") or raw.get("viewer_url") or raw.get("url") or ""),
        thumbnail_url=str(raw.get("thumbnailUrl") or raw.get("thumbnail_url") or ""),
        formats={str(k).lower(): int(v or 0) for k, v in formats.items()},
        license=str(raw.get("license") or raw.get("licenseLabel") or ""),
        attribution=str(raw.get("attribution") or raw.get("user") or raw.get("author") or ""),
        downloadable=bool(raw.get("downloadable") if "downloadable" in raw else formats),
    )


def parse_model_candidates(payload: str | dict[str, Any] | list[Any]) -> list[ModelCandidate]:
    """Parse MCP/Sketchfab-style search output into ranked candidates."""
    data: Any = payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        rows = data.get("downloadable_models") or data.get("models") or data.get("results") or []
    else:
        rows = data
    if not isinstance(rows, list):
        return []
    candidates = [normalize_candidate(row) for row in rows if isinstance(row, dict)]
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def search_models(query: str, *, use_mcp: bool = True) -> tuple[list[ModelCandidate], str]:
    """Search configured Three.js asset providers; return candidates and source label."""
    compact = asset_query(query)
    if use_mcp:
        try:
            from arka.integrations.mcp_manager import call_tool, list_server_names

            if "threejs" in list_server_names():
                text = call_tool("threejs", "threejs_search_models", {"query": compact})
                return parse_model_candidates(text), "threejs-mcp"
        except Exception as exc:
            return [], f"threejs-mcp unavailable: {exc}"
    return [], "no configured provider"


def format_recommendations(query: str, candidates: list[ModelCandidate], *, source: str) -> str:
    lines = [
        "Three.js asset search",
        f"query\t{asset_query(query)}",
        f"source\t{source}",
    ]
    if not candidates:
        lines.extend([
            "candidates\t0",
            "next\tarka mcp preset threejs --apply",
            "policy\tDo not invent model URLs; ask for a URL or configure a provider before integrating real assets.",
        ])
        return "\n".join(lines)
    lines.append(f"candidates\t{len(candidates)}")
    for index, candidate in enumerate(candidates[:5], 1):
        formats = ",".join(sorted((candidate.formats or {}).keys())) or "unknown"
        lines.append(
            f"{index}\t{candidate.name}\tformats={formats}\tdownloadable={candidate.downloadable}\t"
            f"license={candidate.license or 'unknown'}\tattribution={candidate.attribution or 'unknown'}\t"
            f"url={candidate.viewer_url or 'missing'}"
        )
    return "\n".join(lines)


def model_selection_instruction(text: str) -> str:
    """Compact symbolic+AI instruction used in coding prompts."""
    reality = symbolic_real_world_entity(text)
    if reality is True:
        return (
            "Reality check: this appears to be a real-world entity. Verify with a trusted catalog or "
            "user-provided URL; use Arka's `three_js_model search` asset-normalization layer "
            "(optionally backed by `threejs` MCP) or another realistic licensed "
            "GLTF/GLB model source with textures. Do not use "
            "geometric placeholders unless no verified asset exists and the user approves it."
        )
    if reality is None:
        return (
            "Reality check: if the requested object may exist in real life, verify that with a trusted "
            "source before choosing geometry; use a realistic licensed model when confirmed."
        )
    return "The user requested an abstract/procedural form; geometric generation is acceptable."


def dimension_research_instruction(text: str) -> str:
    """Require sourced dimensions for real-world 3D entities."""
    if symbolic_real_world_entity(text) is not True:
        return ""
    return (
        "Dimension check: look up authoritative real-world dimensions for the entity before modeling "
        "(prefer manufacturer, NASA, government, museum, or other primary sources). Record the source "
        "URL, measurement date, units, and which dimension is represented; preserve uncertainty or "
        "variant ranges instead of inventing a precise value. Apply the chosen scale consistently in "
        "Three.js and show the user the cited dimensions."
    )


def route_command(text: str) -> str:
    clean = (text or "").strip()
    if not re.search(r"(?i)\b(?:3d|three\.js|threejs|react[- ]three|gltf|glb|mesh|model)\b", clean):
        return ""
    if not (
        re.search(r"(?i)\bthree\.js\b|\b(?:web|website|app|frontend|scene|browser)\b", clean)
        or (re.search(r"(?i)\b(?:satellite|spacecraft|planet|solar\s+system)\b", clean) and re.search(r"(?i)\b(?:3d|model|scene|app|build|add)\b", clean))
    ):
        return ""
    if re.search(r"(?i)\b(?:find|search|lookup|choose|select|get)\b.*\b(?:asset|model|gltf|glb|threejs|three\.js)\b", clean):
        return "three_js_model search " + clean
    return "three_js_model guide " + clean


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefer verified Three.js-compatible models for web 3D builds")
    sub = parser.add_subparsers(dest="cmd")
    guide = sub.add_parser("guide")
    guide.add_argument("topic", nargs="*")
    search = sub.add_parser("search")
    search.add_argument("query", nargs="+")
    search.add_argument("--json", action="store_true")
    search.add_argument("--no-mcp", action="store_true", help="Do not call configured MCP providers")
    args = parser.parse_args(argv)
    if args.cmd == "guide":
        print(GUIDANCE)
        if args.topic:
            print(f"Requested scene: {' '.join(args.topic)}")
        return 0
    if args.cmd == "search":
        query = " ".join(args.query)
        candidates, source = search_models(query, use_mcp=not args.no_mcp)
        if args.json:
            print(json.dumps({"query": asset_query(query), "source": source, "candidates": [asdict(c) for c in candidates]}, indent=2))
        else:
            print(format_recommendations(query, candidates, source=source))
        return 0
    parser.print_help()
    return 1
