"""Tests for X/Twitter post parsing, shorten logic, and routing."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.integrations.x_post import (
    _MAX_TWEET_CHARS,
    bird_exec_prefix,
    bird_npm_missing_message,
    bird_subprocess_timeout,
    build_post_x_argv_from_nl,
    build_symbolic_allowed_urls,
    collect_source_urls,
    compose_tweet,
    count_words,
    ensure_bird_exec_prefix,
    extract_urls_from_text,
    git_remote_github_url,
    install_bird,
    is_blocked_github_url,
    main,
    parse_post_x_request,
    parse_word_limit,
    pick_link_url,
    post_tweet,
    post_url_to_x,
    post_via_bird,
    reset_bird_install_cache,
    resolve_source_url,
    sanitize_shortened_post,
    scrape_linkedin_post,
    shorten_post,
    strip_all_urls,
    strip_hashtags_not_in_source,
    strip_urls_not_in_source,
    symbolic_verify_urls,
    truncate_words,
    url_in_source_verbatim,
    verify_bird_binary,
    x_auth_configured,
)

MOCK_LINKEDIN_ARTICLE = (
    "Thrilled that Arka was accepted into the Mintlify Open Source Program! "
    "We now have Mintlify Pro to improve our documentation experience for every user. "
    "Huge thanks to the Mintlify team for supporting open-source projects like ours. "
    "Looking forward to making it easier for everyone to get started with Arka. "
    "Repo: https://github.com/Sumit884-byte/arka "
    "#OpenSource #Mintlify #Documentation"
)


class PostXParseTests(unittest.TestCase):
    def test_parse_post_linkedin_on_x(self) -> None:
        cmd = "post this https://www.linkedin.com/posts/foo on my x"
        parsed = parse_post_x_request(cmd)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["url"], "https://www.linkedin.com/posts/foo")
        self.assertEqual(parsed["words"], 40)

    def test_parse_shorten_and_post_followup(self) -> None:
        cmd = "shorten the post from linkedin to <=40 words and then post it on x"
        parsed = parse_post_x_request(cmd)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["url"], "")
        self.assertEqual(parsed["words"], 40)

    def test_rejects_monitor_twitter(self) -> None:
        self.assertIsNone(parse_post_x_request("monitor twitter @elonmusk"))

    def test_build_argv_with_url(self) -> None:
        argv = build_post_x_argv_from_nl(
            "share https://example.com/article on twitter in 25 words"
        )
        self.assertEqual(
            argv,
            ["post", "https://example.com/article", "--words", "25"],
        )

    def test_build_argv_from_session_when_no_url(self) -> None:
        argv = build_post_x_argv_from_nl(
            "shorten the linkedin post and post it on my x"
        )
        self.assertEqual(argv, ["post", "--from-session"])

    def test_parse_word_limit_variants(self) -> None:
        self.assertEqual(parse_word_limit("in 30 words"), 30)
        self.assertEqual(parse_word_limit("<=40 words"), 40)
        self.assertEqual(parse_word_limit("give a 25-word summary"), 25)


class PostXUrlGuardTests(unittest.TestCase):
    def test_extract_urls_from_text_finds_github(self) -> None:
        urls = extract_urls_from_text(MOCK_LINKEDIN_ARTICLE)
        self.assertIn("https://github.com/Sumit884-byte/arka", urls)

    def test_collect_source_urls_includes_page_and_body(self) -> None:
        page = "https://www.linkedin.com/posts/foo"
        urls = collect_source_urls(MOCK_LINKEDIN_ARTICLE, page)
        self.assertIn(page, urls)
        self.assertIn("https://github.com/Sumit884-byte/arka", urls)

    def test_pick_link_url_prefers_github(self) -> None:
        page = "https://www.linkedin.com/posts/foo"
        urls = collect_source_urls(MOCK_LINKEDIN_ARTICLE, page)
        self.assertEqual(pick_link_url(urls, page), "https://github.com/Sumit884-byte/arka")

    def test_strip_invented_github_url(self) -> None:
        allowed = collect_source_urls(MOCK_LINKEDIN_ARTICLE, "https://linkedin.com/posts/x")
        hallucinated = (
            "Arka joined Mintlify Open Source Program. "
            "Check it out: https://github.com/arkahq/arka"
        )
        cleaned = strip_urls_not_in_source(hallucinated, allowed)
        self.assertNotIn("arkahq", cleaned)
        self.assertNotIn("github.com", cleaned)

    def test_strip_invented_hashtags(self) -> None:
        draft = "Arka joined Mintlify #OpenSource #Mintlify #AI #BuildInPublic #GitHub"
        cleaned = strip_hashtags_not_in_source(draft, MOCK_LINKEDIN_ARTICLE)
        self.assertIn("#OpenSource", cleaned)
        self.assertIn("#Mintlify", cleaned)
        self.assertNotIn("#AI", cleaned)
        self.assertNotIn("#BuildInPublic", cleaned)
        self.assertNotIn("#GitHub", cleaned)

    def test_sanitize_removes_hallucinated_link_and_caps_words(self) -> None:
        allowed = collect_source_urls(MOCK_LINKEDIN_ARTICLE, "https://linkedin.com/posts/x")
        draft = (
            "Excited to share that Arka has been accepted into the Mintlify Open Source Program! "
            "We now have access to Mintlify Pro to build a better documentation experience. "
            "Huge thanks to the Mintlify team for supporting open-source. "
            "Looking forward to making it easier for everyone to get started. "
            "Check it out: https://github.com/arkahq/arka "
            "#OpenSource #Mintlify #Documentation #DeveloperTools #GitHub #AI #BuildInPublic"
        )
        out = sanitize_shortened_post(
            draft,
            source_text=MOCK_LINKEDIN_ARTICLE,
            allowed_urls=allowed,
            max_words=40,
        )
        self.assertLessEqual(count_words(out), 40)
        self.assertNotIn("arkahq", out)
        self.assertNotIn("#AI", out)
        self.assertNotIn("#BuildInPublic", out)

    def test_compose_tweet_uses_allowed_github_only(self) -> None:
        allowed = collect_source_urls(MOCK_LINKEDIN_ARTICLE, "https://linkedin.com/posts/x")
        body = "Arka joined the Mintlify Open Source Program with Mintlify Pro for docs."
        tweet = compose_tweet(
            body,
            "https://github.com/Sumit884-byte/arka",
            allowed_urls=allowed,
            source_text=MOCK_LINKEDIN_ARTICLE,
        )
        self.assertIn("https://github.com/Sumit884-byte/arka", tweet)
        self.assertNotIn("arkahq", tweet)

    def test_strip_all_urls_removes_hallucinated_github(self) -> None:
        text = "Great news. Check it out: https://github.com/arkahq/arka"
        cleaned = strip_all_urls(text)
        self.assertNotIn("github.com", cleaned)
        self.assertNotIn("arkahq", cleaned)

    def test_symbolic_verify_rejects_arkahq(self) -> None:
        allowed = collect_source_urls(MOCK_LINKEDIN_ARTICLE, "https://linkedin.com/posts/x")
        body = "Arka joined Mintlify. Check it out: https://github.com/arkahq/arka"
        cleaned, accepted, rejected = symbolic_verify_urls(
            body,
            source_text=MOCK_LINKEDIN_ARTICLE,
            allowed_urls=allowed,
        )
        self.assertNotIn("arkahq", cleaned)
        self.assertNotIn("github.com", cleaned)
        self.assertEqual(accepted, [])
        self.assertTrue(any("arkahq" in r for r in rejected))

    def test_is_blocked_github_url_blocks_arkahq(self) -> None:
        self.assertTrue(
            is_blocked_github_url(
                "https://github.com/arkahq/arka",
                MOCK_LINKEDIN_ARTICLE,
            )
        )
        self.assertFalse(
            is_blocked_github_url(
                "https://github.com/Sumit884-byte/arka",
                MOCK_LINKEDIN_ARTICLE,
            )
        )

    def test_url_in_source_verbatim(self) -> None:
        self.assertTrue(
            url_in_source_verbatim(
                "https://github.com/Sumit884-byte/arka",
                MOCK_LINKEDIN_ARTICLE,
            )
        )
        self.assertFalse(
            url_in_source_verbatim(
                "https://github.com/arkahq/arka",
                MOCK_LINKEDIN_ARTICLE,
            )
        )

    def test_build_symbolic_allowed_urls_git_remote_fallback(self) -> None:
        article = (
            "Thrilled that Arka was accepted into the Mintlify Open Source Program! "
            "Huge thanks to the Mintlify team for supporting open-source projects."
        )
        with mock.patch(
            "arka.integrations.x_post.git_remote_github_url",
            return_value="https://github.com/Sumit884-byte/arka",
        ):
            urls, meta = build_symbolic_allowed_urls(article, "https://linkedin.com/posts/x")
        self.assertIn("https://github.com/Sumit884-byte/arka", urls)
        self.assertEqual(meta.get("from_git_remote"), "https://github.com/Sumit884-byte/arka")

    def test_llm_hallucination_stripped_compose_uses_source_github(self) -> None:
        allowed = collect_source_urls(MOCK_LINKEDIN_ARTICLE, "https://linkedin.com/posts/x")
        llm_body = (
            "Arka joined Mintlify Open Source Program. "
            "Check it out: https://github.com/arkahq/arka"
        )
        tweet = compose_tweet(
            llm_body,
            "https://github.com/Sumit884-byte/arka",
            allowed_urls=allowed,
            source_text=MOCK_LINKEDIN_ARTICLE,
        )
        self.assertIn("https://github.com/Sumit884-byte/arka", tweet)
        self.assertNotIn("arkahq", tweet)
        self.assertNotIn("Check it out:", tweet)


class PostXLinkedInScrapeTests(unittest.TestCase):
    def test_scrape_linkedin_prefers_candidate_with_github(self) -> None:
        page_html = """
        <html><head>
        <meta property="og:description" content="Short update about Arka and Mintlify." />
        <meta name="description" content="Arka joined Mintlify Open Source Program.
        https://github.com/Sumit884-byte/arka #OpenSource #Mintlify" />
        </head><body></body></html>
        """
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = page_html.encode()
            text = scrape_linkedin_post("https://www.linkedin.com/posts/example")
        self.assertIn("https://github.com/Sumit884-byte/arka", text)


class PostXShortenTests(unittest.TestCase):
    def test_truncate_words_hard_cap(self) -> None:
        text = " ".join(f"w{i}" for i in range(50))
        clipped = truncate_words(text, 10)
        self.assertEqual(count_words(clipped), 10)
        self.assertTrue(clipped.endswith("…"))

    def test_shorten_post_uses_llm_then_caps(self) -> None:
        long = " ".join(f"word{i}" for i in range(80))
        still_long = " ".join(f"keep{i}" for i in range(50))
        with mock.patch("arka.llm.cli.llm_complete", return_value=still_long):
            out = shorten_post(long, max_words=12, source_url="https://example.com")
        self.assertLessEqual(count_words(out), 12)

    def test_shorten_post_sanitizes_hallucinated_urls(self) -> None:
        long = MOCK_LINKEDIN_ARTICLE + " " + "extra " * 80
        bad_llm = (
            "Arka is in the Mintlify Open Source Program with Mintlify Pro for docs. "
            "Check it out: https://github.com/arkahq/arka "
            "#OpenSource #Mintlify #AI #BuildInPublic"
        )
        allowed = collect_source_urls(long, "https://linkedin.com/posts/x")
        with mock.patch("arka.llm.cli.llm_complete", return_value=bad_llm):
            out = shorten_post(
                long,
                max_words=40,
                source_url="https://linkedin.com/posts/x",
                source_urls=allowed,
            )
        self.assertLessEqual(count_words(out), 40)
        self.assertNotIn("arkahq", out)
        self.assertNotIn("#AI", out)
        self.assertNotIn("#BuildInPublic", out)

    def test_shorten_post_no_llm_when_already_short(self) -> None:
        short = "A concise update about product launch today."
        with mock.patch("arka.llm.cli.llm_complete") as llm:
            out = shorten_post(short, max_words=40)
        llm.assert_not_called()
        self.assertEqual(out, short)

    def test_compose_tweet_appends_url(self) -> None:
        tweet = compose_tweet("Hello world", "https://linkedin.com/post/1")
        self.assertIn("https://linkedin.com/post/1", tweet)
        self.assertLessEqual(len(tweet), 280)

    def test_compose_tweet_truncates_body_to_fit_url(self) -> None:
        url = "https://github.com/Sumit884-byte/arka"
        body = "word " * 80  # far over 280 chars with URL
        tweet = compose_tweet(body.strip(), url)
        self.assertLessEqual(len(tweet), _MAX_TWEET_CHARS)
        self.assertIn(url, tweet)
        self.assertTrue(tweet.endswith(url))

    def test_compose_tweet_long_body_with_hashtag_suffix(self) -> None:
        allowed = collect_source_urls(MOCK_LINKEDIN_ARTICLE, "https://linkedin.com/posts/x")
        body = (
            "Thrilled that Arka was accepted into the Mintlify Open Source Program! "
            "We now have Mintlify Pro to improve our documentation experience for every user. "
            "Huge thanks to the Mintlify team for supporting open-source projects like ours. "
            "Looking forward to making it easier for everyone to get started with Arka. "
            "#OpenSource #Mintlify #Documentation #DeveloperTools"
        )
        url = "https://github.com/Sumit884-byte/arka"
        tweet = compose_tweet(
            body,
            url,
            allowed_urls=allowed,
            source_text=MOCK_LINKEDIN_ARTICLE,
        )
        self.assertLessEqual(len(tweet), _MAX_TWEET_CHARS)
        self.assertIn(url, tweet)


class PostXBirdCliTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_bird_install_cache()

    def tearDown(self) -> None:
        reset_bird_install_cache()

    def test_bird_exec_prefix_prefers_global_binary(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which") as which,
        ):
            which.side_effect = lambda name: "/usr/local/bin/bird" if name == "bird" else None
            self.assertEqual(bird_exec_prefix(), ["/usr/local/bin/bird"])

    def test_bird_exec_prefix_falls_back_to_npx(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which") as which,
        ):
            which.side_effect = lambda name: "/usr/bin/npx" if name == "npx" else None
            self.assertEqual(bird_exec_prefix(), ["npx", "@steipete/bird"])

    def test_bird_exec_prefix_respects_bird_cli_override(self) -> None:
        with mock.patch.dict("os.environ", {"BIRD_CLI": "/custom/bird"}):
            self.assertEqual(bird_exec_prefix(), ["/custom/bird"])

    def test_bird_subprocess_timeout_longer_for_npx(self) -> None:
        self.assertGreater(
            bird_subprocess_timeout(["npx", "@steipete/bird"]),
            bird_subprocess_timeout(["/usr/local/bin/bird"]),
        )

    def test_post_via_bird_timeout_shows_install_hint(self) -> None:
        with (
            mock.patch(
                "arka.integrations.x_post.ensure_bird_exec_prefix",
                return_value=["npx", "@steipete/bird"],
            ),
            mock.patch(
                "arka.integrations.x_post.subprocess.run",
                side_effect=__import__("subprocess").TimeoutExpired(
                    cmd=["npx", "@steipete/bird", "tweet", "hi"],
                    timeout=180,
                ),
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                post_via_bird("hello world")
        msg = str(ctx.exception)
        self.assertIn("timed out", msg.lower())
        self.assertIn("npm install -g", msg)
        self.assertIn("TWITTER_API_KEY", msg)

    def test_post_via_bird_uses_global_binary(self) -> None:
        completed = mock.Mock(returncode=0, stdout="https://x.com/u/status/42\n", stderr="")
        with (
            mock.patch(
                "arka.integrations.x_post.ensure_bird_exec_prefix",
                return_value=["/usr/local/bin/bird"],
            ),
            mock.patch("arka.integrations.x_post.subprocess.run", return_value=completed) as run,
        ):
            tweet_id = post_via_bird("hello world")
        run.assert_called_once()
        cmd, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(cmd[0], "/usr/local/bin/bird")
        self.assertEqual(kwargs["timeout"], bird_subprocess_timeout(["/usr/local/bin/bird"]))
        self.assertEqual(tweet_id, "42")

    def test_bird_npm_missing_message(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            msg = bird_npm_missing_message()
        self.assertIn("Node.js", msg)
        self.assertIn("npm", msg)

    def test_ensure_bird_exec_prefix_auto_installs_global(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which") as which,
            mock.patch("arka.integrations.x_post._bird_binary_from_state", return_value=""),
            mock.patch("arka.integrations.x_post.install_bird", return_value="/usr/local/bin/bird") as install,
            mock.patch("arka.integrations.x_post.verify_bird_binary", return_value=True),
        ):
            which.side_effect = lambda name: {
                "node": "/usr/bin/node",
                "npm": "/usr/bin/npm",
            }.get(name)
            prefix = ensure_bird_exec_prefix(auto_install=True)
        install.assert_called_once()
        self.assertEqual(prefix, ["/usr/local/bin/bird"])

    def test_ensure_bird_exec_prefix_uses_cache_without_reinstall(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which", return_value=None),
            mock.patch(
                "arka.integrations.x_post._bird_binary_from_state",
                return_value="/cache/bird-npm/node_modules/.bin/bird",
            ),
            mock.patch("arka.integrations.x_post.verify_bird_binary", return_value=True),
            mock.patch("arka.integrations.x_post.install_bird") as install,
        ):
            prefix = ensure_bird_exec_prefix(auto_install=True)
        install.assert_not_called()
        self.assertEqual(prefix, ["/cache/bird-npm/node_modules/.bin/bird"])

    def test_ensure_bird_exec_prefix_falls_back_to_npx_on_install_failure(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("shutil.which") as which,
            mock.patch("arka.integrations.x_post._bird_binary_from_state", return_value=""),
            mock.patch(
                "arka.integrations.x_post.install_bird",
                side_effect=RuntimeError("npm failed"),
            ),
        ):
            which.side_effect = lambda name: {
                "node": "/usr/bin/node",
                "npm": "/usr/bin/npm",
                "npx": "/usr/bin/npx",
            }.get(name)
            prefix = ensure_bird_exec_prefix(auto_install=True)
        self.assertEqual(prefix, ["npx", "@steipete/bird"])

    def test_install_bird_global_success(self) -> None:
        version_proc = mock.Mock(returncode=0, stdout="bird 0.1.0\n", stderr="")
        bird_hits = {"n": 0}

        def which_side(name: str) -> str | None:
            if name == "node":
                return "/usr/bin/node"
            if name == "npm":
                return "/usr/bin/npm"
            if name == "bird":
                bird_hits["n"] += 1
                return None if bird_hits["n"] == 1 else "/usr/local/bin/bird"
            return None

        with (
            mock.patch("shutil.which", side_effect=which_side),
            mock.patch("arka.integrations.x_post._run_npm_install") as npm_install,
            mock.patch("arka.integrations.x_post._save_bird_install_state") as save_state,
            mock.patch("arka.integrations.x_post.subprocess.run", return_value=version_proc),
            mock.patch("arka.integrations.x_post._bird_binary_from_state", return_value=""),
            mock.patch("arka.integrations.x_post.verify_bird_binary", return_value=True),
        ):
            path = install_bird(quiet=True)
        npm_install.assert_called_once_with(["install", "-g", "@steipete/bird"], quiet=True)
        self.assertEqual(path, "/usr/local/bin/bird")
        save_state.assert_called_once()

    def test_install_bird_local_fallback(self) -> None:
        from pathlib import Path

        version_proc = mock.Mock(returncode=0, stdout="bird 0.1.0\n", stderr="")
        local_bird = "/tmp/arka-cache/bird-npm/node_modules/.bin/bird"

        def which_side(name: str) -> str | None:
            if name == "node":
                return "/usr/bin/node"
            if name == "npm":
                return "/usr/bin/npm"
            return None

        prefix_dir = mock.Mock()
        prefix_dir.mkdir = mock.Mock()

        with (
            mock.patch("shutil.which", side_effect=which_side),
            mock.patch("arka.integrations.x_post._run_npm_install") as npm_install,
            mock.patch(
                "arka.integrations.x_post._bird_local_prefix_dir",
                return_value=prefix_dir,
            ),
            mock.patch(
                "arka.integrations.x_post._bird_local_binary",
                return_value=Path(local_bird),
            ),
            mock.patch("arka.integrations.x_post._save_bird_install_state") as save_state,
            mock.patch("arka.integrations.x_post.subprocess.run", return_value=version_proc),
            mock.patch("arka.integrations.x_post._bird_binary_from_state", return_value=""),
            mock.patch("arka.integrations.x_post.verify_bird_binary", return_value=True),
        ):
            path = install_bird(quiet=True)

        self.assertEqual(
            npm_install.call_args_list[0][0][0],
            ["install", "-g", "@steipete/bird"],
        )
        self.assertEqual(
            npm_install.call_args_list[1][0][0][0:2],
            ["install", "@steipete/bird"],
        )
        self.assertEqual(path, local_bird)
        save_state.assert_called_once()

    def test_verify_bird_binary_checks_version(self) -> None:
        ok = mock.Mock(returncode=0, stdout="0.1.0", stderr="")
        bad = mock.Mock(returncode=1, stdout="", stderr="fail")
        with mock.patch("arka.integrations.x_post.subprocess.run", side_effect=[ok, bad]):
            self.assertTrue(verify_bird_binary("/usr/local/bin/bird"))
            self.assertFalse(verify_bird_binary("/usr/local/bin/bird"))


class PostXSessionUrlTests(unittest.TestCase):
    def test_resolve_url_from_session(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": "post this https://www.linkedin.com/posts/abc on my x",
            },
            {"role": "assistant", "content": "I cannot post"},
            {
                "role": "user",
                "content": "shorten the post from linkedin and post it on x",
            },
        ]
        with mock.patch("arka.agent.chat.load_session", return_value=msgs):
            url = resolve_source_url("shorten the linkedin post and post it on x")
        self.assertEqual(url, "https://www.linkedin.com/posts/abc")


class PostXFlowTests(unittest.TestCase):
    def test_x_auth_configured_api_keys(self) -> None:
        env = {
            "TWITTER_API_KEY": "k",
            "TWITTER_API_SECRET": "s",
            "TWITTER_ACCESS_TOKEN": "t",
            "TWITTER_ACCESS_TOKEN_SECRET": "ts",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertTrue(x_auth_configured())

    def test_x_auth_configured_bird_cookies(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"X_AUTH_TOKEN": "abc", "X_CT0": "def"},
            clear=True,
        ):
            self.assertTrue(x_auth_configured())

    def test_x_auth_not_configured_without_creds(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(x_auth_configured())

    def test_post_url_to_x_no_creds_returns_draft(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "arka.integrations.x_post.fetch_url_text",
                return_value=MOCK_LINKEDIN_ARTICLE,
            ),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Arka joined Mintlify Open Source Program.",
            ),
            mock.patch("arka.integrations.x_post.post_tweet") as post_tweet,
            mock.patch("arka.integrations.x_post.ensure_bird_exec_prefix") as ensure_bird,
        ):
            tweet, tweet_id, backend = post_url_to_x(
                "https://www.linkedin.com/posts/foo",
                max_words=40,
            )
        post_tweet.assert_not_called()
        ensure_bird.assert_not_called()
        self.assertEqual(tweet_id, "draft")
        self.assertEqual(backend, "draft_only")
        self.assertIn("Mintlify", tweet)

    def test_post_url_to_x_with_creds_posts(self) -> None:
        article = " ".join(["insight"] * 100)
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "TWITTER_API_KEY": "k",
                    "TWITTER_API_SECRET": "s",
                    "TWITTER_ACCESS_TOKEN": "t",
                    "TWITTER_ACCESS_TOKEN_SECRET": "ts",
                },
                clear=True,
            ),
            mock.patch("arka.integrations.x_post.fetch_url_text", return_value=article),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Short insight about the article.",
            ),
            mock.patch(
                "arka.integrations.x_post.post_tweet",
                return_value=("12345", "twitter_api"),
            ) as post_tweet,
        ):
            tweet, tweet_id, backend = post_url_to_x(
                "https://www.linkedin.com/posts/foo",
                max_words=40,
            )
        post_tweet.assert_called_once()
        self.assertIn("Short insight", tweet)
        self.assertEqual(tweet_id, "12345")
        self.assertEqual(backend, "twitter_api")

    def test_post_url_to_x_force_post_without_creds_exits_cleanly(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "arka.integrations.x_post.fetch_url_text",
                return_value=MOCK_LINKEDIN_ARTICLE,
            ),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Arka joined Mintlify Open Source Program.",
            ),
            mock.patch("arka.integrations.x_post.post_tweet", side_effect=SystemExit(1)) as post_tweet,
        ):
            with self.assertRaises(SystemExit):
                post_url_to_x(
                    "https://www.linkedin.com/posts/foo",
                    max_words=40,
                    force_post=True,
                )
        post_tweet.assert_called_once()

    def test_post_tweet_without_creds_raises_system_exit(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                post_tweet("hello")
        self.assertIn("auth not configured", str(ctx.exception).lower())

    def test_main_post_without_creds_exits_zero(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "arka.integrations.x_post.fetch_url_text",
                return_value=MOCK_LINKEDIN_ARTICLE,
            ),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Arka joined Mintlify Open Source Program.",
            ),
            mock.patch("arka.integrations.x_post.post_tweet") as post_tweet,
        ):
            code = main(["https://www.linkedin.com/posts/foo"])
        post_tweet.assert_not_called()
        self.assertEqual(code, 0)

    def test_main_force_post_without_creds_exits_nonzero(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "arka.integrations.x_post.fetch_url_text",
                return_value=MOCK_LINKEDIN_ARTICLE,
            ),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Arka joined Mintlify Open Source Program.",
            ),
        ):
            with self.assertRaises(SystemExit):
                main(["https://www.linkedin.com/posts/foo", "--post"])

    def test_post_url_to_x_mocked(self) -> None:
        article = " ".join(["insight"] * 100)
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "TWITTER_API_KEY": "k",
                    "TWITTER_API_SECRET": "s",
                    "TWITTER_ACCESS_TOKEN": "t",
                    "TWITTER_ACCESS_TOKEN_SECRET": "ts",
                },
                clear=True,
            ),
            mock.patch("arka.integrations.x_post.fetch_url_text", return_value=article),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Short insight about the article.",
            ),
            mock.patch(
                "arka.integrations.x_post.post_tweet",
                return_value=("12345", "twitter_api"),
            ),
        ):
            tweet, tweet_id, backend = post_url_to_x(
                "https://www.linkedin.com/posts/foo",
                max_words=40,
                force_post=True,
            )
        self.assertIn("Short insight", tweet)
        self.assertEqual(tweet_id, "12345")
        self.assertEqual(backend, "twitter_api")

    def test_post_url_to_x_uses_source_github_not_hallucination(self) -> None:
        bad_llm = (
            "Arka joined the Mintlify Open Source Program with Mintlify Pro for better docs. "
            "Check it out: https://github.com/arkahq/arka "
            "#OpenSource #Mintlify #Documentation #DeveloperTools #GitHub #AI #BuildInPublic"
        )
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "TWITTER_API_KEY": "k",
                    "TWITTER_API_SECRET": "s",
                    "TWITTER_ACCESS_TOKEN": "t",
                    "TWITTER_ACCESS_TOKEN_SECRET": "ts",
                },
                clear=True,
            ),
            mock.patch(
                "arka.integrations.x_post.fetch_url_text",
                return_value=MOCK_LINKEDIN_ARTICLE,
            ),
            mock.patch("arka.llm.cli.llm_complete", return_value=bad_llm),
            mock.patch(
                "arka.integrations.x_post.post_tweet",
                return_value=("99999", "twitter_api"),
            ) as post_tweet,
        ):
            tweet, tweet_id, backend = post_url_to_x(
                "https://www.linkedin.com/posts/foo",
                max_words=40,
                force_post=True,
            )
        self.assertLessEqual(count_words(tweet.split("https://")[0]), 40)
        self.assertIn("https://github.com/Sumit884-byte/arka", tweet)
        self.assertNotIn("arkahq", tweet)
        self.assertNotIn("#AI", tweet)
        post_tweet.assert_called_once()

    def test_post_url_to_x_no_github_in_scrape_uses_git_remote(self) -> None:
        article = (
            "Thrilled that Arka was accepted into the Mintlify Open Source Program! "
            "We now have Mintlify Pro to improve our documentation experience. "
            "Huge thanks to the Mintlify team for supporting open-source projects like ours."
        )
        bad_llm = (
            "Arka joined the Mintlify Open Source Program with Mintlify Pro for better docs. "
            "Check it out: https://github.com/arkahq/arka"
        )
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "TWITTER_API_KEY": "k",
                    "TWITTER_API_SECRET": "s",
                    "TWITTER_ACCESS_TOKEN": "t",
                    "TWITTER_ACCESS_TOKEN_SECRET": "ts",
                },
                clear=True,
            ),
            mock.patch("arka.integrations.x_post.fetch_url_text", return_value=article),
            mock.patch("arka.llm.cli.llm_complete", return_value=bad_llm),
            mock.patch(
                "arka.integrations.x_post.git_remote_github_url",
                return_value="https://github.com/Sumit884-byte/arka",
            ),
            mock.patch(
                "arka.integrations.x_post.post_tweet",
                return_value=("88888", "twitter_api"),
            ),
        ):
            tweet, _tweet_id, _backend = post_url_to_x(
                "https://www.linkedin.com/posts/foo",
                max_words=40,
                force_post=True,
                verify_urls=True,
            )
        self.assertIn("https://github.com/Sumit884-byte/arka", tweet)
        self.assertNotIn("arkahq", tweet)
        self.assertNotIn("Check it out:", tweet)

    def test_post_url_to_x_dry_run_skips_post(self) -> None:
        with (
            mock.patch(
                "arka.integrations.x_post.fetch_url_text",
                return_value=MOCK_LINKEDIN_ARTICLE,
            ),
            mock.patch(
                "arka.integrations.x_post.shorten_post",
                return_value="Arka joined Mintlify Open Source Program.",
            ),
            mock.patch("arka.integrations.x_post.post_tweet") as post_tweet,
        ):
            tweet, tweet_id, backend = post_url_to_x(
                "https://www.linkedin.com/posts/foo",
                max_words=40,
                dry_run=True,
            )
        post_tweet.assert_not_called()
        self.assertEqual(tweet_id, "dry-run")
        self.assertEqual(backend, "dry_run")
        self.assertIn("Mintlify", tweet)


class PostXRoutingTests(unittest.TestCase):
    def test_symbolic_route_post_x(self) -> None:
        from arka.routing.symbolic import route_post_x

        hit = route_post_x("post https://linkedin.com/posts/x on my x")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("post_x "))
        self.assertIn("linkedin.com", hit)
        self.assertNotIn("web_answer", hit)

    def test_fish_route_preview_post_on_x(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        cmd = "post this https://www.linkedin.com/posts/activity-123 on my x"
        preview = fish_route_preview(cmd)
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertTrue(preview.action.startswith("post_x "))
        self.assertNotEqual(preview.action.split()[0], "web_answer")

    def test_fish_route_preview_shorten_followup(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        preview = fish_route_preview(
            "shorten the post from linkedin to <=40 words and then post it on x"
        )
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertTrue(preview.action.startswith("post_x "))
        self.assertTrue(
            "--from-session" in preview.action or "linkedin.com" in preview.action
        )


if __name__ == "__main__":
    unittest.main()
