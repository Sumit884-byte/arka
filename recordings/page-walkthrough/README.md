# Page walkthrough capture

Playwright script that records step-by-step PNGs and a WebM walkthrough of the
Arka web dashboard. Output lands in `recordings/live-demo-ui/run-*/`, which is
gitignored.

## CLI (preferred)

```bash
pip install playwright
playwright install chromium
arka capture video --walkthrough
```

Or capture a custom URL:

```bash
arka capture video http://127.0.0.1:5173 --walkthrough --output my-run/
```

## Standalone script

Prerequisites: `arka serve`, web bridge (`python3 web/bridge.py`), and Playwright.

```bash
pip install playwright
playwright install chromium
python3 recordings/page-walkthrough/walkthrough.py
```

Set `ARKA_WALKTHROUGH_URL` to target a different base URL. Set
`ARKA_WALKTHROUGH_NO_VIDEO=1` for PNG-only output.

## MCP is still PNG-only

**Arka MCP captures PNGs only — no video.** IDE agents using `web_screenshot` or
similar MCP skills get still images, not walkthrough recordings. Use `arka capture video`
or this script when you need a full UI walkthrough artifact.

Committed polished stills live in `recordings/live-demo-ui/*.png`. The empty
[`../video/`](../video/) folder is for committed MP4s when explicitly checked in.
