from pathlib import Path

from arka.routing.symbolic import route_offline_extras


def test_text_to_3d_route_prefers_new_skill():
    hit = route_offline_extras("generate a 3d model from text using hugging face")
    assert hit and hit.startswith("text_to_3d generate")


def test_text_to_3d_routes_free_provider_language():
    from arka.agent.text_to_3d import route_command

    route = route_command("create 3d model from text of a dragon using free providers")
    assert route.startswith("text_to_3d generate")
    assert "dragon" in route


def test_text_to_3d_providers_prints_free_first_policy(capsys):
    from arka.agent.text_to_3d import main

    assert main(["providers"]) == 0
    output = capsys.readouterr().out
    assert "free/non-trial first" in output
    assert "ARKA_3D_ALLOW_TRIAL_PROVIDERS" in output
    assert "hf-shap-e" in output


def test_text_to_3d_generate_delegates_to_compose(monkeypatch):
    from arka.agent import text_to_3d

    calls = []
    monkeypatch.setattr("arka.media.compose_3d.main", lambda argv: calls.append(argv) or 0)
    assert text_to_3d.generate("a small robot", backend="auto", fmt="glb", name="bot") == 0
    assert calls == [["compose", "a small robot", "--backend", "auto", "--format", "glb", "--name", "bot"]]


def test_text_to_3d_manifest_exists():
    manifest = Path("src/arka/skills/text_to_3d/skill.json")
    assert manifest.is_file()
    assert "hugging face" in manifest.read_text(encoding="utf-8").lower()
