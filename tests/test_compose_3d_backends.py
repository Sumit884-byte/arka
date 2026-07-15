"""Tests for compose_3d backends — mocked API responses (no live calls)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from arka.media.compose_3d_backends import (
    GeneratedMesh,
    _generate_tripo,
    _meshy_model_url,
    _poll_tripo_task,
    auto_backend_order,
    backend_catalog,
    generate_with_backend,
)


def test_backend_catalog_includes_tripo(monkeypatch):
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    slugs = {b.slug for b in backend_catalog()}
    assert "tripo" in slugs
    assert "hf-shap-e" in slugs
    assert "procedural" in slugs


def test_auto_backend_order_prefers_tripo_when_key_set(monkeypatch):
    monkeypatch.setenv("TRIPO_API_KEY", "tsk_test")
    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    order = auto_backend_order()
    assert "tripo" in order
    assert order.index("tripo") < order.index("llm")


def test_auto_backend_order_procedural_only():
    order = auto_backend_order(prefer_procedural=True)
    assert order == ["procedural"]


def test_configured_backend_chain_is_respected(monkeypatch):
    monkeypatch.setenv("MODEL_3D_BACKEND_CHAIN", "tripo,openscad,llm")
    assert auto_backend_order() == ["tripo", "openscad", "llm"]


def test_meshy_model_url_prefers_obj():
    task = {"model_urls": {"glb": "https://example.com/a.glb", "obj": "https://example.com/a.obj"}}
    assert _meshy_model_url(task).endswith(".obj")


def test_poll_tripo_task_success(monkeypatch):
    responses = [
        {"data": {"status": "running", "progress": 50}},
        {"data": {"status": "success", "output": {"model": "https://example.com/m.glb"}}},
    ]

    def fake_http(method, url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr("arka.media.compose_3d_backends._http_json", fake_http)
    monkeypatch.setattr("arka.media.compose_3d_backends.time.sleep", lambda _: None)
    monkeypatch.setenv("TRIPO_API_KEY", "tsk_test")
    result = _poll_tripo_task("task-123")
    assert result["output"]["model"].endswith(".glb")


def test_generate_tripo_downloads_mesh(tmp_path, monkeypatch):
    cube_obj = "\n".join(
        [
            "v 0 0 0",
            "v 1 0 0",
            "v 0 1 0",
            "v 0 0 1",
            "f 1 2 3",
            "f 1 3 4",
            "f 1 4 2",
            "f 2 4 3",
        ]
    )

    def fake_http(method, url, **kwargs):
        if method == "POST":
            return {"data": {"task_id": "abc"}}
        return {"data": {"status": "success", "output": {"model": "https://example.com/m.obj"}}}

    def fake_download(url, dest, **kwargs):
        dest.write_text(cube_obj, encoding="utf-8")
        return dest

    monkeypatch.setattr("arka.media.compose_3d_backends._http_json", fake_http)
    monkeypatch.setattr("arka.media.compose_3d_backends._poll_tripo_task", lambda _tid: {"output": {"model": "https://example.com/m.obj"}})
    monkeypatch.setattr("arka.media.compose_3d_backends._download_url", fake_download)
    monkeypatch.setenv("TRIPO_API_KEY", "tsk_test")

    mesh = _generate_tripo("a wooden chair", tmp_path)
    assert mesh.method == "Tripo AI API"
    assert len(mesh.vertices) == 4
    assert len(mesh.faces) == 4


def test_generate_with_backend_unknown_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with patch("arka.media.compose_3d_backends._has_local_shap_e", return_value=False):
        with patch("arka.media.compose_3d_backends._has_gradio_client", return_value=False):
            with pytest.raises(RuntimeError, match="All 3D backends failed"):
                generate_with_backend("dragon figurine", "auto", tmp_path)


def test_generate_with_backend_single_backend_error(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TRIPO_API_KEY not set"):
        generate_with_backend("dragon", "tripo", tmp_path)


def test_compose_backend_flag_procedural_unchanged(tmp_path, monkeypatch):
    from arka.media.compose_3d import cmd_compose
    import argparse

    monkeypatch.setenv("MODEL_3D_OUTPUT_DIR", str(tmp_path))
    args = argparse.Namespace(
        shape="cube",
        width=1.0,
        height=1.0,
        depth=1.0,
        radius=1.0,
        inner_radius=0.2,
        major_radius=1.0,
        minor_radius=0.3,
        max_radius=0.06,
        neck_radius=0.03,
        segments=None,
        rings=None,
        teeth=12,
        name="",
        quality="medium",
        backend="procedural",
        format="obj",
    )
    assert cmd_compose(args) == 0
    assert any(tmp_path.glob("cube*.obj"))


def test_compose_external_backend_mock(tmp_path, monkeypatch):
    from arka.media.compose_3d import cmd_compose
    import argparse

    monkeypatch.setenv("MODEL_3D_OUTPUT_DIR", str(tmp_path))
    fake_mesh = GeneratedMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(1, 2, 3)],
        method="Tripo AI API (test)",
    )

    with patch("arka.media.compose_3d_backends.generate_with_backend", return_value=fake_mesh):
        args = argparse.Namespace(
            shape="dragon",
            width=1.0,
            height=1.0,
            depth=1.0,
            radius=1.0,
            inner_radius=0.2,
            major_radius=1.0,
            minor_radius=0.3,
            max_radius=0.06,
            neck_radius=0.03,
            segments=None,
            rings=None,
            teeth=12,
            name="dragon",
            quality="medium",
            backend="tripo",
            format="obj",
        )
        assert cmd_compose(args) == 0
        assert any(tmp_path.glob("dragon*.obj"))
