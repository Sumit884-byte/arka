import json

from arka.agent.word_counter import count_text
from arka.routing.symbolic import route_offline_extras


def test_count_text_is_local_and_deterministic():
    result = count_text("Hello world. Hello Arka!")
    assert result["words"] == 4
    assert result["unique_words"] == 3
    assert result["sentences"] == 2
    assert result["reading_minutes"] == 0.02


def test_word_counter_route():
    assert route_offline_extras('count words in "hello world"').startswith("word_counter --text")


def test_word_counter_manifest():
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / "src/arka/skills/word_counter/skill.json").read_text())
    assert manifest["name"] == "word_counter"
