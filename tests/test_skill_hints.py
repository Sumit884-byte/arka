from arka.agent.skill_hints import recommend_skill_hint


def test_symbolic_skill_hint_is_compact_and_canonical():
    hint = recommend_skill_hint("check repo health before coding")
    assert hint == "Symbolic skill hint: prefer `repo_health` if it directly matches; do not invent a different skill."


def test_symbolic_skill_hint_is_bounded_and_does_not_invent():
    assert recommend_skill_hint("make up a completely new thing") == ""
    assert len(recommend_skill_hint("create a pitch deck with slides")) < 140
