"""Generate a resume PDF from a public GitHub profile."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from arka.core.ssl_context import urllib_ssl_context
from arka.env import env_get
from arka.paths import generated_data_dir, load_env_file

_USER_AGENT = "ArkaGitHubResume/1.0"
_GITHUB_USER_RE = re.compile(
    r"(?:https?://(?:www\.)?github\.com/|@)([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)",
    re.I,
)
_RESUME_INTENT_RE = re.compile(
    r"(?i)\b("
    r"resume|cv|curriculum\s+vitae|"
    r"generate\s+(?:a\s+)?resume|"
    r"create\s+(?:a\s+)?resume|"
    r"build\s+(?:a\s+)?resume|"
    r"make\s+(?:a\s+)?resume"
    r")\b"
)
_GITHUB_PROFILE_RE = re.compile(
    r"(?i)\b(?:github\s+profile|my\s+github|from\s+github|github\s+resume|github\s+cv)\b"
)


class GitHubResumeError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubProfile:
    login: str
    name: str
    bio: str
    location: str
    company: str
    blog: str
    email: str
    html_url: str
    public_repos: int
    followers: int
    created_at: str


@dataclass(frozen=True)
class ResolvedUsername:
    login: str
    source: str
    requested: str | None = None


@dataclass(frozen=True)
class GitHubRepo:
    name: str
    full_name: str
    description: str
    html_url: str
    language: str
    stargazers_count: int
    forks_count: int
    topics: tuple[str, ...]
    updated_at: str


def _gh_auth_token() -> str | None:
    gh = _gh_binary()
    if not gh:
        return None
    try:
        proc = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return None
        token = (proc.stdout or "").strip()
        return token or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _github_token() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "github_token"):
        value = env_get(key)
        if value:
            return value
    return _gh_auth_token()


def _github_headers() -> dict[str, str]:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(path: str, *, params: dict[str, str] | None = None) -> Any:
    query = ""
    if params:
        query = "?" + "&".join(f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items())
    url = f"https://api.github.com{path}{query}"
    request = urllib.request.Request(url, headers=_github_headers())
    try:
        with urllib.request.urlopen(request, timeout=60, context=urllib_ssl_context()) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            raise GitHubResumeError(f"GitHub user or resource not found: {path}") from exc
        if exc.code == 403 and "rate limit" in detail.lower():
            raise GitHubResumeError(
                "GitHub API rate limit exceeded. Set GITHUB_TOKEN, GH_TOKEN, or github_token in your environment."
            ) from exc
        raise GitHubResumeError(f"GitHub API error ({exc.code}): {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise GitHubResumeError(f"GitHub API request failed: {exc}") from exc
    return json.loads(payload.decode("utf-8"))


def _authenticated_github_login() -> str | None:
    if not _github_token():
        return None
    try:
        row = _github_get("/user")
    except GitHubResumeError:
        return None
    if not isinstance(row, dict):
        return None
    login = str(row.get("login") or "").strip()
    return login or None


def _parse_explicit_username(value: str) -> str:
    raw = value.strip()
    match = _GITHUB_USER_RE.search(raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", raw):
        return raw
    raise GitHubResumeError(f"could not parse GitHub username from: {value!r}")


def resolve_username_detailed(value: str | None = None) -> ResolvedUsername:
    load_env_file()
    raw = (value or "").strip()
    if raw:
        login = _parse_explicit_username(raw)
        return ResolvedUsername(login=login, source="explicit", requested=raw)

    for env_key in ("GITHUB_USERNAME", "GITHUB_USER"):
        env_value = env_get(env_key)
        if env_value:
            login = _parse_explicit_username(env_value)
            return ResolvedUsername(login=login, source="env", requested=env_value)

    api_user = _authenticated_github_login()
    if api_user:
        return ResolvedUsername(login=api_user, source="token")

    gh_user = _gh_current_user()
    if gh_user:
        return ResolvedUsername(login=gh_user, source="gh_cli")

    if _github_token():
        raise GitHubResumeError(
            "GitHub token is set but could not resolve the authenticated user. "
            "Check that the token is valid and has read:user scope."
        )

    raise GitHubResumeError(
        "GitHub username required. Pass --user, set GITHUB_USERNAME, set GITHUB_TOKEN/GH_TOKEN, "
        "or authenticate with gh auth login."
    )


def resolve_username(value: str | None = None) -> str:
    return resolve_username_detailed(value).login


def resolve_display_name(profile: GitHubProfile) -> str:
    """Real name for resume heading; env overrides GitHub profile name."""
    load_env_file()
    for key in ("RESUME_NAME", "USER_FULL_NAME", "FULL_NAME"):
        value = env_get(key)
        if value and value.strip():
            return value.strip()
    return profile.name.strip() or profile.login


def _gh_binary() -> str | None:
    from shutil import which

    found = which("gh")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/bin/gh",
        "/usr/local/bin/gh",
        os.path.expanduser("~/.local/bin/gh"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _gh_current_user() -> str | None:
    gh = _gh_binary()
    if not gh:
        return None
    env = os.environ.copy()
    token = _github_token()
    if token:
        env["GH_TOKEN"] = token
        env.setdefault("GITHUB_TOKEN", token)
    try:
        proc = subprocess.run(
            [gh, "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if proc.returncode != 0:
            return None
        login = (proc.stdout or "").strip()
        return login or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def member_since_year(created_at: str) -> str | None:
    if not created_at or len(created_at) < 4:
        return None
    year = created_at[:4]
    return year if year.isdigit() else None


def auth_mismatch_note(profile_login: str, authenticated_as: str | None) -> str | None:
    if not authenticated_as:
        return None
    if authenticated_as.lower() == profile_login.lower():
        return None
    return (
        f"GitHub token is authenticated as {authenticated_as}; "
        f"profile stats are for {profile_login}."
    )


def profile_stats_lines(
    profile: GitHubProfile,
    *,
    member_prefix: str = "GitHub member since",
    project_count: int | None = None,
) -> list[str]:
    stats: list[str] = []
    count = project_count if project_count is not None else profile.public_repos
    if count:
        label = "project" if count == 1 else "projects"
        stats.append(f"{count} public {label}")
    if profile.followers:
        stats.append(f"{profile.followers} followers")
    year = member_since_year(profile.created_at)
    if year:
        stats.append(f"{member_prefix} {year}")
    return stats


def count_public_repos(username: str, *, max_pages: int = 10) -> int:
    """Count public repos owned by username (includes forks, matching GitHub public_repos)."""
    total = 0
    for page in range(1, max_pages + 1):
        rows = _github_get(
            f"/users/{username}/repos",
            params={
                "type": "owner",
                "per_page": "100",
                "page": str(page),
                "sort": "updated",
                "direction": "desc",
            },
        )
        if not isinstance(rows, list) or not rows:
            break
        total += sum(1 for row in rows if isinstance(row, dict))
        if len(rows) < 100:
            break
    return total


def fetch_profile(username: str, *, expected_login: str | None = None) -> GitHubProfile:
    row = _github_get(f"/users/{username}")
    if not isinstance(row, dict):
        raise GitHubResumeError("unexpected GitHub profile response")
    login = str(row.get("login") or username)
    if expected_login and login.lower() != expected_login.lower():
        raise GitHubResumeError(
            f"GitHub profile login mismatch: requested {expected_login!r}, got {login!r}"
        )
    return GitHubProfile(
        login=login,
        name=str(row.get("name") or row.get("login") or username),
        bio=str(row.get("bio") or "").strip(),
        location=str(row.get("location") or "").strip(),
        company=str(row.get("company") or "").strip(),
        blog=str(row.get("blog") or "").strip(),
        email=str(row.get("email") or "").strip(),
        html_url=str(row.get("html_url") or f"https://github.com/{username}"),
        public_repos=int(row.get("public_repos") or 0),
        followers=int(row.get("followers") or 0),
        created_at=str(row.get("created_at") or ""),
    )


def _repo_from_row(row: dict[str, Any]) -> GitHubRepo | None:
    if row.get("fork"):
        return None
    topics = tuple(str(item) for item in (row.get("topics") or [])[:6])
    return GitHubRepo(
        name=str(row.get("name") or ""),
        full_name=str(row.get("full_name") or ""),
        description=str(row.get("description") or "").strip(),
        html_url=str(row.get("html_url") or ""),
        language=str(row.get("language") or "").strip(),
        stargazers_count=int(row.get("stargazers_count") or 0),
        forks_count=int(row.get("forks_count") or 0),
        topics=topics,
        updated_at=str(row.get("updated_at") or ""),
    )


def fetch_non_fork_repos(
    username: str,
    *,
    limit: int | None = None,
    max_pages: int = 10,
) -> list[GitHubRepo]:
    repos: list[GitHubRepo] = []
    for page in range(1, max_pages + 1):
        rows = _github_get(
            f"/users/{username}/repos",
            params={
                "type": "owner",
                "per_page": "100",
                "page": str(page),
                "sort": "stars",
                "direction": "desc",
            },
        )
        if not isinstance(rows, list):
            raise GitHubResumeError("unexpected GitHub repos response")
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            repo = _repo_from_row(row)
            if repo is not None:
                repos.append(repo)
        if len(rows) < 100:
            break
    repos.sort(key=lambda repo: (-repo.stargazers_count, repo.name.lower()))
    if limit is not None:
        return repos[:limit]
    return repos


def fetch_top_repos(username: str, *, limit: int = 8) -> list[GitHubRepo]:
    return fetch_non_fork_repos(username, limit=limit)


def language_breakdown(repos: list[GitHubRepo]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for repo in repos:
        if repo.language:
            counts[repo.language] += max(1, repo.stargazers_count)
    return counts.most_common(12)


def _strip_markdown(text: str) -> str:
    clean = text.replace("\r\n", "\n")
    clean = re.sub(r"<!--.*?-->", "", clean, flags=re.S)
    clean = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"^#{1,6}\s+", "", clean, flags=re.M)
    clean = re.sub(r"[*_`~]", "", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def _first_paragraph(text: str, *, limit: int = 400) -> str:
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        paragraph = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if paragraph:
            paragraphs.append(paragraph)
    if not paragraphs:
        return text.strip()[:limit]
    chosen = paragraphs[0]
    if len(chosen) < 40 and len(paragraphs) > 1:
        chosen = paragraphs[1]
    if len(chosen) <= limit:
        return chosen
    trimmed = chosen[: limit - 1].rsplit(" ", 1)[0]
    return trimmed + "…"


def fetch_profile_readme(username: str) -> str:
    try:
        row = _github_get(f"/repos/{username}/{username}/readme")
    except GitHubResumeError:
        return ""
    if not isinstance(row, dict):
        return ""
    encoding = str(row.get("encoding") or "").lower()
    raw_content = row.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return ""
    payload = raw_content.encode("utf-8")
    if encoding == "base64":
        try:
            decoded = base64.b64decode(payload).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return ""
    else:
        decoded = raw_content
    return _first_paragraph(_strip_markdown(decoded))


def synthesize_about_me(
    profile: GitHubProfile,
    repos: list[GitHubRepo],
    *,
    project_count: int | None = None,
    display_name: str | None = None,
) -> str:
    parts: list[str] = []

    if profile.company:
        company = profile.company.removeprefix("@").strip()
        parts.append(f"I'm a developer at {company}.")
    else:
        parts.append("I'm a developer on GitHub.")

    count = project_count if project_count is not None else len(repos)
    if count:
        label = "project" if count == 1 else "projects"
        parts.append(f"I maintain {count} public {label}.")

    languages = [lang for lang, _ in language_breakdown(repos)[:4] if lang]
    if languages:
        if len(languages) == 1:
            parts.append(f"My primary language is {languages[0]}.")
        else:
            parts.append(f"My primary languages include {', '.join(languages)}.")

    if profile.location:
        parts.append(f"I'm based in {profile.location}.")

    return " ".join(parts)


def resolve_about_me(
    profile: GitHubProfile,
    repos: list[GitHubRepo],
    *,
    profile_readme: str | None = None,
    project_count: int | None = None,
    display_name: str | None = None,
) -> tuple[str, str]:
    if profile.bio:
        return profile.bio, "bio"
    readme = profile_readme if profile_readme is not None else fetch_profile_readme(profile.login)
    if readme:
        return readme, "profile_readme"
    return (
        synthesize_about_me(
            profile,
            repos,
            project_count=project_count,
            display_name=display_name,
        ),
        "synthesized",
    )


def default_output_path(username: str, *, suffix: str = "pdf") -> Path:
    stamp = date.today().isoformat()
    out_dir = generated_data_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"github-resume-{username}-{stamp}.{suffix}"


def build_markdown(
    profile: GitHubProfile,
    repos: list[GitHubRepo],
    *,
    about_me: str | None = None,
    authenticated_as: str | None = None,
    project_count: int | None = None,
    display_name: str | None = None,
) -> str:
    heading = display_name or resolve_display_name(profile)
    if about_me is None:
        about_me, _ = resolve_about_me(
            profile,
            repos,
            project_count=project_count,
            display_name=heading,
        )
    lines = [
        f"# {heading}",
        "",
        f"GitHub: [{profile.login}]({profile.html_url})",
    ]
    contact_bits = [bit for bit in (profile.location, profile.company, profile.email, profile.blog) if bit]
    if contact_bits:
        lines.append(" | ".join(contact_bits))
    lines.append("")
    lines.extend(["## About Me", "", about_me, ""])

    languages = language_breakdown(repos)
    if languages:
        lines.extend(["## Languages", ""])
        lines.append(", ".join(f"{name} ({count})" for name, count in languages))
        lines.append("")

    if repos:
        lines.extend(["## Projects", ""])
        for repo in repos:
            meta = []
            if repo.language:
                meta.append(repo.language)
            if repo.stargazers_count:
                meta.append(f"{repo.stargazers_count} stars")
            header = f"### {repo.name}"
            if meta:
                header += f" ({', '.join(meta)})"
            lines.append(header)
            if repo.description:
                lines.append(repo.description)
            lines.append(repo.html_url)
            if repo.topics:
                lines.append(f"Topics: {', '.join(repo.topics)}")
            lines.append("")

    stats = profile_stats_lines(profile, project_count=project_count)
    auth_note = auth_mismatch_note(profile.login, authenticated_as)
    if stats or auth_note:
        lines.extend(["## GitHub Stats", ""])
        if stats:
            lines.append(" · ".join(stats))
        if auth_note:
            lines.append(auth_note)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _escape_pdf_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_pdf(
    profile: GitHubProfile,
    repos: list[GitHubRepo],
    output: Path,
    *,
    style: str = "modern",
    about_me: str | None = None,
    authenticated_as: str | None = None,
    project_count: int | None = None,
    display_name: str | None = None,
) -> Path:
    try:
        return _render_pdf_reportlab(
            profile,
            repos,
            output,
            style=style,
            about_me=about_me,
            authenticated_as=authenticated_as,
            project_count=project_count,
            display_name=display_name,
        )
    except ImportError as exc:
        raise GitHubResumeError("reportlab is required; pip install reportlab") from exc


def _render_pdf_reportlab(
    profile: GitHubProfile,
    repos: list[GitHubRepo],
    output: Path,
    *,
    style: str,
    about_me: str | None = None,
    authenticated_as: str | None = None,
    project_count: int | None = None,
    display_name: str | None = None,
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    modern = style.lower() != "classic"
    accent = colors.HexColor("#2563eb") if modern else colors.HexColor("#111827")
    muted = colors.HexColor("#6b7280")

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ResumeTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=accent,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ResumeSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=muted,
        spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "ResumeSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=accent,
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ResumeBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        spaceAfter=4,
    )
    project_title_style = ParagraphStyle(
        "ResumeProjectTitle",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#111827"),
    )
    link_style = ParagraphStyle(
        "ResumeLink",
        parent=body_style,
        fontSize=9,
        textColor=accent,
    )

    heading = display_name or resolve_display_name(profile)
    story: list[Any] = [
        Paragraph(_escape_pdf_text(heading), title_style),
        Paragraph(_escape_pdf_text(profile.html_url), subtitle_style),
    ]

    contact_bits = [bit for bit in (profile.location, profile.company, profile.email, profile.blog) if bit]
    if contact_bits:
        story.append(Paragraph(_escape_pdf_text(" · ".join(contact_bits)), subtitle_style))

    stats = profile_stats_lines(profile, member_prefix="member since", project_count=project_count)
    if stats:
        story.append(Paragraph(_escape_pdf_text(" · ".join(stats)), subtitle_style))
    auth_note = auth_mismatch_note(profile.login, authenticated_as)
    if auth_note:
        story.append(Paragraph(_escape_pdf_text(auth_note), subtitle_style))

    if about_me is None:
        about_me, _ = resolve_about_me(
            profile,
            repos,
            project_count=project_count,
            display_name=heading,
        )
    story.append(Paragraph("About Me", section_style))
    story.append(Paragraph(_escape_pdf_text(about_me), body_style))

    languages = language_breakdown(repos)
    if languages:
        story.append(Paragraph("Languages", section_style))
        lang_line = ", ".join(name for name, _ in languages[:10])
        story.append(Paragraph(_escape_pdf_text(lang_line), body_style))

    story.append(Paragraph("Projects", section_style))
    if not repos:
        story.append(Paragraph("No public projects found.", body_style))
    for repo in repos:
        meta = []
        if repo.language:
            meta.append(repo.language)
        if repo.stargazers_count:
            meta.append(f"{repo.stargazers_count} stars")
        title = repo.name
        if meta:
            title += f" ({', '.join(meta)})"
        story.append(Paragraph(_escape_pdf_text(title), project_title_style))
        if repo.description:
            story.append(Paragraph(_escape_pdf_text(repo.description), body_style))
        story.append(Paragraph(_escape_pdf_text(repo.html_url), link_style))
        if repo.topics:
            story.append(
                Paragraph(_escape_pdf_text("Topics: " + ", ".join(repo.topics)), subtitle_style)
            )
        story.append(Spacer(1, 4))

    doc.build(story)
    return output


def generate_resume(
    username: str | None = None,
    *,
    output: Path | None = None,
    style: str = "modern",
    write_markdown: bool = False,
    repo_limit: int | None = None,
) -> dict[str, Any]:
    load_env_file()
    resolved = resolve_username_detailed(username)
    user = resolved.login
    authenticated_as = _authenticated_github_login()
    expected_login = user if resolved.source in {"explicit", "env"} else None
    profile = fetch_profile(user, expected_login=expected_login)
    user = profile.login
    all_repos = fetch_non_fork_repos(user)
    project_count = len(all_repos)
    repos = all_repos if repo_limit is None else all_repos[:repo_limit]
    display_name = resolve_display_name(profile)
    about_me, about_me_source = resolve_about_me(
        profile,
        repos,
        project_count=project_count,
        display_name=display_name,
    )
    pdf_path = output or default_output_path(user)
    pdf_path = pdf_path.expanduser().resolve()
    if pdf_path.suffix.lower() != ".pdf":
        pdf_path = pdf_path.with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(
        profile,
        repos,
        pdf_path,
        style=style,
        about_me=about_me,
        authenticated_as=authenticated_as,
        project_count=project_count,
        display_name=display_name,
    )

    result: dict[str, Any] = {
        "ok": True,
        "username": user,
        "name": display_name,
        "github_name": profile.name,
        "pdf_path": str(pdf_path),
        "repo_count": len(repos),
        "public_repos": project_count,
        "member_since": member_since_year(profile.created_at),
        "about_me": about_me,
        "about_me_source": about_me_source,
        "style": style,
        "username_source": resolved.source,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if authenticated_as:
        result["authenticated_as"] = authenticated_as
    auth_note = auth_mismatch_note(user, authenticated_as)
    if auth_note:
        result["auth_note"] = auth_note
    if profile.public_repos and profile.public_repos != project_count:
        result["public_repos_profile"] = profile.public_repos
    if write_markdown:
        md_path = pdf_path.with_suffix(".md")
        md_path.write_text(
            build_markdown(
                profile,
                repos,
                about_me=about_me,
                authenticated_as=authenticated_as,
                project_count=project_count,
                display_name=display_name,
            ),
            encoding="utf-8",
        )
        result["markdown_path"] = str(md_path)
    return result


def wants_github_resume(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.search(r"(?i)\bgithub\s+resume\b", clean):
        return True
    if _GITHUB_PROFILE_RE.search(clean) and _RESUME_INTENT_RE.search(clean):
        return True
    if _RESUME_INTENT_RE.search(clean) and re.search(r"(?i)\bgithub\b", clean):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_github_resume(text):
        return ""
    clean = " ".join((text or "").split()).strip()
    match = _GITHUB_USER_RE.search(clean)
    if match:
        return f"github resume --user {match.group(1)}"
    user_match = re.search(
        r"(?i)\b(?:user|username|for)\s+([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)",
        clean,
    )
    if user_match:
        return f"github resume --user {user_match.group(1)}"
    return "github resume"


def resume_payload(username: str | None = None, **kwargs: Any) -> dict[str, Any]:
    try:
        return generate_resume(username, **kwargs)
    except GitHubResumeError as exc:
        return {"ok": False, "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    raw_argv = list(argv or [])
    known_cmds = {"route", "generate"}
    if raw_argv and raw_argv[0] not in known_cmds:
        raw_argv = ["generate", *raw_argv]

    parser = argparse.ArgumentParser(prog="arka github resume")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to github resume command")
    p_route.add_argument("text", nargs="+")

    p_gen = sub.add_parser("generate", help="Generate resume PDF from GitHub profile")
    p_gen.add_argument("--user", "-u", help="GitHub username (default: env or gh auth)")
    p_gen.add_argument("--output", "-o", help="Output PDF path")
    p_gen.add_argument("--style", choices=("modern", "classic"), default="modern")
    p_gen.add_argument("--markdown", action="store_true", help="Also write markdown")
    p_gen.add_argument(
        "--repos",
        type=int,
        default=0,
        help="Max non-fork projects to include (0 = all)",
    )
    p_gen.add_argument("--json", action="store_true")

    args = parser.parse_args(raw_argv or ["generate"])
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1

    cmd = args.cmd or "generate"
    if cmd == "generate":
        try:
            output = Path(args.output).expanduser() if getattr(args, "output", None) else None
            result = generate_resume(
                getattr(args, "user", None),
                output=output,
                style=getattr(args, "style", "modern"),
                write_markdown=getattr(args, "markdown", False),
                repo_limit=(
                    None
                    if int(getattr(args, "repos", 0)) <= 0
                    else max(1, min(int(getattr(args, "repos", 0)), 50))
                ),
            )
        except GitHubResumeError as exc:
            print(f"github resume error: {exc}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
        else:
            print(f"Resume saved: {result['pdf_path']}")
            print(f"GitHub user: {result['username']} ({result['name']})")
            if result.get("public_repos") is not None:
                count = int(result["public_repos"])
                label = "project" if count == 1 else "projects"
                stats_bits = [f"{count} public {label}"]
                if result.get("member_since"):
                    stats_bits.append(f"member since {result['member_since']}")
                print(" · ".join(stats_bits))
            if result.get("auth_note"):
                print(result["auth_note"])
            print(f"Projects included: {result['repo_count']}")
            if result.get("markdown_path"):
                print(f"Markdown: {result['markdown_path']}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
