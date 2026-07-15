def test_repo_reverse_contains_history(tmp_path) -> None:
    import subprocess
    from arka.agent.repo_reverse import reverse
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text("print('ok')")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=test", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    assert "app.py" in reverse(tmp_path)
