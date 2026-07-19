from arka.agent.visual_diagnose import diagnose


def test_visual_diagnose_describes_then_diagnoses(monkeypatch, tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"pixels")
    calls = []
    def fake_describe(path, prompt):
        calls.append(prompt)
        return "description" if "Do not suggest" in prompt else '{"issues":[]}'

    monkeypatch.setattr("arka.vision.describe.describe_source", fake_describe)
    result = diagnose(str(image))
    assert len(calls) == 2
    assert result["description"] == "description"
    assert "issues" in result["diagnosis"]
