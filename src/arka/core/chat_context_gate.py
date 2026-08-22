"""Decide whether past chat turns are needed before answering the latest message."""

from __future__ import annotations

import os
import re

_SHORT_FOLLOWUP = re.compile(
    r"^(?:[a-e]|yes|no|y|n|ok|okay|\d{1,3}|option\s+[a-e])\.?$",
    re.I,
)
_NEEDS_PAST_CHAT = re.compile(
    r"(?i)\b("
    r"previous|earlier|above|continue|go on|"
    r"tell more|say more|keep going|go deeper|elaborate|expand|"
    r"same (one|thing|question)|"
    r"what about|how about|"
    r"the (first|second|third|last) (one|option|answer)|"
    r"explain (that|this|it)|tell me more|more detail|"
    r"support (this|that|it)|for (this|that|it)|about (this|that|it)|"
    r"(this|that) (process|topic|approach|concept|idea|method|plan|strategy|setup|workflow)"
    r")\b"
)
_CONTINUE_FOLLOWUP = re.compile(
    r"(?i)^(?:"
    r"tell more|tell me more|say more|more please|keep going|go on|continue|"
    r"next(?: subtopic| topic| part| section)?|what else|expand|elaborate|go deeper|"
    r"and then|more on this|more details?"
    r")\.?$"
)
_LIST_ITEM_FOLLOWUP = re.compile(
    r"(?i)(?:"
    r"(?:detail|expand|elaborate(?: on)?|explain|more on|tell me more about)\s+"
    r"(?:point|item|option|#|no\.?)\s*\d+|"
    r"(?:point|item|option|#|no\.?)\s*\d+|"
    r"number\s+\d+"
    r")"
)
_FORMAT_REFINEMENT = re.compile(
    r"(?i)\b("
    r"in bullet points|as bullet points|in bullets|as bullets|"
    r"as a (?:numbered )?list|in a list|bullet point format|"
    r"make it (?:shorter|longer|simpler)|summarize (?:this|it)"
    r")\b"
)
_SHORT_REF = re.compile(r"(?i)\b(that|this|those|these|it)\b")
# "this/these/those" in a thread usually refer to the prior turn; bare "that/it" need tighter rules.
_DEICTIC_THIS = re.compile(r"(?i)\b(this|these|those)\b")
_CONTEXTUAL_REF = re.compile(
    r"(?i)\b("
    r"that (process|topic|approach|one|idea|plan|method|concept|feature|issue|strategy|setup|workflow)|"
    r"(support|implement|apply|use|adopt|enable|achieve|explain|describe|expand on|elaborate on)"
    r"\s+(this|that|it)|"
    r"(for|about|regarding|on)\s+(this|that|it)|"
    r"what about (this|that|it)|how about (this|that|it)|"
    r"(do|build|ship|fix|try)\s+it"
    r")\b"
)
_BUILD_PREFIXES = frozenset(
    {"ok", "okay", "yes", "yep", "yeah", "sure", "please", "just", "now", "then", "go", "let's", "lets"}
)
_BUILD_OBJECTS = frozenset({"it", "this", "that", "one", "them"})
_BUILD_VERBS = frozenset({"build", "make", "create", "implement", "scaffold", "code", "write", "ship"})
_BUILD_EXACT = frozenset(
    {
        "go ahead",
        "do it",
        "ship it",
        "start building",
        "let's build",
        "lets build",
        "build now",
        "build it",
        "implement it",
        "scaffold it",
        "code it",
        "write it",
    }
)
_CONTINUE_INSTRUCTIONS = (
    "The user wants the NEXT part of the same subject — a new subtopic, phase, or section. "
    "Use prior chat to know the topic. Do NOT ask what to elaborate on. "
    "Do NOT repeat sections already covered; add the next logical subtopic with concrete detail."
)
_BUILD_FOLLOWUP_INSTRUCTIONS = (
    "The user approved a prior plan and wants implementation now — not another roadmap. "
    "Using the earlier topic from past chat, output working starter code: file paths, "
    "copy-pasteable snippets (HTML/CSS/JS or the stack already discussed), and minimal "
    "setup commands. Prefer concrete code blocks over prose. Only ask clarifying "
    "questions if a blocker is truly missing."
)
_LIST_ITEM_INSTRUCTIONS = (
    "The user is asking for more detail on a numbered item from the assistant's last "
    "list. Expand only the referenced item with practical steps and examples. "
    "Do not ask what the point refers to — use the prior assistant list."
)
_FORMAT_INSTRUCTIONS = (
    "The user wants the previous assistant answer reformatted or refined "
    "(e.g. bullet points, shorter). Re-answer using the same substance — "
    "do not ask them to pick a numbered item or repeat the question back."
)
_ANSWER_TO_QUESTION_INSTRUCTIONS = (
    "The latest user message is a direct answer to the assistant's last question. "
    "Treat it as their choice or reply in context — do not reinterpret it as a new "
    "standalone topic. Continue the task the assistant was doing before asking "
    "(act on their choice; do not reset with a generic greeting)."
)
_CODING_GAME_ANSWER_INSTRUCTIONS = (
    "The user picked a concrete build target (game, app, or code task). "
    "Continue the implementation task from the assistant's last question — output "
    "working starter code with file paths, copy-pasteable snippets, and minimal "
    "run instructions. Do NOT switch to an unrelated topic such as language lessons."
)
_ASSISTANT_LANGUAGE_QUESTION = re.compile(
    r"(?i)(?:"
    r"\b(?:which|what)\s+language\b|"
    r"\blanguage\s+(?:are you|would you like|do you want|interested)\b|"
    r"\b(?:learn|teach|study)\s+(?:a\s+)?(?:new\s+)?language\b|"
    r"\binterested in learning\b[^.?!]{0,40}\blanguage\b"
    r")"
)
_ASSISTANT_CODING_GAME_QUESTION = re.compile(
    r"(?i)(?:"
    r"\b(?:what kind of|which)\s+(?:game|project|app|program|script)\b|"
    r"\b(?:would you like to create|want to (?:build|make|create))\b|"
    r"\bfor example\b[^.?!]{0,120}\b(?:game|tic[- ]?tac[- ]?toe|adventure|guessing)\b"
    r")"
)
_CODING_OR_GAME_TASK = re.compile(
    r"(?i)(?:"
    r"\b(?:python|javascript|typescript|html|css|py)\b[^.\n]{0,80}\b(?:game|code|app|project)\b|"
    r"\b(?:write|build|create|implement|scaffold)\b[^.\n]{0,80}\b(?:python|code|game|app)\b|"
    r"\bwrite\s+(?:python\s+)?code\b|"
    r"\b(?:python|py)\s+(?:game|code)\b"
    r")"
)
_GAME_NAME_ANSWER = re.compile(
    r"(?i)^(?:"
    r"tic[- ]?tac[- ]?toe|snake|pong|chess|checkers|hangman|wordle|"
    r"sudoku|minesweeper|breakout|flappy|mario|tetris|"
    r"text[- ]based adventure|guessing game|adventure game"
    r")(?:\s+game)?\.?$"
)
_LANGUAGE_LEARN_RE = re.compile(
    r"(?i)\b(?:learn|teach|study|practice)\b[^.\n]{0,80}\b(?:language|lang)\b|"
    r"\b(?:language|lang)\b[^.\n]{0,80}\b(?:learn|teach|study|practice)\b|"
    r"\bwhich language\b|"
    r"\b(?:learn|teach(?:\s+me)?|study|practice)\s+(?:me\s+)?(?:survival|basic|conversational|beginner)\b|"
    r"\b(?:survival|basic|conversational|beginner)\s+(?:phrases?|words?|language)\b"
)
_LANGUAGE_ALIASES = {
    "japan": "japanese",
    "korea": "korean",
    "china": "chinese",
    "mandarin": "chinese",
    "espanol": "spanish",
    "español": "spanish",
    "deutsch": "german",
    "francais": "french",
    "français": "french",
}
_LANGUAGE_LESSON_INSTRUCTIONS = (
    "The user asked to learn a specific language. Teach ONLY that language in the latest "
    "user message — never switch to another language from earlier chat unless the user "
    "explicitly named the new language in the latest message. "
    "Start or continue the lesson: script/alphabet when relevant, pronunciation, "
    "greetings, and 5–10 practical survival phrases with transliteration where helpful."
)
_NEW_QUESTION_START = re.compile(
    r"(?i)^(?:"
    r"what|how|why|when|where|who|which|can you|could you|would you|"
    r"please|tell me|explain|describe|show me|help me|give me|list|"
    r"teach me|teach us|help me learn|help me study|learn|study|practice|"
    r"is there|are there|do you|does|did|will|should|can i|could i"
    r")\b"
)
_ASSISTANT_QUESTION = re.compile(
    r"(?i)(?:"
    r"\?\s*$|"
    r"\b(?:which|what|where|when|who|how)\b[^.!?]{0,120}\?|"
    r"\b(?:would you like|do you want|pick one|choose (?:one|from)|"
    r"can you tell me|could you tell me|shall we|should we|ready to)\b"
    r")"
)
_DAILY_BRIEF = re.compile(
    r"(?i)\b("
    r"(?:daily|morning|news)\s+brief|"
    r"today['']?s\s+(?:tech\s+)?brief|"
    r"tech\s+brief|"
    r"(?:give\s+(?:me\s+)?)?(?:today['']?s|todays|latest)\s+news|"
    r"(?:give\s+(?:me\s+)?)?news\s+today|"
    r"give\s+(?:me\s+)?(?:the\s+)?news"
    r")\b"
)

_MAX_HISTORY_TURNS = 8
_MAX_MSG_CHARS = 1500
_MAX_HISTORY_CHARS = 8000
_MAX_GATE_TURNS = 6
_MAX_GATE_CHARS = 3500


def _mode() -> str:
    raw = os.environ.get("CHAT_CONTEXT_GATE", "heuristic").strip().lower()
    if raw in {"heuristic", "regex", "fast", "ngram"}:
        return "heuristic"
    if raw in {"0", "off", "false", "never", "no"}:
        return "off"
    if raw in {"llm", "model"}:
        return "llm"
    return "heuristic"


def _language_names() -> tuple[str, ...]:
    try:
        from arka.agent.survival_lang import LANG_CODES

        return tuple(LANG_CODES.keys())
    except ImportError:
        return (
            "hindi", "spanish", "french", "german", "japanese", "korean", "chinese",
            "arabic", "portuguese", "italian", "russian", "tamil", "telugu", "bengali",
        )


def named_language(text: str) -> str | None:
    """Return canonical language name mentioned in text, if any."""
    t = " ".join((text or "").strip().split()).lower()
    if not t:
        return None
    for alias, canonical in _LANGUAGE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return canonical
    for name in sorted(_language_names(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return name
    return None


def is_language_learning_request(text: str) -> bool:
    """True when the user explicitly asks to learn/teach a named language."""
    t = " ".join((text or "").strip().split())
    if not t:
        return False
    lang = named_language(t)
    if not lang:
        return False
    if _LANGUAGE_LEARN_RE.search(t):
        return True
    if re.search(
        r"(?i)\b(?:learn|teach|study|practice|survival|lesson|lessons|phrases?|alphabet|pronunciation)\b",
        t,
    ):
        return True
    return False


_SURVIVAL_RE = re.compile(r"(?i)\bsurvival\b")


def is_survival_language_request(text: str) -> bool:
    """True when the user asks for survival phrases in a named language."""
    t = " ".join((text or "").strip().split())
    if not t or not _SURVIVAL_RE.search(t):
        return False
    return named_language(t) is not None


def survival_language_target(text: str) -> str | None:
    """Canonical language name for a survival phrase request."""
    t = " ".join((text or "").strip().split())
    if not t or not _SURVIVAL_RE.search(t):
        return None
    return named_language(t)


def _language_lesson_instructions(text: str) -> str:
    lang = named_language(text)
    label = (lang or "the requested language").replace("_", " ").title()
    return f"{_LANGUAGE_LESSON_INSTRUCTIONS}\nTarget language: {label}."


def is_coding_or_game_task(text: str) -> bool:
    """True when the user is asking for code, a game, or naming a game to build."""
    t = " ".join((text or "").strip().split())
    if not t:
        return False
    if _GAME_NAME_ANSWER.match(t):
        return True
    return bool(_CODING_OR_GAME_TASK.search(t))


def assistant_asked_language_choice(text: str) -> bool:
    """True when the assistant's last turn asked the user to pick a language."""
    t = " ".join((text or "").strip().split())
    if not t or not assistant_asked_question(t):
        return False
    return bool(_ASSISTANT_LANGUAGE_QUESTION.search(t))


def assistant_asked_coding_or_game_choice(text: str) -> bool:
    """True when the assistant asked what game/app/code to build."""
    t = " ".join((text or "").strip().split())
    if not t or not assistant_asked_question(t):
        return False
    return bool(_ASSISTANT_CODING_GAME_QUESTION.search(t))


def _recent_exchange_rows(rows: list[tuple[str, str]], *, max_pairs: int = 4) -> list[tuple[str, str]]:
    """Last N user/assistant pairs — keeps follow-ups tied to the immediate task."""
    if not rows:
        return []
    limit = max(2, max_pairs * 2)
    return rows[-limit:]


def _answer_to_question_instructions(rows: list[tuple[str, str]], last_user: str = "") -> str:
    """Tailor follow-up instructions when the user answers the assistant's question."""
    last_assistant = _last_assistant_before_user(rows) if rows and rows[-1][0] == "user" else ""
    if assistant_asked_coding_or_game_choice(last_assistant) or is_coding_or_game_task(last_user):
        return _CODING_GAME_ANSWER_INSTRUCTIONS
    if assistant_asked_language_choice(last_assistant):
        lang = named_language(last_user)
        label = (lang or "the chosen language").replace("_", " ").title()
        return (
            f"{_ANSWER_TO_QUESTION_INSTRUCTIONS} "
            f"The user chose {label} — begin the first {label} lesson now "
            "(script/alphabet, pronunciation, basic greetings, 3–5 useful phrases). "
            f"Do NOT teach a different language. "
            "Do not reply with only a generic greeting or 'how can I help you' in that language."
        )
    if is_language_learning_request(last_user):
        return _language_lesson_instructions(last_user)
    return _ANSWER_TO_QUESTION_INSTRUCTIONS


def is_short_followup(text: str) -> bool:
    t = " ".join((text or "").strip().split())
    return bool(t) and bool(_SHORT_FOLLOWUP.match(t))


def _last_assistant_before_user(rows: list[tuple[str, str]]) -> str:
    if not rows or rows[-1][0] != "user":
        return ""
    for role, content in reversed(rows[:-1]):
        if role == "assistant":
            return content.strip()
    return ""


def assistant_asked_question(text: str) -> bool:
    """True when the assistant turn ends with or contains a direct question."""
    t = " ".join((text or "").strip().split())
    if not t:
        return False
    if t.endswith("?"):
        return True
    return bool(_ASSISTANT_QUESTION.search(t))


def is_answer_to_assistant_question(text: str, rows: list[tuple[str, str]]) -> bool:
    """Short reply that answers the assistant's immediately preceding question."""
    t = " ".join((text or "").strip().split())
    if not t or not rows:
        return False
    if is_language_learning_request(t):
        return False
    if is_short_followup(t):
        return False
    if is_continue_followup(t) or is_list_item_followup(t) or is_build_followup(t):
        return False
    if t.endswith("?"):
        return False
    if _NEW_QUESTION_START.match(t):
        return False
    last_assistant = _last_assistant_before_user(rows)
    if not assistant_asked_question(last_assistant):
        return False
    words = len(t.split())
    if words <= 4:
        return True
    return words <= 6 and not _looks_standalone(t)


def is_continue_followup(text: str) -> bool:
    """True when the user wants the next slice of the same topic (tell more, next, etc.)."""
    t = " ".join((text or "").strip().split())
    if not t:
        return False
    if _CONTINUE_FOLLOWUP.match(t):
        return True
    try:
        from arka.core.web_topic_memory import CONTINUE_RE

        return bool(CONTINUE_RE.search(t))
    except ImportError:
        return bool(_NEEDS_PAST_CHAT.search(t))


def is_list_item_followup(text: str) -> bool:
    """True when the user wants detail on a numbered point from the last assistant list."""
    t = " ".join((text or "").strip().split())
    return bool(t) and bool(_LIST_ITEM_FOLLOWUP.search(t))


def is_format_refinement(text: str, rows: list[tuple[str, str]] | None = None) -> bool:
    """True when the user wants the prior answer reformatted (e.g. bullet points)."""
    t = " ".join((text or "").strip().split())
    if not t:
        return False
    if _FORMAT_REFINEMENT.search(t) and len(t.split()) <= 12:
        return True
    if not rows:
        return False
    prior_user = ""
    for role, content in reversed(rows[:-1] if len(rows) > 1 else rows):
        if role == "user":
            prior_user = " ".join(content.strip().split()).rstrip(".?!")
            break
    if not prior_user:
        return False
    cur = t.rstrip(".?!")
    if not cur.lower().startswith(prior_user.lower()) or len(cur) <= len(prior_user) + 4:
        return False
    suffix = cur[len(prior_user) :].strip().lstrip(",;:-")
    return bool(suffix) and (_FORMAT_REFINEMENT.search(suffix) or len(suffix.split()) <= 6)


def strip_assistant_meta(text: str) -> str:
    """Remove internal/meta lines that should not be shown to the user."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        low = line.lower()
        if "pick one for me to expand" in low:
            continue
        if re.match(r"(?i)^(?:follow[- ]?up questions?|prompts?):?\s*$", line.strip()):
            continue
        kept.append(line)
    out = "\n".join(kept).strip()
    out = re.sub(r"(?im)^SUBTOPICS:\s*.+$", "", out).strip()
    return out


def is_daily_brief_request(text: str) -> bool:
    return bool(_DAILY_BRIEF.search(text or ""))


def is_build_followup(text: str) -> bool:
    """True when the user is confirming they want code/build output from prior chat."""
    t = " ".join((text or "").strip().split()).lower().rstrip(".")
    if not t:
        return False
    if t in _BUILD_EXACT:
        return True
    words = t.split()
    if len(words) == 2 and words[0] in _BUILD_VERBS and words[1] in _BUILD_OBJECTS:
        return True
    if len(words) == 3 and words[0] in _BUILD_PREFIXES and words[1] in _BUILD_VERBS and words[2] in _BUILD_OBJECTS:
        return True
    if len(words) >= 2 and words[0] == "go" and words[1] == "ahead":
        return True
    return False


def daily_brief_prompt(text: str) -> str:
    t = (text or "").strip()
    if re.search(r"(?i)\btech\b", t):
        head = "daily_brief tech"
    else:
        head = "daily_brief"
    return f"{head} {t}" if t else head


def needs_past_chat_heuristic(text: str, rows: list[tuple[str, str]] | None = None) -> bool:
    """Fast regex gate — obvious follow-ups and explicit references."""
    t = " ".join((text or "").strip().split())
    if not t:
        return False
    if is_daily_brief_request(t):
        return False
    if is_short_followup(t):
        return True
    if rows and is_answer_to_assistant_question(t, rows):
        return True
    if is_continue_followup(t):
        return True
    if is_list_item_followup(t):
        return True
    if _FORMAT_REFINEMENT.search(t) and len(t.split()) <= 12:
        return True
    if is_build_followup(t):
        return True
    if _NEEDS_PAST_CHAT.search(t):
        return True
    if _DEICTIC_THIS.search(t) or _CONTEXTUAL_REF.search(t):
        return True
    return len(t.split()) <= 8 and bool(_SHORT_REF.search(t))


def _compact_rows(rows: list[tuple[str, str]], *, max_turns: int, max_chars: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for role, content in rows[-max_turns:]:
        text = " ".join(content.split())
        if len(text) > _MAX_MSG_CHARS:
            text = text[: _MAX_MSG_CHARS].rstrip() + "…"
        out.append((role, text))
    transcript = "\n".join(f"{role}: {text}" for role, text in out)
    if len(transcript) <= max_chars:
        return out
    trimmed: list[tuple[str, str]] = []
    used = 0
    for role, text in reversed(out):
        line = f"{role}: {text}\n"
        if used + len(line) > max_chars:
            break
        trimmed.insert(0, (role, text))
        used += len(line)
    return trimmed or out[-2:]


def needs_past_chat_llm(last_user: str, rows: list[tuple[str, str]]) -> bool:
    """Ask a cheap model whether prior turns are required."""
    prior = [(role, content) for role, content in rows if role in {"user", "assistant"}]
    if not prior or not any(role == "assistant" for role, _ in prior):
        return False
    compact = _compact_rows(prior, max_turns=_MAX_GATE_TURNS, max_chars=_MAX_GATE_CHARS)
    transcript = "\n".join(
        f"{'User' if role == 'user' else 'Assistant'}: {content}" for role, content in compact
    )
    system = (
        "You decide whether a chat assistant needs prior conversation turns to answer "
        "the latest user message correctly.\n"
        "Reply with exactly one word: YES or NO.\n\n"
        "YES when the latest message is a short follow-up, answer to a quiz/question, "
        "continuation, or cannot be understood without prior turns.\n"
        "NO when the latest message is a standalone new question, command, or topic "
        "even if unrelated chat happened earlier."
    )
    user = f"Prior chat:\n{transcript}\n\nLatest user message:\n{last_user}"
    try:
        from arka.llm.fallback import llm_complete

        raw = llm_complete(
            system,
            user,
            temperature=0.0,
            task="chat",
            skill="context_gate",
        ).strip()
    except Exception:
        return needs_past_chat_heuristic(last_user)
    head = raw.split(None, 1)[0].upper() if raw else ""
    if head.startswith("YES"):
        return True
    if head.startswith("NO"):
        return False
    return needs_past_chat_heuristic(last_user)


def _looks_standalone(text: str) -> bool:
    """Long or clearly self-contained messages that do not need prior chat."""
    t = " ".join((text or "").strip().split())
    if _DEICTIC_THIS.search(t) or _CONTEXTUAL_REF.search(t) or _NEEDS_PAST_CHAT.search(t):
        return False
    words = len(t.split())
    if words >= 10:
        return True
    if words >= 6 and not _SHORT_REF.search(t):
        return True
    return False


def needs_past_chat(last_user: str, rows: list[tuple[str, str]] | None = None) -> bool:
    """True when prior chat should be attached for the latest user message."""
    t = " ".join((last_user or "").strip().split())
    if not t:
        return False
    if is_daily_brief_request(t):
        return False
    if is_short_followup(t):
        return True
    if is_continue_followup(t):
        return True
    if is_list_item_followup(t):
        return True
    if is_build_followup(t):
        return True

    prior = rows or []
    if prior and is_answer_to_assistant_question(t, prior):
        return True
    if prior and is_format_refinement(t, prior):
        return True

    if not prior or not any(role == "assistant" for role, _ in prior):
        return False

    try:
        from arka.core.context_ngrams import query_relates_to_texts

        prior_texts = [content for role, content in prior if role == "assistant"][-4:]
        prior_texts += [content for role, content in prior if role == "user"][-2:]
        if prior_texts and not query_relates_to_texts(t, prior_texts, threshold=1.25):
            if len(t.split()) >= 4 and not is_continue_followup(t):
                if not is_list_item_followup(t) and not is_build_followup(t):
                    return False
    except ImportError:
        pass

    mode = _mode()
    if mode == "off":
        return False
    if mode == "heuristic":
        return needs_past_chat_heuristic(t, prior)
    if needs_past_chat_heuristic(t, prior):
        return True
    if _looks_standalone(t):
        return False
    return needs_past_chat_llm(t, prior)


def rows_from_turns(turns: object) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not isinstance(turns, list):
        return rows
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(turn.get("text") or turn.get("content") or "").strip()
        if not content:
            continue
        rows.append((role, content))
    return rows


def rows_from_openai_messages(messages: object) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not isinstance(messages, list):
        return rows
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = msg.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            content = "\n".join(p for p in parts if p)
        content = str(content or "").strip()
        if not content:
            continue
        if len(content) > _MAX_MSG_CHARS:
            content = content[: _MAX_MSG_CHARS].rstrip() + "…"
        rows.append((role, content))
    return rows


def is_webui_meta_prompt(text: str) -> bool:
    """Open WebUI background tasks (title, tags, follow-ups) — not user chat."""
    low = (text or "").lower()
    return (
        "generate a concise title" in low
        or "### task:" in low
        or ("chat history:" in low and "json format" in low)
    )


def is_webui_title_generation_prompt(text: str) -> bool:
    low = (text or "").lower()
    return "generate a concise title" in low and "chat history" in low


def is_webui_followup_generation_prompt(text: str) -> bool:
    low = (text or "").lower()
    if "follow_ups" in low and "{" in low and "### task:" not in low and "chat history" not in low:
        return True
    if "suggest 3-5 relevant follow-up" in low or "follow_up_generation" in low:
        return True
    return (
        "follow-up" in low
        or "follow up" in low
        or "follow_ups" in low
    ) and ("### task:" in low or "chat history" in low or "suggest" in low)


def is_session_turn_skippable(text: str, *, role: str = "") -> bool:
    """Skip Open WebUI meta tasks and follow-up-only replies in session memory."""
    raw = (text or "").strip()
    if not raw:
        return True
    if is_webui_meta_prompt(raw):
        return True
    if (role or "").lower() == "assistant" and is_followups_only_response(raw):
        return True
    return False


def is_followups_only_json(text: str) -> bool:
    """True when the assistant reply is only Open WebUI follow-up metadata."""
    import json

    raw = (text or "").strip()
    if not raw or "follow_ups" not in raw.lower():
        return False
    obj_start, obj_end = raw.find("{"), raw.rfind("}")
    if obj_start < 0 or obj_end <= obj_start:
        return False
    try:
        obj = json.loads(raw[obj_start : obj_end + 1])
    except json.JSONDecodeError:
        return False
    if not isinstance(obj, dict):
        return False
    ups = obj.get("follow_ups") or obj.get("followups") or obj.get("followUps")
    if not isinstance(ups, list) or not ups:
        return False
    allowed = {"follow_ups", "followups", "followUps"}
    return all(key in allowed for key in obj.keys())


def is_followups_only_prose(text: str) -> bool:
    """True when the assistant reply is only a follow-up question list, not an answer."""
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if "follow-up questions" not in low and "follow up questions" not in low:
        return False
    numbered = len(re.findall(r"(?m)^\s*\d+[.)]\s+", raw))
    return numbered >= 2 and numbered * 40 >= len(raw) * 0.35


def is_followups_only_response(text: str) -> bool:
    return is_followups_only_json(text) or is_followups_only_prose(text)


def normalize_followups_payload(raw: str) -> list[str]:
    """Normalize LLM output to a list of follow-up question strings."""
    import json

    text = (raw or "").strip()
    if not text:
        return []
    obj_start, obj_end = text.find("{"), text.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        try:
            obj = json.loads(text[obj_start : obj_end + 1])
            if isinstance(obj, dict):
                ups = obj.get("follow_ups") or obj.get("followups") or obj.get("followUps")
                if isinstance(ups, list):
                    return [str(x).strip() for x in ups if str(x).strip()][:8]
        except json.JSONDecodeError:
            pass
    arr_start, arr_end = text.find("["), text.rfind("]")
    if arr_start >= 0 and arr_end > arr_start:
        try:
            arr = json.loads(text[arr_start : arr_end + 1])
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()][:8]
        except json.JSONDecodeError:
            pass
    numbered: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*\d+[.)]\s*(.+)$", line.strip())
        if match:
            numbered.append(match.group(1).strip())
    return numbered[:8]


def _fallback_followups_from_meta(text: str) -> list[str]:
    """Generic follow-ups when the model returns unparseable output."""
    exchange = recent_exchange_from_webui_meta(text) or chat_history_from_webui_meta(text)
    quick = heuristic_followups_from_exchange(exchange)
    if quick:
        return quick
    seed = ""
    for line in reversed(exchange.splitlines()):
        stripped = line.strip()
        if stripped.upper().startswith("USER:"):
            seed = stripped.split(":", 1)[1].strip()
            break
    if not seed:
        seed = first_user_line_from_webui_meta(text) or "this topic"
    seed = " ".join(seed.split())[:80].rstrip(".?!")
    return [
        f"Can you explain more about {seed}?",
        f"What are the next steps for {seed}?",
        f"What should I watch out for with {seed}?",
    ]


def chat_history_from_webui_meta(text: str) -> str:
    """Extract the ### Chat History block from an Open WebUI task prompt."""
    raw = text or ""
    low = raw.lower()
    marker = "### chat history:"
    idx = low.find(marker)
    if idx < 0:
        return ""
    section = raw[idx + len(marker) :].strip()
    stop = section.lower().find("\n### ")
    if stop >= 0:
        section = section[:stop]
    return section.strip()


def recent_exchange_from_webui_meta(text: str) -> str:
    """Last user + assistant turn only — ignore older topics in the same thread."""
    history = chat_history_from_webui_meta(text)
    if not history:
        return ""
    user_line = ""
    assistant_line = ""
    for line in reversed(history.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if not assistant_line and upper.startswith("ASSISTANT:"):
            assistant_line = stripped
            continue
        if upper.startswith("USER:"):
            user_line = stripped
            break
    if user_line and assistant_line:
        return f"{user_line}\n{assistant_line}"
    return user_line or history


def heuristic_followups_from_exchange(exchange: str, *, max_items: int = 5) -> list[str]:
    """Fast follow-ups from the latest user question — no LLM, no stale memory."""
    user_q = ""
    for line in (exchange or "").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("USER:"):
            user_q = stripped.split(":", 1)[1].strip()
    if not user_q or len(user_q.split()) < 4:
        return []
    topic = user_q.rstrip(".?!")
    return [
        f"Can you go deeper on: {topic}?",
        f"What are practical first steps for {topic[:70]}?",
        f"What mistakes should I avoid with {topic[:70]}?",
        f"Can you give a simple example related to {topic[:60]}?",
    ][:max_items]


def webui_followup_generation_response(text: str) -> str:
    """Open WebUI follow-up task — disabled; chat should answer, not suggest chips."""
    return ""


def first_user_line_from_webui_meta(text: str) -> str:
    """First USER: line from an Open WebUI task prompt (the opening user message)."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("USER:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def chat_title_from_first_prompt(text: str, *, max_len: int = 48) -> str:
    """Sidebar title from the chat's first user message."""
    first = first_user_line_from_webui_meta(text)
    if not first:
        return ""
    title = " ".join(first.split())
    title = title.rstrip(".?!")
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + "…"
    return title


def webui_title_generation_response(text: str) -> str:
    """JSON body Open WebUI expects for automatic chat renaming."""
    import json

    title = chat_title_from_first_prompt(text)
    if not title:
        return ""
    return json.dumps({"title": title}, ensure_ascii=False)


def build_web_agent_text(
    rows: list[tuple[str, str]],
    *,
    max_history_turns: int = _MAX_HISTORY_TURNS,
    max_history_chars: int = _MAX_HISTORY_CHARS,
) -> str:
    """Build the text sent to /v1/agent, attaching prior chat only when needed."""
    last_user = ""
    for role, content in rows:
        if role == "user":
            last_user = content
    if not last_user:
        return ""
    if is_webui_meta_prompt(last_user):
        return last_user
    if is_daily_brief_request(last_user):
        return daily_brief_prompt(last_user)
    if is_language_learning_request(last_user):
        instructions = _language_lesson_instructions(last_user)
        return f"{instructions}\n\nLatest user message:\n{last_user}"
    if not any(role == "assistant" for role, _ in rows) or not needs_past_chat(last_user, rows):
        return last_user

    try:
        from arka.core.context_ngrams import (
            context_hint_for_query,
            select_relevant_rows,
        )

        use_ngram_pick = not (
            is_short_followup(last_user)
            or is_answer_to_assistant_question(last_user, rows)
            or is_continue_followup(last_user)
            or is_list_item_followup(last_user)
            or is_build_followup(last_user)
            or is_format_refinement(last_user, rows)
            or _DEICTIC_THIS.search(last_user)
            or _CONTEXTUAL_REF.search(last_user)
            or len(last_user.split()) <= 2
        )
        if use_ngram_pick:
            recent = select_relevant_rows(
                last_user,
                rows,
                max_turns=max_history_turns,
                max_chars=max_history_chars,
            )
        elif is_answer_to_assistant_question(last_user, rows):
            last_asst = _last_assistant_before_user(rows)
            pairs = 1 if (
                is_coding_or_game_task(last_user) or assistant_asked_coding_or_game_choice(last_asst)
            ) else 4
            recent = _recent_exchange_rows(rows, max_pairs=pairs)
        else:
            recent = rows[-(max_history_turns * 2) :]
        hint = context_hint_for_query(last_user, rows)
    except ImportError:
        recent = rows[-(max_history_turns * 2) :]
        hint = ""
    transcript = "\n\n".join(
        f"{'User' if role == 'user' else 'Assistant'}: {content}" for role, content in recent
    )
    if hint:
        transcript = f"Context match ({hint}):\n{transcript}"
    if len(transcript) > max_history_chars:
        transcript = transcript[-max_history_chars:]

    if is_short_followup(last_user):
        return (
            "The latest user message is a short answer to the assistant's last question. "
            "Grade it and continue the exercise.\n\n"
            f"{transcript}\n\n"
            f"Latest answer: {last_user}"
        )
    if is_answer_to_assistant_question(last_user, rows):
        return (
            f"{_answer_to_question_instructions(rows, last_user)}\n\n"
            f"{transcript}\n\n"
            f"Latest answer: {last_user}"
        )
    if is_build_followup(last_user):
        return (
            f"{_BUILD_FOLLOWUP_INSTRUCTIONS}\n\n"
            f"{transcript}\n\n"
            f"Latest user message: {last_user}"
        )
    if is_continue_followup(last_user):
        return (
            f"{_CONTINUE_INSTRUCTIONS}\n\n"
            f"{transcript}\n\n"
            f"Latest user message: {last_user}"
        )
    if is_list_item_followup(last_user):
        return (
            f"{_LIST_ITEM_INSTRUCTIONS}\n\n"
            f"{transcript}\n\n"
            f"Latest user message: {last_user}"
        )
    if is_format_refinement(last_user, rows):
        return (
            f"{_FORMAT_INSTRUCTIONS}\n\n"
            f"{transcript}\n\n"
            f"Latest user message: {last_user}"
        )
    return (
        "The latest message refers to earlier turns. Use past chat only to resolve "
        "that reference, then answer the latest message.\n\n"
        f"{transcript}\n\n"
        f"Latest question:\n{last_user}"
    )
