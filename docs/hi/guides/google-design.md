# Google DESIGN.md guide

Arka, Google के open **DESIGN.md** format का एक curated सारांश bundle करता है, ताकि agents
UI बनाते समय एक सुसंगत visual identity लागू करें — user-facing copy के लिए
[frontend content guide](./frontend-content-guide.md) के साथ।

**Upstream spec:** https://github.com/google-labs-code/design.md

---

## यह क्या करता है

- Frontend/UI goals, coding-tui plans, और `frontend_loop` reviews के लिए अपने-आप inject होता है
- अगर project-root में `DESIGN.md` मौजूद हो, तो उसे प्राथमिकता देता है
- अन्यथा bundled `google-design.md` (format rules + agent workflow) पर fall back करता है
- MCP / CLI aliases उपलब्ध कराता है: `google-design`, `design.md`, `DESIGN.md`

---

## Environment

`~/.config/arka/.env` में:

```bash
GOOGLE_DESIGN_GUIDE=1                 # default on
GOOGLE_DESIGN_GUIDE_MODE=auto         # auto | always | off
FRONTEND_CONTENT_GUIDE=1              # copy policy (paired by default)
```

किसी भी guide को स्वतंत्र रूप से disable करने के लिए उसे `0` पर सेट करें।

---

## CLI

```bash
arka md_doc read google-design
arka md_doc read design.md            # project DESIGN.md if present
arka md_doc context google-design
```

Natural language (symbolic routing):

```text
follow google design.md
use design.md for this UI
```

---

## MCP

`arka_markdown` ये स्वीकार करता है:

| Alias | किस पर resolve होता है |
|-------|-------------|
| `google-design` | project का `DESIGN.md` या bundled guide |
| `design.md` | वही |
| `frontend-content-guide` | bundled copy policy |

उदाहरण: `action=read`, `path=google-design` के साथ `arka_markdown`।

---

## Project DESIGN.md

Repo root पर एक project-specific `DESIGN.md` commit करें (YAML tokens + markdown
sections)। Arka इसे bundled सारांश की तुलना में प्राथमिकता देगा। इससे validate करें:

```bash
npx @google/design.md lint DESIGN.md
```

पूरे token schema, section order, और CLI reference के लिए
[official spec](https://github.com/google-labs-code/design.md) देखें।
