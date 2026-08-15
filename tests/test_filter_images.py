"""Tests for hybrid filter_images skill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from arka.agent.filter_images import (
    _parse_vlm_json,
    collect_images,
    filter_images,
    filter_images_result,
    main,
    nl_to_argv,
)
from arka.routing.symbolic import route_filter_images
from arka.vision.embeddings import average_hash, cosine_similarity, z_scores


def _make_images(tmp_path: Path, count: int = 3) -> list[Path]:
    from PIL import Image, ImageDraw

    paths: list[Path] = []
    colors = [(200, 40, 40), (40, 160, 40), (40, 40, 200)]
    for i in range(count):
        path = tmp_path / f"img_{i}.jpg"
        img = Image.new("RGB", (120, 120), colors[i % len(colors)])
        draw = ImageDraw.Draw(img)
        draw.rectangle((20, 20, 100, 100), fill=(255, 255, 255))
        img.save(path, quality=90)
        paths.append(path)
    return paths


class _FakeEmbedder:
    available = True

    class backend:
        name = "fake"

    def __init__(self, vectors: list[np.ndarray], query_vec: np.ndarray) -> None:
        self._vectors = vectors
        self._query_vec = query_vec

    def embed_text(self, text: str) -> np.ndarray:
        return self._query_vec

    def embed_image_paths(self, paths: list[str | Path]) -> list[np.ndarray]:
        return self._vectors[: len(paths)]


class TestEmbeddingsHelpers:
    def test_cosine_similarity_identical(self) -> None:
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_z_scores(self) -> None:
        zs = z_scores([1.0, 2.0, 3.0, 4.0])
        assert len(zs) == 4
        assert zs[0] < zs[-1]

    def test_average_hash_stable(self, tmp_path: Path) -> None:
        paths = _make_images(tmp_path, 1)
        h1 = average_hash(paths[0])
        h2 = average_hash(paths[0])
        assert h1 == h2


class TestFilterImagesCore:
    def test_collect_images_folder(self, tmp_path: Path) -> None:
        paths = _make_images(tmp_path, 2)
        found = collect_images(tmp_path)
        assert len(found) == 2
        assert paths[0].resolve() in found

    def test_filter_with_mock_clip(self, tmp_path: Path) -> None:
        paths = _make_images(tmp_path, 4)
        query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vectors = [
            np.array([0.95, 0.05, 0.0], dtype=np.float32),
            np.array([0.90, 0.10, 0.0], dtype=np.float32),
            np.array([0.20, 0.80, 0.0], dtype=np.float32),
            np.array([0.10, 0.90, 0.0], dtype=np.float32),
        ]
        embedder = _FakeEmbedder(vectors, query_vec)
        report = filter_images(paths, query="red square", embedder=embedder, vlm_pass=False)
        assert report.backend == "fake"
        assert len(report.images) == 4
        assert len(report.kept) >= 1
        assert len(report.rejected) >= 1

    def test_vlm_pass_overrides_borderline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        paths = _make_images(tmp_path, 3)
        query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vectors = [
            np.array([0.95, 0.05, 0.0], dtype=np.float32),
            np.array([0.55, 0.45, 0.0], dtype=np.float32),
            np.array([0.10, 0.90, 0.0], dtype=np.float32),
        ]
        embedder = _FakeEmbedder(vectors, query_vec)

        def _fake_vlm(path: str | Path, query: str) -> dict[str, Any]:
            return {"relevant": True, "score": 0.92, "reason": "matches query"}

        monkeypatch.setattr("arka.agent.filter_images.vlm_relevance", _fake_vlm)
        report = filter_images(paths, query="test", embedder=embedder, vlm_pass=True, borderline_pct=40.0)
        borderline_items = [i for i in report.images if i.pass1_decision == "borderline"]
        for item in borderline_items:
            assert item.vlm_score == pytest.approx(0.92)
            assert item.final_decision == "keep"

    def test_hash_fallback_warns(self, tmp_path: Path) -> None:
        paths = _make_images(tmp_path, 2)

        class _Unavailable:
            available = False

        report = filter_images(paths, query="anything", embedder=_Unavailable(), vlm_pass=False)
        assert report.mode == "hash"
        assert report.warnings
        assert all(img.hash_hex for img in report.images)


class TestFilterImagesRouting:
    def test_nl_to_argv_filter(self) -> None:
        argv = nl_to_argv('filter irrelevant images in ./photos --query "laptop on desk"')
        assert argv[0] == "filter"
        assert "--query" in argv
        assert "laptop on desk" in argv

    def test_nl_to_argv_score(self) -> None:
        argv = nl_to_argv("score images for query product hero shot in ./shots")
        assert argv[0] == "score"

    def test_route_filter_images(self) -> None:
        hit = route_filter_images("find outliers in photo batch ./album")
        assert hit is not None
        assert hit.startswith("filter_images ")


class TestFilterImagesCli:
    def test_main_score_json(self, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_images(tmp_path, 2)
        query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vectors = [
            np.array([0.9, 0.1, 0.0], dtype=np.float32),
            np.array([0.2, 0.8, 0.0], dtype=np.float32),
        ]

        class _Fake:
            available = True

            class backend:
                name = "fake"

            def embed_text(self, text: str) -> np.ndarray:
                return query_vec

            def embed_image_paths(self, ps: list[str | Path]) -> list[np.ndarray]:
                return vectors

        monkeypatch.setattr("arka.vision.embeddings.ClipEmbedder", lambda *a, **k: _Fake())
        code = main(["score", str(tmp_path), "--query", "white box", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["total"] == 2

    def test_main_check(self, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _make_images(tmp_path, 1)[0]

        class _Fake:
            available = True

            class backend:
                name = "fake"

            def embed_text(self, text: str) -> np.ndarray:
                return np.array([1.0, 0.0, 0.0], dtype=np.float32)

            def embed_image_paths(self, ps: list[str | Path]) -> list[np.ndarray]:
                return [np.array([0.8, 0.2, 0.0], dtype=np.float32)]

        monkeypatch.setattr("arka.vision.embeddings.ClipEmbedder", lambda *a, **k: _Fake())
        code = main(["check", str(path), "--query", "portrait", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["images"][0]["path"] == str(path.resolve())

    def test_main_filter_copies_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_images(tmp_path, 2)
        out_dir = tmp_path / "kept"

        class _Fake:
            available = True

            class backend:
                name = "fake"

            def embed_text(self, text: str) -> np.ndarray:
                return np.array([1.0, 0.0, 0.0], dtype=np.float32)

            def embed_image_paths(self, ps: list[str | Path]) -> list[np.ndarray]:
                return [
                    np.array([0.99, 0.01, 0.0], dtype=np.float32),
                    np.array([0.10, 0.90, 0.0], dtype=np.float32),
                ]

        monkeypatch.setattr("arka.vision.embeddings.ClipEmbedder", lambda *a, **k: _Fake())
        code = main(["filter", str(tmp_path), "--query", "box", "--output", str(out_dir), "--json"])
        assert code == 0
        assert out_dir.is_dir()
        assert any(out_dir.iterdir())


class TestFilterImagesMcp:
    def test_filter_images_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _make_images(tmp_path, 1)[0]

        class _Fake:
            available = True

            class backend:
                name = "fake"

            def embed_text(self, text: str) -> np.ndarray:
                return np.array([1.0, 0.0, 0.0], dtype=np.float32)

            def embed_image_paths(self, ps: list[str | Path]) -> list[np.ndarray]:
                return [np.array([0.85, 0.15, 0.0], dtype=np.float32)]

        monkeypatch.setattr("arka.vision.embeddings.ClipEmbedder", lambda *a, **k: _Fake())
        payload = filter_images_result("check", path, query="white")
        assert payload["images"][0]["clip_score"] is not None

    def test_handle_arka_filter_images(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from arka.integrations.mcp_server import _handle_arka_filter_images

        path = _make_images(tmp_path, 1)[0]

        class _Fake:
            available = True

            class backend:
                name = "fake"

            def embed_text(self, text: str) -> np.ndarray:
                return np.array([1.0, 0.0, 0.0], dtype=np.float32)

            def embed_image_paths(self, ps: list[str | Path]) -> list[np.ndarray]:
                return [np.array([0.85, 0.15, 0.0], dtype=np.float32)]

        monkeypatch.setattr("arka.vision.embeddings.ClipEmbedder", lambda *a, **k: _Fake())
        raw = _handle_arka_filter_images({"action": "check", "path": str(path), "query": "box"})
        payload = json.loads(raw)
        assert "images" in payload

    def test_parse_vlm_json(self) -> None:
        parsed = _parse_vlm_json('Sure. {"relevant": true, "score": 0.8, "reason": "laptop visible"}')
        assert parsed["score"] == pytest.approx(0.8)
        assert parsed["relevant"] is True


def test_mcp_tool_registered() -> None:
    from arka.integrations.mcp_server import list_tool_names

    assert "arka_filter_images" in list_tool_names()
