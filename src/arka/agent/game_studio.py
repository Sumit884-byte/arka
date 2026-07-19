"""Generate polished, dependency-free browser game starters."""
from __future__ import annotations

import argparse
from pathlib import Path

INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="style.css"></head>
<body><main><header><span class="eyebrow">ARKA GAME STUDIO</span><h1>{title}</h1><p>Move with WASD or arrow keys · collect the glowing cores</p></header>
<canvas id="game" aria-label="{title} game"></canvas><div class="hud"><b id="score">SCORE 0000</b><span id="status">READY</span></div></main><script src="game.js"></script></body></html>
"""

STYLE = """:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#080b18;color:#f5f7ff}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% 0,#243b72 0,#080b18 55%);display:grid;place-items:center}main{width:min(960px,94vw)}header{padding:24px 4px}.eyebrow{color:#70f6d2;font-size:.72rem;letter-spacing:.2em}h1{font-size:clamp(2rem,7vw,5rem);margin:.2em 0;background:linear-gradient(90deg,#fff,#70f6d2);color:transparent;background-clip:text}p{color:#aab5d6}canvas{display:block;width:100%;aspect-ratio:16/9;border:1px solid #354476;border-radius:20px;box-shadow:0 20px 80px #0008;background:#0e1530}.hud{display:flex;justify-content:space-between;padding:14px 4px;color:#70f6d2;letter-spacing:.08em}#status{color:#aab5d6}
"""

SCRIPT = """const canvas=document.querySelector('#game'),ctx=canvas.getContext('2d'),scoreEl=document.querySelector('#score'),statusEl=document.querySelector('#status');
const keys=new Set();let score=0,player={x:.5,y:.5},orb={x:.7,y:.4};
addEventListener('keydown',e=>keys.add(e.key.toLowerCase()));addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));
function resize(){canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=canvas.clientHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0)}addEventListener('resize',resize);resize();
function frame(t){const w=canvas.clientWidth,h=canvas.clientHeight,dt=.016,s=.35*dt;if(keys.has('arrowleft')||keys.has('a'))player.x-=s;if(keys.has('arrowright')||keys.has('d'))player.x+=s;if(keys.has('arrowup')||keys.has('w'))player.y-=s;if(keys.has('arrowdown')||keys.has('s'))player.y+=s;player.x=Math.max(.03,Math.min(.97,player.x));player.y=Math.max(.05,Math.min(.95,player.y));
ctx.clearRect(0,0,w,h);ctx.strokeStyle='#23345f';for(let x=0;x<w;x+=48){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}for(let y=0;y<h;y+=48){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
const pulse=8+Math.sin(t/180)*3;ctx.shadowBlur=24;ctx.shadowColor='#70f6d2';ctx.fillStyle='#70f6d2';ctx.beginPath();ctx.arc(orb.x*w,orb.y*h,pulse,0,7);ctx.fill();ctx.shadowBlur=0;ctx.fillStyle='#ff6bd6';ctx.beginPath();ctx.arc(player.x*w,player.y*h,14,0,7);ctx.fill();
if(Math.hypot((player.x-orb.x)*w,(player.y-orb.y)*h)<24){score+=10;orb={x:.08+Math.random()*.84,y:.12+Math.random()*.76};scoreEl.textContent='SCORE '+String(score).padStart(4,'0')}statusEl.textContent='LIVE';requestAnimationFrame(frame)}requestAnimationFrame(frame);
"""


def create(title: str, output: str) -> dict[str, str]:
    root = Path(output).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    safe_title = title.strip() or "Neon Core"
    files = {"index.html": INDEX.format(title=safe_title), "style.css": STYLE, "game.js": SCRIPT}
    for name, body in files.items():
        target = root / name
        if target.exists():
            raise FileExistsError(f"refusing to overwrite existing file: {target}")
        target.write_text(body, encoding="utf-8")
    return {"output": str(root), "files": ",".join(files), "template": "neon-arena"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka game")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create", help="Create a polished browser game starter")
    new.add_argument("title", nargs="+", help="Game title")
    new.add_argument("--out", default="arka-game")
    new.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = create(" ".join(args.title), args.out)
    except (OSError, FileExistsError) as exc:
        parser.error(str(exc))
    print(result if args.json else f"Created {result['template']} game in {result['output']} ({result['files']})")
    return 0
