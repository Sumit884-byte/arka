from unittest.mock import patch

from arka.agent.launch_recap import (
    format_launch_briefing,
    is_launch_recap_question,
    launch_rewrite_prompt,
    official_youtube_query,
    pick_official_video,
    score_official_video,
    summarize_official_launch,
)


def test_detects_apple_launch_question() -> None:
    assert is_launch_recap_question("what apple launched in 2026")
    assert is_launch_recap_question("what did Apple announce at the event")
    assert not is_launch_recap_question("who is current finance minister of usa")


def test_official_query_uses_year_and_keynote() -> None:
    q = official_youtube_query("what apple launched in 2026")
    assert "Apple Event 2026" in q
    assert "keynote" in q


def test_prefers_official_apple_channel() -> None:
    hits = [
        ("aaaaaaaaaaa", "Apple Event 2026 REACTION", "TechLeak"),
        ("bbbbbbbbbbb", "Apple Event 2026", "Apple"),
        ("ccccccccccc", "iPhone 18 rumors", "Random Channel"),
    ]
    picked = pick_official_video(hits, brand="apple", year="2026")
    assert picked is not None
    assert picked[0] == "bbbbbbbbbbb"
    assert score_official_video("Apple Event 2026", "Apple", brand="apple", year="2026") > (
        score_official_video("Apple Event 2026 REACTION", "TechLeak", brand="apple", year="2026")
    )


def test_summarize_rewrites_transcript_not_paste() -> None:
    hits = [("bbbbbbbbbbb", "Apple Event 2026", "Apple")]
    transcript = (
        "Good morning. Welcome to Apple Park. Today we are excited to introduce iPhone 18 Pro, "
        "iPhone 18 Pro Max, and our first foldable iPhone Duo, plus Apple Watch Series 12. "
        "Let's take a look. Wow. Thank you. One more thing. AirPods Pro. "
    ) * 8
    briefing = (
        "[FROM SEARCH]\n"
        "Apple's 2026 event introduced iPhone 18 Pro, iPhone 18 Pro Max, "
        "a foldable iPhone Duo, and Watch Series 12."
    )
    with (
        patch("arka.youtube.transcript.youtube_search", return_value=hits),
        patch("arka.youtube.transcript.fetch_transcript_text", return_value=transcript),
        patch("arka.llm.fallback.llm_complete", return_value=briefing) as llm,
    ):
        out = summarize_official_launch("what apple launched in 2026")
    assert "iPhone 18 Pro" in out
    assert "Good morning" not in out
    assert "youtube.com/watch?v=bbbbbbbbbbb" in out
    system, user = llm.call_args.args[:2]
    assert "keynote transcript" in system.lower()
    assert "Good morning" in user
    _, prompt = launch_rewrite_prompt(
        "what apple launched in 2026",
        title="Apple Event 2026",
        url="https://www.youtube.com/watch?v=bbbbbbbbbbb",
        transcript=transcript,
        duration_sec=4800,
    )
    assert "Mix the transcript and search" in prompt
    assert "full overview sentence" in prompt
    assert "80 minutes" in prompt


def test_unsquashes_smashed_product_heading() -> None:
    raw = (
        "iPhone 18 Pro Apple introduced the iPhone 18 Pro, featuring a new hardware architecture.\n\n"
        "Siri AI and Apple Intelligence The iPhone 18 Pro debuts Siri AI."
    )
    out = format_launch_briefing(raw)
    assert out.startswith("iPhone 18 Pro\n\nApple introduced")
    assert "Siri AI and Apple Intelligence\n\nThe iPhone 18 Pro debuts" in out
    assert "iPhone 18 Pro Apple introduced" not in out
