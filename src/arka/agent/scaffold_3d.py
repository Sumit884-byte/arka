"""Deterministic greenfield scaffold for beautiful 3D space web apps."""
from __future__ import annotations

from pathlib import Path

_3D_GOAL_TOKENS = (
    "3d space",
    "3d simulation",
    "space simulation",
    "three.js",
    "threejs",
    "react 3d",
    "react three",
    "orbit controls",
    "starfield",
    "beautiful 3d",
    "3d scene",
    "3d world",
    "cosmos",
    "solar system",
)

_3D_GOAL_PATTERNS = (
    r"\b3d\b.*\b(?:space|scene|simulation|world|cosmos)\b",
    r"\b(?:space|cosmos|universe)\b.*\b3d\b",
    r"\bthree\.?js\b",
    r"\b@react-three\b",
)


def goal_mentions_3d_space(goal: str) -> bool:
    """True when the goal asks for an interactive 3D space / scene app."""
    text = " ".join((goal or "").lower().split())
    if any(token in text for token in _3D_GOAL_TOKENS):
        return True
    import re

    return any(re.search(pattern, text) for pattern in _3D_GOAL_PATTERNS)


def is_greenfield_repo(root: Path) -> bool:
    """True for empty or nearly empty project directories."""
    if not root.is_dir():
        return False
    files = sum(1 for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
    if files == 0:
        return True
    return (
        files < 5
        and not (root / "package.json").is_file()
        and not (root / "pyproject.toml").is_file()
    )


def should_scaffold_3d(goal: str, root: Path, *, is_arka_repo: bool = False) -> bool:
    if is_arka_repo:
        return False
    return is_greenfield_repo(root) and goal_mentions_3d_space(goal)


def scaffold_file_manifest() -> list[tuple[str, str]]:
    """Return (relative_path, description) pairs for plan previews."""
    return [
        ("package.json", "npm project with React, Vite, Three.js, and R3F"),
        ("vite.config.js", "Vite dev server with the React plugin"),
        ("index.html", "HTML shell that mounts the React app"),
        ("src/main.jsx", "React root entry point"),
        ("src/App.jsx", "Canvas scene: starfield, Earth, Moon, orbit controls"),
        ("src/App.css", "dark space theme and layout"),
        ("README.md", "setup steps and npm scripts"),
    ]


def _package_json() -> str:
    return """{
  "name": "space-simulation",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@react-three/drei": "^9.117.3",
    "@react-three/fiber": "^8.17.10",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.170.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.3"
  }
}
"""


def _vite_config() -> str:
    return """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
"""


def _index_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Beautiful 3D Space</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""


def _main_jsx() -> str:
    return """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './App.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
"""


def _app_jsx() -> str:
    return """import { Suspense, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'

function Earth() {
  const ref = useRef()
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta * 0.15
  })
  return (
    <mesh ref={ref} position={[0, 0, 0]}>
      <sphereGeometry args={[1.2, 64, 64]} />
      <meshStandardMaterial color="#4f8cff" emissive="#112244" emissiveIntensity={0.35} roughness={0.55} metalness={0.2} />
    </mesh>
  )
}

function Moon() {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (!ref.current) return
    const t = clock.getElapsedTime() * 0.35
    ref.current.position.x = Math.cos(t) * 3.2
    ref.current.position.z = Math.sin(t) * 3.2
    ref.current.rotation.y += 0.01
  })
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.35, 48, 48]} />
      <meshStandardMaterial color="#d9d9d9" roughness={0.85} metalness={0.05} />
    </mesh>
  )
}

function SpaceScene() {
  return (
    <>
      <color attach="background" args={['#02040a']} />
      <fog attach="fog" args={['#02040a', 14, 42]} />
      <ambientLight intensity={0.25} />
      <pointLight position={[6, 4, 2]} intensity={1.4} color="#ffd27a" />
      <pointLight position={[-5, -2, -4]} intensity={0.5} color="#6ea8ff" />
      <Stars radius={80} depth={40} count={6000} factor={3.5} saturation={0.15} fade speed={0.6} />
      <Earth />
      <Moon />
      <OrbitControls enablePan enableZoom enableRotate minDistance={2.5} maxDistance={18} />
    </>
  )
}

export default function App() {
  return (
    <div className="app">
      <header className="hud">
        <h1>Beautiful 3D Space</h1>
        <p>Drag to orbit · scroll to zoom · watch Earth and Moon drift through the stars</p>
      </header>
      <Canvas camera={{ position: [0, 1.5, 6], fov: 55 }}>
        <Suspense fallback={null}>
          <SpaceScene />
        </Suspense>
      </Canvas>
    </div>
  )
}
"""


def _app_css() -> str:
    return """* {
  box-sizing: border-box;
}

html,
body,
#root {
  width: 100%;
  height: 100%;
  margin: 0;
}

body {
  font-family: Inter, system-ui, sans-serif;
  background: radial-gradient(circle at top, #0b1020 0%, #02040a 55%, #000 100%);
  color: #e8eefc;
}

.app {
  position: relative;
  width: 100%;
  height: 100%;
}

canvas {
  display: block;
}

.hud {
  position: absolute;
  top: 1.25rem;
  left: 1.25rem;
  z-index: 2;
  max-width: 28rem;
  padding: 0.85rem 1rem;
  border-radius: 0.85rem;
  background: rgba(4, 8, 18, 0.72);
  border: 1px solid rgba(120, 160, 255, 0.25);
  backdrop-filter: blur(8px);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
}

.hud h1 {
  margin: 0 0 0.35rem;
  font-size: 1.15rem;
  letter-spacing: 0.02em;
}

.hud p {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.45;
  color: #a8b8d8;
}
"""


def _readme() -> str:
    return """# Beautiful 3D Space

A React + Vite + Three.js starfield scene with Earth, Moon, and orbit controls.

## Setup

```bash
npm install
npm run dev
```

Open the printed local URL in your browser.

## Scripts

- `npm run dev` — start the Vite dev server
- `npm run build` — production build
- `npm run preview` — preview the production build
"""


def scaffold_files() -> dict[str, str]:
    return {
        "package.json": _package_json(),
        "vite.config.js": _vite_config(),
        "index.html": _index_html(),
        "src/main.jsx": _main_jsx(),
        "src/App.jsx": _app_jsx(),
        "src/App.css": _app_css(),
        "README.md": _readme(),
    }


def write_scaffold(root: Path, *, force: bool = False) -> list[str]:
    """Write scaffold files under *root*. Returns relative paths created."""
    created: list[str] = []
    for rel_path, content in scaffold_files().items():
        target = root / rel_path
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def has_meaningful_scaffold(root: Path) -> bool:
    """True when the project has the core 3D app files."""
    app = root / "src/App.jsx"
    if not app.is_file():
        return False
    text = app.read_text(encoding="utf-8", errors="replace")
    return "@react-three/fiber" in text and "Canvas" in text
