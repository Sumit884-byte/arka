"""Daily/tech brief headline prompts and OpenAI changelog URL helpers."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime

_BRIEF_URL_WORDS_DEFAULT = "30"
_BRIEF_URL_LIMIT_ENABLED_DEFAULT = ""

OPENAI_OFFICIAL_HOSTS = (
    "platform.openai.com",
    "openai.com",
)

HEADLINE_URL_INSTRUCTION = (
    " Output ONLY bullet lines — no introduction, preamble, or closing summary. "
    "Do not write lines like 'Here are N headlines' or 'covering AI, startups'. "
    "For each bullet, put the source URL on the same line after an em dash "
    '(e.g. "- Headline — https://example.com/article"). '
    "Include a clickable URL for every item when one appears in search results. "
    "For OpenAI updates or API changelog items, prefer official URLs at "
    "https://platform.openai.com/docs/changelog or https://openai.com/index/... "
    "Never invent URLs — only use links from the provided search results."
)

_PREAMBLE_START_RE = re.compile(
    r"^(?:"
    r"here\s+are|below\s+are|the\s+following\s+(?:are|headlines?)|"
    r"today'?s?\s+(?:top\s+)?(?:tech\s+)?news\s+headlines?|"
    r"\d+\s+concise\s+(?:tech\s+)?news\s+headlines?"
    r")",
    re.I,
)
_STALE_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_MONTH_DAY_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b",
    re.I,
)
_MONTH_TO_NUM: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

CHANGELOG_EXEMPT_URL_MARKERS = ("platform.openai.com/docs/changelog",)

_MEMORY_ID_RE = re.compile(r"\bMemory\s+[0-9a-f]+\b", re.I)
_MEMORY_TS_RE = re.compile(r"^\([0-9T:\-. ]+\):\s*")
_SECTION_HEADER_RE = re.compile(
    r"^(?:Relevant memories|Static profile|Dynamic context|Memory context)\b",
    re.I,
)
_TEST_MEMORY_RE = re.compile(
    r"\b(test(?:ing)?\s+only|ignore\s+this|dummy|placeholder|lorem\s+ipsum|"
    r"delete\s+me|sample\s+memory|test\s+entry)\b",
    re.I,
)


def is_headlines_bullet_request(question: str) -> bool:
    low = question.lower()
    if not re.search(r"\bheadlines?\b", low):
        return False
    return bool(
        re.search(r"\b(bullet|concise|brief\s+top|top\s+news)\b", low)
        or re.search(r"\bgive\s+\d", low)
    )


def tech_focus_from_prompt(question: str) -> bool:
    return bool(re.search(r"\btech\b", question, re.I))


def mentions_openai(question: str, web_context: str = "") -> bool:
    text = f"{question}\n{web_context}".lower()
    return "openai" in text


def _is_openai_official_link(link: str) -> bool:
    low = (link or "").lower()
    return any(host in low for host in OPENAI_OFFICIAL_HOSTS)


def current_brief_date(*, long_form: bool = True) -> str:
    """Human-readable date for brief prompts and search queries."""
    today = datetime.now()
    if long_form:
        return today.strftime("%B %d, %Y")
    return today.strftime("%B %d %Y")


def openai_changelog_search_queries() -> list[str]:
    today = datetime.now()
    year = today.year
    month = today.strftime("%B")
    return [
        f"OpenAI API changelog {year} site:platform.openai.com",
        f"OpenAI news announcement {month} {year} site:openai.com",
    ]


def brief_url_limit_enabled() -> bool:
    """Whether daily/tech brief headlines include a short excerpt under each URL."""
    try:
        from arka.env import env_get

        explicit = env_get("BRIEF_URL_LIMIT_ENABLED", _BRIEF_URL_LIMIT_ENABLED_DEFAULT).lower()
        if explicit:
            return explicit not in ("0", "false", "no", "off")
        # Legacy: BRIEF_URL_WORDS alone controlled on/off before the toggle existed.
        try:
            return int(env_get("BRIEF_URL_WORDS", "0")) > 0
        except ValueError:
            return False
    except ImportError:
        return False


def brief_url_words_limit() -> int:
    """Max words per source URL for brief excerpts and headline scraping (0 = off)."""
    if not brief_url_limit_enabled():
        return 0
    try:
        from arka.env import env_get

        return max(0, int(env_get("BRIEF_URL_WORDS", _BRIEF_URL_WORDS_DEFAULT)))
    except ValueError:
        return 0


def truncate_words(text: str, max_words: int) -> str:
    """Return up to max_words words; append ellipsis when truncated."""
    words = re.sub(r"\s+", " ", (text or "").strip()).split()
    if not words or max_words <= 0:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "…"


def headlines_scrape_kwargs() -> dict[str, int]:
    """Lighter web scrape settings for headline bullet requests."""
    per_url = brief_url_words_limit()
    return {
        "min_words": 0,
        "hard_limit": 10,
        "per_page_words": per_url,
    }


def format_openai_changelog_context(results: list[dict]) -> str:
    lines = ["[OpenAI changelog/news sources]"]
    seen: set[str] = set()
    word_limit = brief_url_words_limit()
    for row in results:
        link = (row.get("link") or "").strip()
        title = (row.get("title") or "").strip()
        if not link or link in seen or not _is_openai_official_link(link):
            continue
        seen.add(link)
        snippet = (row.get("snippet") or "").strip()
        lines.append(f"- {title} — {link}")
        if snippet:
            if word_limit > 0:
                lines.append(f"  {truncate_words(snippet, word_limit)}")
            else:
                lines.append(f"  {snippet[:200]}")
    return "\n".join(lines) if len(lines) > 1 else ""


def fetch_openai_changelog_context() -> str:
    try:
        from arka.agent.chat import duckduckgo_search
    except ImportError:
        return ""
    results: list[dict] = []
    seen_links: set[str] = set()
    for query in openai_changelog_search_queries():
        for row in duckduckgo_search(query, max_results=5):
            link = row.get("link") or ""
            if link in seen_links:
                continue
            seen_links.add(link)
            results.append(row)
    return format_openai_changelog_context(results)


def sanitize_brief_memory_context(raw: str, *, max_items: int = 6) -> str:
    """Strip memory IDs, test junk, and section headers for brief personalization."""
    if not raw.strip():
        return ""

    facts: list[str] = []
    seen: set[str] = set()
    chunks: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if not text or _SECTION_HEADER_RE.match(text):
            continue
        if text.endswith(":") and len(text) < 48 and ";" not in text:
            continue
        chunks.extend(part.strip() for part in re.split(r";", text) if part.strip())

    for text in chunks:
        text = re.sub(r"^[-•*]\s*", "", text)
        text = _MEMORY_ID_RE.sub("", text)
        text = _MEMORY_TS_RE.sub("", text)
        text = re.sub(r"\s{2,}", " ", text).strip(" -—:")
        if not text or len(text) < 4 or _TEST_MEMORY_RE.search(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        facts.append(text)
        if len(facts) >= max_items:
            break
    return "; ".join(facts)


def fetch_brief_memory_context(goal: str) -> str:
    """Fetch and sanitize memory context for daily/tech brief prompts."""
    goal = goal.strip()
    if not goal:
        return ""

    raw = ""
    try:
        from arka.integrations.supermemory import context_for

        raw = context_for(goal, limit_chars=3500)
    except Exception:
        pass

    if not raw.strip():
        try:
            from arka.agent.core import memory_context_for

            raw = memory_context_for(goal)
        except Exception:
            pass

    return sanitize_brief_memory_context(raw)


def _excerpt_from_context_block(block: str, *, max_words: int) -> tuple[str, str]:
    """Parse one web-context block into (url, excerpt)."""
    block = block.strip()
    if not block or max_words <= 0:
        return "", ""

    bullet_match = re.search(r"^-\s+.+\s*[—–-]\s*(https?://\S+)", block, re.M)
    if bullet_match:
        url = bullet_match.group(1).rstrip(").,;")
        after_bullet = block[bullet_match.end() :].strip()
        body = re.sub(r"^\s{2,}", "", after_bullet, flags=re.M)
        return url, truncate_words(body, max_words)

    url_match = re.search(r"^URL:\s*(https?://\S+)", block, re.M)
    if url_match:
        url = url_match.group(1).rstrip(").,;")
        body_parts: list[str] = []
        past_url = False
        for line in block.splitlines():
            if re.match(r"^Source:\s*", line):
                continue
            if re.match(r"^URL:\s*", line):
                past_url = True
                continue
            if past_url and line.strip():
                body_parts.append(line.strip())
        return url, truncate_words(" ".join(body_parts), max_words)

    inline = re.search(r"[—–-]\s*(https?://\S+)", block)
    if inline:
        url = inline.group(1).rstrip(").,;")
        after = block[inline.end() :].strip()
        return url, truncate_words(after, max_words)
    return "", ""


def _url_from_context_block(block: str) -> str:
    """Extract the first URL from a scraped search/context block."""
    url_match = re.search(r"^URL:\s*(https?://\S+)", block, re.M)
    if url_match:
        return url_match.group(1).rstrip(").,;")
    bullet_match = re.search(r"^-\s+.+\s*[—–-]\s*(https?://\S+)", block, re.M)
    if bullet_match:
        return bullet_match.group(1).rstrip(").,;")
    inline = re.search(r"[—–-]\s*(https?://\S+)", block)
    if inline:
        return inline.group(1).rstrip(").,;")
    return ""


def _context_by_url(web_context: str) -> dict[str, str]:
    """Map source URL -> full context block for staleness checks."""
    mapping: dict[str, str] = {}
    for block in re.split(r"\n{2,}", web_context):
        text = block.strip()
        if not text:
            continue
        url = _url_from_context_block(text)
        if url and url not in mapping:
            mapping[url] = text
    return mapping


def _excerpts_from_web_context(web_context: str, *, max_words: int) -> dict[str, str]:
    """Map source URL -> short excerpt parsed from scraped search context."""
    if not web_context.strip() or max_words <= 0:
        return {}

    excerpts: dict[str, str] = {}
    for block in re.split(r"\n{2,}", web_context):
        url, excerpt = _excerpt_from_context_block(block, max_words=max_words)
        if url and excerpt and url not in excerpts:
            excerpts[url] = excerpt
    return excerpts


def _urls_from_web_context(web_context: str) -> dict[str, str]:
    urls: dict[str, str] = {}
    for match in re.finditer(
        r"(?:^|\n)(?:Source:\s*)?(.+?)\s*[—–-]\s*(https?://\S+)",
        web_context,
    ):
        title = match.group(1).strip()
        url = match.group(2).rstrip(").,;")
        if title:
            urls[title.lower()] = url
    for match in re.finditer(
        r"(?:^|\n)Source:\s*(.+?)\s*\nURL:\s*(https?://\S+)",
        web_context,
    ):
        title = match.group(1).strip()
        url = match.group(2).rstrip(").,;")
        if title:
            urls[title.lower()] = url
    return urls


_HEADLINE_URL_RE = re.compile(r"[—–-]\s*(https?://\S+)")
_URL_THEN_NEXT_RE = re.compile(
    r"(https?://\S+)(?:\.\.\.)?(?:[)\].,;]*)?\s*[-–]\s+(?=\S)"
)
_MID_BULLET_RE = re.compile(r"(?<!\n)\s+[\*•]\s+")
_LEADING_BULLET_RE = re.compile(r"^[\*•\-]\s+")


def is_headline_preamble_line(line: str) -> bool:
    """True when a line is intro junk, not a headline bullet."""
    stripped = line.strip()
    if not stripped:
        return True
    body = re.sub(r"^[\*•\-]\s+", "", stripped)
    if re.match(r"^\[FROM\s+SEARCH\]\s*$", body, re.I):
        return True
    if re.match(r"^\[FROM\s+SEARCH\]\s+", body, re.I):
        rest = re.sub(r"^\[FROM\s+SEARCH\]\s*", "", body, flags=re.I).strip()
        if not rest or _PREAMBLE_START_RE.match(rest):
            return True
        body = rest
    if _PREAMBLE_START_RE.match(body):
        return True
    low = body.lower()
    if re.search(r"\bhere\s+are\s+\d+\b", low) and not _HEADLINE_URL_RE.search(body):
        return True
    if "headlines" in low and ("covering" in low or "concise" in low):
        if not _HEADLINE_URL_RE.search(body):
            return True
    return False


def is_changelog_exempt_url(url: str) -> bool:
    """Cumulative changelog pages are not dated news and stay eligible."""
    low = (url or "").lower()
    return any(marker in low for marker in CHANGELOG_EXEMPT_URL_MARKERS)


def _reference_today(*, ref_date: date | None = None, ref_year: int | None = None) -> date:
    if ref_date is not None:
        return ref_date
    if ref_year is not None:
        now = datetime.now()
        return date(ref_year, now.month, now.day)
    return date.today()


def _month_num(name: str) -> int | None:
    key = name.lower()
    return _MONTH_TO_NUM.get(key) or _MONTH_TO_NUM.get(key[:3])


def headline_date_from_text(text: str, *, ref_year: int | None = None) -> date | None:
    """Return the latest calendar date mentioned in text, if any."""
    if not text or not text.strip():
        return None

    year_default = ref_year if ref_year is not None else datetime.now().year
    found: list[date] = []

    for match in _ISO_DATE_RE.finditer(text):
        try:
            found.append(
                date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            )
        except ValueError:
            continue

    for match in _MONTH_DAY_RE.finditer(text):
        month = _month_num(match.group(1))
        if not month:
            continue
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else year_default
        try:
            found.append(date(year, month, day))
        except ValueError:
            continue

    if not found:
        return None
    return max(found)


def headline_looks_stale(
    title: str,
    *,
    context: str = "",
    url: str = "",
    ref_date: date | None = None,
    ref_year: int | None = None,
) -> bool:
    """True when a headline or its context references a clearly past date."""
    if is_changelog_exempt_url(url):
        return False

    today = _reference_today(ref_date=ref_date, ref_year=ref_year)
    year = today.year
    combined = f"{title}\n{context}"

    for match in _STALE_YEAR_RE.finditer(combined):
        if int(match.group(1)) < year - 1:
            return True

    parsed = headline_date_from_text(combined, ref_year=year)
    if parsed is not None and parsed < today:
        return True
    return False


def context_block_looks_stale(block: str, *, ref_date: date | None = None) -> bool:
    """True when a scraped search/context block is clearly from a previous day."""
    if not block.strip():
        return False
    url = _url_from_context_block(block)
    if is_changelog_exempt_url(url):
        return False
    today = ref_date or date.today()
    parsed = headline_date_from_text(block, ref_year=today.year)
    return parsed is not None and parsed < today


def filter_stale_brief_context(web_context: str, *, ref_date: date | None = None) -> str:
    """Drop search/scrape blocks whose snippet text is clearly from yesterday or older."""
    if not web_context.strip():
        return web_context

    kept: list[str] = []
    for block in re.split(r"\n{2,}", web_context):
        text = block.strip()
        if not text or not context_block_looks_stale(text, ref_date=ref_date):
            kept.append(text)
    return "\n\n".join(kept)


def brief_search_date_boost(
    query: str,
    title: str,
    snippet: str,
    *,
    ref_date: date | None = None,
) -> int:
    """Score adjustment for headline searches: prefer today, penalize older dates."""
    if not re.search(r"\b(headlines?|tech\s+news|today|latest)\b", query, re.I):
        return 0

    today = ref_date or date.today()
    combined = f"{title}\n{snippet}"
    parsed = headline_date_from_text(combined, ref_year=today.year)
    if parsed is None:
        return 0
    if parsed == today:
        return 8
    if parsed < today:
        return -12
    return 0


def headlines_search_query(question: str) -> str:
    """Build a date-aware web search query for headline bullet requests."""
    try:
        from arka.agent.chat import ground_search_query, normalize_question
    except ImportError:
        return question

    base = ground_search_query(normalize_question(question))
    today = datetime.now()
    date_long = current_brief_date(long_form=True)
    month_day = today.strftime("%B %d")

    if tech_focus_from_prompt(question):
        has_day = month_day.lower() in base.lower()
        if has_day and re.search(r"\b(today|latest)\b", base, re.I):
            return base
        return f"tech news today latest {date_long} AI startups developer tools"

    has_day = month_day.lower() in base.lower() or date_long.lower().replace(",", "") in base.lower().replace(",", "")
    if has_day and re.search(r"\b(today|latest)\b", base, re.I):
        return base
    return f"{base} news today latest {date_long}"


def _match_url_for_headline(title: str, url_map: dict[str, str]) -> str:
    low = title.lower()
    if low in url_map:
        return url_map[low]
    for key, url in url_map.items():
        if low in key or key in low:
            return url
    return ""


def _split_concatenated_headline_line(line: str) -> list[str]:
    """Split one physical line that contains multiple 'Title — URL' headline bullets."""
    text = line.strip()
    if not text:
        return []
    text = _LEADING_BULLET_RE.sub("", text, count=1)
    fragments: list[str] = []
    pos = 0
    while pos < len(text):
        match = _URL_THEN_NEXT_RE.search(text, pos)
        if not match:
            tail = text[pos:].strip()
            if tail:
                fragments.append(tail)
            break
        url_tail = re.match(r"https?://\S+", text[match.start() :])
        url_end = match.start() + (url_tail.end() if url_tail else 0)
        head = text[pos:url_end].strip()
        if head:
            fragments.append(head)
        pos = match.end()
    return fragments or [line.strip()]


def _parse_headline_fragment(fragment: str, url_map: dict[str, str]) -> tuple[str, str]:
    matches = list(_HEADLINE_URL_RE.finditer(fragment))
    if matches:
        last = matches[-1]
        title = fragment[: last.start()].strip()
        url = last.group(1).rstrip(").,;")
        return title, url
    title = fragment.strip()
    return title, _match_url_for_headline(title, url_map)


def format_headlines_response(answer: str, *, web_context: str = "") -> str:
    """Normalize headline bullets to one-per-line '- Title — URL' markdown."""
    if not answer.strip():
        return answer

    url_map = _urls_from_web_context(web_context)
    excerpt_limit = brief_url_words_limit()
    url_excerpts = _excerpts_from_web_context(web_context, max_words=excerpt_limit)
    url_context = _context_by_url(web_context)
    text = re.sub(r"^\[FROM\s+SEARCH\]\s*", "", answer.strip(), flags=re.I)
    text = re.sub(r"\s*\*\s{2,}", "\n- ", text)
    text = _MID_BULLET_RE.sub("\n- ", text)

    lines_out: list[str] = []
    seen_urls: set[str] = set()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or is_headline_preamble_line(stripped):
            continue

        for fragment in _split_concatenated_headline_line(stripped):
            title, url = _parse_headline_fragment(fragment, url_map)
            if not title or is_headline_preamble_line(title):
                continue
            context_bits = [url_excerpts.get(url, ""), url_context.get(url, "")]
            context = "\n".join(bit for bit in context_bits if bit)
            if headline_looks_stale(title, context=context, url=url):
                continue
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                lines_out.append(f"- {title} — {url}")
                excerpt = url_excerpts.get(url, "")
                if excerpt:
                    lines_out.append(f"  {excerpt}")
            else:
                lines_out.append(f"- {title}")

    return "\n".join(lines_out)


def build_headlines_prompt(*, tech_focus: bool = False, mem_ctx: str = "") -> str:
    clean_mem = sanitize_brief_memory_context(mem_ctx) if mem_ctx else ""
    today = current_brief_date(long_form=True)
    if tech_focus:
        prompt = (
            f"Give 5-7 concise tech news headlines for today ({today}) in bullet points "
            "covering AI, startups, developer tools, and major tech industry news. "
            f"Include ONLY news published today ({today}). "
            "Do not include yesterday's stories unless they broke overnight and are still developing today."
        )
        prompt += (
            " Check OpenAI API changelog and OpenAI announcements;"
            " platform.openai.com/docs/changelog is cumulative (not dated news) and may be cited anytime."
            " For dated OpenAI announcements, use https://openai.com/index/... with today's date."
        )
        if clean_mem:
            prompt += f" Personalize headline selection to: {clean_mem}"
    elif clean_mem:
        prompt = (
            f"Give 5 brief top news headlines for today ({today}) in bullet points, "
            f"India and world mix. Include ONLY news published today ({today}). "
            "Do not include yesterday's stories unless they broke overnight and are still developing today. "
            f"Personalize to: {clean_mem}"
        )
    else:
        prompt = (
            f"Give 5 brief top news headlines for today ({today}) in bullet points, "
            "India and world mix. Include ONLY news published today ({today}). "
            "Do not include yesterday's stories unless they broke overnight and are still developing today."
        )
    return prompt + HEADLINE_URL_INSTRUCTION


def headline_answer_instructions(question: str, web_context: str = "") -> str:
    if not is_headlines_bullet_request(question):
        return ""
    today = current_brief_date(long_form=True)
    extra = (
        f"\nIMPORTANT: Today is {today}. Output ONLY headline bullets — no introduction, "
        "preamble, or summary. Do not write lines like 'Here are N headlines' or "
        "'covering AI, startups'. "
        "Format each headline as a bullet with the source URL on the same line "
        'after an em dash (e.g. "- Headline — https://example.com/article"). '
        "Include a URL for every item when one appears in the search results. "
        f"Include ONLY news published today ({today}). "
        "Do not include yesterday's stories unless they broke overnight and are still developing today."
    )
    if tech_focus_from_prompt(question) or mentions_openai(question, web_context):
        extra += (
            " For OpenAI changelog, use https://platform.openai.com/docs/changelog "
            "(cumulative, not dated news). For dated OpenAI announcements, use "
            "https://openai.com/index/... only when published today."
        )
    return extra


def enrich_headlines_web_context(question: str, web_context: str) -> str:
    """Prepend OpenAI changelog search hits for tech briefs; drop stale dated blocks."""
    if not is_headlines_bullet_request(question):
        return web_context
    web_context = filter_stale_brief_context(web_context)
    if not tech_focus_from_prompt(question):
        return web_context
    openai_ctx = fetch_openai_changelog_context()
    if not openai_ctx:
        return web_context
    if web_context:
        return f"{openai_ctx}\n\n{web_context}"
    return openai_ctx


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka daily brief helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prompt = sub.add_parser("prompt", help="Build headlines prompt for web_answer")
    p_prompt.add_argument("--tech-focus", action="store_true")
    p_prompt.add_argument("--mem-ctx", default="")

    p_mem = sub.add_parser("mem-ctx", help="Fetch sanitized memory context for briefs")
    p_mem.add_argument("goal")

    args = parser.parse_args()
    if args.cmd == "prompt":
        print(build_headlines_prompt(tech_focus=args.tech_focus, mem_ctx=args.mem_ctx.strip()))
        return 0
    if args.cmd == "mem-ctx":
        print(fetch_brief_memory_context(args.goal.strip()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
