# Human-facing documentation

Use this guide whenever Arka might produce README files, markdown docs, changelogs, contributing guides, or other prose meant for humans to read later—not in chat.

## Golden rule: files, not chat

If the deliverable is documentation someone will **read offline** (README, CHANGELOG, CONTRIBUTING, docs pages, release notes, portfolio copy, ADRs, Notion exports):

1. **Write it to a file** (`README.md`, `docs/...`, `CHANGELOG.md`, etc.).
2. In chat, reply with **one or two lines**: what file was written and how to open it.
3. Do **not** paste the full document into chat unless the user explicitly asks to preview it there.

Chat is for coordination. Markdown files are for reading.

## What counts as human-facing

- README, QUICKSTART, INSTALL, CONTRIBUTING, CHANGELOG, LICENSE notes
- Docs site pages (`docs/**/*.mdx`, `docs/**/*.md`)
- Release notes, migration guides, API overviews for external readers
- About pages, portfolio blurbs, job-application cover letters saved as files
- Comments in PR descriptions when the user asked for a **written draft to paste** → still prefer a `.md` scratch file they can copy from

## What stays in chat

- Short answers to questions ("how do I run tests?")
- Debugging back-and-forth
- Code snippets under ~20 lines when editing live
- Confirmations and next-step suggestions

## Sound human, not generated

Write like a developer explaining the project to a colleague—not like marketing AI.

**Do:**

- Use first person plural sparingly ("we ship", "this repo") or second person ("you can run")
- Vary sentence length; one idea per sentence
- Name concrete commands, paths, and versions
- Admit tradeoffs honestly ("this is experimental", "requires Python 3.11+")
- Use active voice: "Run `arka doctor`" not "The doctor command should be executed"

**Avoid:**

- "In today's fast-paced world", "It's worth noting that", "In conclusion"
- Hollow openers: "Certainly!", "Great question!", "I'd be happy to help"
- Emoji headers and excessive bold
- Symmetrical "Pros / Cons" unless the user asked for a comparison table
- Repeating the user's question back as the first paragraph
- Lists where every bullet starts with the same verb

## Structure defaults

**README:** what it is → quick install → one example → where to learn more. Skip badges unless the repo already uses them.

**CHANGELOG:** reverse chronological, Keep a Changelog style when possible.

**Contributing:** how to set up, how to run tests, how to send a PR—no manifesto.

## File placement

| Intent | Default path |
|--------|----------------|
| Project overview | `README.md` |
| Setup for contributors | `CONTRIBUTING.md` |
| Version history | `CHANGELOG.md` |
| User guide | `docs/guides/<topic>.mdx` or `docs/<topic>.md` |
| Scratch draft | `notes/<slug>.md` or user-provided `--out` |

Ask before overwriting an existing file unless the user said to update it.

## When using LLM generation

- Pass this guide in context (Arka injects it automatically when `HUMAN_DOCS_BIAS` is on).
- After writing, re-read once for AI tells; cut filler.
- Prefer editing existing docs over replacing wholesale.
