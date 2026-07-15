"""Practical Spline 3D integration guidance."""
from __future__ import annotations

import argparse

GUIDES = {
    "web": "Export from Spline as a Public URL, then embed with <spline-viewer url=...> or an iframe. Give the canvas a responsive aspect-ratio container and lazy-load below the fold.",
    "react": "Install @splinetool/react-spline, render <Spline scene=\"SCENE_URL\" />, and keep the scene URL in an environment/config value. Render only on the client in Next.js.",
    "performance": "Reduce geometry, textures, lights, and animation loops in Spline; lazy-load the scene, pause it when offscreen, and provide a static poster for slow devices.",
    "responsive": "Use a fluid container with explicit min-height and width:100%; test PC, tablet, and mobile separately. Keep text and primary controls in HTML outside the 3D canvas.",
    "accessibility": "Treat 3D as enhancement: provide an accessible HTML heading, description, keyboard-operable controls, reduced-motion behavior, and a non-WebGL fallback.",
}


def guide(topic: str = "web") -> str:
    key = topic.lower().replace(" ", "-")
    aliases = {"embed": "web", "website": "web", "next": "react", "nextjs": "react", "speed": "performance", "a11y": "accessibility"}
    return GUIDES.get(aliases.get(key, key), GUIDES["web"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka spline", description="Guide Spline 3D model integration")
    parser.add_argument("topic", nargs="?", default="web", choices=[*GUIDES, "embed", "website", "next", "nextjs", "speed", "a11y"])
    args = parser.parse_args(argv)
    print(guide(args.topic))
    return 0
