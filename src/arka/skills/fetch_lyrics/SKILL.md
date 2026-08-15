# Fetch Lyrics

Fetch song lyrics, translate them, and optionally generate a new track with the translated words.

## Providers

- **LRCLIB** (primary) — free search API, no key required
- **lyrics.ovh** (fallback) — free lyrics API

Translation uses Google Translate (same backend as `translate` / `survive_lang`).

## CLI

```bash
arka fetch_lyrics fetch Queen "Bohemian Rhapsody"
arka fetch_lyrics fetch --query "Shape of You by Ed Sheeran"
arka fetch_lyrics translate Queen "Bohemian Rhapsody" --target hindi
arka fetch_lyrics translate "Ed Sheeran" "Shape of You" --target ta --generate --style "tamil pop"
```

## Natural language

- "fetch lyrics for Bohemian Rhapsody by Queen"
- "translate lyrics of Shape of You by Ed Sheeran to hindi"
- "translate song Blinding Lights by The Weeknd to tamil and generate a new song"

## MCP (`arka_fetch_lyrics`)

Actions: `fetch`, `translate`, `parse`, `check`

```json
{ "action": "fetch", "artist": "Queen", "title": "Bohemian Rhapsody" }
{ "action": "translate", "artist": "Queen", "title": "Bohemian Rhapsody", "target": "hindi", "generate": true }
```
