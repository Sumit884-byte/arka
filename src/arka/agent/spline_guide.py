"""Practical Spline 3D integration guidance, preferring Spline MCP when available."""
from __future__ import annotations

import argparse
import json

GUIDES = {
    "web": "Export from Spline as a Public URL, then embed with <spline-viewer url=...> or an iframe. Give the canvas a responsive aspect-ratio container and lazy-load below the fold.",
    "react": "Install @splinetool/react-spline, render <Spline scene=\"SCENE_URL\" />, and keep the scene URL in an environment/config value. Render only on the client in Next.js.",
    "performance": "Reduce geometry, textures, lights, and animation loops in Spline; lazy-load the scene, pause it when offscreen, and provide a static poster for slow devices.",
    "responsive": "Use a fluid container with explicit min-height and width:100%; test PC, tablet, and mobile separately. Keep text and primary controls in HTML outside the 3D canvas.",
    "accessibility": "Treat 3D as enhancement: provide an accessible HTML heading, description, keyboard-operable controls, reduced-motion behavior, and a non-WebGL fallback.",
}


def spline_mcp_available() -> bool:
    try:
        from arka.integrations.mcp_manager import list_server_names

        return "spline" in list_server_names()
    except Exception:
        return False


def query_spline_mcp(topic: str) -> str | None:
    try:
        from arka.integrations.mcp_manager import call_tool, list_tools

        tools = list_tools("spline")
        tool_names = [tool.name for tool in tools]
        selected = next((name for name in tool_names if name in {"guide", "search", "describe", "create_scene", "spline_guide"}), "")
        if not selected:
            return None
        args = {"query": topic, "topic": topic, "prompt": topic}
        return call_tool("spline", selected, args)
    except Exception as exc:
        return f"Spline MCP configured but unavailable: {exc}"


def guide(topic: str = "web") -> str:
    key = topic.lower().replace(" ", "-")
    aliases = {"embed": "web", "website": "web", "next": "react", "nextjs": "react", "speed": "performance", "a11y": "accessibility"}
    local = GUIDES.get(aliases.get(key, key), GUIDES["web"])
    if spline_mcp_available():
        mcp_answer = query_spline_mcp(topic)
        if mcp_answer:
            return f"Spline MCP preferred\n\n{mcp_answer}\n\nLocal fallback:\n{local}".strip()
    return (
        "Spline MCP is the preferred/default provider for Spline work.\n"
        "Set it up with: arka mcp preset spline --apply\n\n"
        f"Local fallback:\n{local}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka spline", description="Guide Spline 3D model integration")
    parser.add_argument("--json", action="store_true", help="Emit provider and guidance as JSON")
    parser.add_argument("topic", nargs="?", default="web", choices=[*GUIDES, "embed", "website", "next", "nextjs", "speed", "a11y"])
    args = parser.parse_args(argv)
    text = guide(args.topic)
    if args.json:
        print(json.dumps({"provider": "spline-mcp" if spline_mcp_available() else "local-fallback", "text": text}, indent=2))
    else:
        print(text)
    return 0
