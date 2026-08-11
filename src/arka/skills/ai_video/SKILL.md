# AI Video (full text-to-video)

Generate **real AI video** from a text prompt — every backend produces actual video pixels, not stock photos or slideshows.

## Not these skills

| Skill | What it does |
|-------|----------------|
| **compose_video** | YouTube-style explainers — Unsplash B-roll + TTS + ffmpeg |
| **create_video** | Local ffmpeg slideshows, image+audio, text slides |
| **google_flow** | Google Flow UI or Veo API via browser automation |

## Requirements

At least one backend:

- **Pollinations** (recommended): `POLLINATIONS_API_KEY` from [enter.pollinations.ai](https://enter.pollinations.ai/)
- **Gemini Veo 3.1**: `GEMINI_API_KEY` + billing on [AI Studio](https://aistudio.google.com/)
- **Replicate** (optional): `REPLICATE_API_TOKEN`

## CLI

```bash
arka ai_video cinematic drone shot over mountains at golden hour
arka ai_video "a cat walking in rain" -o ~/Videos/cat.mp4 -d 8
arka ai_video check
arka ai_video setup-pollinations          # Selenium (Brave) → save key to .env
```

Get a key manually at [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys), or run `setup-pollinations` (requires `pip install selenium webdriver-manager`; opens Brave with an isolated profile at `~/.arka/pollinations-brave-profile`, not your default browser; login/captcha may need manual steps).

```bash
python3 scripts/pollinations_api_key_selenium.py
BRAVE_BINARY=/path/to/Brave python3 scripts/pollinations_api_key_selenium.py
```

Aliases: `arka generate video`, `arka generate_video`

## Natural language

- "generate full ai video of sunset mountains"
- "create ai video cinematic drone shot over ocean"
- "text to video a robot dancing in neon city"

## Backend chain (`VIDEO_BACKEND=auto`)

1. Pollinations (`wan-fast` by default)
2. Gemini Veo 3.1: `fast` → `lite` → `standard`
3. Replicate (when `REPLICATE_API_TOKEN` is set)

Progress for each attempt is logged to stderr.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `VIDEO_BACKEND` | `auto` | `auto`, `pollinations`, `gemini`, `replicate` |
| `VIDEO_MODEL` | `veo-3.1-generate-preview` | Preferred Gemini model (fallback chain still applies) |
| `VIDEO_ASPECT` | `16:9` | `16:9`, `9:16`, `1:1` |
| `VIDEO_DURATION` | `5` | Seconds (2–15) |
| `VIDEO_POLLINATIONS_MODEL` | `wan-fast` | Pollinations video model |
| `VIDEO_REPLICATE_MODEL` | `minimax/video-01` | Replicate model slug |
| `BRAVE_BINARY` | (auto-detect) | Brave executable for `setup-pollinations` |
| `POLLINATIONS_BRAVE_PROFILE` | `~/.arka/pollinations-brave-profile` | Isolated Brave user-data-dir |
