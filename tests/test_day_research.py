"""Tests for day / interval research skill."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def research_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "arka"
    cfg.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(cfg))

    def _cfg() -> Path:
        return cfg

    monkeypatch.setattr("arka.agent.day_research._config_dir", _cfg)
    return cfg


def test_parse_duration_day_and_hours() -> None:
    from arka.agent.day_research import parse_duration

    assert parse_duration("day") == 8 * 3600
    assert parse_duration("entire day") == 8 * 3600
    assert parse_duration("4h") == 4 * 3600
    assert parse_duration("90m") == 90 * 60
    assert parse_duration("2 hours") == 2 * 3600


def test_nl_to_argv_entire_day() -> None:
    from arka.agent.day_research import nl_to_argv

    assert nl_to_argv("research quantum computing for the entire day") == [
        "start",
        "quantum computing",
        "--for",
        "day",
    ]


def test_nl_to_argv_custom_interval() -> None:
    from arka.agent.day_research import nl_to_argv

    assert nl_to_argv("research rust for 2 hours every 15 minutes") == [
        "start",
        "rust",
        "--for",
        "2h",
        "--every",
        "15m",
    ]


def test_nl_to_argv_status_stop_list() -> None:
    from arka.agent.day_research import nl_to_argv

    assert nl_to_argv("day research status") == ["status"]
    assert nl_to_argv("day research stop") == ["stop"]
    assert nl_to_argv("day research list") == ["list"]
    assert nl_to_argv("day_research digest") == ["digest"]


def test_nl_ignores_plain_research_without_duration() -> None:
    from arka.agent.day_research import nl_to_argv

    assert nl_to_argv("research quantum computing") == []
    assert nl_to_argv("youtube research about rust") == []


def test_route_day_research() -> None:
    from arka.routing.symbolic import route_day_research

    out = route_day_research("research AI agents all day")
    assert out is not None
    assert out.startswith("day_research start")
    assert "AI agents" in out
    assert "--for" in out


def test_clamp_target_words() -> None:
    from arka.agent.day_research import clamp_target_words

    assert clamp_target_words(280) == 280
    assert clamp_target_words(50) == 150
    assert clamp_target_words(900) == 450
    assert clamp_target_words("nope", default=300) == 300


def test_plan_next_angle_stores_word_budget(research_config: Path) -> None:
    from arka.agent.day_research import plan_next_angle

    session: dict = {"id": "s1", "topic": "smartwatches", "angles": []}
    planner_json = (
        '{"angle":"MIP vs AMOLED endurance","why":"extends battery thread",'
        '"extends":["r1"],"target_words":340,'
        '"focus_points":["compare always-on draw","name tradeoffs"]}'
    )
    with patch("arka.agent.day_research._llm", return_value=planner_json) as mocked:
        angle = plan_next_angle(session)

    assert angle == "MIP vs AMOLED endurance"
    assert session["_planned_words"] == 340
    assert session["_planned_focus"]
    mocked.assert_called_once()
    assert mocked.call_args.kwargs.get("role") == "planner"


def test_llm_roles_map_to_skills() -> None:
    from arka.agent.day_research import _LLM_ROLES
    from arka.llm.skill_profiles import skill_task_profile

    assert skill_task_profile(_LLM_ROLES["planner"]["skill"]) == "agent"
    assert skill_task_profile(_LLM_ROLES["executor"]["skill"]) == "summarize"


def test_default_image_searches_use_topic() -> None:
    from arka.agent.day_research import _default_image_searches

    rows = _default_image_searches({"topic": "smartwatches", "angles": ["MIP battery life"]})
    assert len(rows) == 3
    assert all(row["query"] for row in rows)
    assert "smartwatches" in rows[0]["query"]


def test_generate_session_images_uses_unsplash(research_config: Path, tmp_path: Path) -> None:
    from arka.media.unsplash import UnsplashPhoto

    from arka.agent.day_research import _generate_session_images, images_dir

    sid = "unsplash-test"
    session = {"id": sid, "topic": "smartwatches", "angles": ["battery"], "pdf_images": True}
    fake = UnsplashPhoto(
        id="abc",
        url="https://example.com/photo.jpg",
        download_url="https://example.com/dl",
        photographer="Jane Doe",
        photographer_url="https://unsplash.com/@jane",
        description="watch on desk",
    )

    def _fake_download(photo: UnsplashPhoto, dest: Path) -> Path:
        dest.write_bytes(b"fake-jpeg")
        return dest

    with (
        patch("arka.agent.day_research._plan_image_searches", return_value=[{"file": "cover", "query": "smartwatch"}]),
        patch("arka.media.unsplash.access_key", return_value="test-key"),
        patch("arka.media.unsplash.search_photos", return_value=[fake]),
        patch("arka.media.unsplash.download_photo", side_effect=_fake_download),
    ):
        paths = _generate_session_images(session, "digest text")

    assert len(paths) == 1
    assert paths[0].name == "cover.jpg"
    assert session.get("image_credits")
    assert (images_dir(sid) / "credits.json").is_file()


def test_format_inline_md_bold_and_link() -> None:
    from arka.agent.day_research import _format_inline_md

    out = _format_inline_md("**Battery** and [source](https://example.com)")
    assert "<b>Battery</b>" in out
    assert "link href" in out
    assert "example.com" in out


def test_parse_source_bullet() -> None:
    from arka.agent.day_research import _parse_source_bullet, _short_source_label

    url = "https://example.com/path/to/page"
    assert _parse_source_bullet(f"- {url}") == url
    assert _parse_source_bullet(f"* {url}") == url
    assert _parse_source_bullet(f"- [{url}]({url})") == url
    assert _parse_source_bullet("- not a url") is None
    assert "example.com" in _short_source_label(url)


def test_md_to_flowables_bold_heading() -> None:
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet

    from arka.agent.day_research import _md_to_flowables, _pdf_styles

    styles = _pdf_styles(getSampleStyleSheet(), colors)
    flow = _md_to_flowables("**Key findings**\n\n- one\n- two", styles)
    assert len(flow) >= 3


def test_md_to_flowables_hides_noise_and_defers_sources() -> None:
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Table

    from arka.agent.day_research import _md_to_flowables, _pdf_styles

    styles = _pdf_styles(getSampleStyleSheet(), colors)
    md = "\n".join(
        [
            "<!-- round 6 @ 2026-07-29 18:48 -->",
            "<!-- used_chunks: r5, r4, r1 -->",
            "## Battery life",
            "Some findings here.",
            "**Links to prior research**:",
            "- earlier angle",
            "Sources:",
            "- https://example.com/a",
            "## Display tech",
            "More findings.",
            "Sources:",
            "- https://example.com/b",
            "- https://example.com/a",
        ]
    )
    flow = _md_to_flowables(md, styles, defer_sources=True)
    texts = []
    for item in flow:
        if isinstance(item, Paragraph):
            texts.append(item.text)
        elif isinstance(item, Table):
            texts.append("TABLE")
    joined = " ".join(texts)
    assert "round 6" not in joined
    assert "used_chunks" not in joined
    assert "Links to prior research" not in joined
    assert "earlier angle" not in joined
    assert joined.count("Sources") == 1
    assert joined.count("TABLE") == 2
    assert "Battery life" in joined
    assert "Display tech" in joined


def test_start_once_round(research_config: Path) -> None:
    from arka.agent.day_research import cmd_start, list_sessions, notes_path

    with (
        patch("arka.agent.day_research.plan_next_angle", return_value="history of transformers"),
        patch("arka.agent.day_research._web_context", return_value="Transformers were introduced in 2017."),
        patch(
            "arka.agent.day_research._llm",
            return_value="## History\n\nTransformers arrived in 2017.\n\nSources:\n- paper",
        ),
    ):
        rc = cmd_start(
            argparse.Namespace(
                topic=["transformers"],
                duration="1h",
                every="30m",
                foreground=False,
                daemon=False,
                once=True,
                skip_first=False,
                light=True,
                force=False,
                no_pdf=True,
                no_images=True,
            )
        )

    assert rc == 0
    rows = list_sessions()
    assert len(rows) == 1
    assert rows[0]["rounds_done"] == 1
    assert rows[0]["topic"] == "transformers"
    notes = notes_path(rows[0]["id"]).read_text(encoding="utf-8")
    assert "History" in notes


def test_skill_manifest_exists() -> None:
    import json

    manifest = Path(__file__).parents[1] / "src/arka/skills/day_research/skill.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["name"] == "day_research"
    assert "day research" in data["triggers"]


def test_retrieve_chunks_prefers_related(research_config: Path) -> None:
    from arka.agent.day_research import retrieve_chunks, save_chunks

    sid = "test-session"
    save_chunks(
        sid,
        [
            {
                "id": "r1",
                "round": 1,
                "angle": "battery life comparison",
                "summary": "MIP displays help Garmin battery last longer than AMOLED rivals.",
                "key_points": ["MIP is power efficient", "claims are often exaggerated"],
                "open_questions": ["real world Apple Watch Ultra endurance?"],
                "tags": ["battery", "garmin", "mip"],
            },
            {
                "id": "r2",
                "round": 2,
                "angle": "heart rate sensor accuracy",
                "summary": "Optical HR is weaker during HIIT than chest straps.",
                "key_points": ["motion artifacts"],
                "open_questions": [],
                "tags": ["heart-rate", "sensors"],
            },
        ],
    )
    hits = retrieve_chunks(sid, "smartwatch battery endurance Garmin MIP", limit=2)
    assert hits
    assert hits[0]["id"] == "r1"


def test_run_round_stores_chunk_and_uses_prior(research_config: Path) -> None:
    from arka.agent.day_research import (
        cmd_start,
        list_sessions,
        load_chunks,
        load_state,
        run_round,
    )

    with (
        patch("arka.agent.day_research.plan_next_angle", return_value="battery life comparison"),
        patch("arka.agent.day_research._web_context", return_value="MIP displays save power."),
        patch(
            "arka.agent.day_research._llm",
            side_effect=[
                "## Battery\n\nMIP helps endurance.\n\nSources:\n- example.com",
                '{"summary":"MIP displays improve battery.","key_points":["MIP efficient"],'
                '"open_questions":["AMOLED tradeoffs?"],"entities":["Garmin"],"tags":["battery","mip"]}',
                '{"thesis":"Battery depends on display tech.","themes":[{"name":"battery","status":"thin","notes":"MIP helps"}],'
                '"open_questions":["AMOLED tradeoffs?"],"confident_findings":["MIP efficient"],"next_gaps":["AMOLED tradeoffs?"]}',
            ],
        ),
    ):
        rc = cmd_start(
            argparse.Namespace(
                topic=["smartwatches"],
                duration="1h",
                every="30m",
                foreground=False,
                daemon=False,
                once=True,
                skip_first=False,
                light=True,
                force=False,
                no_pdf=True,
                no_images=True,
            )
        )
    assert rc == 0
    sid = list_sessions()[0]["id"]
    chunks = load_chunks(sid)
    assert len(chunks) == 1
    assert chunks[0]["summary"]
    assert load_state(sid).get("thesis")

    session = list_sessions()[0]
    with (
        patch(
            "arka.agent.day_research.plan_next_angle",
            return_value="AMOLED vs MIP endurance tradeoffs",
        ),
        patch(
            "arka.agent.day_research._web_context",
            return_value="AMOLED looks better but drains faster.",
        ),
        patch(
            "arka.agent.day_research._llm",
            side_effect=[
                "## Tradeoffs\n\nBuilding on battery findings, AMOLED costs endurance.\n\n"
                "**Links to prior research**\n- r1 battery life\n\nSources:\n- example.com",
                '{"summary":"AMOLED looks better, MIP lasts longer.","key_points":["display tradeoff"],'
                '"open_questions":[],"entities":["AMOLED","MIP"],"tags":["battery","amoled","mip"]}',
                '{"thesis":"Display tech drives battery.","themes":[{"name":"battery","status":"solid","notes":"MIP vs AMOLED"}],'
                '"open_questions":[],"confident_findings":["MIP lasts longer"],"next_gaps":[]}',
            ],
        ),
    ):
        info = run_round(session, deep=False)

    assert info["round"] == 2
    assert len(load_chunks(sid)) == 2
    assert "r1" in info["retrieved"]
