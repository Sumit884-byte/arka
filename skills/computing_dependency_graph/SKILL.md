---
name: computing-dependency-graph
description: >-
  Build interactive causal/evolution dependency graphs with vanilla SVG — data
  model, validation rules, layout, multicolor edges, drag, and hover. Use when
  the user asks for a dependency graph, influence map, milestone DAG, technology
  lineage, or computing evolution graph like ComputeHistory.
argument-hint: <domain or project path>
---

# Computing Dependency Graph

Build **interactive influence / dependency graphs** for milestones, inventions, or systems — left-to-right by era, branching paths, labeled causal edges, drag-to-rearrange, and hover highlighting.

Reference implementation: `/Users/sumitmishra/dev/computer_history` (`data.js`, `app.js`, `styles.css`, `index.html`).

## When to use

Use this skill when the user wants:

- A **dependency graph**, **influence map**, **causal graph**, or **evolution graph**
- A **milestone DAG** showing how breakthroughs enabled later ones
- A **technology lineage** or **computing history** graph section in a static site
- To **audit or fix** edges in an existing graph (chronology, causality, labels)

Do **not** use for code-repo dependency graphs → use Arka `graphify` instead.

## Invoke via Arka

```text
arka_skill({ skill: "computing_dependency_graph" })
arka_skill({ skill: "computing_dependency_graph", args: "computing history" })
```

CLI / fish (after `arka skills refresh`):

```bash
arka computing_dependency_graph
arka skills run computing_dependency_graph
```

Install to any path Arka scans (then `arka skills refresh`):

| Path | When |
|------|------|
| `~/.config/arka/skills/computing_dependency_graph/` | Default user config |
| `~/.local/share/arka/skills/computing_dependency_graph/` | Shared install (always scanned) |
| `$CONFIG_DIR/skills/computing_dependency_graph/` | Dev trees where `CONFIG_DIR` is the Arka repo |

Cursor agents also load: `~/.agents/skills/computing-dependency-graph/SKILL.md`

---

## Data model

### Entity catalog (nodes source of truth)

Each milestone/system in a shared catalog with at least:

```javascript
{ id: "intel-4004", name: "Intel 4004", year: 1971, era: "microprocessors", category: "Hardware", ... }
```

Optional era metadata for colors/icons:

```javascript
{ id: "microprocessors", name: "Microprocessor Age", color: "#6c5ce7", icon: "🖲️", ... }
```

### Graph nodes

Subset of catalog ids plus optional **row** for vertical branching:

```javascript
const DEPENDENCY_NODES = [
  { id: "transistor", row: 0 },      // main hardware spine
  { id: "apollo-guidance", row: 1 }, // side branch
  { id: "www", row: 2 },             // networking branch
];
```

- **`id`**: must exist in the entity catalog
- **`row`**: integer lane (0 = main path); same depth column can stack multiple rows

### Graph edges

Directional, labeled causal links:

```javascript
const DEPENDENCIES = [
  { from: "transistor", to: "intel-4004", label: "built on" },
];
```

- **`from` → `to`**: influence flows left to right (earlier → later)
- **`label`**: one of the four approved verbs (see validation)

---

## Validation rules (mandatory)

Run these **before** committing edge data. Every edge needs a one-sentence mechanism.

### 1. CHRONOLOGY

Every edge from **earlier year → later year**. Flag or remove any backwards edge.

### 2. CAUSAL REALITY

Real documented technical/design lineage only — not "next in chronological list." One-sentence mechanism required per edge. Remove edges without real mechanism.

- BAD: Apollo AGC → WWW (no link)
- GOOD: Transistor → Intel 4004 (transistors are building blocks of microprocessors)

### 3. NO ORPHAN/DEAD-END

Significant nodes with obvious downstream effects must connect (e.g. WWW → GPT-4 via data/training infrastructure if justifiable, or WWW → iPhone for mobile web — audit all nodes aren't dead ends without reason).

Side branches (e.g. Apollo AGC) may end without merging if the milestone is intentionally peripheral.

### 4. LABEL ACCURACY

- **evolved from** = direct successor, same lineage (target evolved from source)
- **built on** = foundational component or conceptual/technical basis
- **enabled** = necessary technical precondition (often indirect, multi-hop)
- **succeeded by** = replacement in same category

Do not use interchangeably. **Never use** "evolved to" — use **evolved from** with correct direction.

### Validation checklist

```
- [ ] All from-years ≤ to-years
- [ ] Each edge has a one-sentence justification
- [ ] No chronology-only edges
- [ ] No significant dead-end nodes without reason
- [ ] Labels match mechanism type
- [ ] Every DEPENDENCY_NODES id appears in ≥1 edge (or document why isolated)
```

---

## Example edge list (computing history)

| Source | Target | Label | Justification |
|--------|--------|-------|---------------|
| abacus | difference-engine | evolved from | Mechanical calculation lineage from bead tools to Babbage's engine |
| difference-engine | eniac | built on | Programmable/automated calculation concepts realized electronically |
| eniac | transistor | succeeded by | Transistors replaced vacuum tubes in electronic switching |
| eniac | www | enabled | General-purpose computers made packet networking and the Web feasible |
| transistor | apollo-guidance | built on | AGC integrated circuits used transistor semiconductor fabrication |
| transistor | intel-4004 | built on | Microprocessors are CPUs built from transistors on one chip |
| intel-4004 | apple-ii | enabled | Single-chip CPU made mass-market personal computers viable |
| www | iphone | enabled | Mobile web required HTTP/HTML and internet infrastructure |
| www | gpt-4 | enabled | Web-scale text corpora supply LLM training data |
| iphone | gpt-4 | enabled | Smartphones made AI assistants accessible to mainstream users |

Common **removed** weak edges: `www → apple-ii` (backwards in time — use `intel-4004 → apple-ii`), `apple-ii → iphone` (not a direct product lineage — use `www → iphone` for mobile web), `transistor → www` (too indirect), `apollo-guidance → intel-4004` (different lineage), `iphone → gpt-4` as **built on** (use **enabled**).

---

## Implementation checklist

Vanilla HTML/CSS/JS — no graph library required.

### HTML section

```html
<section class="section dependency-section" id="dependency-graph">
  <div class="dependency-graph-wrap" id="dependency-graph-wrap">
    <svg class="dependency-graph-svg" id="dependency-graph-svg" role="img"
         aria-label="Dependency graph"></svg>
    <div class="dependency-tooltip" id="dependency-tooltip" hidden></div>
  </div>
  <div class="dependency-legend">
    <span class="dependency-legend-hint">Drag nodes · Hover paths · Click details · Double-click node to reset</span>
    <button type="button" class="dependency-reset-btn" id="dependency-reset-layout" hidden>Reset layout</button>
  </div>
</section>
```

### Data (`data.js`)

- `DEPENDENCY_NODES`, `DEPENDENCIES`
- Entity catalog with `year` for chronology checks

### Layout (`computeDependencyLayout`)

1. **Depth**: longest path from sources (`depth[to] = max(depth[from]+1)`)
2. **Columns**: `x = paddingX + depth * colGap`
3. **Rows**: `y = paddingY + row * rowGap`; enforce min vertical gap for label clearance
4. **Merge overrides** after drag (`depNodePositionOverrides`)

### SVG render (`renderDependencyGraph`)

- [ ] `<defs>` arrow marker (`dep-arrow`)
- [ ] Edges: invisible **hit path** (wide stroke) + visible path + label group
- [ ] **Multicolor edges**: assign unique `--edge-color` per edge (era colors + tint variants)
- [ ] **Color-coded labels**: label fill/stroke derived from `--edge-color`
- [ ] Nodes: glow, ring, hit circle, era icon, name, year
- [ ] Draw edges **under** nodes; label groups **above** nodes

### Interactions

- [ ] **Single-edge hover**: dim all except hovered edge + its endpoints (`is-edge-focus`)
- [ ] **Node hover**: highlight directly connected edges and neighbor nodes (`is-dimmed`)
- [ ] **Draggable nodes**: pointer capture, 5px threshold, update connected edge paths live
- [ ] **Reset layout**: button clears all overrides; double-click single node resets that node
- [ ] **Click node**: open detail modal; suppress click after drag
- [ ] **Tooltip**: follows cursor on edge/node hover

### CSS essentials

- `.dependency-graph-wrap` — scroll container, dark gradient background
- `.dep-edge` — `stroke: color-mix(... var(--edge-color))`, arrow via `marker-end`
- `.dep-edge-label` — `fill: color-mix(... var(--edge-color) 80%, white)` (**not** parent opacity)
- `.is-dimmed` — `opacity: 0.18` on non-highlighted elements
- `.is-edge-hovered` / `.is-highlighted` — bright `--edge-color-bright`, thicker stroke
- `.dep-node-hit` — `cursor: grab`; disable edge pointer events while dragging

Full CSS/JS patterns: [reference.md](reference.md)

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Backwards edges (later → earlier) | Reverse or remove; verify against `year` |
| Chronology-only edges | Require documented mechanism |
| `www → apple-ii` or other backwards-time edges | Remove; verify against milestone `year` |
| `apple-ii → iphone` as lineage | Not a real technical lineage; use `www → iphone` instead |
| `apple-ii → www` or other cross-domain leaps | Only if real causal story exists |
| `evolved to` label | Use `evolved from` (edge direction: predecessor → successor) |
| `built on` for distribution/access | Use `enabled` |
| `opacity` on parent group for dimming | Dim elements individually — parent opacity washes out label colors |
| Edge labels behind nodes | Append label group **after** nodes group |
| Duplicate edge colors | `assignDependencyEdgeColors()` with tint fallback |
| Orphan milestones in graph | Connect or remove from `DEPENDENCY_NODES` |
| Missing hit targets | Add `.dep-edge-hit` with `stroke-width: 12` |

---

## Workflow

1. Define entity catalog with years and era colors
2. Draft `DEPENDENCY_NODES` + `DEPENDENCIES`
3. **Validate** all four rules; write justifications table
4. Scaffold HTML section + CSS classes
5. Implement layout + render + interactions (checklist above)
6. `node --check` on JS files; manual hover/drag/reset test
7. Resize handler debounced re-layout (preserve drag overrides)

---

## Additional resources

- [reference.md](reference.md) — key functions, CSS selectors, file map from ComputeHistory
