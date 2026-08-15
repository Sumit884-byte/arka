"""NL routing for local vs cloud image generation."""

from __future__ import annotations

import io
import os
import re
import shlex
import shutil
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from arka.agent.local_image_gen import nl_to_argv as local_nl_to_argv, route_command, wants_local_image
from arka.generate.image import nl_to_argv as cloud_nl_to_argv
from arka.router import route
from arka.routing.symbolic import route_generate_image, route_local_image_gen

REPO = Path(__file__).resolve().parents[1]
FISH_CFG = REPO / "src" / "arka" / "fish" / "config.fish"

# (natural language, exact routed skill line, parse stdout, argv tail after "generate")
LOCAL_IMAGE_FORMAT_CASES: list[tuple[str, str, str, list[str]]] = [
    (
        "generate image locally of a moonlit forest",
        "image generate 'a moonlit forest'",
        "generate 'a moonlit forest'",
        ["generate", "a moonlit forest"],
    ),
    (
        "create picture with stable diffusion of a robot",
        "image generate 'a robot'",
        "generate 'a robot'",
        ["generate", "a robot"],
    ),
    (
        "draw picture offline of Taj Mahal",
        "image generate 'Taj Mahal'",
        "generate 'Taj Mahal'",
        ["generate", "Taj Mahal"],
    ),
    (
        "'generate image locally of a moonlit forest'",
        "image generate 'a moonlit forest'",
        "generate 'a moonlit forest'",
        ["generate", "a moonlit forest"],
    ),
]

GENERATED_LOCAL_IMAGE_RE = re.compile(
    r"^Generated local image: (?P<path>.+\.png)$",
    re.MULTILINE,
)


def assert_local_image_skill(skill: str, *, expected_prompt: str) -> None:
    """Routed skill must be exactly: image generate '<prompt>'."""
    parts = shlex.split(skill.strip())
    assert parts[:2] == ["image", "generate"], (
        f"expected skill to start with 'image generate', got {skill!r}"
    )
    prompt = " ".join(parts[2:])
    assert prompt == expected_prompt, (
        f"expected prompt {expected_prompt!r}, got {prompt!r} in skill {skill!r}"
    )


def assert_local_image_parse(stdout: str, *, expected_prompt: str) -> None:
    """Parse stdout must be exactly: generate '<prompt>'."""
    line = stdout.strip()
    parts = shlex.split(line)
    assert parts[0] == "generate", f"parse must start with 'generate', got {line!r}"
    prompt = " ".join(parts[1:])
    assert prompt == expected_prompt, (
        f"expected parse prompt {expected_prompt!r}, got {prompt!r} in {line!r}"
    )


@pytest.mark.parametrize("phrase,expected_skill,expected_parse,expected_argv", LOCAL_IMAGE_FORMAT_CASES)
def test_local_image_output_format_constraints(
    phrase: str,
    expected_skill: str,
    expected_parse: str,
    expected_argv: list[str],
) -> None:
    assert local_nl_to_argv(phrase) == expected_argv
    assert route_command(phrase) == expected_skill
    assert route_local_image_gen(phrase) == expected_skill

    with redirect_stdout(io.StringIO()) as buf:
        from arka.agent.local_image_gen import main

        assert main(["parse", phrase]) == 0
    assert_local_image_parse(buf.getvalue(), expected_prompt=expected_argv[1])

    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        routed = route(phrase)
    assert routed is not None
    assert_local_image_skill(routed.skill, expected_prompt=expected_argv[1])
    assert routed.skill == expected_skill


def test_wants_local_image_phrases():
    assert wants_local_image("generate image locally of a red panda")
    assert wants_local_image("create picture offline of a mountain")
    assert wants_local_image("draw an image with stable diffusion of a castle")
    assert wants_local_image("use local image model to generate a logo")
    assert not wants_local_image("generate image of a cyberpunk city")


def test_local_nl_to_argv_extracts_prompt():
    assert local_nl_to_argv("generate image locally of a moonlit forest") == [
        "generate",
        "a moonlit forest",
    ]
    assert local_nl_to_argv("create picture with stable diffusion of a robot") == [
        "generate",
        "a robot",
    ]


def test_cloud_nl_defers_to_local():
    assert cloud_nl_to_argv("generate image locally of a sunset") == []
    assert route_generate_image("generate image locally of a sunset") is None


def test_route_local_image_gen_symbolic():
    result = route_local_image_gen("generate image locally of a lighthouse")
    assert result == "image generate 'a lighthouse'"
    assert_local_image_skill(result, expected_prompt="a lighthouse")


def test_route_symbolic_prefers_local_over_cloud():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("generate image locally of a neon alley")
    assert result is not None
    assert result.skill == "image generate 'a neon alley'"
    assert_local_image_skill(result.skill, expected_prompt="a neon alley")


def test_route_symbolic_cloud_still_works():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        local_result = route("generate image locally of a neon alley")
        cloud_result = route("generate image of a cyberpunk neon alley")
    assert local_result is not None
    assert local_result.skill == "image generate 'a neon alley'"
    assert cloud_result is not None
    assert cloud_result.skill.startswith("generate_image ")
    cloud_parts = shlex.split(cloud_result.skill)
    assert cloud_parts[0] == "generate_image"
    assert " ".join(cloud_parts[1:]) == "a cyberpunk neon alley"


def test_local_allows_real_world_subjects():
    """Local SD routing should not apply cloud real-world subject guards."""
    assert local_nl_to_argv("generate image locally of Indian Pariah dog") == [
        "generate",
        "Indian Pariah dog",
    ]
    assert route_command("draw picture offline of Taj Mahal") == "image generate 'Taj Mahal'"


def test_local_image_parse_subcommand(capsys):
    from arka.agent.local_image_gen import main

    assert main(["parse", "generate image locally of a moonlit forest"]) == 0
    assert_local_image_parse(
        capsys.readouterr().out,
        expected_prompt="a moonlit forest",
    )

    assert main(["parse", "'generate image locally of a moonlit forest'"]) == 0
    assert_local_image_parse(
        capsys.readouterr().out,
        expected_prompt="a moonlit forest",
    )


def test_run_nl_stdout_format(capsys):
    from arka.cli import _try_local_image_nl

    with mock.patch(
        "arka.agent.local_image_gen.generate",
        return_value={"output": "/tmp/moonlit-forest.png"},
    ):
        code = _try_local_image_nl("generate image locally of a moonlit forest")
    assert code == 0
    out = capsys.readouterr().out.strip()
    match = GENERATED_LOCAL_IMAGE_RE.fullmatch(out)
    assert match is not None, f"unexpected run_nl stdout: {out!r}"
    assert match.group("path") == "/tmp/moonlit-forest.png"


def test_resolve_start_cmd_discovers_webui(tmp_path, monkeypatch):
    from arka.agent.local_image_gen import _resolve_start_cmd

    webui = tmp_path / "stable-diffusion-webui" / "webui.sh"
    webui.parent.mkdir(parents=True)
    webui.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ARKA_SD_START_CMD", raising=False)
    assert _resolve_start_cmd().endswith("webui.sh --api --listen")


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ARKA_AUTO_REFETCH"] = "0"
    env["INSTALL_HOME"] = str(REPO)
    env["CONFIG_DIR"] = "/tmp/arka-local-image-fish-test"
    env["PYTHONPATH"] = str(REPO / "src")
    return env


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
@pytest.mark.parametrize(
    "phrase,expected_skill,expected_prompt",
    [
        (
            "generate image locally of a moonlit forest",
            "image generate 'a moonlit forest'",
            "a moonlit forest",
        ),
        (
            "create picture with stable diffusion of a robot",
            "image generate 'a robot'",
            "a robot",
        ),
    ],
)
def test_fish_agent_route_local_image_format(
    phrase: str, expected_skill: str, expected_prompt: str
) -> None:
    cfg = shlex.quote(str(FISH_CFG))
    inner = f"source {cfg}; agent_route {shlex.quote(phrase)}"
    proc = subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=_fish_env(),
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    action = ""
    for line in proc.stdout.splitlines():
        if line.strip().startswith("Action:"):
            action = line.split(":", 1)[1].strip()
            break
    assert action == expected_skill, proc.stdout
    assert_local_image_skill(action, expected_prompt=expected_prompt)


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_offline_route_not_bare_generate_image() -> None:
    phrase = "generate image locally of a moonlit forest"
    cfg = shlex.quote(str(FISH_CFG))
    inner = f"source {cfg}; _agent_offline_route_cmd {shlex.quote(phrase)}"
    proc = subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=_fish_env(),
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    routed = proc.stdout.strip()
    assert routed == "image generate 'a moonlit forest'"
    assert "generate_image" not in routed
    assert "Nano Banana" not in proc.stdout
