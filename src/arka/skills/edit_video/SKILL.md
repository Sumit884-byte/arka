# Edit Video

Local ffmpeg video editing — trim, concat, caption, extract audio, crop, resize, and mux audio.

## Requirements

- **ffmpeg** and **ffprobe** on `PATH` (`brew install ffmpeg`)

## CLI

```bash
arka edit_video trim clip.mp4 --start 5 --duration 10
arka edit_video concat part1.mp4 part2.mp4 -o full.mp4
arka edit_video overlay-text reel.mp4 --text "Subscribe!"
arka edit_video extract-audio talk.mp4
arka edit_video mux-audio clip.mp4 --audio narration.mp3
arka edit_video crop video.mp4 --width 1080 --height 1920
arka edit_video resize clip.mp4 --width 1280
arka edit_video check
```

## Natural language

- "trim clip.mp4 from 10 to 30"
- "concat part1.mp4 part2.mp4"
- `add text "Hello" to video.mp4`
- "extract audio from talk.mp4"
- "add audio narration.mp3 to video.mp4"
- "crop video.mp4 to 1080x1920"

## MCP (`arka_edit_video`)

| Action | Purpose |
|--------|---------|
| `trim` | Cut a time range |
| `concat` | Join clips (`paths` + `output`) |
| `overlay-text` | Burn caption (`text`) |
| `extract-audio` | Rip audio track |
| `mux-audio` | Attach audio to video (`audio`) |
| `crop` / `resize` | Reframe or scale |
| `detect` | Duration + media kind |
| `parse` | NL → argv |
| `check` | Verify ffmpeg |

Example MCP call:

```json
{
  "action": "trim",
  "path": "/path/to/reel.mp4",
  "start": 0,
  "duration": 60,
  "output": "/path/to/reel-trimmed.mp4"
}
```
