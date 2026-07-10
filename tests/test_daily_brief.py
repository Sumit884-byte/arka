"""Tests for daily brief headline URL helpers."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from arka.agent.daily_brief import (
    _excerpts_from_web_context,
    brief_search_date_boost,
    brief_url_limit_enabled,
    brief_url_words_limit,
    build_headlines_prompt,
    context_block_looks_stale,
    current_brief_date,
    fetch_brief_memory_context,
    filter_stale_brief_context,
    format_headlines_response,
    format_openai_changelog_context,
    headline_answer_instructions,
    headline_date_from_text,
    headline_looks_stale,
    headlines_scrape_kwargs,
    headlines_search_query,
    is_changelog_exempt_url,
    is_headline_preamble_line,
    is_headlines_bullet_request,
    mentions_openai,
    sanitize_brief_memory_context,
    tech_focus_from_prompt,
    truncate_words,
)


class DailyBriefPromptTests(unittest.TestCase):
    def test_build_tech_prompt_includes_url_instruction(self) -> None:
        prompt = build_headlines_prompt(tech_focus=True)
        self.assertIn("headlines", prompt.lower())
        self.assertIn("https://platform.openai.com/docs/changelog", prompt)
        self.assertIn("em dash", prompt.lower())

    def test_build_tech_prompt_includes_current_date(self) -> None:
        prompt = build_headlines_prompt(tech_focus=True)
        self.assertIn(current_brief_date(), prompt)
        self.assertIn("ONLY news published today", prompt)

    def test_build_general_prompt_includes_current_date(self) -> None:
        prompt = build_headlines_prompt(tech_focus=False)
        self.assertIn(current_brief_date(), prompt)
        self.assertIn("ONLY news published today", prompt)

    def test_build_prompt_forbids_preamble(self) -> None:
        prompt = build_headlines_prompt(tech_focus=True)
        self.assertIn("no introduction", prompt.lower())
        self.assertIn("here are n headlines", prompt.lower())

    def test_build_tech_prompt_mentions_openai_changelog(self) -> None:
        prompt = build_headlines_prompt(tech_focus=True)
        self.assertIn("OpenAI API changelog", prompt)

    def test_build_general_prompt_includes_urls(self) -> None:
        prompt = build_headlines_prompt(tech_focus=False)
        self.assertIn("em dash", prompt.lower())
        self.assertNotIn("OpenAI API changelog", prompt)

    def test_build_personalized_prompt(self) -> None:
        prompt = build_headlines_prompt(mem_ctx="AI startups in India")
        self.assertIn("AI startups in India", prompt)
        self.assertIn("em dash", prompt.lower())


    def test_build_tech_prompt_with_personalization(self) -> None:
        prompt = build_headlines_prompt(
            tech_focus=True,
            mem_ctx="Memory abc123: Sumit works on AI agents; test entry only",
        )
        self.assertIn("Personalize headline selection to:", prompt)
        self.assertIn("Sumit works on AI agents", prompt)
        self.assertNotIn("Memory abc123", prompt)
        self.assertNotIn("test entry", prompt.lower())


class BriefMemorySanitizeTests(unittest.TestCase):
    def test_sanitize_strips_ids_and_test_junk(self) -> None:
        raw = (
            "Relevant memories (Supermemory):\n"
            "- Memory 5009cae95a40 (2025-01-01): Sumit builds AI agents in India\n"
            "- Memory deadbeef1234: test entry only ignore this\n"
            "- Interested in LLM tooling and observability"
        )
        clean = sanitize_brief_memory_context(raw)
        self.assertIn("Sumit builds AI agents", clean)
        self.assertIn("LLM tooling", clean)
        self.assertNotIn("Memory 5009cae95a40", clean)
        self.assertNotIn("test entry", clean.lower())

    def test_fetch_brief_memory_context_sanitizes(self) -> None:
        from unittest import mock

        with mock.patch(
            "arka.integrations.supermemory.context_for",
            return_value="- Memory abc: Name is Sumit\n- test only memory",
        ):
            ctx = fetch_brief_memory_context("tech interests")
        self.assertIn("Name is Sumit", ctx)
        self.assertNotIn("Memory abc", ctx)
        self.assertNotIn("test only", ctx.lower())


class HeadlineFormatTests(unittest.TestCase):
    def test_is_headline_preamble_line_detects_intro(self) -> None:
        intro = (
            "• Here are 7 concise tech news headlines for today, July 10, 2026, "
            "covering AI, startups, developer tools, and major tech industry news."
        )
        self.assertTrue(is_headline_preamble_line(intro))
        self.assertFalse(
            is_headline_preamble_line(
                "- OpenAI releases GPT-5.6 — https://platform.openai.com/docs/changelog"
            )
        )

    def test_format_headlines_response_strips_preamble(self) -> None:
        raw = (
            "[FROM SEARCH]\n"
            "• Here are 7 concise tech news headlines for today, July 10, 2026, "
            "covering AI, startups, developer tools, and major tech industry news.\n"
            "- OpenAI releases GPT-5.6 model family — https://platform.openai.com/docs/changelog\n"
            "- OpenAI plans to acquire Ona — https://openai.com/index/openai-to-acquire-ona/"
        )
        formatted = format_headlines_response(raw)
        self.assertNotIn("Here are 7", formatted)
        self.assertNotIn("covering AI", formatted)
        self.assertNotIn("[FROM SEARCH]", formatted)
        lines = [ln for ln in formatted.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 2)
        self.assertIn("GPT-5.6 model family", lines[0])
        self.assertIn("acquire Ona", lines[1])

    def test_format_headlines_response_filters_stale_headlines(self) -> None:
        raw = (
            "- OpenAI ships GPT-4 in 2023 — https://example.com/old\n"
            "- OpenAI releases GPT-5.6 — https://example.com/new"
        )
        formatted = format_headlines_response(raw)
        self.assertIn("GPT-5.6", formatted)
        self.assertNotIn("GPT-4", formatted)

    def test_headline_looks_stale(self) -> None:
        self.assertTrue(headline_looks_stale("Best AI tools of 2023", ref_year=2026))
        self.assertFalse(headline_looks_stale("OpenAI releases GPT-5.6", ref_year=2026))

    def test_headline_looks_stale_rejects_jul_9_when_today_jul_10(self) -> None:
        today = date(2026, 7, 10)
        self.assertTrue(
            headline_looks_stale(
                "OpenAI Engineering fixes an 18-year-old bug",
                context="Published Jul 9, 2026 on openai.com/news",
                ref_date=today,
            )
        )
        self.assertTrue(
            headline_looks_stale(
                "OpenAI ships feature",
                context="2026-07-09",
                ref_date=today,
            )
        )
        self.assertTrue(
            headline_looks_stale(
                "OpenAI ships feature",
                context="July 9, 2026",
                ref_date=today,
            )
        )
        self.assertFalse(
            headline_looks_stale(
                "OpenAI ships feature",
                context="July 10, 2026",
                ref_date=today,
            )
        )

    def test_changelog_url_not_stale(self) -> None:
        today = date(2026, 7, 10)
        self.assertFalse(
            headline_looks_stale(
                "GPT-5.6 models add Programmatic Tool Calling",
                context="Updated last month",
                url="https://platform.openai.com/docs/changelog",
                ref_date=today,
            )
        )
        self.assertTrue(is_changelog_exempt_url("https://platform.openai.com/docs/changelog"))

    def test_headline_date_from_text(self) -> None:
        self.assertEqual(headline_date_from_text("Posted Jul 9, 2026"), date(2026, 7, 9))
        self.assertEqual(headline_date_from_text("2026-07-10"), date(2026, 7, 10))
        self.assertEqual(headline_date_from_text("July 10"), date(2026, 7, 10))

    def test_filter_stale_brief_context_drops_yesterday(self) -> None:
        today = date(2026, 7, 10)
        web = (
            "Source: Old OpenAI story\n"
            "URL: https://openai.com/news/old-story\n"
            "Published July 9, 2026\n\n"
            "Source: Fresh story\n"
            "URL: https://example.com/fresh\n"
            "Published July 10, 2026"
        )
        filtered = filter_stale_brief_context(web, ref_date=today)
        self.assertNotIn("openai.com/news/old-story", filtered)
        self.assertIn("example.com/fresh", filtered)

    def test_filter_stale_brief_context_keeps_changelog(self) -> None:
        today = date(2026, 7, 10)
        web = (
            "[OpenAI changelog/news sources]\n"
            "- API Changelog — https://platform.openai.com/docs/changelog\n"
            "  Mentioned July 9, 2026 in an older entry."
        )
        filtered = filter_stale_brief_context(web, ref_date=today)
        self.assertIn("platform.openai.com/docs/changelog", filtered)

    def test_format_headlines_response_filters_dated_yesterday(self) -> None:
        today = date(2026, 7, 10)
        raw = (
            "- OpenAI Engineering fixes an 18-year-old bug — https://openai.com/news/bug\n"
            "- Fresh launch today — https://example.com/new"
        )
        web = (
            "Source: OpenAI Engineering fixes an 18-year-old bug\n"
            "URL: https://openai.com/news/bug\n"
            "Published Jul 9, 2026\n\n"
            "Source: Fresh launch today\n"
            "URL: https://example.com/new\n"
            "Published July 10, 2026"
        )
        formatted = format_headlines_response(raw, web_context=web)
        self.assertNotIn("18-year-old bug", formatted)
        self.assertIn("Fresh launch today", formatted)
        self.assertIn("https://example.com/new", formatted)
        self.assertEqual(headline_looks_stale("x", context="Jul 9, 2026", ref_date=today), True)

    def test_brief_search_date_boost_prefers_today(self) -> None:
        today = date(2026, 7, 10)
        self.assertGreater(
            brief_search_date_boost(
                "tech news headlines today",
                "Story",
                "Published July 10, 2026",
                ref_date=today,
            ),
            0,
        )
        self.assertLess(
            brief_search_date_boost(
                "tech news headlines today",
                "Story",
                "Published Jul 9, 2026",
                ref_date=today,
            ),
            0,
        )

    def test_format_headlines_response_normalizes_inline_bullets(self) -> None:
        raw = "[FROM SEARCH]\n*   OpenAI ships new API *   Google launches Gemini"
        formatted = format_headlines_response(raw)
        self.assertIn("- OpenAI ships new API", formatted)
        self.assertIn("- Google launches Gemini", formatted)
        self.assertNotIn("*", formatted)

    def test_format_headlines_response_attaches_urls_from_context(self) -> None:
        raw = "[FROM SEARCH]\n- OpenAI API changelog update"
        web = (
            "[OpenAI changelog/news sources]\n"
            "- OpenAI API changelog update — https://platform.openai.com/docs/changelog"
        )
        formatted = format_headlines_response(raw, web_context=web)
        self.assertIn("https://platform.openai.com/docs/changelog", formatted)

    def test_format_preserves_existing_urls(self) -> None:
        raw = "- New model — https://openai.com/index/new-model"
        formatted = format_headlines_response(raw)
        self.assertIn("https://openai.com/index/new-model", formatted)

    def test_format_splits_concatenated_headlines_on_one_line(self) -> None:
        raw = (
            "• OpenAI unveils GPT-5.6 Sol, Terra, and Luna models — "
            "https://community.openai.com/t/gpt-5-6 - GPT-5.6 models add Programmatic "
            "Tool Calling — https://platform.openai.com/docs/changelog - "
            "OpenAI releases GPT-Realtime-2.1 — https://openai.com/index/gpt-realtime-2-1"
        )
        formatted = format_headlines_response(raw)
        lines = [ln for ln in formatted.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 3)
        self.assertIn("GPT-5.6 Sol, Terra, and Luna", lines[0])
        self.assertIn("https://community.openai.com/t/gpt-5-6", lines[0])
        self.assertIn("Programmatic Tool Calling", lines[1])
        self.assertIn("https://platform.openai.com/docs/changelog", lines[1])
        self.assertIn("GPT-Realtime-2.1", lines[2])
        self.assertIn("https://openai.com/index/gpt-realtime-2-1", lines[2])

    def test_format_deduplicates_identical_urls(self) -> None:
        raw = (
            "- First headline — https://example.com/a - "
            "Second headline — https://example.com/a - "
            "Third headline — https://example.com/b"
        )
        formatted = format_headlines_response(raw)
        lines = [ln for ln in formatted.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 2)
        self.assertIn("https://example.com/a", lines[0])
        self.assertIn("https://example.com/b", lines[1])

    def test_format_adds_excerpt_when_brief_url_words_set(self) -> None:
        from unittest import mock

        web = (
            "Source: OpenAI ships GPT-5\n"
            "URL: https://openai.com/index/gpt-5\n"
            "OpenAI announced a major model release with improved reasoning and lower latency."
        )
        raw = "- OpenAI ships GPT-5 — https://openai.com/index/gpt-5"
        with mock.patch("arka.agent.daily_brief.brief_url_words_limit", return_value=6):
            formatted = format_headlines_response(raw, web_context=web)
        self.assertIn("- OpenAI ships GPT-5 — https://openai.com/index/gpt-5", formatted)
        self.assertIn(
            "  OpenAI announced a major model release…",
            formatted,
        )

    def test_format_skips_excerpt_when_brief_url_words_zero(self) -> None:
        from unittest import mock

        web = (
            "Source: OpenAI ships GPT-5\n"
            "URL: https://openai.com/index/gpt-5\n"
            "OpenAI announced a major model release."
        )
        raw = "- OpenAI ships GPT-5 — https://openai.com/index/gpt-5"
        with mock.patch("arka.agent.daily_brief.brief_url_words_limit", return_value=0):
            formatted = format_headlines_response(raw, web_context=web)
        lines = formatted.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("- "))


class BriefUrlWordsTests(unittest.TestCase):
    def test_truncate_words_adds_ellipsis(self) -> None:
        self.assertEqual(
            truncate_words("one two three four five", 3),
            "one two three…",
        )

    def test_brief_url_limit_enabled_from_env(self) -> None:
        from unittest import mock

        with mock.patch.dict(
            "os.environ",
            {"BRIEF_URL_LIMIT_ENABLED": "1", "BRIEF_URL_WORDS": "12"},
            clear=False,
        ):
            self.assertTrue(brief_url_limit_enabled())
            self.assertEqual(brief_url_words_limit(), 12)

    def test_brief_url_limit_disabled_explicit(self) -> None:
        from unittest import mock

        with mock.patch.dict(
            "os.environ",
            {"BRIEF_URL_LIMIT_ENABLED": "0", "BRIEF_URL_WORDS": "30"},
            clear=False,
        ):
            self.assertFalse(brief_url_limit_enabled())
            self.assertEqual(brief_url_words_limit(), 0)

    def test_brief_url_limit_legacy_words_zero(self) -> None:
        from unittest import mock

        env = {"BRIEF_URL_LIMIT_ENABLED": "", "BRIEF_URL_WORDS": "0"}
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertFalse(brief_url_limit_enabled())
            self.assertEqual(brief_url_words_limit(), 0)

    def test_brief_url_limit_legacy_words_positive(self) -> None:
        from unittest import mock

        env = {"BRIEF_URL_LIMIT_ENABLED": "", "BRIEF_URL_WORDS": "15"}
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertTrue(brief_url_limit_enabled())
            self.assertEqual(brief_url_words_limit(), 15)

    def test_headlines_scrape_kwargs_snippet_only_by_default(self) -> None:
        from unittest import mock

        with mock.patch("arka.agent.daily_brief.brief_url_words_limit", return_value=0):
            opts = headlines_scrape_kwargs()
        self.assertEqual(opts["per_page_words"], 0)
        self.assertEqual(opts["min_words"], 0)
        self.assertEqual(opts["hard_limit"], 10)

    def test_headlines_scrape_kwargs_respects_limit(self) -> None:
        from unittest import mock

        with mock.patch("arka.agent.daily_brief.brief_url_words_limit", return_value=30):
            opts = headlines_scrape_kwargs()
        self.assertEqual(opts["per_page_words"], 30)

    def test_excerpts_from_openai_changelog_block(self) -> None:
        web = (
            "[OpenAI changelog/news sources]\n"
            "- API Changelog — https://platform.openai.com/docs/changelog\n"
            "  New models added to the API with improved tool calling support."
        )
        excerpts = _excerpts_from_web_context(web, max_words=5)
        self.assertIn("https://platform.openai.com/docs/changelog", excerpts)
        self.assertEqual(
            excerpts["https://platform.openai.com/docs/changelog"],
            "New models added to the…",
        )


class HeadlineScrapeTests(unittest.TestCase):
    def test_scrape_search_results_snippet_only_for_headlines(self) -> None:
        from unittest import mock

        from arka.agent.chat import scrape_search_results

        results = [
            {
                "title": "Tech story",
                "link": "https://example.com/story",
                "snippet": "A short search snippet about the story.",
            }
        ]
        with (
            mock.patch("arka.agent.chat.duckduckgo_search", return_value=results),
            mock.patch("arka.agent.chat.scrape_url") as scrape_mock,
        ):
            out = scrape_search_results(
                "tech headlines today",
                min_words=0,
                hard_limit=5,
                per_page_words=0,
            )
        scrape_mock.assert_not_called()
        self.assertIn("https://example.com/story", out)
        self.assertIn("short search snippet", out)

    def test_scrape_search_results_truncates_page_for_headlines(self) -> None:
        from unittest import mock

        from arka.agent.chat import scrape_search_results

        results = [
            {
                "title": "Tech story",
                "link": "https://example.com/story",
                "snippet": "Snippet.",
            }
        ]
        long_page = " ".join(f"word{i}" for i in range(1, 60))
        with (
            mock.patch("arka.agent.chat.duckduckgo_search", return_value=results),
            mock.patch("arka.agent.chat._scrape_page", return_value=(long_page, "")),
        ):
            out = scrape_search_results(
                "tech headlines today",
                min_words=0,
                hard_limit=5,
                per_page_words=10,
            )
        self.assertIn("word1 word2 word3 word4 word5 word6 word7 word8 word9 word10…", out)
        self.assertNotIn("word11", out)


class DailyBriefDetectionTests(unittest.TestCase):
    def test_is_headlines_bullet_request(self) -> None:
        self.assertTrue(
            is_headlines_bullet_request(
                "Give 5-7 concise tech news headlines for today in bullet points"
            )
        )
        self.assertFalse(is_headlines_bullet_request("what is Python?"))

    def test_tech_focus_from_prompt(self) -> None:
        self.assertTrue(tech_focus_from_prompt("Give tech news headlines"))
        self.assertFalse(tech_focus_from_prompt("Give top news headlines"))

    def test_mentions_openai(self) -> None:
        self.assertTrue(mentions_openai("OpenAI released GPT-5"))
        self.assertTrue(mentions_openai("tech news", "OpenAI changelog update"))
        self.assertFalse(mentions_openai("Google Cloud news"))


class OpenAIChangelogFormatTests(unittest.TestCase):
    def test_format_openai_changelog_context(self) -> None:
        ctx = format_openai_changelog_context(
            [
                {
                    "title": "API Changelog",
                    "link": "https://platform.openai.com/docs/changelog",
                    "snippet": "New models added.",
                },
                {
                    "title": "Random blog",
                    "link": "https://example.com/openai",
                    "snippet": "Not official.",
                },
                {
                    "title": "OpenAI Blog Post",
                    "link": "https://openai.com/index/new-model",
                    "snippet": "We are announcing a new model.",
                },
            ]
        )
        self.assertIn("platform.openai.com/docs/changelog", ctx)
        self.assertIn("openai.com/index/new-model", ctx)
        self.assertNotIn("example.com", ctx)

    def test_headline_answer_instructions_for_tech_brief(self) -> None:
        question = "Give 5-7 concise tech news headlines for today in bullet points"
        extra = headline_answer_instructions(question)
        self.assertIn("em dash", extra.lower())
        self.assertIn("platform.openai.com/docs/changelog", extra)
        self.assertIn(current_brief_date(), extra)
        self.assertIn("no introduction", extra.lower())
        self.assertIn("here are n headlines", extra.lower())
        self.assertIn("ONLY news published today", extra)

    def test_headlines_search_query_includes_date_for_tech_brief(self) -> None:
        question = "Give 5-7 concise tech news headlines for today in bullet points"
        query = headlines_search_query(question)
        self.assertIn(str(datetime.now().year), query)
        self.assertIn("tech news", query.lower())
        self.assertIn("latest", query.lower())
        self.assertIn("today", query.lower())
        month_day = datetime.now().strftime("%B %d")
        self.assertIn(month_day, query)

    def test_headlines_search_query_appends_date_for_general_brief(self) -> None:
        question = "Give 5 brief top news headlines for today in bullet points"
        query = headlines_search_query(question)
        month = datetime.now().strftime("%B")
        self.assertIn(month, query)
        self.assertIn("today", query.lower())

    def test_headline_answer_instructions_skips_non_headlines(self) -> None:
        self.assertEqual(headline_answer_instructions("what is rust?"), "")


if __name__ == "__main__":
    unittest.main()
