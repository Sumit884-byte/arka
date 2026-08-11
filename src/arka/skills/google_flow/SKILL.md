# Google Flow

Create AI video with [Google Flow](https://labs.google/fx/tools/flow) — Google's creative studio (Veo, Gemini Omni, scene builder).

Arka uses **Gemini Veo API** when `GEMINI_API_KEY` is set (same models as Flow), or **Playwright browser automation** to drive the Flow web UI.

## Requirements

- **Gemini Veo** (recommended): `GEMINI_API_KEY` with GCP billing — https://aistudio.google.com/
- **Browser backend**: `pip install playwright && playwright install chromium`
- Optional saved Google session: `GOOGLE_FLOW_USER_DATA_DIR=~/.arka/google-flow-profile`

## CLI

```bash
arka google_flow cinematic drone shot over mountains at sunset
arka google_flow open
arka google_flow "ocean waves at dawn" --backend browser
arka google_flow sunset city timelapse -a 16:9 -d 8
arka google_flow check
```

Aliases: `arka flow_video`, `arka google-flow`

## Natural language

- "create video in google flow of a cat walking in the rain"
- "use google flow to make a movie about space exploration"
- "google flow video cinematic forest fog"

## Backends

| `GOOGLE_FLOW_BACKEND` | Behavior |
|-----------------------|----------|
| `auto` (default) | Gemini Veo when keyed, else browser automation |
| `gemini` | Direct Veo API (Flow-equivalent models) |
| `browser` | Playwright on labs.google/fx/tools/flow |
| `open` | Open Flow UI in your browser only |

## Limitations

- Google Flow has no public REST API — browser mode needs Google sign-in and UI selectors may break
- Veo clips are typically 4–8 seconds via API
- Browser download detection is best-effort; use `--backend open` to finish manually if needed
