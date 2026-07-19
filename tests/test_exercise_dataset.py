import json
from pathlib import Path


SAMPLE = [
    {
        "id": "0001",
        "name": "3/4 sit-up",
        "category": "waist",
        "body_part": "waist",
        "equipment": "body weight",
        "instructions": {"en": "Lie flat and curl up.", "tr": "Uzanın."},
        "muscle_group": "hip flexors",
        "secondary_muscles": ["lower back"],
        "target": "abs",
        "image": "images/0001.jpg",
        "gif_url": "videos/0001.gif",
    },
    {
        "id": "0002",
        "name": "Barbell bench press",
        "category": "chest",
        "equipment": "barbell",
        "instructions": {"en": "Press the bar.", "tr": "Barı itin."},
        "target": "pectorals",
    },
]


def test_import_dataset_caches_validated_records(monkeypatch, tmp_path):
    from arka.agent import exercise_dataset as ex

    monkeypatch.setattr(ex, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ex, "_download_text", lambda source, **kwargs: json.dumps(SAMPLE))

    meta = ex.import_dataset()

    assert meta["records"] == 2
    assert meta["categories"]["waist"] == 1
    assert Path(meta["cache_path"]).is_file()
    cached = json.loads(Path(meta["cache_path"]).read_text(encoding="utf-8"))
    assert cached[0]["instructions"]["en"] == "Lie flat and curl up."
    assert "non-commercial" in meta["license_note"]


def test_search_records_filters_by_equipment_and_target():
    from arka.agent.exercise_dataset import search_records, validate_records

    rows = validate_records(SAMPLE)
    results = search_records("barbell chest", records=rows)

    assert [row["name"] for row in results] == ["Barbell bench press"]


def test_export_csv(tmp_path):
    from arka.agent.exercise_dataset import export_records, validate_records

    out = export_records(validate_records(SAMPLE), tmp_path / "exercises.csv", fmt="csv")

    text = out.read_text(encoding="utf-8")
    assert "Barbell bench press" in text
    assert "gif_url" in text


def test_exercise_dataset_routes():
    from arka.agent.exercise_dataset import route_command
    from arka.routing.symbolic import route_offline_extras

    assert route_command("add data from hasaneyldrm/exercises-dataset").startswith("exercise_dataset import")
    assert route_offline_extras("quickly add exercise data from hasaneyldrm/exercises-dataset") == "exercise_dataset import"
    assert route_offline_extras("search exercise dataset for barbell chest").startswith("exercise_dataset search")


def test_cli_exercises_direct_command_does_not_fall_through_to_fish(monkeypatch, capsys, tmp_path):
    from arka import cli
    from arka.agent import exercise_dataset as ex

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(ex, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ex, "_download_text", lambda source, **kwargs: json.dumps(SAMPLE))

    assert cli.main(["exercises", "import", "--force", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"records": 2' in out
