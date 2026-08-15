# ComputeHistory reference — dependency graph implementation

File map for `/Users/sumitmishra/dev/computer_history`:

| File | Role |
|------|------|
| `data.js` | `MILESTONES`, `ERAS`, `DEPENDENCY_NODES`, `DEPENDENCIES` |
| `app.js` | `renderDependencyGraph`, layout, drag, hover (~lines 706–1433) |
| `styles.css` | `.dependency-*`, `.dep-*` (~lines 868–1165) |
| `index.html` | `#dependency-graph` section (~lines 136–156) |

## Key functions (`app.js`)

| Function | Purpose |
|----------|---------|
| `buildDependencyAdjacency()` | upstream/downstream maps |
| `collectInfluencePath(nodeId, adj)` | BFS ancestors + descendants for node hover |
| `isInfluencePathEdge(from, to, up, down)` | edge in highlighted chain |
| `computeDependencyDepths()` | longest-path column assignment |
| `computeDependencyLayout(width)` | x/y positions, viewBox size |
| `depEdgePath(from, to, r)` | cubic bezier; horizontal vs vertical lane offset |
| `depEdgeLabelPoint(from, to, r, index)` | label anchor with stagger |
| `assignDependencyEdgeColors()` | unique per-edge color from era palette |
| `applyDependencyEdgeColor(el, color)` | sets `--edge-color`, `--edge-color-bright` |
| `renderDependencyGraph()` | full SVG rebuild |
| `updateEdgesForNode(svg, id, positions, r)` | live edge update during drag |
| `resetDependencyLayout()` | clear overrides, re-render |

## Layout constants

```javascript
const nodeRadius = 26;
const labelSpace = 38;
const rowGap = 112;
const colGap = Math.max(128, Math.min(168, (width - paddingX * 2) / maxDepth));
const DEP_DRAG_THRESHOLD = 5;
```

## SVG layer order

1. `<defs>` markers
2. `<g class="dep-edges">` — hit paths + visible paths
3. `<g class="dep-nodes">` — node groups
4. `<g class="dep-edge-labels">` — label rects + text (on top)

## CSS variables

Per edge (set in JS):

- `--edge-color` — base stroke/label tint
- `--edge-color-bright` — hover/highlight (tintHex +0.22)

Per node:

- `--node-color` — from era `color`

## Hover state classes

| Class | Applied to | Effect |
|-------|------------|--------|
| `is-dimmed` | svg root | non-highlighted → opacity 0.18 |
| `is-edge-focus` | svg root | edge-only hover mode |
| `is-edge-hovered` | one edge + label group | bright stroke |
| `is-highlighted` | nodes/edges in influence path | bright |
| `is-active` | focused/hovered node | strongest ring glow |
| `is-node-dragging` | svg root | disable edge label pointer events |
| `is-dragging` | node being dragged | grabbing cursor |

## Edge color assignment algorithm

1. Prefer `milestoneEraColor(edge.to)`, then `edge.from`, then era palette
2. Pick first unused color (case-insensitive)
3. If exhausted, tint base by 8–40% steps until unique

## Bezier routing

- Nearly horizontal (`|dy| < 10`): control point at 55% of dx
- Otherwise: lane offset ±18px at 42% dx to reduce overlap

## Label width

```javascript
const labelWidth = Math.max(56, edge.label.length * 5.8 + 14);
```

## Approved edge labels only

```javascript
const APPROVED_LABELS = ["evolved from", "built on", "enabled", "succeeded by"];
```

## Chronology guard (validate in data or script)

```javascript
function validateDependencies(milestones, deps) {
  const year = id => milestones.find(m => m.id === id)?.year;
  return deps.filter(e => {
    const fy = year(e.from), ty = year(e.to);
    return fy != null && ty != null && fy <= ty;
  });
}
```

## HTML ids expected by app.js

- `#dependency-graph-wrap`
- `#dependency-graph-svg`
- `#dependency-tooltip`
- `#dependency-reset-layout`

## Init

```javascript
function initDependencyGraph() {
  renderDependencyGraph();
  window.addEventListener("resize", debounce(renderDependencyGraph, 150));
}
```

Call on `DOMContentLoaded` after entity data is loaded.
