import json
from pathlib import Path


def test_video_evidence_routes_architecture_pr_and_bug():
    from arka.agent.video_evidence import route_command
    from arka.routing.symbolic import route_offline_extras

    assert route_command("turn architecture whiteboard meeting.mp4 into docs") == "video_evidence architecture meeting.mp4"
    assert route_command("summarize screen recording bug.mp4 as PR reproduction steps") == "video_evidence pr bug.mp4"
    assert route_command("convert Loom bug report bug.mov into a Jira ticket") == "video_evidence bug bug.mov"
    assert route_offline_extras("make a Jam-style ticket from ui-regression.webm") == "video_evidence bug ui-regression.webm"


def test_build_artifact_uses_kind_specific_sections(monkeypatch):
    from arka.agent import video_evidence

    monkeypatch.setattr(video_evidence, "_describe", lambda source, kind, frames: "frame evidence")

    artifact = video_evidence.build_artifact("meeting.mp4", "architecture")

    assert artifact["kind"] == "architecture"
    assert artifact["analysis"] == "frame evidence"
    assert "Code stubs" in artifact["sections"]


def test_write_markdown_and_json(monkeypatch, tmp_path):
    from arka.agent import video_evidence

    monkeypatch.setattr(video_evidence, "_describe", lambda source, kind, frames: "step 1 clicked login")
    artifact = video_evidence.build_artifact("bug.mp4", "bug")

    md = video_evidence.write_artifact(artifact, tmp_path / "ticket.md")
    js = video_evidence.write_artifact(artifact, tmp_path / "ticket.json", fmt="json")

    assert "# Video bug report ticket" in md.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["kind"] == "bug"


def test_cli_writes_pr_context(monkeypatch, tmp_path, capsys):
    from arka.agent import video_evidence

    monkeypatch.setattr(video_evidence, "_describe", lambda source, kind, frames: "repro evidence")
    out = tmp_path / "pr.md"

    assert video_evidence.main(["pr", "repro.mp4", "--output", str(out)]) == 0
    assert out.is_file()
    assert "PR video reproduction context" in out.read_text(encoding="utf-8")
    assert str(out) in capsys.readouterr().out


def test_skill_manifest_exists():
    manifest = Path(__file__).parents[1] / "src/arka/skills/video_evidence/skill.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["name"] == "video_evidence"
    assert "video bug report to jira ticket" in data["triggers"]
