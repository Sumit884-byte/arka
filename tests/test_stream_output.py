from unittest.mock import patch

from arka.output import (
    consume_answer_streamed,
    llm_user_answer,
    print_block,
    should_stream_answer,
    stream_llm_answer,
)


def test_pytest_does_not_stream_by_default() -> None:
    assert should_stream_answer() is False


def test_stream_prints_tokens_then_skips_reprint(capsys) -> None:
    deltas = ["NVIDIA ", "GTC ", "introduced Vera Rubin."]

    def _fake_stream(*_args, **_kwargs):
        yield from deltas

    with (
        patch("arka.llm.fallback.llm_stream_complete", side_effect=_fake_stream),
        patch("arka.output.format_model_footer", return_value="gemini/flash"),
        patch("arka.output.format_metrics_footer", return_value=""),
        patch("arka.output.active_context7_label", return_value=None),
    ):
        text = stream_llm_answer("sys", "user", suffix="https://www.youtube.com/watch?v=bbbbbbbbbbb")
    out = capsys.readouterr().out
    assert "━━━ Answer ━━━" in out
    assert "NVIDIA GTC introduced Vera Rubin." in out
    assert "youtube.com/watch?v=bbbbbbbbbbb" in out
    assert "Model: gemini/flash" in out
    assert "Vera Rubin" in text
    print_block("Answer", text)
    reprinted = capsys.readouterr().out
    assert reprinted == ""
    assert consume_answer_streamed() is False


def test_buffered_path_uses_complete_under_pytest() -> None:
    with patch("arka.llm.fallback.llm_complete", return_value="buffered recap") as complete:
        out = llm_user_answer("sys", "user", skill="web_answer")
    assert out == "buffered recap"
    complete.assert_called_once()
