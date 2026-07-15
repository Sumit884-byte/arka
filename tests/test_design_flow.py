def test_design_plan_accept_redo(tmp_path, monkeypatch) -> None:
    from arka.agent import design_flow
    monkeypatch.setattr(design_flow, "_path", lambda: tmp_path / "draft.json")
    assert design_flow.main(["plan", "build a dashboard"]) == 0
    assert design_flow.main(["accept"]) == 0
    assert '"status": "accepted"' in (tmp_path / "draft.json").read_text()
