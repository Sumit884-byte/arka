"""Tests for finetune_model — NL parsing, routing, dry-run generation, MCP."""

from __future__ import annotations

import json
from pathlib import Path

from arka.integrations.mcp_server import _handle_arka_finetune_model, list_tool_names
from arka.llm.finetune_model import (
    generate_artifacts,
    job_status,
    main as finetune_main,
    nl_to_argv,
    plan_job,
    validate_dataset,
)
from arka.routing.symbolic import route_finetune_model, route_offline_extras


def test_nl_to_argv_plan():
    assert nl_to_argv("fine-tune llama model on ./data.jsonl with qlora") == [
        "plan",
        "fine-tune llama model on ./data.jsonl with qlora",
    ]
    assert nl_to_argv("lora training on support tickets dataset") == [
        "plan",
        "lora training on support tickets dataset",
    ]
    assert nl_to_argv("train model on ./dataset") == ["plan", "train model on ./dataset"]


def test_nl_to_argv_explicit():
    assert nl_to_argv("finetune_model validate ./data.jsonl") == ["validate", "./data.jsonl"]
    assert nl_to_argv("arka model finetune plan qlora on tickets") == [
        "plan",
        "qlora",
        "on",
        "tickets",
    ]


def test_nl_to_argv_does_not_steal_other_skills():
    assert nl_to_argv("check repo health") == []
    assert nl_to_argv("check docker daemon") == []
    assert nl_to_argv("generate image locally of a moonlit forest") == []


def test_route_finetune_model():
    routed = route_finetune_model("fine tune llama model on ./data/support.jsonl")
    assert routed is not None
    assert routed.startswith("finetune_model plan ")
    assert route_offline_extras("train model on tickets.jsonl with lora").startswith("finetune_model")


def test_plan_job_parses_nl():
    job = plan_job("fine-tune llama on ./data.jsonl with qlora base model meta-llama/Llama-3.2-3B")
    assert job["method"] in {"qlora", "lora", "full"}
    assert job["dataset"] == "./data.jsonl"
    assert "meta-llama/Llama-3.2-3B" in job["base_model"]
    assert job["dry_run_default"] is True


def test_validate_dataset_jsonl(tmp_path: Path):
    fp = tmp_path / "train.jsonl"
    fp.write_text(
        '{"messages":[{"role":"user","content":"hi"},{"role":"assistant","content":"hello"}]}\n',
        encoding="utf-8",
    )
    result = validate_dataset(fp)
    assert result["supported"] is True
    assert result["chat_format_ok"] is True
    assert result["rows_sampled"] == 1


def test_generate_dry_run():
    result = generate_artifacts(
        base_model="meta-llama/Llama-3.2-3B",
        dataset="./data.jsonl",
        method="qlora",
        apply=False,
    )
    assert result["dry_run"] is True
    assert "finetune_config.yaml" in result["files"]["config"]["path"]
    assert "qlora" in result["files"]["config"]["content"] or result["method"] == "qlora"


def test_generate_apply(tmp_path: Path):
    out = tmp_path / "job"
    result = generate_artifacts(
        base_model="meta-llama/Llama-3.2-3B",
        dataset=str(tmp_path / "data.jsonl"),
        output_dir=str(out),
        apply=True,
    )
    assert result["dry_run"] is False
    assert (out / "finetune_config.yaml").is_file()
    assert (out / "run_finetune.sh").is_file()
    status = job_status(out)
    assert status["status"] == "scaffolded"


def test_cli_plan_json(capsys):
    code = finetune_main(["plan", "fine-tune model on ./data.jsonl", "--method", "lora"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "lora"


def test_mcp_tool_registered():
    assert "arka_finetune_model" in list_tool_names()


def test_mcp_plan_and_generate_dry_run():
    plan = json.loads(
        _handle_arka_finetune_model(
            {"action": "plan", "task": "fine-tune llama on ./data.jsonl with qlora"}
        )
    )
    assert plan["method"] in {"qlora", "lora", "full"}
    gen = json.loads(
        _handle_arka_finetune_model(
            {
                "action": "generate",
                "base_model": "meta-llama/Llama-3.2-3B",
                "dataset": "./data.jsonl",
                "method": "qlora",
            }
        )
    )
    assert gen["dry_run"] is True


def test_mcp_parse():
    payload = json.loads(
        _handle_arka_finetune_model(
            {"action": "parse", "text": "train model on ./dataset with lora"}
        )
    )
    assert payload["argv"][0] == "plan"
