"""Daily/tech brief headline prompts and OpenAI changelog URL helpers."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from functools import lru_cache
from urllib.parse import urlparse

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
    # When formatting a captured search response, use the newest publication
    # date in that response as the reference day. This keeps replayed/cached
    # briefs deterministic instead of comparing them with the machine's date.
    context_dates = [headline_date_from_text(web_context)] if web_context else []
    reference_date = max((item for item in context_dates if item), default=None)
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
            if headline_looks_stale(title, context=context, url=url, ref_date=reference_date):
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


def parse_news_context_items(web_context: str) -> list[dict[str, str]]:
    """Parse Source/URL blocks into title, url, snippet dicts."""
    items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for block in re.split(r"\n{2,}", web_context or ""):
        text = block.strip()
        if not text:
            continue
        title_match = re.search(r"^Source:\s*(.+)$", text, re.M)
        url_match = re.search(r"^URL:\s*(https?://\S+)", text, re.M)
        if not title_match or not url_match:
            continue
        title = sanitize_news_title(title_match.group(1).strip())
        url = normalize_news_url(url_match.group(1).rstrip(").,;"))
        if not title or not url or url in seen_urls:
            continue
        if not is_valid_news_url(url):
            continue
        if headline_title_looks_like_nav(title):
            continue
        snippet = ""
        after = re.split(r"^URL:\s*https?://\S+\s*", text, maxsplit=1, flags=re.M)
        if len(after) == 2:
            snippet = sanitize_scraped_news_text(after[1], max_chars=280)
        if headline_looks_like_engagement(title, snippet):
            continue
        if news_snippet_looks_like_filler(title, snippet):
            continue
        seen_urls.add(url)
        items.append({"title": title, "url": url, "snippet": snippet})
    return items


def headlines_from_web_context(
    web_context: str,
    *,
    limit: int = 7,
    place: str = "",
) -> str:
    """Build headline bullets from scraped search context without an LLM."""
    items = pick_news_items(web_context, limit=limit, place=place)
    if not items:
        return ""
    lines = [f"- {row['title']} — {row['url']}" for row in items]
    return format_headlines_response("\n".join(lines), web_context=web_context)


def gather_headlines_context(question: str) -> str:
    """Build snippet-only headline context — no page scrapes (fast for web UI)."""
    try:
        from arka.agent.chat import duckduckgo_search
    except ImportError:
        return ""

    search_q = headlines_search_query(question)
    try:
        results = duckduckgo_search(search_q, max_results=10)
    except Exception as exc:
        print(f"Headlines search error: {exc}", file=sys.stderr)
        return ""
    if not results:
        return ""

    merged: list[str] = []
    seen: set[str] = set()
    for row in results:
        link = (row.get("link") or "").strip()
        if not link or link in seen:
            continue
        title = (row.get("title") or link).strip()
        snippet = (row.get("snippet") or "").strip()
        if not is_changelog_exempt_url(link) and headline_looks_stale(title, context=snippet, url=link):
            continue
        seen.add(link)
        merged.append(f"Source: {title}\nURL: {link}\n{snippet}".strip())
    ctx = "\n\n".join(merged)
    return filter_stale_brief_context(ctx) if ctx else ""


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


_NEWS_SOURCE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("bbc.com", r"\bbbc(?:\s+news)?\b"),
    ("cnn.com", r"\bcnn\b"),
    ("reuters.com", r"\breuters\b"),
    ("theguardian.com", r"\b(?:the\s+)?guardian\b"),
    ("nytimes.com", r"\b(?:ny\s*times|new\s+york\s+times)\b"),
    ("apnews.com", r"\b(?:ap\s+news|associated\s+press)\b"),
    ("aljazeera.com", r"\bal\s+jazeera\b"),
    ("ndtv.com", r"\bndtv\b"),
    ("indiatoday.in", r"\bindia\s+today\b"),
    ("usatoday.com", r"\b(?:usatoday|usa\s*today\.com|usa today newspaper)\b"),
)

_NEWS_HOST_ALIASES: dict[str, tuple[str, ...]] = {
    "bbc.com": ("bbc.com", "bbc.co.uk"),
}


def url_matches_news_host(url: str, host: str) -> bool:
    """True when a URL belongs to a named outlet (handles BBC .com vs .co.uk)."""
    if not host:
        return True
    low = (url or "").lower()
    aliases = _NEWS_HOST_ALIASES.get(host, (host,))
    return any(alias in low for alias in aliases)


_DISPLAY_OVERRIDES: dict[str, str] = {
    "united states": "United States",
    "united kingdom": "United Kingdom",
    "united arab emirates": "United Arab Emirates",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "south africa": "South Africa",
    "saudi arabia": "Saudi Arabia",
    "sri lanka": "Sri Lanka",
    "new zealand": "New Zealand",
    "czech republic": "Czech Republic",
    "hong kong": "Hong Kong",
}

_EXTRA_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "United States",
    "us": "United States",
    "u.s": "United States",
    "u.s.a": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
}

_NON_COUNTRY_PLACES = frozenset(
    {
        "news",
        "the news",
        "world",
        "the world",
        "event",
        "the event",
        "launch",
        "brief",
        "morning",
        "evening",
        "gtc",
        "wwdc",
        "ces",
        "apple",
        "google",
        "nvidia",
        "microsoft",
    }
)
_EVENT_PLACE_RE = re.compile(
    r"(?i)\b(gtc|wwdc|ces|i/?o|keynote|launch|event|conference|unpacked|devday)\b"
)
_COUNTRY_TODAY_GENERIC_RE = re.compile(
    r"(?i)\b(?:what\s+happened|what'?s\s+happening|news|happening)\s+"
    r"(?:in|across)\s+(?:the\s+)?(?P<place>.+?)\s+today\b"
)
_IN_PLACE_TODAY_RE = re.compile(r"(?i)\bin\s+(?:the\s+)?(?P<place>.+?)\s+today\b")


def _display_country(canon: str) -> str:
    low = (canon or "").strip().lower()
    if low in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[low]
    return " ".join(part.capitalize() for part in low.split())


@lru_cache(maxsize=1)
def _country_alias_map() -> dict[str, str]:
    mapping = dict(_EXTRA_COUNTRY_ALIASES)
    try:
        from arka.core.office_titles import FINANCE_OFFICES

        for aliases, canon, _title in FINANCE_OFFICES:
            display = _display_country(canon)
            mapping[canon] = display
            for alias in aliases:
                mapping[re.sub(r"\s+", " ", alias.lower()).rstrip(".")] = display
    except ImportError:
        pass
    try:
        from arka.charts.data import COUNTRY_CODES

        for name, code in COUNTRY_CODES.items():
            key = name.lower().strip()
            if key in mapping or key in {"world"}:
                continue
            if code == "US":
                mapping[key] = "United States"
            elif code == "GB":
                mapping[key] = "United Kingdom"
            else:
                mapping[key] = _display_country(key)
    except ImportError:
        pass
    return mapping


_CANON_ISO: dict[str, str] = {
    "united states": "us",
    "united kingdom": "uk",
    "india": "in",
    "canada": "ca",
    "australia": "au",
    "new zealand": "nz",
    "germany": "de",
    "france": "fr",
    "japan": "jp",
    "china": "cn",
    "south korea": "kr",
    "north korea": "kp",
    "italy": "it",
    "spain": "es",
    "portugal": "pt",
    "netherlands": "nl",
    "belgium": "be",
    "switzerland": "ch",
    "austria": "at",
    "sweden": "se",
    "norway": "no",
    "denmark": "dk",
    "finland": "fi",
    "ireland": "ie",
    "iceland": "is",
    "poland": "pl",
    "czech republic": "cz",
    "hungary": "hu",
    "romania": "ro",
    "greece": "gr",
    "ukraine": "ua",
    "russia": "ru",
    "turkey": "tr",
    "israel": "il",
    "saudi arabia": "sa",
    "united arab emirates": "ae",
    "qatar": "qa",
    "egypt": "eg",
    "south africa": "za",
    "nigeria": "ng",
    "kenya": "ke",
    "ethiopia": "et",
    "ghana": "gh",
    "mexico": "mx",
    "brazil": "br",
    "argentina": "ar",
    "chile": "cl",
    "colombia": "co",
    "peru": "pe",
    "indonesia": "id",
    "malaysia": "my",
    "singapore": "sg",
    "thailand": "th",
    "vietnam": "vn",
    "philippines": "ph",
    "pakistan": "pk",
    "bangladesh": "bd",
    "sri lanka": "lk",
    "nepal": "np",
    "taiwan": "tw",
    "hong kong": "hk",
}


@lru_cache(maxsize=1)
def _country_geo_map() -> dict[str, str]:
    geos = {display: iso for canon, iso in _CANON_ISO.items() for display in (_display_country(canon),)}
    geos["United States"] = "us"
    geos["United Kingdom"] = "uk"
    try:
        from arka.charts.data import COUNTRY_CODES

        aliases = _country_alias_map()
        for name, code in COUNTRY_CODES.items():
            display = aliases.get(name.lower(), _display_country(name))
            iso = "uk" if code == "GB" else code.lower()
            if len(iso) == 2:
                geos.setdefault(display, iso)
    except ImportError:
        pass
    return geos


def resolve_country_place(token: str) -> str:
    """Map a captured place phrase to a display country, or '' if it is not a place."""
    raw = re.sub(r"\s+", " ", (token or "").strip().lower()).rstrip(".")
    if raw.startswith("the "):
        raw = raw[4:]
    if not raw or raw in _NON_COUNTRY_PLACES or _EVENT_PLACE_RE.search(raw):
        return ""
    aliases = _country_alias_map()
    if raw in aliases:
        return aliases[raw]
    if re.fullmatch(r"[a-z]{2,}(?:\s+[a-z]{2,}){0,3}", raw):
        return _display_country(raw)
    return ""


def country_news_place(question: str) -> str:
    """Country name when the user asked what happened there today — not a newspaper."""
    q = (question or "").strip()
    if not q:
        return ""
    if re.search(r"(?i)\b(?:usatoday|usa\s*today\.com|usa today newspaper)\b", q):
        return ""
    match = _COUNTRY_TODAY_GENERIC_RE.search(q) or _IN_PLACE_TODAY_RE.search(q)
    if not match:
        return ""
    return resolve_country_place(match.group("place"))


def country_news_geo(place: str) -> str:
    """Bright Data geo code for a resolved country display name."""
    return _country_geo_map().get((place or "").strip(), "")


def news_source_host(question: str) -> str:
    """Return a host fragment (e.g. bbc.com) when the user names a news outlet."""
    if country_news_place(question):
        return ""
    low = (question or "").lower()
    for host, pattern in _NEWS_SOURCE_PATTERNS:
        if re.search(pattern, low):
            return host
    return ""


def news_source_label(question: str) -> str:
    host = news_source_host(question)
    if not host:
        return ""
    return host.split(".")[0].upper()


def is_live_news_question(question: str) -> bool:
    """True when the user wants a synthesized news answer (not a bare skill token)."""
    q = (question or "").strip()
    if not q:
        return False
    low = q.lower()
    if news_source_host(q):
        return True
    if re.search(
        r"\b("
        r"latest|today['']?s|todays|current|breaking|top"
        r")\s+(?:\w+\s+){0,3}news\b",
        low,
    ):
        return True
    if re.search(r"\bnews\s+(today|now|headlines?)\b", low):
        return True
    if re.search(r"\bgive\s+(?:me\s+)?(?:the\s+)?news\b", low):
        return True
    if re.search(r"\bbest\s+(?:\w+\s+){0,4}(?:news|headlines?)\b", low):
        return True
    if re.search(r"\bwhat\s+happened\b", low):
        return True
    if re.search(r"\b(?:gtc|wwdc|kubecon|ces|aws\s+re:?invent|google\s+i/?o)\b", low):
        return True
    if re.search(r"\b(?:apple\s+(?:event|launch|keynote)|foldable\s+iphone|iphone\s+duo)\b", low):
        return True
    if re.search(r"\b(?:iphone|ipad)\s*(?:1[6-9]|[2-9]\d)\b", low):
        return True
    try:
        from arka.agent.launch_recap import is_launch_recap_question

        if is_launch_recap_question(q):
            return True
    except ImportError:
        pass
    return False


def is_classic_brief_bullets(question: str) -> bool:
    """True for explicit daily/morning briefs and headline-bullet formats."""
    q = (question or "").strip()
    if not q:
        return True
    if re.search(r"\b(daily|morning|tech)\s+brief\b", q, re.I):
        return True
    return is_headlines_bullet_request(q)


def should_use_live_news_web(question: str) -> bool:
    """Route to verified headline fetch instead of free-form LLM chat."""
    q = (question or "").strip()
    if not q:
        return False
    return is_live_news_question(q) and not is_classic_brief_bullets(q)


def wants_weather_with_brief(question: str) -> bool:
    """Include weather only when the user asked for a brief or weather."""
    q = (question or "").strip()
    if not q:
        return True
    low = q.lower()
    if re.search(r"\b(weather|forecast|temperature)\b", low):
        return True
    if re.search(r"\b(daily|morning)\s+brief\b", low):
        return True
    return False


def news_search_query(question: str) -> str:
    """Build a Bright Data / web search query tuned to the user's news request."""
    host = news_source_host(question)
    today = current_brief_date(long_form=True)
    month_day = datetime.now().strftime("%B %d")

    if host == "bbc.com":
        return f"site:bbc.com/news site:bbc.com news {month_day} {today} latest headlines"
    if host:
        label = news_source_label(question)
        return f"site:{host} {label} news latest {today}"

    place = country_news_place(question)
    if place:
        if place == "United States":
            return (
                f"{place} {today} breaking news "
                "site:apnews.com OR site:reuters.com OR site:bbc.com/news OR site:npr.org"
            )
        return f"{place} {today} breaking news"

    if tech_focus_from_prompt(question):
        return headlines_search_query(question)

    try:
        from arka.agent.chat import ground_search_query, normalize_question

        base = ground_search_query(normalize_question(question))
    except ImportError:
        base = question.strip()

    if re.search(r"\b(today|latest|breaking|current)\b", base, re.I):
        if month_day.lower() in base.lower() or today.lower().replace(",", "") in base.lower().replace(",", ""):
            return base
    return f"{base} news latest {today}"


def optimized_news_search_query(question: str) -> str:
    """Bright Data–tuned query: site operators + date, conversational noise stripped."""
    raw = news_search_query(question)
    try:
        from arka.integrations.brightdata_retrieval import optimize_brightdata_query

        return optimize_brightdata_query(raw)
    except ImportError:
        return raw


_BBC_SECTION_SLUGS = frozenset(
    {
        "world",
        "uk",
        "business",
        "politics",
        "health",
        "science_and_environment",
        "technology",
        "entertainment_and_arts",
        "sport",
        "africa",
        "asia",
        "us_and_canada",
        "europe",
        "latin_america",
        "middle_east",
        "india",
        "wales",
        "scotland",
        "northern_ireland",
        "england",
        "newsbeat",
        "video",
        "live",
        "topics",
        "weather",
        "in_pictures",
        "have_your_say",
    }
)

_NAV_LINE_RE = re.compile(
    r"(?i)^(?:\s*(?:skip to content|menu|sections?|related topics|more on this|"
    r"bbc navigation|homepage|sign in|subscribe now|share|copy link|"
    r"advertisement|cookie settings|privacy policy|terms of use))\s*$"
)

_NEWS_RSS_FEEDS: dict[str, str] = {
    "bbc.com": "http://feeds.bbci.co.uk/news/rss.xml",
    "reuters.com": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
    "apnews.com": "https://apnews.com/apf-topnews?output=rss",
    "npr.org": "https://feeds.npr.org/1001/rss.xml",
}

_COUNTRY_NEWS_RSS: dict[str, tuple[str, ...]] = {
    "United States": ("npr.org", "bbc.com"),
    "United Kingdom": ("bbc.com",),
}

_NEWS_FILLER_PATTERNS: tuple[str, ...] = (
    r"(?i)\bheart[- ]shaped\b.*\bsmoke\b",
    r"(?i)\b(?:red arrows|airshow|aerobatic|aeroplanes?\s+loop)\b",
    r"(?i)\bregional developments\b",
    r"(?i)\binfrastructure projects and cultural events\b",
    r"(?i)\bclimate change documentary\b",
    r"(?i)\bbbc verify\b.*\b(?:launch(?:es|ed)?|new initiative|debut)\b",
    r"(?i)\b(?:new initiative|newly launched|debuts)\b.*\bbbc verify\b",
    r"(?i)\bvarious (?:regional|local) (?:developments|events)\b",
)


def _dedupe_consecutive_words(text: str) -> str:
    return re.sub(r"\b(\w+(?:\s+\w+){0,2})\s+\1\b", r"\1", text, flags=re.I)


def sanitize_news_title(title: str) -> str:
    """Strip site chrome and doubled words from search result titles."""
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = re.sub(
        r"\s*[-–|]\s*(?:BBC News|CNN|Reuters|The Guardian|AP News).*$",
        "",
        t,
        flags=re.I,
    )
    t = _dedupe_consecutive_words(t)
    t = re.sub(r"\s+(?:page|section)\s*$", "", t, flags=re.I)
    return t.strip(" -–|")


def sanitize_scraped_news_text(text: str, *, max_chars: int = 2500) -> str:
    """Remove navigation chrome and markdown link glue from scraped pages."""
    if not text:
        return ""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    lines: list[str] = []
    for line in t.splitlines():
        line = line.strip()
        if not line or _NAV_LINE_RE.match(line):
            continue
        if re.search(r"(?i)^(americas|europe|asia|africa|uk|world)\s*$", line):
            continue
        lines.append(_dedupe_consecutive_words(line))
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned[:max_chars]


def headline_title_looks_like_nav(title: str) -> bool:
    t = (title or "").lower().strip()
    if not t:
        return True
    if re.search(r"\b(?:homepage|navigation|sections?)\b", t):
        return True
    if re.search(r"\b(?:americas|europe|asia)\s+(?:americas|europe|page)\b", t):
        return True
    if re.search(r"(?i)\b(?:news headlines|latest headlines|national news|breaking news live)\b", t):
        return True
    if re.search(r"(?i)\bnews broadcast\b", t):
        return True
    return t in {"bbc news", "news", "world", "home"}


def headline_looks_like_engagement(title: str, snippet: str = "") -> bool:
    """Drop audience callouts, newsletters, and 'tell us your story' items."""
    combined = f"{title}\n{snippet}"
    return bool(
        re.search(
            r"(?i)\b("
            r"wants? to know|tell us|have your say|we want to hear|"
            r"share your (?:story|experience)|how are .{0,40} you\b|"
            r"up first newsletter|newsletter\b|listener (?:question|mail)"
            r")\b",
            combined,
        )
    )


_US_STORY_RE = re.compile(
    r"(?i)\b("
    r"senate|senator|congress|house|white house|washington|fed(?:eral reserve)?|"
    r"interest rates?|supreme court|trump|biden|harris|midterm|"
    r"surgeon general|kennedy center|hhs|rfk|treasury|irs|"
    r"california|texas|florida|new york|hurricane|wildfire"
    r")\b"
)
_WORLD_ONLY_RE = re.compile(
    r"(?i)\b("
    r"kosovo|mecca|houthis?|von der leyen|ukraine|russia|"
    r"saudi arabia|thaci|pows?"
    r")\b"
)


def country_story_score(place: str, title: str, snippet: str = "") -> int:
    """Prefer domestic leads for a country-day recap; keep world items as fillers."""
    text = f"{title} {snippet}"
    if headline_looks_like_engagement(title, snippet) or headline_title_looks_like_nav(title):
        return -100
    score = 4
    if place == "United States":
        if _US_STORY_RE.search(text):
            score += 8
        if _WORLD_ONLY_RE.search(text) and not _US_STORY_RE.search(text):
            score -= 3
    elif place:
        tokens = [tok for tok in re.split(r"\W+", place.lower()) if len(tok) > 2]
        if any(tok in text.lower() for tok in tokens):
            score += 6
    return score


def pick_news_items(
    web_context: str,
    *,
    limit: int = 5,
    place: str = "",
) -> list[dict[str, str]]:
    """Pick a short, ranked set of stories — not the whole RSS dump."""
    items = parse_news_context_items(web_context)
    if not items:
        return []
    ranked = sorted(
        items,
        key=lambda row: country_story_score(place, row["title"], row.get("snippet", "")),
        reverse=True,
    )
    domestic: list[dict[str, str]] = []
    world: list[dict[str, str]] = []
    for row in ranked:
        title, snippet = row["title"], row.get("snippet", "")
        if country_story_score(place, title, snippet) < 0:
            continue
        text = f"{title} {snippet}"
        if (
            place == "United States"
            and _WORLD_ONLY_RE.search(text)
            and not _US_STORY_RE.search(text)
        ):
            world.append(row)
        else:
            domestic.append(row)
    picked = domestic[:limit]
    if len(picked) < 2:
        picked.extend(world[: limit - len(picked)])
    return picked


def format_country_news_brief(place: str, web_context: str) -> str:
    """Curated country briefing from titles/snippets when the LLM is unavailable."""
    items = pick_news_items(web_context, limit=4, place=place)
    if not items:
        return ""
    today = current_brief_date(long_form=True)
    lede_bits: list[str] = []
    for row in items[:2]:
        piece = (row.get("snippet") or row["title"]).strip()
        piece = re.sub(r"\s+", " ", piece).rstrip(" .")
        if piece and piece.lower() not in {bit.lower() for bit in lede_bits}:
            lede_bits.append(piece)
    lede = ". ".join(lede_bits).strip()
    if lede and not lede.endswith((".", "!", "?")):
        lede += "."
    lines = [f"**{place} today ({today})**", ""]
    if lede:
        lines.extend([lede, ""])
    for row in items:
        link = f"[{row['title']}]({row['url']})"
        snippet = (row.get("snippet") or "").strip()
        if snippet and snippet.lower() not in row["title"].lower():
            lines.append(f"- {link} — {snippet}")
        else:
            lines.append(f"- {link}")
    return "\n".join(lines).strip()


def news_snippet_looks_like_filler(title: str, snippet: str = "") -> bool:
    """True for airshow stunts, evergreen re-launches, and vague regional filler."""
    combined = f"{title}\n{snippet}".strip()
    if not combined:
        return True
    for pattern in _NEWS_FILLER_PATTERNS:
        if re.search(pattern, combined):
            return True
    if re.search(
        r"(?i)\b(?:including|such as)\s+(?:infrastructure|cultural events)\b",
        combined,
    ):
        return True
    return False


def fetch_news_rss_context(host: str, *, limit: int = 8) -> str:
    """Fetch fresh headline blocks from a known outlet RSS feed."""
    feed_url = _NEWS_RSS_FEEDS.get(host)
    if not feed_url:
        return ""
    try:
        import feedparser
    except ImportError:
        return ""

    try:
        feed = feedparser.parse(feed_url)
    except Exception:
        return ""

    blocks: list[str] = []
    seen: set[str] = set()
    for entry in feed.entries[: limit * 2]:
        title = sanitize_news_title((entry.get("title") or "").strip())
        link = (entry.get("link") or "").strip()
        summary = sanitize_scraped_news_text((entry.get("summary") or "").strip(), max_chars=400)
        if not title or not link or link in seen:
            continue
        link = normalize_news_url(link, host=host)
        if not link or not is_valid_news_url(link, host=host):
            continue
        if headline_title_looks_like_nav(title):
            continue
        if news_snippet_looks_like_filler(title, summary):
            continue
        seen.add(link)
        block = f"Source: {title}\nURL: {link}"
        if summary:
            block = f"{block}\n{summary}"
        blocks.append(block)
        if len(blocks) >= limit:
            break
    return "\n\n".join(blocks)


def _merge_news_context_blocks(primary: str, secondary: str, *, max_blocks: int = 8) -> str:
    """Merge RSS and search blocks, deduping by URL and preferring primary."""
    seen_urls: set[str] = set()
    merged: list[str] = []
    for ctx in (primary, secondary):
        if not (ctx or "").strip():
            continue
        for block in re.split(r"\n{2,}", ctx):
            text = block.strip()
            if not text:
                continue
            url_match = re.search(r"^URL:\s*(https?://\S+)", text, re.M)
            if not url_match:
                continue
            url = url_match.group(1).rstrip(").,;")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(text)
            if len(merged) >= max_blocks:
                break
        if len(merged) >= max_blocks:
            break
    return "\n\n".join(merged)


def normalize_news_url(url: str, *, host: str = "") -> str:
    """Return an absolute https URL or empty string when the link is unusable."""
    raw = (url or "").strip().rstrip(").,;]")
    if not raw:
        return ""
    if raw.startswith("/"):
        if host == "bbc.com" or "bbc." in host:
            raw = f"https://www.bbc.com{raw}"
        else:
            return ""
    if raw.startswith("//"):
        raw = f"https:{raw}"
    if not raw.startswith(("http://", "https://")):
        return ""
    return raw.replace("http://", "https://", 1)


_BROKEN_NEWS_URL_RE = re.compile(
    r"(?i)(?:/news/hi/|/video/docs|/news/bbcverify|\?page=|\?story=)"
)


def is_valid_news_url(url: str, *, host: str = "") -> bool:
    """Reject relative paths, pagination indexes, and other broken news links."""
    normalized = normalize_news_url(url, host=host)
    if not normalized.startswith("https://"):
        return False
    if _BROKEN_NEWS_URL_RE.search(normalized):
        return False
    low = normalized.lower()
    if "youtube.com/watch" in low or "youtu.be/" in low:
        return bool(host)
    if host and not url_matches_news_host(normalized, host):
        return False
    return is_news_article_url(normalized, host=host) if host else is_news_article_url(normalized)


def is_news_article_url(url: str, *, host: str = "") -> bool:
    """True when a URL looks like a news article, not a homepage or section index."""
    raw = normalize_news_url(url, host=host) or (url or "").strip()
    if not raw:
        return False
    if host and not url_matches_news_host(raw, host):
        return False
    parsed = urlparse(raw.split("?")[0].split("#")[0])
    path = (parsed.path or "").strip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    low = raw.lower()

    if "bbc." in low:
        if not segments or segments[0] != "news":
            return False
        if len(segments) == 1:
            return False
        if len(segments) == 2:
            slug = segments[1]
            if slug in _BBC_SECTION_SLUGS or slug == "articles":
                return False
            if re.search(r"-\d{5,}", slug) or re.search(r"^c[a-z0-9]{10,}$", slug):
                return True
            if re.search(r"\d{7,}", slug):
                return True
            return slug not in _BBC_SECTION_SLUGS and len(slug) > 20
        if segments[1] == "articles" and len(segments) >= 3:
            return True
        return len(segments) >= 3

    if len(segments) <= 1:
        return False
    if (
        len(segments) >= 3
        and re.fullmatch(r"20\d{2}", segments[0] or "")
        and re.fullmatch(r"\d{1,2}", segments[1] or "")
        and re.fullmatch(r"\d{1,2}", segments[2] or "")
        and len(segments) == 3
    ):
        return False
    tail = segments[-1]
    section_names = {
        "news",
        "world",
        "politics",
        "business",
        "sport",
        "sports",
        "tech",
        "health",
        "national",
        "nation",
        "nation-world",
        "headlines",
        "live",
        "video",
        "videos",
        "latest",
        "breaking",
        "local",
        "international",
        "regional",
    }
    if tail.lower() in section_names:
        return False
    if re.search(r"\d{5,}", tail):
        return True
    if len(tail) > 24 and "-" in tail:
        return True
    if len(segments) >= 3 and "-" in tail and len(tail) > 16:
        return True
    if len(segments) == 2 and segments[-1] in section_names:
        return False
    return False


def extract_youtube_urls(text: str) -> list[str]:
    return re.findall(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+)",
        text or "",
        flags=re.I,
    )


def _news_youtube_context_enabled() -> bool:
    import os

    return os.environ.get("NEWS_YOUTUBE_CONTEXT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def fetch_youtube_video_context(url: str) -> str:
    """Build a verified context block from an official YouTube video + transcript excerpt."""
    try:
        from arka.youtube.transcript import extract_video_id, fetch_transcript_text
    except ImportError:
        return ""

    video_id = extract_video_id(url)
    if not video_id:
        return ""
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    title = sanitize_news_title(url)
    snippet = ""
    try:
        transcript = fetch_transcript_text(video_id, research=True, allow_whisper=False)
        if transcript:
            snippet = sanitize_scraped_news_text(transcript, max_chars=500)
    except Exception:
        pass
    block = f"Source: {title or 'YouTube video'}\nURL: {watch_url}"
    if snippet:
        block = f"{block}\n{snippet}"
    return block


def fetch_news_youtube_context(question: str, *, host: str = "", limit: int = 2) -> str:
    """Find recent official outlet videos on YouTube and attach transcript excerpts."""
    if not host or not _news_youtube_context_enabled():
        return ""
    try:
        from arka.youtube.transcript import fetch_transcript_text, youtube_search
    except ImportError:
        return ""

    month_day = datetime.now().strftime("%B %d")
    year = datetime.now().year
    label = news_source_label(question) or host.split(".")[0].upper()
    query = f"{label} News {month_day} {year}"
    try:
        hits = youtube_search(query, limit=8)
    except BaseException:
        return ""

    blocks: list[str] = []
    seen: set[str] = set()
    for video_id, title, channel in hits:
        if host == "bbc.com" and "bbc" not in channel.lower():
            continue
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        if watch_url in seen:
            continue
        clean_title = sanitize_news_title(title)
        if not clean_title or news_snippet_looks_like_filler(clean_title):
            continue
        snippet = ""
        try:
            transcript = fetch_transcript_text(video_id, research=True, allow_whisper=False)
            if transcript:
                snippet = sanitize_scraped_news_text(transcript, max_chars=500)
        except Exception:
            pass
        seen.add(watch_url)
        block = f"Source: {clean_title}\nURL: {watch_url}"
        if snippet:
            block = f"{block}\n{snippet}"
        blocks.append(block)
        if len(blocks) >= limit:
            break
    return "\n\n".join(blocks)


def _finalize_news_context(
    question: str,
    *,
    host: str,
    rss_context: str,
    search_ctx: str,
    max_results: int,
) -> str:
    if rss_context and search_ctx:
        ctx = _merge_news_context_blocks(rss_context, search_ctx, max_blocks=max_results)
    elif rss_context:
        ctx = rss_context
    else:
        ctx = search_ctx

    youtube_blocks: list[str] = []
    for yt_url in extract_youtube_urls(question):
        block = fetch_youtube_video_context(yt_url)
        if block:
            youtube_blocks.append(block)
    yt_search = fetch_news_youtube_context(question, host=host) if host else ""
    if yt_search:
        ctx = _merge_news_context_blocks(yt_search, ctx, max_blocks=max_results)
    if youtube_blocks:
        ctx = _merge_news_context_blocks(
            "\n\n".join(youtube_blocks),
            ctx,
            max_blocks=max_results,
        )
    return ctx


_SERP_LEDE_RE = re.compile(
    r"(?i)(?:\b\d+\s+(?:day|days|hour|hours|week|weeks)\s+ago|[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\s+[—–-]\s+"
)


def looks_like_serp_dump(text: str) -> bool:
    """True when the reply is glued search-result ledes, not a written answer."""
    body = re.sub(r"^\[FROM\s+(?:SEARCH|MEMORY)\]\s*", "", (text or "").strip(), flags=re.I)
    if not body:
        return False
    ledes = _SERP_LEDE_RE.findall(body)
    if len(ledes) >= 2:
        return True
    if _SERP_LEDE_RE.search(body) and "..." in body:
        return True
    if body.count("...") >= 2 and len(body) < 500:
        return True
    return False


def news_summary_looks_truncated(text: str) -> bool:
    """True when the summary ends mid-thought or with a dangling ellipsis."""
    body = (text or "").strip()
    if not body:
        return True
    if re.search(r"\.{2,}\s*$", body):
        return True
    tail = body.rstrip()[-1]
    if tail in ".!?\"')]}":
        return False
    if re.search(r"\]\([^)]+\)\.?\s*$", body):
        return False
    return True


def trim_incomplete_summary(text: str) -> str:
    """Drop a trailing fragment when the model stopped mid-sentence."""
    body = (text or "").strip()
    if not body or not news_summary_looks_truncated(body):
        return body
    parts = re.split(r"(?<=[.!?])\s+", body)
    if len(parts) <= 1:
        return body
    trimmed = " ".join(parts[:-1]).strip()
    return trimmed or body


def news_summary_looks_like_ai_filler(text: str) -> bool:
    """True when the briefing talks about 'coverage' instead of what happened."""
    return bool(
        re.search(
            r"(?i)\b("
            r"major (?:national )?developments.{0,60}unfolding|"
            r"(?:breaking news )?stories are unfolding|"
            r"are being tracked|"
            r"being covered live|"
            r"broadcast coverage|"
            r"coverage of today|"
            r"latest video updates|"
            r"across the country\b.*\bbreaking news"
            r")\b",
            text or "",
        )
    )


def news_summary_looks_like_refusal(text: str) -> bool:
    """True when the model refused instead of briefing the search hits."""
    return bool(
        re.search(
            r"(?i)\b("
            r"i cannot fulfill|cannot fulfil|do not contain any text|"
            r"no (?:text or )?content snippets|preventing me from|"
            r"unable to (?:summarize|verify)|i can't (?:fulfill|summarize)|"
            r"all configured llm providers failed"
            r")\b",
            text or "",
        )
    )


def news_summary_looks_off_topic(question: str, text: str) -> bool:
    """True when a country/day recap is actually leftover GTC/CUDA memory."""
    if not country_news_place(question):
        return False
    if re.search(r"(?i)\b(cuda|cudnn|rapids|cublas|tensorrt|npp|vera rubin)\b", question):
        return False
    return bool(re.search(r"(?i)\b(cuda|cudnn|rapids|cublas|tensorrt|npp|vera rubin)\b", text or ""))


def news_summary_looks_low_quality(text: str, web_context: str = "", question: str = "") -> bool:
    """Reject nav glue, stale evergreen reframes, filler tropes, and truncation."""
    if question and news_summary_looks_off_topic(question, text):
        return True
    if news_summary_looks_like_refusal(text):
        return True
    if news_summary_looks_like_ai_filler(text):
        return True
    if looks_like_serp_dump(text):
        return True
    if news_summary_looks_ungrounded(text, web_context):
        return True
    low = (text or "").lower()
    stale_framing = (
        r"(?i)\b(?:new initiative|newly launched|debuts|launches)\b.*\bbbc verify\b",
        r"(?i)\bbbc verify\b.*\b(?:new initiative|newly launched|debuts)\b",
    )
    if any(re.search(pattern, text) for pattern in stale_framing):
        return True
    filler_phrases = (
        "heart-shaped",
        "heart shaped",
        "aeroplanes loop",
        "smoke trail",
        "regional developments",
        "infrastructure projects and cultural events",
        "climate change documentary",
    )
    if any(phrase in low for phrase in filler_phrases):
        return True
    if re.search(
        r"(?i)\b(?:scotland|northern ireland)\b.*\b(?:regional developments|cultural events|infrastructure)\b",
        text,
    ):
        return True
    if news_summary_looks_truncated(text):
        return True
    return False


def format_named_source_headlines(question: str, web_context: str) -> str:
    """Return verified headline bullets for a named outlet — no LLM narrative."""
    headlines = headlines_from_web_context(web_context, limit=8)
    if not headlines:
        return ""
    label = news_source_label(question) or "News"
    today = current_brief_date(long_form=True)
    return (
        f"**{label} headlines ({today})**\n\n"
        f"{headlines}\n\n"
        "_Verified links from RSS/search/official video — not an AI-written narrative._"
    )


def news_summary_looks_ungrounded(text: str, web_context: str = "") -> bool:
    """Heuristic: LLM stitched navigation chrome or generic filler into a summary."""
    body = (text or "").strip()
    if not body:
        return True
    if re.search(r"\b(\w+)\s+\1(?:\s+page)?\b", body, re.I):
        return True
    if re.search(r"(?i)\b(?:skip to|homepage|related topics|navigation)\b", body):
        return True
    low = body.lower()
    nav_phrases = (
        "americas page",
        "americas americas",
        "aeroplanes loop",
        "bbc homepage",
    )
    if any(phrase in low for phrase in nav_phrases):
        return True
    if web_context:
        urls = set(re.findall(r"https?://\S+", web_context))
        cited = set(re.findall(r"\((https?://[^)]+)\)", body))
        if cited and urls and not cited.intersection(urls):
            return True
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", body):
        cited_url = normalize_news_url(match.group(1).strip())
        if not cited_url.startswith("https://"):
            return True
        if _BROKEN_NEWS_URL_RE.search(cited_url):
            return True
    return False


def gather_news_web_context(
    question: str,
    *,
    max_results: int = 8,
    scrape_top: int = 3,
) -> str:
    """Gather news context via Bright Data search (+ optional scrape) for AI summaries."""
    try:
        from arka.agent.chat import duckduckgo_search
        from arka.integrations.brightdata_mcp import (
            brightdata_configured,
            brightdata_scrape_urls,
            brightdata_search,
            prefer_brightdata_search,
        )
    except ImportError:
        return gather_headlines_context(question)

    search_q = optimized_news_search_query(question)
    try:
        from arka.integrations.brightdata_retrieval import brightdata_search_parameters
    except ImportError:
        brightdata_search_parameters = None  # type: ignore[assignment,misc]

    results: list[dict] = []
    if prefer_brightdata_search():
        if brightdata_search_parameters is not None:
            params = brightdata_search_parameters(question, optimized_query=search_q)
            results = brightdata_search(
                params["query"],
                max_results=max_results,
                engine=params.get("engine", "google"),
                geo_location=params.get("geo_location", ""),
            )
        else:
            results = brightdata_search(search_q, max_results=max_results)
    if not results:
        results = duckduckgo_search(search_q, max_results=max_results)

    host = news_source_host(question)
    rss_context = fetch_news_rss_context(host, limit=max_results) if host else ""
    if not host:
        place = country_news_place(question)
        for extra_host in _COUNTRY_NEWS_RSS.get(place, ()):
            extra = fetch_news_rss_context(extra_host, limit=max_results)
            if extra:
                rss_context = _merge_news_context_blocks(
                    rss_context, extra, max_blocks=max_results
                )
    if not results:
        finalized = _finalize_news_context(
            question,
            host=host,
            rss_context=rss_context,
            search_ctx="",
            max_results=max_results,
        )
        return finalized

    if host:
        filtered = [
            row for row in results if url_matches_news_host((row.get("link") or ""), host)
        ]
        if filtered:
            results = filtered
        articles = [
            row
            for row in results
            if is_news_article_url((row.get("link") or "").strip(), host=host)
        ]
        if articles:
            results = articles
        # Homepages and section indexes scrape as nav chrome — use snippets only.
        scrape_top = 0

    scrape_urls: list[str] = []
    for row in results:
        link = normalize_news_url((row.get("link") or "").strip(), host=host)
        if not link or link in scrape_urls:
            continue
        if not is_valid_news_url(link, host=host):
            continue
        scrape_urls.append(link)
        if len(scrape_urls) >= scrape_top:
            break

    scraped: dict[str, str] = {}
    if brightdata_configured() and scrape_urls:
        scraped = brightdata_scrape_urls(scrape_urls, max_chars=2500)

    blocks: list[str] = []
    seen: set[str] = set()
    for row in results[:max_results]:
        link = normalize_news_url((row.get("link") or "").strip(), host=host)
        if not link or link in seen:
            continue
        if not is_valid_news_url(link, host=host):
            continue
        title = sanitize_news_title((row.get("title") or link).strip())
        snippet = sanitize_scraped_news_text((row.get("snippet") or "").strip(), max_chars=600)
        if headline_title_looks_like_nav(title):
            continue
        if news_snippet_looks_like_filler(title, snippet):
            continue
        if not is_changelog_exempt_url(link) and headline_looks_stale(
            title, context=snippet, url=link
        ):
            continue
        seen.add(link)
        block = f"Source: {title}\nURL: {link}"
        page = sanitize_scraped_news_text(scraped.get(link, "").strip())
        if page and len(page) >= 80:
            block = f"{block}\n\n{page}"
        elif snippet:
            block = f"{block}\n{snippet}"
        blocks.append(block)

    search_ctx = "\n\n".join(blocks)
    search_ctx = filter_stale_brief_context(search_ctx) if search_ctx else ""
    return _finalize_news_context(
        question,
        host=host,
        rss_context=rss_context,
        search_ctx=search_ctx,
        max_results=max_results,
    )


def news_summary_prompt(question: str, web_context: str) -> tuple[str, str]:
    """System + user prompts for conversational news summaries."""
    source = news_source_label(question)
    place = country_news_place(question)
    today = current_brief_date(long_form=True)
    source_hint = f" Prioritize {source} stories." if source else ""
    if place:
        source_hint = (
            f" This is a {place} day recap. Pick the 4 most important stories for {place}. "
            "Prefer domestic politics, economy, courts, and disasters. "
            "Drop audience polls, 'tell us', newsletters, and extra world briefs "
            "unless they clearly affect that country."
        )
    system = (
        "You are Arka, a helpful assistant. Summarize the latest news in clear, natural prose. "
        "Write like a concise news briefing — not a raw list of URLs. "
        "Cover the 4 most important stories with two sentences each — pick and trim, "
        "do not dump every RSS item. "
        "Use markdown links [headline](url) when citing a source. "
        "CRITICAL: Only state facts from the Search results below. "
        "Source titles are valid evidence — if snippets are missing, brief from the headlines and URLs. "
        "Never refuse. Never say you cannot fulfill the request or that there are no snippets. "
        "Do not infer stories from site navigation, section labels, menu text, or page chrome. "
        "Ignore fragments like duplicated words, 'Americas page', or airshow stunt blurbs "
        "unless a full article snippet clearly describes them as today's lead news. "
        "Never describe old launches (e.g. BBC Verify from 2023) as new initiatives. "
        "Do not write vague regional filler ('infrastructure projects and cultural events'). "
        "Name specific people, places, votes, accidents, or decisions from the sources. "
        "Do not write meta filler such as 'major developments are unfolding', "
        "'stories are being tracked', or 'coverage is available'. "
        "Do not open with 'major national developments' — name the first event. "
        "Do not cite date-index pages, section fronts, or live news videos. "
        "Skip 'wants to know', listener questions, and newsletter roundups. "
        "Finish every sentence; do not trail off with '....'. "
        "Never paste search-result ledes such as '7 days ago — …' or date-stamped blurbs. "
        "Rewrite the facts in your own words as a briefing. "
        "If the results are thin or ambiguous, say so briefly and summarize only what is verified. "
        "Do not mention weather unless the user asked for it. "
        "Do not describe your search process. Start with a one-sentence overview."
    )
    user = (
        f"Today is {today}.{source_hint}\n\n"
        f"User question: {question.strip()}\n\n"
        f"Search results:\n---\n{web_context.strip()}\n---\n\n"
        "Write a helpful news briefing based only on these results. "
        "Pick a few leads and elaborate one beat — do not list every link. "
        "Every story must map to a Source/URL block above. "
        "If a block has only a title and URL, use that headline as the story. "
        "Do not concatenate snippets; synthesize them. "
        "Do not say the results lack text. "
        "Do not sound like an AI recap of 'the news' — report the events."
    )
    return system, user


def summarize_news_web(question: str) -> str:
    """Fetch news context; named outlets get RSS/search headlines, others may use LLM."""
    host = news_source_host(question)
    web_context = ""
    if not host:
        web_context = gather_news_web_context(question)
        try:
            from arka.agent.launch_recap import is_launch_recap_question, summarize_official_launch

            if is_launch_recap_question(question):
                recap = summarize_official_launch(question, web_context=web_context)
                if recap:
                    return recap
        except ImportError:
            pass
        if not (web_context or "").strip():
            return ""
    else:
        web_context = gather_news_web_context(question)
        if not (web_context or "").strip():
            return ""

    if host:
        formatted = format_named_source_headlines(question, web_context)
        if formatted:
            return formatted
        return ""

    place = country_news_place(question)
    if place:
        picked = pick_news_items(web_context, limit=4, place=place)
        if picked:
            web_context = "\n\n".join(
                (
                    f"Source: {row['title']}\nURL: {row['url']}"
                    + (f"\n{row['snippet']}" if row.get("snippet") else "")
                )
                for row in picked
            )
    headlines = headlines_from_web_context(web_context, limit=5 if place else 7, place=place)
    try:
        from arka.llm.fallback import llm_complete
    except ImportError:
        if place:
            return format_country_news_brief(place, web_context) or headlines
        return headlines

    def _news_brief_chain() -> list[tuple[str, str]] | None:
        try:
            from arka.llm.fallback import ordered_model_candidates
            from arka.llm.provider_health import ttft_tier
        except ImportError:
            return None
        ordered = ordered_model_candidates(task="chat", skill="daily_brief")
        if not ordered:
            return None
        fast = [pair for pair in ordered if ttft_tier(pair[1]) == "fast"]
        rest = [pair for pair in ordered if ttft_tier(pair[1]) != "fast"]
        return (fast + rest) if fast else ordered

    def _draft(*, retry: bool = False) -> str:
        system, user = news_summary_prompt(question, web_context)
        if retry:
            user += (
                "\n\nThe previous draft just pasted search snippets. "
                "Write a briefing in your own words. No 'N days ago —' ledes "
                "and no ellipsis-joined blurbs."
            )
        raw = llm_complete(
            system,
            user,
            task="chat",
            skill="daily_brief",
            temperature=0.2,
            chain=_news_brief_chain(),
        )
        return trim_incomplete_summary(raw or "")

    reply = _draft()
    if reply and not news_summary_looks_low_quality(reply, web_context, question):
        return reply
    if not news_summary_looks_like_refusal(reply):
        retry = _draft(retry=True)
        if retry and not news_summary_looks_low_quality(retry, web_context, question):
            return retry
    if place:
        curated = format_country_news_brief(place, web_context)
        if curated:
            return curated
    if headlines:
        lead = (
            f"Here is what news outlets are reporting in {place} today:"
            if place
            else "Here are the latest headlines:"
        )
        return f"{lead}\n\n{headlines}"
    return ""


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
