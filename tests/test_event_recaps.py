"""Coverage for flagship tech events: detect, YouTube query, mix transcript + search."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from arka.agent.daily_brief import should_use_live_news_web, summarize_news_web
from arka.agent.launch_recap import (
    briefing_targets,
    is_launch_recap_question,
    launch_rewrite_prompt,
    looks_like_video_description,
    official_youtube_query,
    pick_official_video,
    sample_keynote_transcript,
    summarize_official_launch,
    tech_event_cases,
)
from arka.predict.domains import detect_domain
from arka.routing.symbolic import route_offline_extras


CASES = tech_event_cases()


@pytest.mark.parametrize("question,slug,brand,needle", CASES)
def test_every_event_is_a_launch_recap(question: str, slug: str, brand: str, needle: str) -> None:
    assert is_launch_recap_question(question), question
    assert should_use_live_news_web(question), question
    query = official_youtube_query(question)
    assert needle.split()[0] in query or needle in query
    extras = route_offline_extras(question) or ""
    assert extras.startswith("web_answer "), extras
    assert "open_url" not in extras
    assert "event.com" not in extras
    assert not extras.startswith("predict ")
    assert detect_domain(question) == "general"


def test_gtc_youtube_query_is_official_nvidia() -> None:
    q = official_youtube_query("what happened in nvidia gtc")
    assert "NVIDIA GTC" in q
    assert "keynote" in q
    assert "Jensen" in q
    assert "full" in q.lower()


def test_gtc_prefers_nvidia_channel_over_reaction() -> None:
    hits = [
        ("aaaaaaaaaaa", "GTC 2026 REACTION Vera Rubin", "ChipLeaks"),
        ("bbbbbbbbbbb", "NVIDIA GTC 2026 Keynote", "NVIDIA"),
        ("ccccccccccc", "GTC stock recap", "CNBC"),
    ]
    picked = pick_official_video(
        hits,
        brand="nvidia",
        year="2026",
        question="what happened in nvidia gtc",
    )
    assert picked is not None
    assert picked[0] == "bbbbbbbbbbb"


def test_gtc_prefers_full_keynote_over_short_teaser() -> None:
    hits = [
        ("jw_o0xr8MWU", "NVIDIA GTC 2026 Keynote", "NVIDIA", 184),
        ("bbbbbbbbbbb", "NVIDIA GTC 2026 Keynote — Full", "NVIDIA", 7380),
    ]
    picked = pick_official_video(
        hits,
        brand="nvidia",
        year="2026",
        question="what happened in nvidia gtc",
    )
    assert picked is not None
    assert picked[0] == "bbbbbbbbbbb"
    assert picked[3] >= 7000


def test_description_blurb_is_not_a_transcript() -> None:
    blurb = (
        "NVIDIA has spent 20 years building a global footprint of hundreds of millions "
        "of GPUs that run CUDA. Subscribe and visit https://nvidia.com and https://nvidianews.nvidia.com "
        "to learn more about accelerated computing cost reductions."
    )
    assert looks_like_video_description(blurb, duration_sec=7200)
    spoken = (
        "Thank you. Let me show you Vera Rubin. Next up is NVLink. "
        "All right, let's look at the rack. "
    ) * 40
    assert not looks_like_video_description(spoken, duration_sec=7200)


def test_briefing_length_scales_with_runtime() -> None:
    short_m, short_h, short_w = briefing_targets(180)
    long_m, long_h, long_w = briefing_targets(7200)
    assert short_m == 3
    assert long_m == 120
    assert long_h > short_h
    assert long_w > short_w
    assert long_w >= 1600


def test_transcript_sample_keeps_middle_announcements() -> None:
    opening = ("CUDA for twenty years. " * 3000)
    middle = ("VERA_RUBIN_MARKER announced today. " * 400)
    closing = ("Thank you GTC. " * 3000)
    text = opening + middle + closing
    sampled = sample_keynote_transcript(text, duration_sec=7200)
    assert "VERA_RUBIN_MARKER" in sampled
    assert "later in the keynote" in sampled


def test_mixed_prompt_includes_transcript_and_search() -> None:
    system, user = launch_rewrite_prompt(
        "what happened in nvidia gtc",
        title="NVIDIA GTC 2026 Keynote",
        url="https://www.youtube.com/watch?v=bbbbbbbbbbb",
        transcript="Jensen Huang: Today we introduce Vera Rubin, the successor to Blackwell.",
        web_context="Source: NVIDIA GTC 2026\nURL: https://nvidianews.nvidia.com/gtc\nVera Rubin platform announced.",
    )
    assert "transcript" in system.lower()
    assert "search" in system.lower()
    assert "Vera Rubin" in user
    assert "nvidianews.nvidia.com" in user
    assert "Keynote transcript" in user
    assert "Web search results" in user
    assert "minutes" in user.lower()


def test_skips_youtube_description_for_full_transcript() -> None:
    hits = [
        ("aaaaaaaaaaa", "NVIDIA GTC 2026 Keynote", "NVIDIA", 7200),
        ("bbbbbbbbbbb", "NVIDIA GTC 2026 Keynote", "NVIDIA", 7100),
    ]
    description = (
        "NVIDIA has spent 20 years building a global CUDA footprint. "
        "Subscribe and visit https://www.nvidia.com and https://nvidianews.nvidia.com "
        "for accelerated computing updates and cost reductions."
    )
    spoken = (
        "Thank you. Let me introduce Vera Rubin, the successor to Blackwell. "
        "Next up is the rack-scale NVLink switch. All right, let's look at the factory. "
    ) * 25
    briefing = "[FROM SEARCH]\nNVIDIA GTC 2026 introduced Vera Rubin."

    def _fake_transcript(video_id: str, **_kwargs: object) -> str:
        return description if str(video_id).startswith("aaa") else spoken

    with (
        patch("arka.youtube.transcript.youtube_search", return_value=hits),
        patch("arka.youtube.transcript.fetch_transcript_text", side_effect=_fake_transcript),
        patch("arka.llm.fallback.llm_complete", return_value=briefing) as llm,
    ):
        out = summarize_official_launch("what happened in nvidia gtc")
    assert "youtube.com/watch?v=bbbbbbbbbbb" in out
    _system, user = llm.call_args.args[:2]
    assert "Vera Rubin" in user
    assert "20 years building" not in user


def test_summarize_mixes_web_into_llm_prompt() -> None:
    hits = [("bbbbbbbbbbb", "NVIDIA GTC 2026 Keynote", "NVIDIA")]
    transcript = (
        "Welcome to GTC. I am Jensen Huang. Today we introduce the Vera Rubin architecture, "
        "the successor to Blackwell, built to scale AI factories for the next decade. "
        "Thank you. Let's look at the rack. "
    ) * 10
    briefing = (
        "[FROM SEARCH]\n"
        "NVIDIA's GTC 2026 keynote introduced the Vera Rubin platform as Blackwell's successor."
    )
    web = (
        "Source: NVIDIA GTC 2026\n"
        "URL: https://www.cnbc.com/2026/03/16/nvidia-gtc-2026.html\n"
        "Jensen Huang unveiled Vera Rubin."
    )
    with (
        patch("arka.youtube.transcript.youtube_search", return_value=hits),
        patch("arka.youtube.transcript.fetch_transcript_text", return_value=transcript),
        patch("arka.llm.fallback.llm_complete", return_value=briefing) as llm,
    ):
        out = summarize_official_launch("what happened in nvidia gtc", web_context=web)
    assert "Vera Rubin" in out
    assert "youtube.com/watch?v=bbbbbbbbbbb" in out
    _system, user = llm.call_args.args[:2]
    assert "Keynote transcript" in user
    assert "Web search results" in user
    assert "cnbc.com" in user
    assert "Vera Rubin" in user
    assert "minutes" in user.lower()


def test_news_path_passes_search_into_launch_mix() -> None:
    hits = [("bbbbbbbbbbb", "NVIDIA GTC 2026 Keynote", "NVIDIA")]
    transcript = ("Jensen Huang: Vera Rubin is the next architecture after Blackwell. " * 20)
    briefing = "[FROM SEARCH]\nNVIDIA GTC 2026 introduced Vera Rubin."
    web = "Source: GTC\nURL: https://nvidianews.nvidia.com/x\nVera Rubin."
    with (
        patch("arka.agent.daily_brief.gather_news_web_context", return_value=web),
        patch("arka.youtube.transcript.youtube_search", return_value=hits),
        patch("arka.youtube.transcript.fetch_transcript_text", return_value=transcript),
        patch("arka.llm.fallback.llm_complete", return_value=briefing),
    ):
        out = summarize_news_web("what happened in nvidia gtc")
    assert "Vera Rubin" in out


def test_apple_and_gtc_are_not_stock_predict() -> None:
    for question in (
        "what happened in nvidia gtc",
        "what happened in apple launch event",
        "what happened at wwdc",
        "what happened at google i/o",
    ):
        extras = route_offline_extras(question) or ""
        assert extras.startswith("web_answer ")
        assert detect_domain(question) == "general"
