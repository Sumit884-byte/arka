"""Generate a Three.js rig-inspection scene for skinned GLB/GLTF characters."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title><style>html,body{{margin:0;height:100%;overflow:hidden;background:#090d1b}}#hud{{position:fixed;z-index:2;color:#fff;padding:14px;font:14px system-ui;background:#111a;line-height:1.5}}canvas{{display:block}}</style><script type="importmap">{{"imports":{{"three":"https://unpkg.com/three@0.170.0/build/three.module.js"}}}}</script></head><body><div id="hud">{title}<br><span id="clips">Loading rig…</span></div><script type="module">
import * as THREE from 'https://unpkg.com/three@0.170.0/build/three.module.js';import {{OrbitControls}} from 'https://unpkg.com/three@0.170.0/examples/jsm/controls/OrbitControls.js';import {{GLTFLoader}} from 'https://unpkg.com/three@0.170.0/examples/jsm/loaders/GLTFLoader.js';
const scene=new THREE.Scene();scene.background=new THREE.Color(0x090d1b);const camera=new THREE.PerspectiveCamera(40,innerWidth/innerHeight,.1,100);camera.position.set(3,2,6);const renderer=new THREE.WebGLRenderer({{antialias:true}});renderer.setSize(innerWidth,innerHeight);renderer.setPixelRatio(devicePixelRatio);document.body.append(renderer.domElement);const controls=new OrbitControls(camera,renderer.domElement);controls.target.y=1;controls.update();scene.add(new THREE.HemisphereLight(0xc8dcff,0x20243b,2));const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(3,6,4);scene.add(key);const loader=new GLTFLoader();const clock=new THREE.Clock();let mixer;
loader.load({model},g=>{{scene.add(g.scene);mixer=new THREE.AnimationMixer(g.scene);const names=g.animations.map(a=>a.name);document.querySelector('#clips').textContent=`Clips: ${{names.join(', ')||'none'}} · bones: ${{g.scene.getObjectByProperty('isBone',true)?'detected':'not detected'}}`;if(g.animations[0])mixer.clipAction(g.animations[0]).play();g.scene.traverse(o=>{{if(o.isSkinnedMesh){{const helper=new THREE.SkeletonHelper(o);helper.material.linewidth=2;scene.add(helper)}}}})}},undefined,e=>document.querySelector('#clips').textContent='Rig load failed: '+e.message);function loop(){{requestAnimationFrame(loop);mixer?.update(clock.getDelta());renderer.render(scene,camera)}}loop();addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)}});
</script></body></html>"""


def create(title: str, model: str, output: str) -> dict[str, str]:
    if not model.lower().split("?")[0].endswith((".glb", ".gltf")):
        raise ValueError("rigging requires a .glb or .gltf model URL/path")
    root = Path(output).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.html"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {target}")
    target.write_text(HTML.format(title=title or "Arka Rig Lab", model=json.dumps(model)), encoding="utf-8")
    return {"output": str(target), "model": model, "features": "skeleton helper, animation clips, orbit controls"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka rig-3d")
    p.add_argument("title")
    p.add_argument("--model", required=True)
    p.add_argument("--out", default="arka-rig")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = create(args.title, args.model, args.out)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"Created rig lab: {result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
