# Dub Video

Translate and re-voice local videos — transcribe speech, translate, synthesize TTS, mux onto video.

## Pipeline

1. **Transcribe** — Groq/Sarvam/Whisper via `media_transcript`
2. **Translate** — Google Translate (free client)
3. **TTS** — Edge TTS (most languages) or Sarvam Bulbul (Indic, needs `SARVAM_API_KEY`)
4. **Mux** — Replace audio track with `edit_video` mux

## CLI

```bash
arka dub_video dub reel.mp4 --target hindi
arka dub_video dub talk.mp4 --target es --source en
arka dub_video dub clip.mp4 --target ta --script narration.txt
arka dub_video check
```

## Natural language

- "dub reel.mp4 to hindi"
- "translate and dub clip.mp4 into tamil"
- "dubbing video.mp4 in spanish"

## MCP (`arka_dub_video`)

```json
{
  "action": "dub",
  "path": "/path/to/reel.mp4",
  "target": "hindi",
  "output": "/path/to/reel-dub-hi.mp4"
}
```

Sidecar files: `<output-stem>.transcript.txt` and `.translation.txt`.

## Requirements

- ffmpeg
- STT: `GROQ_API_KEY`, `SARVAM_API_KEY`, or local faster-whisper
- TTS: `edge-tts` (pip) and/or `SARVAM_API_KEY` for Indic voices
