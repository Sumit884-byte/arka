"""Readable Three.js scene HTML templates with presets and post-processing."""

from __future__ import annotations

import json
from typing import Any

THREE_VERSION = "0.170.0"
THREE_BASE = f"https://unpkg.com/three@{THREE_VERSION}"

PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "studio": {
        "background": "#1a1f2e",
        "fog": {"color": "#1a1f2e", "near": 8, "far": 40},
        "ground": {"color": "#2a3040", "metalness": 0.15, "roughness": 0.85, "size": 30},
        "bloom": False,
        "stars": False,
    },
    "gallery": {
        "background": "#0a0c12",
        "fog": {"color": "#0a0c12", "near": 10, "far": 45},
        "ground": {"color": "#151820", "metalness": 0.65, "roughness": 0.25, "size": 24},
        "bloom": True,
        "stars": False,
    },
    "outdoor": {
        "background": "#87a8c4",
        "fog": {"color": "#b8cfe0", "near": 15, "far": 80},
        "ground": {"color": "#4a6741", "metalness": 0.05, "roughness": 0.95, "size": 60},
        "bloom": False,
        "stars": False,
    },
    "racing": {
        "background": "#101018",
        "fog": {"color": "#101018", "near": 20, "far": 120},
        "ground": {"color": "#222228", "metalness": 0.2, "roughness": 0.7, "size": 80},
        "bloom": False,
        "stars": False,
    },
    "interior": {
        "background": "#1c1814",
        "fog": {"color": "#1c1814", "near": 6, "far": 28},
        "ground": {"color": "#3a3228", "metalness": 0.08, "roughness": 0.9, "size": 18},
        "bloom": False,
        "stars": False,
    },
    "space": {
        "background": "#02040a",
        "fog": {"color": "#02040a", "near": 14, "far": 42},
        "ground": {"color": "#111118", "metalness": 0.3, "roughness": 0.6, "size": 40},
        "bloom": True,
        "stars": True,
    },
    "museum": {
        "background": "#12141a",
        "fog": {"color": "#12141a", "near": 8, "far": 35},
        "ground": {"color": "#2c3038", "metalness": 0.4, "roughness": 0.45, "size": 28},
        "bloom": True,
        "stars": False,
    },
}

DEFAULT_CAMERA = {"position": [4, 3, 7], "target": [0, 1, 0], "fov": 45}


def build_spec(
    *,
    title: str,
    assets: list[dict[str, Any]],
    preset: str = "studio",
    camera: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete scene specification for HTML rendering."""
    preset_key = preset if preset in PRESET_DEFAULTS else "studio"
    return {
        "title": title or "Arka 3D Scene",
        "preset": preset_key,
        "environment": PRESET_DEFAULTS[preset_key],
        "assets": assets,
        "camera": camera or dict(DEFAULT_CAMERA),
    }


def render_html(spec: dict[str, Any]) -> str:
    """Render a self-contained interactive Three.js scene page."""
    title = spec.get("title") or "Arka 3D Scene"
    env = spec.get("environment") or PRESET_DEFAULTS["studio"]
    assets = spec.get("assets") or []
    camera = spec.get("camera") or DEFAULT_CAMERA
    assets_json = json.dumps(assets)
    cam_pos = camera.get("position", DEFAULT_CAMERA["position"])
    cam_target = camera.get("target", DEFAULT_CAMERA["target"])
    cam_fov = camera.get("fov", DEFAULT_CAMERA["fov"])
    fog = env.get("fog") or {}
    ground = env.get("ground") or {}
    bloom = bool(env.get("bloom"))
    stars = bool(env.get("stars"))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
html,body{{margin:0;height:100%;overflow:hidden;background:{env.get('background','#080b18')}}}
canvas{{display:block}}
#hud{{position:fixed;z-index:3;top:0;left:0;right:0;padding:16px 20px;color:#eef2ff;
  font:14px/1.4 system-ui,-apple-system,sans-serif;pointer-events:none;
  background:linear-gradient(180deg,rgba(0,0,0,.55),transparent)}}
#hud h1{{margin:0;font-size:18px;font-weight:600}}
#hud p{{margin:4px 0 0;opacity:.75;font-size:13px}}
#loading{{position:fixed;inset:0;z-index:5;display:flex;align-items:center;justify-content:center;
  background:rgba(8,11,24,.92);color:#fff;font:16px system-ui;transition:opacity .4s}}
#loading.hidden{{opacity:0;pointer-events:none}}
#anim-ui{{position:fixed;z-index:4;bottom:16px;left:16px;display:none;gap:8px;align-items:center;
  background:rgba(0,0,0,.55);padding:10px 12px;border-radius:10px;color:#fff;font:13px system-ui}}
#anim-ui.visible{{display:flex}}
#anim-ui select{{background:#1a2030;color:#fff;border:1px solid #445;padding:4px 8px;border-radius:6px}}
</style>
</head>
<body>
<div id="loading">Loading scene…</div>
<div id="hud"><h1>{_esc(title)}</h1><p>Drag to orbit · scroll to zoom · double-click to reset camera</p></div>
<div id="anim-ui"><label for="clip">Animation</label><select id="clip"></select></div>
<script type="module">
import * as THREE from '{THREE_BASE}/build/three.module.js';
import {{ OrbitControls }} from '{THREE_BASE}/examples/jsm/controls/OrbitControls.js';
import {{ GLTFLoader }} from '{THREE_BASE}/examples/jsm/loaders/GLTFLoader.js';
{_bloom_imports(bloom)}

const SPEC = {{
  assets: {assets_json},
  camera: {{ position: {json.dumps(cam_pos)}, target: {json.dumps(cam_target)}, fov: {cam_fov} }},
  env: {json.dumps(env)},
  bloom: {json.dumps(bloom)},
  stars: {json.dumps(stars)},
}};

const scene = new THREE.Scene();
scene.background = new THREE.Color(SPEC.env.background || '#080b18');
if (SPEC.env.fog) {{
  const f = SPEC.env.fog;
  scene.fog = new THREE.Fog(f.color || '#080b18', f.near || 8, f.far || 40);
}}

const camera = new THREE.PerspectiveCamera(SPEC.camera.fov, innerWidth / innerHeight, 0.1, 500);
camera.position.set(...SPEC.camera.position);

const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
document.body.append(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(...SPEC.camera.target);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.update();

scene.add(new THREE.HemisphereLight(0xbad7ff, 0x182038, 1.2));
const key = new THREE.DirectionalLight(0xffffff, 2.4);
key.position.set(6, 10, 4);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.near = 0.5;
key.shadow.camera.far = 60;
key.shadow.camera.left = -15;
key.shadow.camera.right = 15;
key.shadow.camera.top = 15;
key.shadow.camera.bottom = -15;
scene.add(key);
const fill = new THREE.DirectionalLight(0x8899cc, 0.6);
fill.position.set(-4, 3, -6);
scene.add(fill);
const rim = new THREE.DirectionalLight(0xffd27a, 0.35);
rim.position.set(0, 2, -8);
scene.add(rim);

const g = SPEC.env.ground || {{}};
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(g.size || 30, g.size || 30),
  new THREE.MeshStandardMaterial({{
    color: g.color || '#2a3040',
    metalness: g.metalness ?? 0.15,
    roughness: g.roughness ?? 0.85,
  }})
);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

if (SPEC.stars) {{
  const starGeo = new THREE.BufferGeometry();
  const count = 4000;
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count * 3; i++) pos[i] = (Math.random() - 0.5) * 120;
  starGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({{ color: 0xffffff, size: 0.08, transparent: true, opacity: 0.85 }})));
}}

{_bloom_setup(bloom)}

const loader = new GLTFLoader();
const mixers = [];
const loadedRoots = [];
let pending = SPEC.assets.length;
const loadingEl = document.getElementById('loading');
const animUi = document.getElementById('anim-ui');
const clipSelect = document.getElementById('clip');

function finishLoad() {{
  pending -= 1;
  if (pending <= 0) {{
    loadingEl.classList.add('hidden');
    frameCameraToScene();
  }}
}}

function frameCameraToScene() {{
  if (!loadedRoots.length) return;
  const box = new THREE.Box3();
  for (const root of loadedRoots) box.expandByObject(root);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 1);
  controls.target.copy(center);
  const dist = maxDim * 2.2;
  camera.position.set(center.x + dist * 0.55, center.y + maxDim * 0.6, center.z + dist * 0.85);
  controls.update();
}}

for (const asset of SPEC.assets) {{
  loader.load(asset.url, (gltf) => {{
    const root = gltf.scene;
    root.position.set(...(asset.position || [0, 0, 0]));
    if (asset.rotation) root.rotation.set(...asset.rotation);
    const scale = asset.scale ?? 1;
    if (Array.isArray(scale)) root.scale.set(...scale);
    else root.scale.setScalar(scale);
    root.traverse((o) => {{ if (o.isMesh) {{ o.castShadow = true; o.receiveShadow = true; }} }});
    scene.add(root);
    loadedRoots.push(root);
    if (asset.animate !== false && gltf.animations.length) {{
      const mixer = new THREE.AnimationMixer(root);
      mixer.clipAction(gltf.animations[0]).play();
      mixers.push({{ mixer, clips: gltf.animations, root }});
      if (gltf.animations.length > 1 && mixers.length === 1) {{
        animUi.classList.add('visible');
        for (const clip of gltf.animations) {{
          const opt = document.createElement('option');
          opt.value = clip.name;
          opt.textContent = clip.name;
          clipSelect.appendChild(opt);
        }}
        clipSelect.onchange = () => {{
          const m = mixers[0];
          m.mixer.stopAllAction();
          const clip = m.clips.find((c) => c.name === clipSelect.value) || m.clips[0];
          m.mixer.clipAction(clip).play();
        }};
      }}
    }}
    finishLoad();
  }}, undefined, (err) => {{
    console.warn('model load failed', asset.url, err);
    finishLoad();
  }});
}}

if (!SPEC.assets.length) loadingEl.classList.add('hidden');

addEventListener('dblclick', () => {{
  camera.position.set(...SPEC.camera.position);
  controls.target.set(...SPEC.camera.target);
  controls.update();
}});

const clock = new THREE.Clock();
function animate() {{
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  for (const m of mixers) m.mixer.update(dt);
  controls.update();
  {_bloom_render(bloom)}
}}
animate();

addEventListener('resize', () => {{
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  {_bloom_resize(bloom)}
}});
</script>
</body>
</html>
"""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _bloom_imports(bloom: bool) -> str:
    if not bloom:
        return ""
    return f"""import {{ EffectComposer }} from '{THREE_BASE}/examples/jsm/postprocessing/EffectComposer.js';
import {{ RenderPass }} from '{THREE_BASE}/examples/jsm/postprocessing/RenderPass.js';
import {{ UnrealBloomPass }} from '{THREE_BASE}/examples/jsm/postprocessing/UnrealBloomPass.js';"""


def _bloom_setup(bloom: bool) -> str:
    if not bloom:
        return "let composer = null;"
    return """
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.35, 0.4, 0.85);
composer.addPass(bloomPass);
"""


def _bloom_render(bloom: bool) -> str:
    if not bloom:
        return "renderer.render(scene, camera);"
    return "composer.render();"


def _bloom_resize(bloom: bool) -> str:
    if not bloom:
        return ""
    return "composer.setSize(innerWidth, innerHeight);"
