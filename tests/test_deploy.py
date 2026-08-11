from arka.agent.deploy import deployment_command, detect_platform, detect_all_platforms

def test_detect_and_preview(tmp_path) -> None:
    (tmp_path / "vercel.json").write_text("{}")
    assert detect_platform(tmp_path) == "vercel"
    assert deployment_command(tmp_path, "vercel", production=True) == ["vercel", "--prod"]


def test_backend_detection_and_command(tmp_path) -> None:
    (tmp_path / "railway.toml").write_text("")
    assert detect_platform(tmp_path) == "railway"
    assert deployment_command(tmp_path, "railway", production=True) == ["railway", "up", "--ci"]
    
    tmp_docker = tmp_path / "docker_proj"
    tmp_docker.mkdir()
    (tmp_docker / "Dockerfile").write_text("FROM python:3.13")
    assert detect_platform(tmp_docker) == "cloud"


def test_free_host_commands(tmp_path) -> None:
    assert deployment_command(tmp_path, "huggingface") == ["git", "push", "hf", "main"]
    assert deployment_command(tmp_path, "cloudflare") == ["wrangler", "deploy"]


def test_cloud_and_docker_deployment_commands(tmp_path) -> None:
    assert deployment_command(tmp_path, "cloud") == ["docker", "compose", "up", "-d", "--build"]
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "deploy_cloud.sh").write_text("#!/bin/bash\n")
    assert deployment_command(tmp_path, "cloud") == ["./scripts/deploy_cloud.sh"]


def test_detect_all_platforms(tmp_path) -> None:
    (tmp_path / "vercel.json").write_text("{}")
    (tmp_path / "railway.toml").write_text("")
    (tmp_path / "Dockerfile").write_text("FROM python:3.13")
    all_targets = detect_all_platforms(tmp_path)
    assert "vercel" in all_targets
    assert "railway" in all_targets
    assert "cloud" in all_targets


def test_cli_multi_platform_deployment(capsys, tmp_path) -> None:
    from arka import cli

    (tmp_path / "vercel.json").write_text("{}")
    (tmp_path / "railway.toml").write_text("")
    assert cli.main(["deploy", str(tmp_path), "--all", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"total_platforms": 2' in out
    assert '"platform": "vercel"' in out
    assert '"platform": "railway"' in out

    assert cli.main(["deploy", str(tmp_path), "--platforms", "vercel,cloud", "--json"]) == 0
    out_custom = capsys.readouterr().out
    assert '"total_platforms": 2' in out_custom
    assert '"platform": "cloud"' in out_custom
