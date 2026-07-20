from arka.agent.deploy import deployment_command, detect_platform

def test_detect_and_preview(tmp_path) -> None:
    (tmp_path / "vercel.json").write_text("{}")
    assert detect_platform(tmp_path) == "vercel"
    assert deployment_command(tmp_path, "vercel", production=True) == ["vercel", "--prod"]


def test_backend_detection_and_command(tmp_path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM python:3.13")
    assert detect_platform(tmp_path) == "railway"
    assert deployment_command(tmp_path, "railway", production=True) == ["railway", "up", "--ci"]


def test_free_host_commands(tmp_path) -> None:
    assert deployment_command(tmp_path, "huggingface") == ["git", "push", "hf", "main"]
    assert deployment_command(tmp_path, "cloudflare") == ["wrangler", "deploy"]


def test_cli_deploy_direct_command_does_not_fall_through_to_fish(capsys) -> None:
    from arka import cli

    assert cli.main(["deploy", "--platform", "railway", "--json"]) == 0
    assert '"platform": "railway"' in capsys.readouterr().out
