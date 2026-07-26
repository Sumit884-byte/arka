# Video folder (intentionally empty)

This folder holds committed walkthrough **videos** when needed. It is empty by
default.

**Arka MCP captures PNGs only — no video.** MCP browser skills write still
images, not screen recordings. Do not expect video files from `arka mcp call`
or headless skills like `web_screenshot`.

To regenerate a UI walkthrough (PNG sequence + optional local MP4 under
`live-demo-ui/run-*/`, gitignored):

```bash
pip install playwright
playwright install chromium
python3 recordings/page-walkthrough/walkthrough.py
```

See [`../README.md`](../README.md) and [`../page-walkthrough/README.md`](../page-walkthrough/README.md).
