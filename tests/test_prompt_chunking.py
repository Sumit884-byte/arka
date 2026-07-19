from arka.llm.chunking import complete_chunked, split_prompt


def test_split_prompt_preserves_content():
    text = "alpha\n\nbeta\n\ngamma"
    parts = split_prompt(text, 6)
    assert "".join(parts).replace("\n\n", "") == "alphabetagamma"


def test_chunked_completion_merges_results():
    calls = []

    def complete(system, user):
        calls.append(user)
        return "merged" if user.startswith("Synthesize") else "chunk result"

    result = complete_chunked(complete, "system", "a" * 20, max_chars=8)
    assert result == "merged"
    assert len(calls) == 4  # three chunks plus one synthesis request
    assert "chunk 1/3" in calls[0]


def test_small_prompt_stays_single_request():
    calls = []
    result = complete_chunked(lambda s, u: calls.append(u) or "ok", "s", "small", max_chars=20)
    assert result == "ok"
    assert calls == ["small"]
