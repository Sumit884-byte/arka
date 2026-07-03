#!/usr/bin/env python3
"""
Market emotion engine — aggregate news sentiment and predict crowd behavior.

Scores recent headlines, sums net public/market emotion, and forecasts
who (retail, FIIs, traders) is likely to do what next.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

STOCK_PROJECT = Path(
    os.environ.get("STOCK_PROJECT", Path.home() / "Projects/python/products/stock_analysis")
)

EMOTION_NEWS_FEEDS: list[tuple[str, str]] = [
    ("Markets", "https://news.google.com/rss/search?q=stock+market+India+investor+sentiment&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Global", "https://news.google.com/rss/search?q=global+stock+market+fear+greed&hl=en-US&gl=US&ceid=US:en"),
    ("Retail", "https://news.google.com/rss/search?q=retail+investors+India+stock+market&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Macro fear", "https://news.google.com/rss/search?q=market+crash+war+inflation+recession+fear&hl=en&gl=US&ceid=US:en"),
]

EMOTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "fear": (
        r"\b(crash|panic|selloff|sell.?off|plunge|collapse|crisis|disaster|war|invasion|"
        r"recession|bloodbath|fear|worried|anxiety|risk.?off|downgrade|default|bankruptcy)\b",
    ),
    "greed": (
        r"\b(surge|soars|rally|boom|record high|all.?time high|fomo|euphoria|melt.?up|"
        r" frenzy|jump|spike|bull run|greed|overbought)\b",
    ),
    "uncertainty": (
        r"\b(uncertain|uncertainty|volatile|volatility|mixed|unclear|wait.?and.?see|"
        r"confusion|may\b|might\b|could\b|if\b|deadlock|stalemate|negotiat)\b",
    ),
    "anger": (
        r"\b(outrage|protest|scam|fraud|penalty|fine|ban|corruption|lawsuit|investigation|"
        r"regulatory action|crackdown)\b",
    ),
    "hope": (
        r"\b(recovery|rebound|peace|deal|ceasefire|optimism|upgrade|beat estimates|"
        r"breakthrough|growth|expansion|rate cut|stimulus|relief)\b",
    ),
}


@dataclass
class HeadlineEmotion:
    title: str
    source: str
    sentiment: str
    score: float
    emotions: list[str]


@dataclass
class EmotionAggregate:
    net_score: float
    avg_score: float
    positive: int
    negative: int
    neutral: int
    total: int
    emotion_counts: dict[str, int]
    dominant_emotion: str
    fear_greed_index: int  # 0=extreme fear, 100=extreme greed
    headlines: list[HeadlineEmotion] = field(default_factory=list)


@dataclass
class BehaviorForecast:
    actor: str
    likely_action: str
    window: str
    confidence: str


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _is_valid_headline(title: str) -> bool:
    t = title.lower()
    return len(t) >= 28 and "wikipedia" not in t and "definition" not in t


def _fetch_rss(source: str, url: str, limit: int, seen: set[str]) -> list[dict]:
    items: list[dict] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "arka-market-emotion/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
        for raw in re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml)[1:]:
            title = _clean_text(raw)
            if not _is_valid_headline(title):
                continue
            key = title.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append({"source": source, "title": title})
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items


def _fetch_news_via_stock_project(limit: int) -> list[dict]:
    py = STOCK_PROJECT / ".venv/bin/python3"
    if not py.is_file():
        return []
    feeds = {k: v for k, v in EMOTION_NEWS_FEEDS}
    code = (
        f"import json; feeds={json.dumps(feeds)}; "
        "from get_free_data import fetch_news; "
        f"n=fetch_news(feeds, 4, {limit * 2}); "
        "print(json.dumps([{'source':x['source'],'title':x['title']} for x in n]))"
    )
    try:
        proc = subprocess.run(
            [str(py), "-c", code],
            cwd=str(STOCK_PROJECT),
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except Exception:
        pass
    return []


def fetch_emotion_news(limit: int = 20) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for item in _fetch_news_via_stock_project(limit * 2):
        title = _clean_text(item.get("title", ""))
        if not _is_valid_headline(title):
            continue
        key = title.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        items.append({"source": item.get("source", "News"), "title": title})
        if len(items) >= limit:
            return items
    for source, url in EMOTION_NEWS_FEEDS:
        for item in _fetch_rss(source, url, 6, seen):
            items.append(item)
            if len(items) >= limit:
                return items
    return items


def _detect_emotions(text: str) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for emotion, patterns in EMOTION_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, low):
                found.append(emotion)
                break
    return found or ["neutral_tone"]


def _score_headlines_batch(headlines: list[str]) -> list[tuple[str, float]]:
    """FinBERT/TextBlob via stock_analysis venv (one model load for all headlines)."""
    if not headlines:
        return []
    py = STOCK_PROJECT / ".venv/bin/python3"
    if not py.is_file():
        return _score_headlines_textblob_local(headlines)

    use_finbert = os.environ.get("USE_FINBERT", "0") == "1"
    headlines_json = json.dumps(headlines[:25])
    code = f"""
import json, os
from sentiment_analyzer import get_analyzer
use_fb = os.environ.get("USE_FINBERT", "0") == "1"
analyzer = get_analyzer(use_finbert=use_fb)
headlines = {headlines_json}
out = []
for h in headlines:
    label, score, _ = analyzer.analyze(h)
    out.append([label, float(score)])
print(json.dumps(out))
"""
    env = os.environ.copy()
    env["USE_FINBERT"] = "0" if not use_finbert else "1"
    try:
        proc = subprocess.run(
            [str(py), "-c", code],
            cwd=str(STOCK_PROJECT),
            capture_output=True,
            text=True,
            timeout=180 if use_finbert else 60,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw = json.loads(proc.stdout.strip())
            return [(str(r[0]), float(r[1])) for r in raw]
    except Exception:
        pass
    return _score_headlines_textblob_local(headlines)


def _score_headlines_textblob_local(headlines: list[str]) -> list[tuple[str, float]]:
    results: list[tuple[str, float]] = []
    for h in headlines:
        low = h.lower()
        score = 0.0
        if re.search(r"\b(surge|rally|gain|beat|growth|peace|deal)\b", low):
            score += 3.0
        if re.search(r"\b(crash|plunge|war|crisis|fear|loss|ban|fine)\b", low):
            score -= 3.0
        label = "Positive" if score > 1 else "Negative" if score < -1 else "Neutral"
        results.append((label, score))
    return results


def analyze_emotions(news: list[dict]) -> EmotionAggregate:
    titles = [n["title"] for n in news]
    scores_raw = _score_headlines_batch(titles)

    headlines: list[HeadlineEmotion] = []
    pos = neg = neu = 0
    total_score = 0.0
    emotion_counts: dict[str, int] = {k: 0 for k in EMOTION_PATTERNS}
    emotion_counts["neutral_tone"] = 0

    for i, item in enumerate(news):
        title = item["title"]
        if i < len(scores_raw):
            sentiment, score = scores_raw[i]
        else:
            sentiment, score = "Neutral", 0.0
        emos = _detect_emotions(title)
        for e in emos:
            emotion_counts[e] = emotion_counts.get(e, 0) + 1
        headlines.append(HeadlineEmotion(
            title=title,
            source=item.get("source", ""),
            sentiment=sentiment,
            score=score,
            emotions=emos,
        ))
        total_score += score
        if sentiment == "Positive":
            pos += 1
        elif sentiment == "Negative":
            neg += 1
        else:
            neu += 1

    n = max(len(headlines), 1)
    net = total_score
    avg = total_score / n

    # Dominant emotion from keyword counts (exclude neutral_tone for dominance)
    emo_only = {k: v for k, v in emotion_counts.items() if k != "neutral_tone" and v > 0}
    dominant = max(emo_only, key=emo_only.get) if emo_only else "mixed"

    # Fear & Greed index 0-100 from net score and emotion mix
    fear_w = emotion_counts.get("fear", 0) + emotion_counts.get("uncertainty", 0) * 0.5
    greed_w = emotion_counts.get("greed", 0) + emotion_counts.get("hope", 0) * 0.5
    total_emo = max(fear_w + greed_w + neg + pos, 1)
    greed_ratio = (greed_w + pos * 0.5) / total_emo
    fear_greed = int(max(0, min(100, 50 + avg * 4 + (greed_ratio - 0.5) * 40)))

    return EmotionAggregate(
        net_score=round(net, 1),
        avg_score=round(avg, 2),
        positive=pos,
        negative=neg,
        neutral=neu,
        total=n,
        emotion_counts=emotion_counts,
        dominant_emotion=dominant,
        fear_greed_index=fear_greed,
        headlines=headlines,
    )


def predict_crowd_behaviors(agg: EmotionAggregate) -> list[BehaviorForecast]:
    """Who will likely do what, based on aggregated news emotion."""
    fg = agg.fear_greed_index
    net = agg.net_score
    fear = agg.emotion_counts.get("fear", 0)
    greed = agg.emotion_counts.get("greed", 0)
    uncertainty = agg.emotion_counts.get("uncertainty", 0)
    hope = agg.emotion_counts.get("hope", 0)
    behaviors: list[BehaviorForecast] = []

    def add(actor: str, action: str, window: str, conf: str) -> None:
        behaviors.append(BehaviorForecast(actor, action, window, conf))

    # Retail
    if fg < 35 or net < -15 or fear >= 3:
        add("Retail investors", "Pause SIPs, book profits, shift to FD/gold; avoid new equity entries", "3–10 days", "high")
    elif fg > 65 or greed >= 3 or net > 15:
        add("Retail investors", "FOMO into hot themes/small-caps; higher delivery volumes on rally days", "5–15 days", "medium")
    elif uncertainty >= 4:
        add("Retail investors", "Wait-and-see; low new inflows; stick to index ETFs or cash", "1–3 weeks", "medium")
    else:
        add("Retail investors", "Steady SIP flow; stock-specific buys on dips", "2–4 weeks", "low")

    # FIIs / institutions
    if fear >= 3 or net < -20:
        add("FIIs / institutions", "Risk-off hedging; reduce India weight; favor defensives & exporters", "2–6 weeks", "high")
    elif hope >= 3 and net > 10:
        add("FIIs / institutions", "Re-risk into large-cap banks & IT; add on policy/peace headlines", "2–8 weeks", "medium")
    else:
        add("FIIs / institutions", "Two-way flows; sector rotation not broad exit", "2–4 weeks", "low")

    # Day traders
    if uncertainty >= 3 or fear >= 2:
        add("Day traders", "Wider intraday ranges; quick reversals; fade gaps; reduce overnight holds", "1–5 days", "high")
    elif greed >= 2 or fg > 60:
        add("Day traders", "Momentum chase in leaders; high turnover in mid/small caps", "3–7 days", "medium")
    else:
        add("Day traders", "Range-bound strategies; focus on news-driven scalps", "1–2 weeks", "low")

    # Long-term investors
    if fg < 30:
        add("Long-term investors", "Accumulate quality names on fear (banks, IT) if fundamentals intact", "1–3 months", "medium")
    elif fg > 75:
        add("Long-term investors", "Trim overheated positions; raise cash; avoid chasing euphoria", "2–8 weeks", "medium")
    else:
        add("Long-term investors", "Hold core; add on corrections only", "1–3 months", "low")

    # Mutual fund flows (India-specific)
    if net < -10:
        add("Mutual fund investors", "Shift to liquid/arbitrage funds; redemptions from thematic funds", "2–4 weeks", "medium")
    elif net > 10:
        add("Mutual fund investors", "Inflows into flexi-cap & index funds; thematic fund marketing push", "2–6 weeks", "medium")

    return behaviors


def _fear_greed_label(index: int) -> str:
    if index < 25:
        return "Extreme Fear"
    if index < 45:
        return "Fear"
    if index < 55:
        return "Neutral"
    if index < 75:
        return "Greed"
    return "Extreme Greed"


def format_emotion_report(news_limit: int = 20) -> tuple[str, list[str]]:
    news = fetch_emotion_news(limit=news_limit)
    if not news:
        return "(Could not fetch news for emotion analysis.)", []

    agg = analyze_emotions(news)
    behaviors = predict_crowd_behaviors(agg)

    lines = [
        "## Market emotion & crowd behavior forecast",
        "",
        f"**Headlines analyzed:** {agg.total}",
        f"**Net emotion sum:** {agg.net_score:+.1f} (sum of FinBERT/TextBlob scores across all headlines)",
        f"**Average sentiment:** {agg.avg_score:+.2f} per headline",
        f"**Split:** {agg.positive} positive · {agg.negative} negative · {agg.neutral} neutral",
        f"**Fear & Greed index:** {agg.fear_greed_index}/100 — {_fear_greed_label(agg.fear_greed_index)}",
        f"**Dominant mood keyword:** {agg.dominant_emotion.replace('_', ' ')}",
        "",
        "### Emotion breakdown (headline keyword hits)",
    ]
    for emo, count in sorted(agg.emotion_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            lines.append(f"- **{emo.replace('_', ' ').title()}:** {count} headlines")

    lines.extend(["", "### Top emotional headlines"])
    sorted_h = sorted(agg.headlines, key=lambda h: abs(h.score), reverse=True)
    for i, h in enumerate(sorted_h[:8], 1):
        emo_tag = ", ".join(h.emotions[:2])
        lines.append(
            f"{i}. [{h.sentiment} {h.score:+.1f}] [{h.source}] {h.title[:100]}{'…' if len(h.title) > 100 else ''}"
        )
        if emo_tag:
            lines.append(f"   _Emotions: {emo_tag}_")

    lines.extend(["", "### Who will do what (probabilistic, from net emotion + news mix)", ""])
    lines.append("| Actor | Likely behavior | Time window | Confidence |")
    lines.append("|-------|-----------------|-------------|------------|")
    for b in behaviors:
        lines.append(f"| {b.actor} | {b.likely_action} | {b.window} | {b.confidence} |")

    lines.extend([
        "",
        "### Sector tilt from crowd emotion",
    ])
    if agg.fear_greed_index < 40:
        lines.append("- **Bid:** gold, liquid funds, defensives (FMCG, pharma), low-beta large caps")
        lines.append("- **Avoid:** high-beta small caps, leveraged names, speculative themes")
    elif agg.fear_greed_index > 60:
        lines.append("- **Bid:** momentum leaders, small/mid caps, thematic (AI, defense, renewables)")
        lines.append("- **Risk:** sharp reversal if greed headlines fade; watch for profit-taking")
    else:
        lines.append("- **Mixed:** stock-picking market; fundamentals + peer leadership matter more than mood")

    lines.extend([
        "",
        "_Net emotion = sum of scores, not a survey. Behavioral table is heuristic, not certainty._",
    ])

    return "\n".join(lines), ["emotion-news", "emotion-finbert", "crowd-behavior"]


def print_emotion_terminal(news_limit: int = 20) -> None:
    from arka.stock.ui import banner, bullet, fear_greed_bar, headline_item, note, section, stat_row, table, tag

    news = fetch_emotion_news(limit=news_limit)
    if not news:
        banner("Market emotion", icon="🎭")
        note("Could not fetch news for emotion analysis.")
        return

    agg = analyze_emotions(news)
    behaviors = predict_crowd_behaviors(agg)
    banner("Market emotion & crowd forecast", subtitle=f"{agg.total} headlines · live sentiment")

    stat_row("Net emotion sum", f"{agg.net_score:+.1f}")
    stat_row("Average / headline", f"{agg.avg_score:+.2f}")
    stat_row(
        "Split",
        f"{tag(str(agg.positive), 'good')} pos  "
        f"{tag(str(agg.negative), 'bad')} neg  "
        f"{tag(str(agg.neutral), 'neutral')} neutral",
    )
    fear_greed_bar(agg.fear_greed_index, _fear_greed_label(agg.fear_greed_index))
    stat_row("Dominant mood", agg.dominant_emotion.replace("_", " ").title())

    section("Emotion keyword hits")
    for emo, count in sorted(agg.emotion_counts.items(), key=lambda x: -x[1]):
        if count > 0 and emo != "neutral_tone":
            bullet(f"{emo.replace('_', ' ').title()}: {count}")

    section("Top emotional headlines")
    sorted_h = sorted(agg.headlines, key=lambda h: abs(h.score), reverse=True)
    for i, h in enumerate(sorted_h[:8], 1):
        tone = "good" if h.score > 0 else "bad" if h.score < 0 else "neutral"
        headline_item(i, h.source, f"{tag(h.sentiment, tone)} {h.title}")

    section("Who will likely do what")
    rows = []
    for b in behaviors:
        conf = tag(
            b.confidence.upper(),
            "good" if b.confidence == "high" else "warn" if b.confidence == "medium" else "neutral",
        )
        rows.append([b.actor, b.likely_action[:52], b.window, conf])
    table(["Actor", "Likely behavior", "Window", "Conf"], rows, aligns=["l", "l", "l", "c"])

    section("Sector tilt")
    if agg.fear_greed_index < 40:
        bullet("Bid: gold, liquid funds, defensives, low-beta large caps")
        bullet("Avoid: high-beta small caps, leveraged names")
    elif agg.fear_greed_index > 60:
        bullet("Bid: momentum leaders, small/mid caps, thematic (AI, defense)")
        bullet("Risk: sharp reversal if greed headlines fade")
    else:
        bullet("Mixed market — stock picking + fundamentals matter more than mood")

    note("Heuristic forecast from headline sentiment, not a survey.")


def is_emotion_query(query: str) -> bool:
    low = query.lower()
    return bool(re.search(
        r"\b(emotion|sentiment|fear|greed|mood|panic|fomo|crowd|retail investor|"
        r"who will (buy|sell)|market feeling|bullish|bearish|psychology)\b",
        low,
    ))


def main() -> int:
    import argparse
    import sys

    from arka.stock.ui import use_terminal_ui

    p = argparse.ArgumentParser(description="Market emotion & crowd behavior forecast")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--plain", action="store_true")
    args = p.parse_args()
    if args.plain:
        import os
        os.environ["STOCK_PLAIN"] = "1"
    if use_terminal_ui():
        print_emotion_terminal(news_limit=args.limit)
    else:
        report, _ = format_emotion_report(news_limit=args.limit)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
