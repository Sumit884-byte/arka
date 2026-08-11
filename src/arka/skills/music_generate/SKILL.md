# Music Generate

Generate original music with Pollinations **elevenmusic** (AI) or a local ffmpeg tone-synthesis fallback.

## Requirements

- **Pollinations** (recommended): `POLLINATIONS_API_KEY` from [enter.pollinations.ai](https://enter.pollinations.ai/)
- **Local fallback**: `ffmpeg` on `PATH` — set `MUSIC_BACKEND=synthesize` or leave `MUSIC_BACKEND=auto` without a key
- No extra Python packages

## CLI

```bash
arka music_generate upbeat lo-fi hip hop
arka music_generate indie folk --lyrics "Verse one..."
arka music_generate cinematic orchestral --instrumental
arka music_generate jazz piano -d 45 -o ~/Music/demo.mp3
arka music_generate check
```

Aliases: `arka generate music`, `arka generate_music`

## Natural language

- "generate music about summer nights"
- "create a song indie folk with lyrics hello world"
- "make an instrumental cinematic track for 45 seconds"

## Backends

| `MUSIC_BACKEND` | Behavior |
|-----------------|----------|
| `auto` (default) | Pollinations when key is set, else ffmpeg tones |
| `pollinations` | AI music via elevenmusic (requires key) |
| `synthesize` | Simple pentatonic melody via ffmpeg (no key) |

## Limitations

- Pollinations generation can take up to a minute and needs network access
- Synthesize fallback produces simple tones, not full songs or vocals
- Lyrics and instrumental flags apply to Pollinations only
