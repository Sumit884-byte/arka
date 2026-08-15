"""Hybrid two-pass image relevance and outlier filter.

Pass 1 (heuristic): CLIP embeddings + cosine similarity vs query and batch centroid.
Pass 2 (VLM, borderline only): vision model yes/no/score for ambiguous images near threshold.

Near-VLM accuracy at near-heuristic speed — VLM runs only on hard cases.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
CLI_HEADS = frozenset(
    {
        "filter_images",
        "filter-images",
        "image_relevance",
        "image-relevance",
        "hybrid_image_filter",
        "hybrid-image-filter",
    }
)

SKILL_HELP = """
Hybrid image relevance filter — fast CLIP pass + VLM only on borderline cases.

Pass 1 embeds images with CLIP (sentence-transformers or transformers) and scores
cosine similarity to your query text and the batch centroid. Outliers are flagged
via z-score or Isolation Forest on centroid distance; bottom-tail low scores are
rejected; ambiguous images near the threshold enter the borderline band.

Pass 2 (optional, --vllm-pass or ARKA_IMAGE_FILTER_VLM_PASS=1) sends only
borderline images to a vision model (describe_source / vLLM / Gemini / Ollama)
for a 0–1 relevance score. Final keep/reject merges pass 1 + pass 2 overrides.

Without CLIP installed, warns and falls back to hash-only duplicate hints or
VLM-only mode when --vllm-pass is set.

Env: ARKA_IMAGE_FILTER_CLIP_MODEL, ARKA_IMAGE_FILTER_VLM_PASS,
     ARKA_IMAGE_FILTER_BORDERLINE_PCT, DESCRIBE_IMAGE_BACKEND
"""

VLM_RELEVANCE_PROMPT = (
    "Is this image relevant to '{query}'? "
    "Reply with JSON only: "
    '{{"relevant": bool, "score": number between 0 and 1, "reason": str}}'
)


@dataclass
class ImageFilterResult:
    path: str
    clip_score: float | None = None
    centroid_sim: float | None = None
    centroid_z: float | None = None
    outlier: bool = False
    pass1_decision: str = "unknown"
    vlm_score: float | None = None
    vlm_reason: str | None = None
    final_decision: str = "unknown"
    hash_hex: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FilterReport:
    query: str | None
    mode: str
    backend: str | None
    borderline_pct: float
    vlm_pass: bool
    threshold: float | None
    images: list[ImageFilterResult] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    borderline: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "backend": self.backend,
            "borderline_pct": self.borderline_pct,
            "vlm_pass": self.vlm_pass,
            "threshold": self.threshold,
            "summary": {
                "total": len(self.images),
                "kept": len(self.kept),
                "rejected": len(self.rejected),
                "borderline": len(self.borderline),
            },
            "warnings": self.warnings,
            "images": [img.to_dict() for img in self.images],
            "kept": self.kept,
            "rejected": self.rejected,
            "borderline": self.borderline,
        }


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def collect_images(target: str | Path) -> list[Path]:
    path = Path(target)
    if path.is_file():
        if not _is_image(path):
            raise ValueError(f"Not an image file: {path}")
        return [path.resolve()]
    if not path.is_dir():
        raise FileNotFoundError(f"Path not found: {path}")
    files = sorted(p.resolve() for p in path.iterdir() if p.is_file() and _is_image(p))
    if not files:
        raise ValueError(f"No images found in {path}")
    return files


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_vlm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    match = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    payload = json.loads(text)
    score = payload.get("score")
    if score is not None:
        score = max(0.0, min(1.0, float(score)))
    relevant = payload.get("relevant")
    if relevant is None and score is not None:
        relevant = score >= 0.5
    return {
        "relevant": bool(relevant),
        "score": score,
        "reason": str(payload.get("reason") or "").strip(),
    }


def vlm_relevance(path: str | Path, query: str) -> dict[str, Any]:
    from arka.vision.describe import describe_source

    prompt = VLM_RELEVANCE_PROMPT.format(query=query.replace("'", "\\'"))
    raw = describe_source(str(path), prompt=prompt)
    try:
        return _parse_vlm_json(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        lower = raw.lower()
        score = 0.7 if "relevant" in lower and "not relevant" not in lower else 0.3
        return {"relevant": score >= 0.5, "score": score, "reason": raw[:240]}


def _pass1_classify(
    *,
    clip_scores: list[float | None],
    centroid_sims: list[float | None],
    centroid_zs: list[float | None],
    outliers: list[bool],
    borderline_pct: float,
    query: str | None,
) -> tuple[float | None, list[str]]:
    """Return threshold and pass1 decisions (keep|reject|borderline)."""
    scored = [s for s in clip_scores if s is not None]
    centroid_scored = [s for s in centroid_sims if s is not None]
    if scored:
        import numpy as np

        threshold = float(np.median(scored))
        spread = float(np.std(scored)) if len(scored) > 1 else 0.08
        band = max(spread * (borderline_pct / 100.0), 0.02)
    elif centroid_scored:
        import numpy as np

        threshold = float(np.median(centroid_scored))
        spread = float(np.std(centroid_scored)) if len(centroid_scored) > 1 else 0.08
        band = max(spread * (borderline_pct / 100.0), 0.02)
    else:
        threshold = None
        band = 0.05

    decisions: list[str] = []
    for idx, clip in enumerate(clip_scores):
        score = clip if clip is not None else centroid_sims[idx]
        z = centroid_zs[idx]
        if score is None:
            decisions.append("reject")
            continue
        if outliers[idx] and (clip is None or clip < (threshold or 0.5)):
            decisions.append("reject")
            continue
        if threshold is None:
            decisions.append("keep")
            continue
        if score >= threshold + band / 2:
            decisions.append("keep")
        elif score < threshold - band / 2:
            decisions.append("reject")
        else:
            decisions.append("borderline")
        if z is not None and abs(z) >= 2.5 and decisions[-1] == "keep" and query:
            decisions[-1] = "borderline"
    return threshold, decisions


def filter_images(
    paths: list[str | Path],
    *,
    query: str | None = None,
    vlm_pass: bool | None = None,
    borderline_pct: float | None = None,
    embedder: Any | None = None,
) -> FilterReport:
    from arka.vision.embeddings import (
        ClipEmbedder,
        average_hash,
        batch_centroid,
        cosine_similarity,
        isolation_outliers,
        z_scores,
    )

    borderline_pct = borderline_pct if borderline_pct is not None else _env_float("ARKA_IMAGE_FILTER_BORDERLINE_PCT", 20.0)
    vlm_pass = _env_bool("ARKA_IMAGE_FILTER_VLM_PASS", False) if vlm_pass is None else vlm_pass

    resolved = [Path(p).resolve() for p in paths]
    report = FilterReport(
        query=query,
        mode="hybrid",
        backend=None,
        borderline_pct=borderline_pct,
        vlm_pass=vlm_pass,
        threshold=None,
    )

    clip = embedder if embedder is not None else ClipEmbedder()
    embeddings: list[Any] = []
    clip_scores: list[float | None] = [None] * len(resolved)
    centroid_sims: list[float | None] = [None] * len(resolved)
    hash_hexes: list[str | None] = [None] * len(resolved)

    if clip.available:
        report.backend = clip.backend.name if clip.backend else "clip"
        try:
            embeddings = clip.embed_image_paths(resolved)
            query_vec = clip.embed_text(query) if query else None
            centroid = batch_centroid(embeddings)
            for i, emb in enumerate(embeddings):
                centroid_sims[i] = cosine_similarity(emb, centroid)
                if query_vec is not None:
                    clip_scores[i] = cosine_similarity(emb, query_vec)
        except (OSError, RuntimeError, ValueError) as exc:
            report.warnings.append(f"CLIP embedding failed: {exc}")
            embeddings = []
    else:
        report.warnings.append(
            "CLIP not installed — using perceptual-hash hints only. "
            "Install: pip install 'sentence-transformers' or pip install 'arka-agent[image-filter]'"
        )
        report.mode = "hash" if not vlm_pass else "vlm-only"
        for i, path in enumerate(resolved):
            try:
                hash_hexes[i] = average_hash(path)
            except OSError:
                hash_hexes[i] = None

    outliers = isolation_outliers(embeddings) if embeddings else [False] * len(resolved)
    dists = [1.0 - (s if s is not None else 0.0) for s in centroid_sims]
    centroid_zs = z_scores(dists) if any(s is not None for s in centroid_sims) else [0.0] * len(resolved)

    if not embeddings and vlm_pass and query:
        report.mode = "vlm-only"
        threshold = 0.5
        pass1 = ["borderline"] * len(resolved)
    elif not embeddings:
        threshold = None
        pass1 = (["borderline"] * len(resolved)) if query else (["keep"] * len(resolved))
    else:
        threshold, pass1 = _pass1_classify(
            clip_scores=clip_scores,
            centroid_sims=centroid_sims,
            centroid_zs=centroid_zs,
            outliers=outliers,
            borderline_pct=borderline_pct,
            query=query,
        )
    report.threshold = threshold

    results: list[ImageFilterResult] = []
    for i, path in enumerate(resolved):
        item = ImageFilterResult(
            path=str(path),
            clip_score=clip_scores[i],
            centroid_sim=centroid_sims[i],
            centroid_z=centroid_zs[i] if i < len(centroid_zs) else None,
            outlier=outliers[i] if i < len(outliers) else False,
            pass1_decision=pass1[i],
            hash_hex=hash_hexes[i],
        )
        item.final_decision = item.pass1_decision
        results.append(item)

    if vlm_pass and query:
        for item in results:
            if item.pass1_decision != "borderline":
                continue
            verdict = vlm_relevance(item.path, query)
            item.vlm_score = verdict.get("score")
            item.vlm_reason = verdict.get("reason")
            if item.vlm_score is not None:
                item.final_decision = "keep" if item.vlm_score >= 0.5 else "reject"
            elif verdict.get("relevant"):
                item.final_decision = "keep"
            else:
                item.final_decision = "reject"

    for item in results:
        if item.final_decision == "keep":
            report.kept.append(item.path)
        elif item.final_decision == "borderline":
            report.borderline.append(item.path)
            if not vlm_pass:
                report.rejected.append(item.path)
        elif item.final_decision == "reject":
            report.rejected.append(item.path)

    report.images = results
    return report


def copy_kept(report: FilterReport, output_dir: str | Path) -> list[str]:
    dest_root = Path(output_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for src in report.kept:
        src_path = Path(src)
        dest = dest_root / src_path.name
        shutil.copy2(src_path, dest)
        copied.append(str(dest.resolve()))
    return copied


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if not re.search(
        r"(?i)\b(?:filter(?:\s+|-)?images?|image(?:\s+|-)?relevance|hybrid(?:\s+|-)?image(?:\s+|-)?filter|"
        r"filter irrelevant images?|find outliers in (?:photo|image) batch|score images? for)\b",
        t,
    ):
        return []

    argv: list[str] = []
    if re.search(r"(?i)\b(?:score|rank|rate)\b", t):
        argv.append("score")
    elif re.search(r"(?i)\b(?:check|inspect|single)\b", t) and re.search(
        r"\.(?:png|jpe?g|webp|gif|bmp|tiff?)\b", t, re.I
    ):
        argv.append("check")
    else:
        argv.append("filter")

    quoted_dir = re.findall(r"""['"]([^'"]+)['"]""", t)
    paths = re.findall(r"\S+\.(?:png|jpe?g|webp|gif|bmp|tiff?)\b", t, flags=re.I)
    folder = re.search(r"(?i)\b(?:folder|directory|photos?|images?)\s+['\"]?([^\s'\"]+)", t)
    if argv[0] == "check" and paths:
        argv.append(paths[0])
    elif folder:
        argv.append(folder.group(1).rstrip("/"))
    elif quoted_dir:
        argv.append(quoted_dir[0])
    elif paths:
        argv.append(paths[0])
    else:
        m = re.search(r"(?i)\b(?:in|from|under)\s+([^\s'\"]+)", t)
        if m:
            argv.append(m.group(1).rstrip("/"))

    query_match = re.search(r"""(?i)(?:query|for|matching|relevant to)\s+['"]([^'"]+)['"]""", t)
    if not query_match:
        query_match = re.search(r"(?i)(?:query|for|matching|relevant to)\s+([^\n.!?]+)", t)
    if query_match:
        argv.extend(["--query", query_match.group(1).strip()])

    if re.search(r"(?i)\b(?:vllm|vlm|vision)\b", t):
        argv.append("--vllm-pass")

    out = re.search(r"(?i)\b(?:output|to|into)\s+['\"]?([^\s'\"]+)", t)
    if out and argv[0] == "filter":
        argv.extend(["--output", out.group(1).rstrip("/")])

    return argv


def filter_images_result(
    action: str,
    target: str | Path | None = None,
    *,
    query: str | None = None,
    output: str | Path | None = None,
    vlm_pass: bool | None = None,
    borderline_pct: float | None = None,
) -> dict[str, Any]:
    action = action.strip().lower()
    if action not in {"score", "filter", "check"}:
        raise ValueError("action must be score, filter, or check")
    if not target:
        raise ValueError("target path or folder is required")
    paths = collect_images(target)
    if action == "check":
        paths = paths[:1]
    report = filter_images(
        paths,
        query=query,
        vlm_pass=vlm_pass,
        borderline_pct=borderline_pct,
    )
    payload = report.to_dict()
    if action == "filter" and output:
        payload["copied"] = copy_kept(report, output)
    return payload


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(
        prog="arka filter_images",
        description="Hybrid CLIP + VLM image relevance and outlier filter",
        epilog=SKILL_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--query", "-q", help="Text query for relevance scoring")
    common.add_argument("--borderline-pct", type=float, default=None, help="Borderline band width (default 20)")
    common.add_argument("--vllm-pass", action="store_true", help="Run VLM on borderline images")
    common.add_argument("--json", action="store_true", help="Emit JSON report")
    common.add_argument("--open-ui", action="store_true", help="Push report to Output Viewer")

    score_p = sub.add_parser("score", parents=[common], help="Score images vs query")
    score_p.add_argument("folder", help="Folder or image path")

    filter_p = sub.add_parser("filter", parents=[common], help="Filter and optionally copy kept images")
    filter_p.add_argument("folder", help="Folder or image path")
    filter_p.add_argument("--output", "-o", help="Copy kept images here")

    check_p = sub.add_parser("check", parents=[common], help="Check one image")
    check_p.add_argument("image", help="Image path")

    args = parser.parse_args(raw)
    if not args.command:
        parser.print_help()
        return 0

    target = getattr(args, "folder", None) or getattr(args, "image", None)
    vlm_pass = args.vllm_pass or _env_bool("ARKA_IMAGE_FILTER_VLM_PASS", False)

    try:
        payload = filter_images_result(
            args.command,
            target,
            query=args.query,
            output=getattr(args, "output", None),
            vlm_pass=vlm_pass,
            borderline_pct=args.borderline_pct,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            from arka.core.output_layout import error

            error(str(exc))
        return 1

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        from arka.core.output_layout import info, push_to_viewer, result_box, section, success, table, warn

        section("Image relevance filter")
        info(f"Mode: {payload.get('mode')} | backend: {payload.get('backend') or 'none'}")
        if payload.get("query"):
            info(f"Query: {payload['query']}")
        if payload.get("warnings"):
            for w in payload["warnings"]:
                warn(w)
        summary = payload.get("summary") or {}
        result_box(
            "Summary",
            f"Total: {summary.get('total', 0)} | kept: {summary.get('kept', 0)} | "
            f"rejected: {summary.get('rejected', 0)} | borderline: {summary.get('borderline', 0)}",
        )
        rows = []
        for img in payload.get("images") or []:
            rows.append(
                [
                    Path(img["path"]).name,
                    f"{img['clip_score']:.3f}" if img.get("clip_score") is not None else "—",
                    img.get("pass1_decision") or "—",
                    f"{img['vlm_score']:.2f}" if img.get("vlm_score") is not None else "—",
                    img.get("final_decision") or "—",
                ]
            )
        if rows:
            table(["Image", "CLIP", "Pass1", "VLM", "Final"], rows)
        if payload.get("copied"):
            success(f"Copied {len(payload['copied'])} image(s) to output")
        elif summary.get("kept"):
            success(f"Kept {summary.get('kept')} image(s)")

    if args.open_ui or _env_bool("ARKA_OPEN_UI", False):
        from arka.core.output_layout import push_to_viewer

        push_to_viewer(json.dumps(payload, indent=2), title="Image filter report", format_hint="json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
