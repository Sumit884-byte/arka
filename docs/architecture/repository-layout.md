# Repository layout

Arka keeps runtime code under `src/arka/`, executable maintenance helpers in
`scripts/`, tests in `tests/`, and user-facing documentation in `docs/`.

## Runtime boundaries

- `agent/`: user-facing, task-oriented skills and workflows
- `core/`: shared configuration, security, routing-adjacent primitives
- `integrations/`: external systems and MCP adapters
- `llm/`: providers, fallback, model selection, and inference backends
- `routing/`: symbolic and natural-language route translation
- `telemetry/`: OpenTelemetry and SigNoz instrumentation
- `vision/`, `media/`, `documents/`, `pdf/`: domain-specific processing
- `fish/` and `bundled/`: Fish runtime and synchronized distribution assets

New runtime features should be placed in the narrowest existing boundary and
exposed through `dispatch.py` plus a symbolic route when user-facing. Generated
state, caches, credentials, and local model artifacts should stay outside the
source tree and must not be committed.
