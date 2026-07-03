#!/usr/bin/env python3
"""Live sports scores via ESPN public scoreboard API (no API key)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

USER_AGENT = "Mozilla/5.0 (compatible; Arka/1.0)"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# sport_path, league_id, display name
LEAGUES: dict[str, tuple[str, str, str]] = {
    "ipl": ("cricket", "8048", "IPL"),
    "t20": ("cricket", "8048", "IPL"),
    "cricket": ("cricket", "8048", "IPL"),
    "icc": ("cricket", "487", "ICC Cricket"),
    "world cup": ("cricket", "487", "ICC Cricket"),
    "nfl": ("football", "nfl", "NFL"),
    "nba": ("basketball", "nba", "NBA"),
    "mlb": ("baseball", "mlb", "MLB"),
    "nhl": ("hockey", "nhl", "NHL"),
    "epl": ("soccer", "eng.1", "Premier League"),
    "premier league": ("soccer", "eng.1", "Premier League"),
    "premier": ("soccer", "eng.1", "Premier League"),
    "la liga": ("soccer", "esp.1", "La Liga"),
    "laliga": ("soccer", "esp.1", "La Liga"),
    "serie a": ("soccer", "ita.1", "Serie A"),
    "bundesliga": ("soccer", "ger.1", "Bundesliga"),
    "ucl": ("soccer", "uefa.champions", "UEFA Champions League"),
    "champions league": ("soccer", "uefa.champions", "UEFA Champions League"),
    "mls": ("soccer", "usa.1", "MLS"),
    "f1": ("racing", "f1", "Formula 1"),
    "formula 1": ("racing", "f1", "Formula 1"),
    "tennis": ("tennis", "atp", "ATP Tennis"),
    "atp": ("tennis", "atp", "ATP Tennis"),
    "wimbledon": ("tennis", "atp", "Tennis"),
}


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _default_league_keys(*, all_leagues: bool = False) -> list[str]:
    custom = (os.environ.get("ARKA_SPORTS_DEFAULT") or "").strip().lower()
    if custom:
        if custom in ("all", "everything"):
            return ["ipl", "epl", "nba", "nfl"]
        return [k.strip() for k in custom.replace(",", " ").split() if k.strip() in LEAGUES]
    if all_leagues:
        lang = (os.environ.get("ARKA_SPEAK_LANG") or "en-IN").lower()
        if lang.endswith("-in") or "hi" in lang:
            return ["ipl", "epl", "nba"]
        return ["nfl", "nba", "epl"]
    # Vague "sports scores" → one primary league (less noise on screen + voice)
    lang = (os.environ.get("ARKA_SPEAK_LANG") or "en-IN").lower()
    if lang.endswith("-in") or "hi" in lang:
        return ["ipl"]
    return ["nfl"]


def resolve_leagues(query: str) -> list[tuple[str, str, str]]:
    raw = (query or "").strip()
    q = re.sub(
        r"(?i)^(show|get|tell me|what is|what are|give me|live|today'?s?)\s+",
        "",
        raw,
    )
    q = re.sub(
        r"(?i)\b(sports?\s+)?(score|scores|scoring|results?|live|today|now)\b",
        "",
        q,
    ).strip()
    q = re.sub(r"\s+", " ", q).strip()
    want_all = bool(re.search(r"(?i)\ball\b|\beverything\b|\ball\s+leagues\b", raw))

    if not q or q.lower() in {"live", "sports", "sport", "games"}:
        return [LEAGUES[k] for k in _default_league_keys(all_leagues=want_all) if k in LEAGUES]

    found: list[tuple[str, str, str]] = []
    low = q.lower()
    for key, spec in sorted(LEAGUES.items(), key=lambda kv: -len(kv[0])):
        if key in low and spec not in found:
            found.append(spec)
    if found:
        return found

    for token in low.split():
        if token in LEAGUES:
            spec = LEAGUES[token]
            if spec not in found:
                found.append(spec)
    return found or [LEAGUES[k] for k in _default_league_keys(all_leagues=want_all) if k in LEAGUES]


def fetch_scoreboard(sport: str, league: str) -> dict:
    url = f"{ESPN_BASE}/{sport}/{league}/scoreboard"
    return _fetch_json(url)


def _comp_name(comp: dict) -> str:
    team = comp.get("team") or {}
    return team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName") or "?"


def _comp_score(comp: dict) -> str:
    score = comp.get("score")
    if score is None:
        return "-"
    if isinstance(score, dict):
        return str(score.get("displayValue") or score.get("value") or "-")
    return str(score)


def _numeric_score(comp: dict) -> float | None:
    score = comp.get("score")
    if isinstance(score, dict):
        val = score.get("value")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    sc = _comp_score(comp)
    m = re.match(r"^(\d+)", sc)
    if m:
        return float(m.group(1))
    return None


def _status_line(competition: dict, *, sport: str = "") -> tuple[str, str]:
    """Return (display status, short voice status)."""
    status = (competition.get("status") or {}).get("type") or {}
    detail = (status.get("detail") or status.get("description") or status.get("shortDetail") or "").strip()
    state = (status.get("state") or "").lower()
    clock = (competition.get("status") or {}).get("displayClock") or ""
    period = (competition.get("status") or {}).get("period") or ""

    low_detail = detail.lower()
    if state in ("post", "final") or "final" in low_detail or low_detail == "result":
        return "Final", "finished"
    if state == "pre" or "scheduled" in low_detail:
        # Prefer human date over "Scheduled Wed..."
        return detail if detail else "Scheduled", detail if detail else "not started yet"
    if state == "in":
        parts = []
        if clock and clock not in ("0", "0'", "0.0", "0:00"):
            parts.append(clock)
        if period and sport != "cricket":
            parts.append(f"Q{period}" if sport == "basketball" else f"P{period}")
        display = " · ".join(["Live", *parts]) if parts else "Live"
        return display, display.lower()
    if detail:
        return detail, detail
    return "Scheduled", "scheduled"


def _winner_side(competitors: list[dict]) -> dict | None:
    for c in competitors:
        if c.get("winner") is True:
            return c
    if len(competitors) < 2:
        return None
    scored = [(c, _numeric_score(c)) for c in competitors]
    scored = [(c, s) for c, s in scored if s is not None]
    if len(scored) >= 2 and scored[0][1] != scored[1][1]:
        return max(scored, key=lambda x: x[1])[0]
    return None


def format_event(event: dict, *, league_label: str, sport: str = "") -> tuple[str, str, str]:
    """Return (display block, brief bullet, voice sentence)."""
    name = event.get("name") or event.get("shortName") or "Match"
    competitions = event.get("competitions") or [{}]
    comp = competitions[0] if competitions else {}
    competitors = comp.get("competitors") or []

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None and len(competitors) >= 1:
        home = competitors[0]
    if away is None and len(competitors) >= 2:
        away = competitors[1 if competitors[0] is not home else 0]

    stat_display, stat_voice = _status_line(comp, sport=sport)
    winner = _winner_side(competitors)

    lines = [f"  {name}"]
    for c in (away, home):
        if c is None:
            continue
        nm = _comp_name(c)
        sc = _comp_score(c)
        tag = " (W)" if c is winner else ""
        lines.append(f"    {nm} {sc}{tag}")
    lines.append(f"    {stat_display}")

    # Brief + voice
    if away and home:
        a_name, h_name = _comp_name(away), _comp_name(home)
        a_sc, h_sc = _comp_score(away), _comp_score(home)
        if winner is away:
            brief = f"{league_label}: {a_name} {a_sc} beat {h_name} {h_sc} — {stat_display}"
            voice = f"In {league_label}, {a_name} beat {h_name}, {a_sc} to {h_sc}. {stat_voice.capitalize()}."
        elif winner is home:
            brief = f"{league_label}: {h_name} {h_sc} beat {a_name} {a_sc} — {stat_display}"
            voice = f"In {league_label}, {h_name} beat {a_name}, {h_sc} to {a_sc}. {stat_voice.capitalize()}."
        elif stat_voice == "not started yet" or "scheduled" in stat_voice.lower():
            brief = f"{league_label}: {away.get('team', {}).get('displayName', a_name)} vs {home.get('team', {}).get('displayName', h_name)} — {stat_display}"
            voice = f"{league_label}: {a_name} versus {h_name}. {stat_display}."
        else:
            brief = f"{league_label}: {a_name} {a_sc}, {h_name} {h_sc} — {stat_display}"
            voice = f"{league_label}: {a_name} {a_sc}, {h_name} {h_sc}. {stat_voice.capitalize()}."
    elif competitors:
        c = competitors[0]
        brief = f"{league_label}: {_comp_name(c)} {_comp_score(c)} — {stat_display}"
        voice = f"{league_label}: {_comp_name(c)} {_comp_score(c)}."
    else:
        brief = f"{league_label}: {name} — {stat_display}"
        voice = f"{league_label}: {name}."

    return "\n".join(lines), brief, voice


def live_scores(query: str = "", *, limit_per_league: int = 3) -> str:
    leagues = resolve_leagues(query)
    if not leagues:
        return "Could not determine which sport or league to show."

    sections: list[str] = []
    brief_lines: list[str] = []
    voice_lines: list[str] = []
    any_events = False

    for sport, league_id, label in leagues:
        try:
            data = fetch_scoreboard(sport, league_id)
        except urllib.error.URLError as exc:
            sections.append(f"━━━ {label} ━━━\n  Could not fetch scores ({exc}).")
            continue

        events = data.get("events") or []
        if not events:
            sections.append(f"━━━ {label} ━━━\n  No matches listed right now.")
            continue

        any_events = True
        block = [f"━━━ {label} ━━━"]
        for event in events[:limit_per_league]:
            display, brief, voice = format_event(event, league_label=label, sport=sport)
            block.append(display)
            brief_lines.append(f"• {brief}")
            voice_lines.append(voice)
        sections.append("\n".join(block))

    if not any_events and not sections:
        return "No live sports scores available right now."

    header = f"Live sports · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    body = "\n\n".join(sections)
    brief = "\n".join(brief_lines)
    spoken = " ".join(voice_lines[:3])
    if len(voice_lines) > 3:
        spoken += f" Plus {len(voice_lines) - 3} more matches."

    hint = ""
    if len(leagues) == 1:
        hint = f"\n\nTip: say sports_score all for IPL, EPL, NBA, and NFL together."

    return f"━━━ Answer ━━━\n{header}\n\n{body}\n\nBrief:\n{brief}\n\n{spoken}{hint}"


def list_leagues() -> str:
    lines = ["Available leagues (examples):"]
    seen: set[str] = set()
    for key, (_, _, label) in sorted(LEAGUES.items()):
        if label in seen:
            continue
        seen.add(label)
        keys = [k for k, v in LEAGUES.items() if v[2] == label]
        lines.append(f"  {label}: {', '.join(sorted(set(keys))[:6])}")
    lines.append("\nUsage: sports_score ipl | nfl | epl | sports_score all")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live sports scores (ESPN)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_live = sub.add_parser("live", help="Live scores for a league or sport")
    p_live.add_argument("query", nargs="*", help="e.g. ipl, nfl, live cricket, all")

    sub.add_parser("leagues", help="List supported leagues")

    args = parser.parse_args()
    if args.cmd == "leagues":
        print(list_leagues())
        return 0
    if args.cmd == "live":
        q = " ".join(args.query).strip()
        try:
            print(live_scores(q))
        except Exception as exc:
            print(f"Sports scores failed: {exc}", file=sys.stderr)
            return 1
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
