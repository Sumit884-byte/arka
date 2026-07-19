"""Create lightweight 2.5D parallax scenes from layered 2D artwork."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HTML = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title><style>html,body{{margin:0;height:100%;overflow:hidden;background:#091122}}#scene{{position:relative;width:100vw;height:100vh;overflow:hidden;perspective:900px}}.layer{{position:absolute;inset:-6%;background-position:center;background-size:cover;background-repeat:no-repeat;will-change:transform}}#hud{{position:fixed;z-index:9;left:18px;bottom:18px;color:#fff;font:14px system-ui;background:#0008;padding:10px 14px;border-radius:8px}}</style><div id="scene">{layers}</div><div id="hud">{title} · move your pointer to explore depth</div><script>const layers=[...document.querySelectorAll('.layer')];addEventListener('pointermove',e=>{{const x=(e.clientX/innerWidth-.5),y=(e.clientY/innerHeight-.5);layers.forEach((el,i)=>{{const d=Number(el.dataset.depth);el.style.transform=`translate(${{-x*d*35}}px,${{-y*d*25}}px) scale(${{1+d*.03}})`}})}});</script>"""


def create(title: str, layers: list[str], output: str) -> dict[str, object]:
    if not layers:
        raise ValueError("provide at least one image layer")
    root = Path(output).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.html"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {target}")
    tags = []
    for index, source in enumerate(layers):
        depth = round((index + 1) / len(layers), 2)
        tags.append(f'<div class="layer" data-depth="{depth}" style="background-image:url({source!r})"></div>')
    target.write_text(HTML.format(title=title or "Parallax scene", layers="".join(tags)), encoding="utf-8")
    return {"output": str(target), "layers": len(layers), "technique": "2.5D parallax"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka parallax-2d")
    p.add_argument("title")
    p.add_argument("--layer", action="append", required=True, help="Image URL/path; repeat back-to-front")
    p.add_argument("--out", default="arka-parallax")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = create(args.title, args.layer, args.out)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"Created parallax scene: {result['output']} ({result['layers']} layers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
