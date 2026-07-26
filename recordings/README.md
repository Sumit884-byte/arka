# Demo recordings

Curated demo captures for judges, docs, and hackathon submissions: CLI screenshots,
terminal transcripts, UI walkthrough PNGs/WebM, and SigNoz UI captures.

## Browser video capture (CLI)

Record walkthrough **videos** (WebM) and step PNGs with Playwright:

```bash
pip install playwright
playwright install chromium
arka capture video https://example.com
arka capture video --walkthrough   # Arka web dashboard preset
python3 recordings/page-walkthrough/walkthrough.py
```

Output for dashboard walkthroughs lands in `recordings/live-demo-ui/run-*/`
(gitignored). See [`page-walkthrough/README.md`](page-walkthrough/README.md) and
[`docs/guides/video-capture.mdx`](../docs/guides/video-capture.mdx).

## MCP screenshot capture (PNG only)

**Arka MCP captures PNGs only — no video.** Headless browser skills such as
`web_screenshot`, `browser_check`, and `component_screenshots` write still images.
They do not produce walkthrough videos or screen recordings. Use `arka capture video`
for MP4/WebM artifacts.

Committed walkthrough **videos** are not stored here by default — see
[`video/`](video/) (intentionally empty). Per-run UI captures under
`live-demo-ui/run-*/` are gitignored build output.

## Regenerate a UI walkthrough

For a new web-dashboard walkthrough (step PNGs + WebM under `live-demo-ui/run-*/`):

```bash
pip install playwright
playwright install chromium
python3 recordings/page-walkthrough/walkthrough.py
```

Requires `arka serve` and the web bridge running — see [`web/README.md`](../web/README.md).

## Other capture scripts

| Script | Output |
| --- | --- |
| `capture_terminal.py` / `capture_terminal_extra.py` | Terminal transcripts in `terminal_captures/` |
| `export_cli_images.py` / `export_cli_images_extra.py` | CLI screenshot JPGs in `cli-images/` |
| `build_demo_video.py` | Terminal demo MP4 via `arka terminal_video` |
| `signoz-screenshots/capture_signoz_ui.py` | SigNoz UI PNGs in `signoz-screenshots/` |
| `page-walkthrough/walkthrough.py` | Dashboard walkthrough PNGs + WebM in `live-demo-ui/run-*/` |

Regeneratable build artifacts (`_demo_build/`, `live-demo-ui/run-*/`) are
gitignored — see [`docs/architecture/repository-layout.md`](../docs/architecture/repository-layout.md).
