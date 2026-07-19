from arka.core.object_orientation import default_view, object_kind, orientation_note, task_context


def test_vehicle_racing_defaults_to_rear_chase_view():
    text = "battle cyber truck vs ferrari in a racing game"
    assert object_kind(text) == "vehicle"
    assert task_context(text) == "racing_game"
    assert default_view(text) == "rear-three-quarter"
    assert "racing-game" in orientation_note(text)


def test_explicit_orientation_wins():
    assert default_view("show the back of a Ferrari") == "rear"
    assert default_view("show car side profile") == "side"
    assert default_view("show car roof layout") == "top"
