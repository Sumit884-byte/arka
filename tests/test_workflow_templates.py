def test_templates_render() -> None:
    from arka.agent.workflow_templates import render
    assert "quantum computing" in render("research_brief", {"topic": "quantum computing"})

def test_templates_are_listed() -> None:
    from arka.agent.workflow_templates import TEMPLATES
    assert "repo_release" in TEMPLATES


def test_code_template_renders_and_writes(tmp_path) -> None:
    from arka.agent.workflow_templates import main, render

    output = render("python_cli", {"default": "ark"})
    assert "argparse" in output
    target = tmp_path / "tool.py"
    assert main(["use", "api_health_check", "--out", str(target)]) == 0
    assert "urlopen" in target.read_text()


def test_walk_folder_template_supports_recursive_mode() -> None:
    from arka.agent.workflow_templates import render

    output = render("walk_folder", {"pattern": "*.py"})
    assert "rglob" in output
    assert "--recursive" in output
