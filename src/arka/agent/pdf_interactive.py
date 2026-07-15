"""Convert a PDF into an interactive browser viewer."""
from __future__ import annotations

import argparse
from pathlib import Path

HTML = """<!doctype html><meta charset='utf-8'><title>Interactive PDF</title><style>body{margin:0;font:14px system-ui;background:#202124;color:#eee}header{position:sticky;top:0;background:#303134;padding:10px;display:flex;gap:8px;align-items:center}#pages{display:grid;gap:18px;justify-content:center;padding:20px}canvas{background:#fff;box-shadow:0 2px 12px #0008;max-width:100%}input{width:220px}</style><body><header><button id='prev'>◀</button><span>Page <b id='num'>1</b> / <b id='total'>?</b></span><button id='next'>▶</button><button id='zoomout'>−</button><button id='zoomin'>+</button><input id='search' placeholder='Search PDF text'><span id='hits'></span></header><main id='pages'></main><script src='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs' type='module'></script><script type='module'>import * as pdfjsLib from 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs';pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs';const pdf=await pdfjsLib.getDocument('PDF_SOURCE').promise;let page=1,scale=1.2;total.textContent=pdf.numPages;async function draw(){pages.innerHTML='';for(let n=1;n<=pdf.numPages;n++){let p=await pdf.getPage(n),v=p.getViewport({scale}),c=document.createElement('canvas');c.dataset.page=n;c.width=v.width;c.height=v.height;pages.append(c);await p.render({canvasContext:c.getContext('2d'),viewport:v}).promise}num.textContent=page;document.querySelector(`[data-page='${page}']`)?.scrollIntoView()}prev.onclick=()=>{page=Math.max(1,page-1);draw()};next.onclick=()=>{page=Math.min(pdf.numPages,page+1);draw()};zoomin.onclick=()=>{scale=Math.min(3,scale+.2);draw()};zoomout.onclick=()=>{scale=Math.max(.5,scale-.2);draw()};search.oninput=async()=>{let q=search.value.toLowerCase(),n=0;for(let i=1;i<=pdf.numPages;i++){let t=await (await pdf.getPage(i)).getTextContent();if(t.items.map(x=>x.str).join(' ').toLowerCase().includes(q))n++}hits.textContent=q?`${n} page(s)`:''};draw();</script>"""

ULTRA = '''<style>body{background:radial-gradient(circle at top,#202b4a,#0d0f16)}#pages canvas{animation:fade .5s ease both}.hero{padding:42px 8vw;animation:rise .8s ease both}model-viewer{width:100%;height:240px;border-radius:20px;background:#141827}@keyframes rise{from{opacity:0;transform:translateY(18px)}}@keyframes fade{from{opacity:0;transform:scale(.98)}}</style><script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script><section class="hero"><h1>Explore this document</h1><button onclick="document.body.classList.toggle('light')">☀ Theme</button> <button onclick="alert('Share this page URL with your team')">↗ Share</button><model-viewer src="model.glb" camera-controls auto-rotate alt="Optional 3D model"></model-viewer></section>'''


def convert(source: str, output: str | None = None, ultra: bool = False) -> Path:
    pdf = Path(source).expanduser().resolve()
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise ValueError("source must be an existing PDF")
    target = Path(output).expanduser().resolve() if output else pdf.with_suffix(".interactive.html")
    document = HTML.replace("PDF_SOURCE", pdf.name)
    if ultra:
        document = document.replace("<body>", "<body>" + ULTRA)
    target.write_text(document, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka pdf-to-interactive")
    parser.add_argument("source")
    parser.add_argument("--output")
    parser.add_argument("--ultra", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(convert(args.source, args.output, args.ultra))
        return 0
    except (OSError, ValueError) as exc:
        print(f"pdf-to-interactive: {exc}")
        return 2
