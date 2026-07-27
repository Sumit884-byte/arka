# Demo recordings

Scripts and **small text captures** for regenerating demo videos locally. **No
videos, screenshots, voiceover audio, or PNG/WebM binaries are committed** — build
them on your machine and upload to Devpost/YouTube separately.

## SigNoz hackathon demo (~3 min)

```bash
# Terminal captures (text) — already small; regenerate if CLI output changes
# recordings/signoz_captures/*.txt

# Optional: fresh SigNoz UI PNGs (requires local SigNoz on :8080)
python3 recordings/signoz-screenshots/capture_signoz_ui.py --no-dashboard

# Build MP4 + voiceover (output gitignored)
python3 recordings/build_signoz_demo_video.py
# → recordings/arka-signoz-hackathon-demo.mp4
# → recordings/signoz-hackathon-voiceover.mp3
```

Voiceover script source: `recordings/signoz-hackathon-voiceover.txt` (local only).

Devpost / YouTube description (copy-paste): `recordings/signoz-hackathon-demo-description.txt` (includes YouTube chapters + hashtags).

## General Arka terminal demo

```bash
python3 recordings/build_demo_video.py
# → recordings/arka-demo-submission.mp4
```

## Browser video capture (CLI)

```bash
pip install playwright
playwright install chromium
arka capture video --walkthrough
python3 recordings/page-walkthrough/walkthrough.py
```

Output lands in `recordings/live-demo-ui/run-*/` (gitignored).

## MCP screenshot capture (PNG only)

**Arka MCP captures PNGs only — no video.** Use `arka capture video` for WebM/MP4.

## Capture scripts (committed)

| Script | Output (gitignored) |
| --- | --- |
| `capture_terminal.py` / `capture_terminal_extra.py` | `terminal_captures/*.txt` |
| `export_cli_images.py` | `cli-images/*.jpg` |
| `build_demo_video.py` | `arka-demo-submission.mp4` |
| `build_signoz_demo_video.py` | `arka-signoz-hackathon-demo.mp4` |
| `signoz-screenshots/capture_signoz_ui.py` | `signoz-screenshots/*.png` |
| `signoz-screenshots/compose_logs_screenshot.py` | fills `logs-explorer.png` when SigNoz logs UI is empty |
| `page-walkthrough/walkthrough.py` | `live-demo-ui/run-*/` |

Terminal transcript `.txt` files under `terminal_captures/` and `signoz_captures/`
are small and may be committed so CI/builds can run without a live SigNoz instance.
