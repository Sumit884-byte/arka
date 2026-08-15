# finetune_model

Plan and scaffold local LLM fine-tuning without launching GPU jobs automatically.

## CLI

```bash
arka finetune_model plan "fine-tune llama on ./data/support.jsonl with qlora"
arka finetune_model validate ./dataset
arka finetune_model generate --base-model meta-llama/Llama-3.2-3B --dataset ./data.jsonl
arka finetune_model generate --base-model meta-llama/Llama-3.2-3B --dataset ./data.jsonl --apply
arka finetune_model status ./finetune-out
arka model finetune plan "train model on tickets.jsonl"
```

## MCP

Tool: `arka_finetune_model`

Actions: `plan`, `validate`, `generate`, `status`, `parse`, `check`

Dry-run is default for `generate`; pass `apply=true` to write config/script files.
