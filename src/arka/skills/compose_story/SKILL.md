# compose_story

Create **labeled story videos** from a topic — LLM writes a narrative script with beat labels (intro, conflict, climax, …), burns captions, and fills visual gaps with AI-generated images when stock search misses.

## Usage

```bash
# Natural language (via agent routing)
compose story about a robot learning to paint

# CLI
arka compose_story "a founder's journey from garage to IPO"
compose_story compose --topic "two friends reunite after twenty years" --scenes 6
```

## What you get

- **Labeled beats** — each scene tagged (INTRO, CONFLICT, CLIMAX, …) shown on screen
- **Voiceover + captions** — TTS narration with synced on-screen text
- **Smart visuals** — stock photos/video first; **AI images fill gaps** automatically
- **Sidecar JSON** — scene manifest with labels, prompts, and media credits

## Options

| Flag | Effect |
|------|--------|
| `--story` | Enable story mode (auto-set by compose_story) |
| `--labeled` | Show beat labels on screen |
| `--auto-fill` | AI-generate images when stock misses |
| `--ai-images-only` | All stills from AI (no stock photos) |
| `--scenes N` | Fixed scene count |
| `--duration 2m` | Target runtime |
| `-o path.mp4` | Output path |

## Env

- `GEMINI_API_KEY` — LLM script + AI image gap-fill (recommended)
- `UNSPLASH_ACCESS_KEY` / `PEXELS_API_KEY` — stock visuals
- `VIDEO_ORIENTATION=portrait` — shorts/reels format

## Related

- `compose_video` — tech explainers, hybrid B-roll
- `ai_video` — single full AI video clip (Veo/Pollinations)
- `create_video` — local ffmpeg slideshows
