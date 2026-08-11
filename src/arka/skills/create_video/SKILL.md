# Create Video

Create local videos with ffmpeg — no cloud APIs required. Supports opaque MP4 and transparent alpha output.

## Requirements

- **ffmpeg** on `PATH` with **libvpx-vp9** for WebM alpha (`brew install ffmpeg` or `sudo apt install ffmpeg`)
- **ProRes 4444** (`mov-prores`) needs ffmpeg built with `prores_ks`
- **Pillow** (optional) — only for `text` mode with JSON slide scripts

## CLI

```bash
arka create_video slideshow ./photos/ -o out.mp4 --duration 4
arka create_video slideshow logo.png --transparent -o logo.webm
arka create_video slideshow frames/ --format mov-prores -o out.mov
arka create_video slideshow img1.jpg img2.jpg --audio track.mp3
arka create_video image-audio --image cover.png --audio narration.mp3
arka create_video text --script slides.json
arka create_video check
```

## Natural language

- "create video from images in ./photos"
- "make slideshow from slide1.png slide2.png"
- "create video from cover.jpg with audio narration.mp3"
- "create transparent video from logo.png"

Topic-based explainer videos (`create video about AI`) route to `compose_video` instead.

## Modes

| Mode | Input | Output |
|------|-------|--------|
| `slideshow` | Image files or folder | Video with optional audio |
| `image-audio` | One image + one audio file | Video length of audio |
| `text` | JSON slide script | Video with rendered text slides |

## Transparency

Use `--transparent` / `--alpha` or `--format` to preserve alpha from PNG/WebP inputs:

| Format | Extension | Codec | Notes |
|--------|-----------|-------|-------|
| `webm-alpha` | `.webm` | VP9 + `yuva420p` | Default for `--transparent`; supports audio (Opus) |
| `mov-prores` | `.mov` | ProRes 4444 | Best for editing; large files |
| `mov-png` | `.mov` | PNG frames | Lossless, very large |
| `apng` | `.apng` | APNG | No audio |
| `gif` | `.gif` | GIF + palette | Simple loops; no audio |

PNG inputs with alpha automatically select `webm-alpha` when no format is specified.

## Text slide JSON

```json
[
  {"title": "Hello", "body": "First slide", "duration": 5},
  {"title": "Next", "body": "Second slide", "duration": 4}
]
```

## Limitations

- No AI text-to-video — use `generate video` for that
- No stock photos or TTS — use `compose_video` for narrated explainers
- Slideshow uses fixed duration per slide (default 3s)
- MP4/H.264 does not support alpha — use a transparent format instead
- GIF/APNG do not support audio tracks
