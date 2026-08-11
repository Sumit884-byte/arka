# Compose Video

YouTube-style narrated explainers — stock photo/video B-roll, optional charts, TTS, ffmpeg.

## Default: hybrid mode

- **No on-screen text** burned in (voiceover/TTS still plays)
- Per scene: stock **video** when motion fits, **photo** otherwise (LLM `media_type` or heuristic)
- Opt in to captions with `--text` or `VIDEO_BURN_TEXT=1`

## CLI

```bash
arka compose_video compose --topic "AI infrastructure" --llm
arka compose_video compose --topic "mountains at sunset" --scenes 4
arka compose_video compose --topic "AI trends" --text          # legacy captions
arka compose_video compose --topic "AI trends" --mode photos   # image-only
arka compose_video compose --topic "travel reel" --mode video    # all stock video
arka compose_video check
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `VIDEO_MODE` | `hybrid` | `hybrid`, `photos`, `video`, `auto` |
| `VIDEO_BURN_TEXT` | off in hybrid | `1` burns titles/captions |
| `VIDEO_NO_TEXT` | — | Force no burned-in text |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | — | Stock video sources |
| `UNSPLASH_ACCESS_KEY` / photo keys | — | Stock photos |
| `BRIGHTDATA_API_TOKEN` | — | Fallback image/video search via Bright Data SERP |
| `VIDEO_STOCK_FALLBACK` | `brightdata` | Enable fallback (`none` to disable) |
| `VIDEO_PHOTO_SOURCES` | includes `brightdata` | Photo source chain order |
| `VIDEO_VIDEO_SOURCES` | includes `brightdata` | Video source chain order |

## Scene JSON

Include `media_type` per scene when writing scripts manually:

```json
{
  "title": "Golden peaks",
  "narration": "At dawn the mountains glow.",
  "media_type": "video",
  "image_keywords": ["mountain sunrise", "alpine ridge"]
}
```

Use `image` for charts, concepts, portraits, diagrams.
