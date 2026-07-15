from arka.routing.symbolic import route_offline_extras


def test_common_new_skill_phrases():
    assert route_offline_extras("convert report.pdf into an ultra interactive website") == "pdf_interactive report.pdf --ultra"
    assert route_offline_extras("analyze this repo for startup architecture") == "super_replica ."
    assert route_offline_extras("make a quiz website from lesson.mp4") == "media_quiz lesson.mp4"
