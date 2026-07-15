from arka.agent.media_quiz import convert
from arka.routing.symbolic import route_media_quiz


def test_media_quiz(tmp_path):
    image = tmp_path / "lesson.png"
    image.write_bytes(b"image")
    output = convert(str(image))
    assert output.is_file()
    assert "Quiz submitted" in output.read_text()


def test_media_quiz_route():
    assert route_media_quiz("make a quiz website from lesson.mp4") == "media_quiz lesson.mp4"
