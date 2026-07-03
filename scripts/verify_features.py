#!/usr/bin/env python3
"""End-to-end verification for professions, routing, QR, password vault, and answer quality."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        msg = f"  ✗ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def section(title: str) -> None:
    print(f"\n━━ {title} ━━")


def run_py(args: list[str], *, timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def test_imports() -> None:
    section("Imports")
    try:
        from arka.agent import professions, profession_sources, profession_projects
        from arka.router import route
        from arka.integrations import qr_code, password_vault

        ok("core modules import", True)
        ok("domain count", len(professions.DOMAINS) >= 12, f"got {len(professions.DOMAINS)}")
        ok("source registry", len(profession_sources.SOURCE_REGISTRY) >= 12)
    except Exception as exc:
        ok("core modules import", False, str(exc))


def test_profession_routing() -> None:
    from arka.agent.professions import detect, route_command

    section("Profession detect + route")

    should_route = [
        ("as a news anchor how do I open a show", "journalism"),
        ("as a nutritionist meal plan for vegetarians", "nutrition"),
        ("as a lawyer what is an NDA", "legal"),
        ("profession ask investor market outlook", "investor"),
        ("nutrition: protein sources", "nutrition"),
        ("I'm a founder building an MVP", "startup"),
        ("profession setup nutrition", None),  # setup command
        ("profession sources journalism", None),
        ("profession list", None),
        ("clone profession projects", None),
    ]
    for text, expected_dom in should_route:
        routed = route_command(text)
        if expected_dom is None:
            ok(f"route: {text[:50]}", bool(routed), routed or "empty")
        else:
            hit = detect(text)
            ok(
                f"detect: {text[:45]}",
                hit is not None and hit[0] == expected_dom,
                f"got {hit}",
            )
            ok(
                f"route: {text[:45]}",
                routed.startswith(f"profession ask {expected_dom}"),
                routed,
            )

    should_not_route = [
        "symptoms of diabetes",
        "what is the capital of France",
        "stock price AAPL",
        "generate_password save wifi",
    ]
    for text in should_not_route:
        hit = detect(text)
        routed = route_command(text)
        ok(f"no profession route: {text[:40]}", hit is None and not routed, routed or str(hit))


def test_router_offline() -> None:
    from arka.router import route

    section("router.route (offline)")
    cases = [
        ("as a journalist covering elections", "profession ask journalism"),
        ("profession list", "profession list"),
        ("generate password for wifi", "generate_password"),
        ("save password for sumit gmail", "generate_password save"),
    ]
    for text, expect_prefix in cases:
        r = route(text)
        skill = r.skill if r else ""
        ok(f"router: {text[:40]}", skill.startswith(expect_prefix), skill)


def test_profession_sources() -> None:
    from arka.agent.profession_sources import gather_profession_context, list_sources
    from arka.agent.professions import DOMAINS

    section("Profession sources")
    for d in DOMAINS:
        srcs = list_sources(d.id)
        ok(f"sources defined: {d.id}", len(srcs) >= 2, f"{len(srcs)} sources")

    ctx, src = gather_profession_context("legal", "what is a non-disclosure agreement")
    ok("gather legal context", len(ctx) > 100, f"len={len(ctx)}, sources={src}")

    ctx2, src2 = gather_profession_context("journalism", "breaking news intro script")
    ok("gather journalism context", len(ctx2) > 50, f"len={len(ctx2)}, sources={src2}")


def test_profession_cli() -> None:
    section("Profession CLI")
    code, out = run_py(["-m", "arka.agent.professions", "list"])
    ok("profession list", code == 0 and "journalism" in out, out[:120])

    code, out = run_py(["-m", "arka.agent.professions", "sources", "teacher"])
    ok("profession sources teacher", code == 0 and "edutopia" in out, out[:120])

    code, out = run_py(
        ["-m", "arka.agent.professions", "route", "as a teacher explain photosynthesis"]
    )
    ok("profession route CLI", code == 0 and "profession ask teacher" in out, out)


def test_memory_detect() -> None:
    from arka.core.memory_detect import extract_fact

    section("Memory profession detect")
    cases = [
        ("I'm a news anchor", "news anchor"),
        ("I'm a lawyer", "lawyer"),
        ("I'm a content creator", "content creator"),
    ]
    for text, role in cases:
        fact = extract_fact(text)
        ok(f"memory: {text}", role in (fact or "").lower(), fact)


def test_qr_code() -> None:
    section("QR code")
    code, out = run_py([str(ROOT / "bin" / "arka_qr.py"), "https://example.com"])
    ok("qr terminal render", code == 0 and len(out) > 20, out[:80] or "empty output")


def test_password_vault() -> None:
    import os

    section("Password vault")
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        env["ARKA_CACHE_DIR"] = td
        # Let vault auto-create a Fernet key in the isolated cache dir.
        env.pop("ARKA_VAULT_KEY", None)

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "arka.integrations.password_vault",
                "generate",
                "sumit gmail",
                "--force",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        ok("vault save multi-word name", proc.returncode == 0, proc.stderr[:200])

        proc2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "arka.integrations.password_vault",
                "get",
                "sumit gmail",
                "--quiet",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        pwd = proc2.stdout.strip()
        ok(
            "vault get multi-word name",
            proc2.returncode == 0 and len(pwd) == 16,
            f"len={len(pwd)}",
        )
        ok("vault default length 16", len(pwd) == 16, pwd[:5] + "...")


ROLEPLAY_BANNED = (
    "as a nutritionist",
    "as a doctor",
    "as a lawyer",
    "from the perspective of",
    "you are advising",
    "act as a",
    "i would recommend as your",
)


def assess_answer_quality(stdout: str, stderr: str) -> tuple[bool, str]:
    """Heuristic quality gate for profession ask output."""
    text = stdout.strip()
    low = text.lower()
    if not text:
        return False, "empty answer"
    if "traceback" in low or "api key" in low or "no llm" in low:
        return False, "LLM/runtime error in output"

    citations = re.findall(r"\([a-z0-9_-]+\)", text, re.I)
    sources_m = re.search(r"\[Sources:\s*([^\]]+)\]", stderr, re.I)
    sources = sources_m.group(1) if sources_m else ""
    honest_gap = any(
        p in low
        for p in (
            "do not contain",
            "sources do not",
            "not enough information",
            "does not contain information",
            "do not outline",
        )
    )

    if any(p in low for p in ROLEPLAY_BANNED):
        return False, "role-play phrasing detected (should be source-backed)"

    if not sources_m:
        return False, "missing [Sources: …] footer"

    if honest_gap and len(text) >= 50:
        return True, f"honest gap report, sources={sources.strip()}"

    if not citations:
        return False, "no source citations"

    if len(text) < 120:
        return False, f"answer too short ({len(text)} chars)"

    if len(citations) >= 1:
        return True, f"{len(citations)} citations, {len(text)} chars, sources={sources.strip()}"
    return False, f"weak answer ({len(citations)} citations, {len(text)} chars)"


def test_rss_feeds() -> None:
    section("RSS feed population")
    try:
        import feedparser  # noqa: F401

        ok("feedparser installed", True)
    except ImportError:
        ok("feedparser installed", False, "pip install feedparser")
        return

    from arka.stock.predictions import fetch_rss_headlines

    bbc = fetch_rss_headlines("http://feeds.bbci.co.uk/news/rss.xml", limit=3)
    ok("BBC RSS headlines", len(bbc) >= 1, str(bbc[:2]))


def test_output_quality_live() -> None:
    section("Profession answer quality (live LLM)")
    cases = [
        ("marketing", "how to write a clear benefit-driven headline", 80),
        ("health", "what does CDC recommend for flu prevention", 200),
        ("journalism", "how should a news anchor open a breaking news segment", 100),
        ("legal", "what are the main parts of a non-disclosure agreement", 80),
    ]
    for domain, question, _min_len in cases:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "arka.agent.professions", "ask", domain, question],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            ok(f"quality {domain}: {question[:40]}", False, "timed out after 180s")
            continue
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        good, detail = assess_answer_quality(stdout, stderr)
        ok(
            f"quality {domain}: {question[:40]}",
            proc.returncode == 0 and good,
            detail,
        )
        if good:
            preview = stdout.strip().replace("\n", " ")[:140]
            print(f"      ↳ {preview}…")


def test_synthesis_offline() -> None:
    """Verify synthesis prompt constraints without calling an LLM."""
    section("Synthesis policy (offline)")
    from arka.agent.professions import _ask_from_sources
    import arka.agent.professions as prof

    orig = prof._dispatch_skill
    captured: list[str] = []

    def _cap(line: str) -> int:
        captured.append(line)
        return 0

    prof._dispatch_skill = _cap
    try:
        prof.profession_ask("teacher", "lesson plan for teaching fractions to grade 4")
        ok("teacher lesson plan → study_agent", captured and captured[0].startswith("study_agent"))
    finally:
        prof._dispatch_skill = orig

    ok("_ask_from_sources exists", callable(_ask_from_sources))


def test_fish_routing() -> None:
    section("Fish agent_route (if fish available)")
    fish = subprocess.run(["which", "fish"], capture_output=True, text=True)
    if fish.returncode != 0:
        ok("fish available", False, "fish not in PATH — skip")
        return
    ok("fish available", True)

    config = ROOT / "src" / "arka" / "fish" / "config.fish"
    for query, expect in [
        ("as a news anchor write a cold open", "profession ask journalism"),
        ("as a lawyer explain NDA basics", "profession ask legal"),
        ("symptoms of diabetes", ""),
    ]:
        script = f"""
            source {config}
            set -l r (_agent_route_profession {repr(query)})
            echo $r
        """
        proc = subprocess.run(["fish", "-c", script], capture_output=True, text=True, timeout=90)
        line = (proc.stdout or "").strip()
        if expect:
            ok(f"fish route: {query[:35]}", expect in line, line or proc.stderr[:120])
        else:
            ok(f"fish no route: {query[:35]}", line == "", line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Arka features and answer quality")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live LLM profession ask quality checks (slower, needs API keys)",
    )
    args = parser.parse_args()

    print("Arka feature verification")
    test_imports()
    test_profession_routing()
    test_router_offline()
    test_profession_sources()
    test_rss_feeds()
    test_profession_cli()
    test_memory_detect()
    test_qr_code()
    test_password_vault()
    test_synthesis_offline()
    test_fish_routing()
    if args.live:
        test_output_quality_live()

    print(f"\n━━ Summary ━━")
    print(f"  Passed: {PASS}")
    print(f"  Failed: {FAIL}")
    if not args.live:
        print("  Tip: run with --live to verify LLM answer quality (needs API keys)")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
