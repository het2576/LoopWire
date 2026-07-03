"""Content extractors for saved links.

All extractors return a plain dict and never raise on ordinary extraction
failure (paywalls, missing captions, etc.) - extraction_success=False
communicates that, per the PRD principle that failures must be visible.

Supported types
---------------
- Articles       — trafilatura
- YouTube        — youtube-transcript-api + oEmbed
- Reddit posts   — Reddit public JSON API (no auth)
- GitHub repos   — raw.githubusercontent.com README fetch
- Hacker News    — HN Algolia API
- PDFs           — pypdf (downloaded via httpx)
"""

import io
import json
import re

import httpx
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

MIN_ARTICLE_WORDS = 200
MIN_PDF_WORDS = 50
MAX_REDDIT_COMMENTS = 10   # top-level comments to include
MAX_HN_COMMENTS = 10       # top comments to include

YOUTUBE_ID_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?v=|youtube\.com/shorts/|youtube\.com/live/)([\w-]{11})"),
    re.compile(r"youtu\.be/([\w-]{11})"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_result(*extra_keys: str) -> dict:
    """Return the standard result skeleton shared by all extractors."""
    base = {
        "title": None,
        "author": None,
        "published_date": None,
        "clean_text": None,
        "extraction_success": False,
        "error": None,
    }
    for k in extra_keys:
        base[k] = None
    return base


# ── YouTube ───────────────────────────────────────────────────────────────────

def extract_youtube_video_id(url: str) -> str | None:
    for pattern in YOUTUBE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def extract_youtube(url: str) -> dict:
    """Extract transcript + metadata for a YouTube video.

    Returns {title, channel, transcript_text, extraction_success, error}.
    """
    result = _base_result("channel", "transcript_text")

    video_id = extract_youtube_video_id(url)
    if not video_id:
        result["error"] = "invalid_url: could not parse a YouTube video id"
        return result

    # Metadata via oEmbed — no API key required.
    try:
        resp = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10,
        )
        if resp.status_code == 200:
            meta = resp.json()
            result["title"] = meta.get("title")
            result["channel"] = meta.get("author_name")
            result["author"] = meta.get("author_name")
    except httpx.HTTPError:
        pass

    try:
        api = YouTubeTranscriptApi()
        try:
            transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        except NoTranscriptFound:
            # No English track specifically - but the video may still have
            # captions in another language (e.g. auto-generated Hindi on a
            # Hinglish-language channel). Fall back to whatever exists rather
            # than reporting "no captions" on a video that actually has them;
            # Gemini can summarize non-English source text just fine and is
            # instructed to always respond in English regardless (summarize.py).
            available = list(api.list(video_id))
            if not available:
                raise
            transcript = available[0].fetch()
    except (TranscriptsDisabled, NoTranscriptFound):
        result["error"] = "no_captions: video has no available transcript in any language"
        return result
    except VideoUnavailable:
        result["error"] = "video_unavailable"
        return result
    except Exception as exc:
        result["error"] = f"transcript_fetch_failed: {exc}"
        return result

    text = " ".join(snippet.text.strip() for snippet in transcript if snippet.text.strip())
    if not text:
        result["error"] = "empty_transcript"
        return result

    result["clean_text"] = text
    result["extraction_success"] = True
    return result


# ── Articles ──────────────────────────────────────────────────────────────────

def extract_article(url: str) -> dict:
    """Extract clean article text via trafilatura.

    Returns {title, author, published_date, clean_text, extraction_success, error}.
    """
    result = _base_result()

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as exc:
        result["error"] = f"fetch_failed: {exc}"
        return result

    if not downloaded:
        result["error"] = "fetch_failed: no content returned (possible paywall/block)"
        return result

    try:
        extracted = trafilatura.extract(
            downloaded, output_format="json", with_metadata=True, favor_precision=True
        )
    except Exception as exc:
        result["error"] = f"parse_failed: {exc}"
        return result

    if not extracted:
        result["error"] = "parse_failed: trafilatura returned no extractable content"
        return result

    data = json.loads(extracted)
    text = (data.get("text") or "").strip()
    word_count = len(text.split())

    result["title"] = data.get("title")
    result["author"] = data.get("author")
    result["published_date"] = data.get("date")
    result["clean_text"] = text or None

    if word_count < MIN_ARTICLE_WORDS:
        result["error"] = (
            f"thin_content: only {word_count} words extracted (min {MIN_ARTICLE_WORDS}), "
            "likely paywalled or JS-rendered"
        )
        return result

    result["extraction_success"] = True
    return result


# ── Reddit ────────────────────────────────────────────────────────────────────

def extract_reddit(url: str) -> dict:
    """Extract a Reddit post body + top comments via the public JSON API.

    No auth needed — works on any public post. Appends .json to the URL.
    Returns {title, author, published_date, clean_text, extraction_success, error}.
    """
    result = _base_result()

    # Normalise URL: strip query params, ensure .json suffix
    clean = url.split("?")[0].rstrip("/")
    if not clean.endswith(".json"):
        clean += ".json"

    try:
        resp = httpx.get(
            clean,
            headers={"User-Agent": "Loopwire/1.0 (content reader)"},
            follow_redirects=True,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        result["error"] = f"fetch_failed: {exc}"
        return result

    if resp.status_code != 200:
        result["error"] = f"fetch_failed: HTTP {resp.status_code}"
        return result

    try:
        data = resp.json()
        post_data = data[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, ValueError) as exc:
        result["error"] = f"parse_failed: unexpected Reddit JSON shape — {exc}"
        return result

    title = post_data.get("title", "")
    body = (post_data.get("selftext") or "").strip()
    author = post_data.get("author")
    created = post_data.get("created_utc")
    subreddit = post_data.get("subreddit_name_prefixed", "")

    # Pull top comments
    comments: list[str] = []
    try:
        comment_listing = data[1]["data"]["children"]
        for child in comment_listing[:MAX_REDDIT_COMMENTS]:
            if child.get("kind") != "t1":
                continue
            cd = child["data"]
            comment_body = (cd.get("body") or "").strip()
            comment_author = cd.get("author", "")
            if comment_body and comment_body != "[deleted]":
                comments.append(f"u/{comment_author}: {comment_body}")
    except (KeyError, IndexError):
        pass  # comments are best-effort

    sections = [f"[{subreddit}] {title}"]
    if body:
        sections.append(body)
    if comments:
        sections.append("\n--- Top comments ---")
        sections.extend(comments)

    full_text = "\n\n".join(sections)
    word_count = len(full_text.split())

    if word_count < MIN_ARTICLE_WORDS:
        # Link post with no body — still worth saving if comments exist
        if not comments:
            result["error"] = (
                f"thin_content: Reddit post has only {word_count} words (link post with no discussion yet)"
            )
            return result

    result["title"] = f"{title} [{subreddit}]" if subreddit else title
    result["author"] = f"u/{author}" if author else None
    result["published_date"] = str(int(created)) if created else None
    result["clean_text"] = full_text
    result["extraction_success"] = True
    return result


# ── GitHub ────────────────────────────────────────────────────────────────────

_GITHUB_REPO_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:/|$)"
)

_README_CANDIDATES = [
    "README.md", "readme.md", "README.rst", "readme.rst", "README.txt", "README",
]


def extract_github(url: str) -> dict:
    """Extract a GitHub repo's README (+ basic metadata via GitHub API).

    No API key needed for public repos. Falls back to raw.githubusercontent.com.
    Returns {title, author, published_date, clean_text, extraction_success, error}.
    """
    result = _base_result()

    match = _GITHUB_REPO_RE.search(url)
    if not match:
        result["error"] = "invalid_url: could not parse owner/repo from GitHub URL"
        return result

    owner, repo = match.group(1), match.group(2)
    repo = repo.removesuffix(".git")

    # Fetch repo metadata (stars, description, default branch) — best effort
    default_branch = "main"
    description = ""
    try:
        api_resp = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Loopwire/1.0"},
            timeout=10,
        )
        if api_resp.status_code == 200:
            meta = api_resp.json()
            default_branch = meta.get("default_branch", "main")
            description = meta.get("description") or ""
            stars = meta.get("stargazers_count", 0)
            language = meta.get("language") or ""
            result["author"] = owner
            header = (
                f"Repository: {owner}/{repo}\n"
                f"Description: {description}\n"
                f"Language: {language}  |  Stars: {stars:,}\n\n"
            )
        else:
            header = f"Repository: {owner}/{repo}\n\n"
    except httpx.HTTPError:
        header = f"Repository: {owner}/{repo}\n\n"

    # Fetch README
    readme_text = ""
    for candidate in _README_CANDIDATES:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{candidate}"
        try:
            r = httpx.get(raw_url, follow_redirects=True, timeout=10)
            if r.status_code == 200 and r.text.strip():
                readme_text = r.text.strip()
                break
        except httpx.HTTPError:
            continue

    if not readme_text:
        result["error"] = "no_readme: could not find a README in the repository"
        return result

    full_text = header + readme_text
    word_count = len(full_text.split())

    if word_count < MIN_ARTICLE_WORDS:
        result["error"] = f"thin_content: README is very short ({word_count} words)"
        return result

    result["title"] = f"{owner}/{repo}"
    result["clean_text"] = full_text
    result["extraction_success"] = True
    return result


# ── Hacker News ───────────────────────────────────────────────────────────────

_HN_ITEM_RE = re.compile(r"news\.ycombinator\.com/item\?id=(\d+)")
_HN_USER_RE = re.compile(r"news\.ycombinator\.com/user\?id=")


def extract_hackernews(url: str) -> dict:
    """Extract a Hacker News post + top comments via the Algolia API.

    Returns {title, author, published_date, clean_text, extraction_success, error}.
    """
    result = _base_result()

    match = _HN_ITEM_RE.search(url)
    if not match:
        result["error"] = "invalid_url: could not parse an HN item ID"
        return result

    item_id = match.group(1)

    try:
        resp = httpx.get(
            f"https://hn.algolia.com/api/v1/items/{item_id}",
            timeout=15,
        )
    except httpx.HTTPError as exc:
        result["error"] = f"fetch_failed: {exc}"
        return result

    if resp.status_code != 200:
        result["error"] = f"fetch_failed: Algolia API returned HTTP {resp.status_code}"
        return result

    try:
        data = resp.json()
    except ValueError as exc:
        result["error"] = f"parse_failed: {exc}"
        return result

    title = data.get("title") or "Untitled HN post"
    author = data.get("author")
    created_at = data.get("created_at")
    story_text = (data.get("text") or "").strip()  # Ask HN / self posts have text
    story_url = data.get("url") or ""  # external link posts

    # Collect top comments
    comments: list[str] = []
    for child in (data.get("children") or [])[:MAX_HN_COMMENTS]:
        if child.get("type") != "comment":
            continue
        comment_author = child.get("author", "unknown")
        comment_text = (child.get("text") or "").strip()
        # HN stores comment text as HTML — do a basic strip
        comment_text = re.sub(r"<[^>]+>", " ", comment_text).strip()
        comment_text = re.sub(r"\s+", " ", comment_text)
        if comment_text and comment_text != "[deleted]":
            comments.append(f"{comment_author}: {comment_text}")

    sections = [f"HN: {title}"]
    if story_url:
        sections.append(f"Link: {story_url}")
    if story_text:
        # Strip basic HTML from Ask HN posts
        clean_story = re.sub(r"<[^>]+>", " ", story_text)
        clean_story = re.sub(r"\s+", " ", clean_story).strip()
        sections.append(clean_story)
    if comments:
        sections.append("--- Top comments ---")
        sections.extend(comments)

    full_text = "\n\n".join(sections)
    word_count = len(full_text.split())

    if word_count < MIN_ARTICLE_WORDS and not comments:
        result["error"] = f"thin_content: only {word_count} words (no comments yet?)"
        return result

    result["title"] = title
    result["author"] = author
    result["published_date"] = created_at
    result["clean_text"] = full_text
    result["extraction_success"] = True
    return result


# ── PDF ───────────────────────────────────────────────────────────────────────

def extract_pdf(url: str) -> dict:
    """Download a PDF from a URL and extract its text content via pypdf.

    Returns {title, author, published_date, clean_text, extraction_success, error}.
    """
    result = _base_result()

    # Download
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Loopwire/1.0 (PDF reader)"},
        )
    except httpx.HTTPError as exc:
        result["error"] = f"fetch_failed: {exc}"
        return result

    if resp.status_code != 200:
        result["error"] = f"fetch_failed: HTTP {resp.status_code}"
        return result

    content_type = resp.headers.get("content-type", "")
    if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
        result["error"] = "not_a_pdf: URL did not return a PDF content-type"
        return result

    # Parse
    try:
        from pypdf import PdfReader  # lazy import — only needed for PDF type

        reader = PdfReader(io.BytesIO(resp.content))
    except Exception as exc:
        result["error"] = f"parse_failed: {exc}"
        return result

    # Extract metadata
    meta = reader.metadata or {}
    result["title"] = (
        meta.get("/Title")
        or meta.get("title")
        or url.split("/")[-1].replace(".pdf", "")
        or "PDF Document"
    )
    result["author"] = meta.get("/Author") or meta.get("author")

    # Extract text page by page
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        except Exception:
            continue  # skip unreadable pages

    full_text = "\n\n".join(pages)
    # Normalise whitespace
    full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
    word_count = len(full_text.split())

    if word_count < MIN_PDF_WORDS:
        result["error"] = (
            f"thin_content: only {word_count} words extracted from PDF "
            "(possibly scanned/image-only document)"
        )
        return result

    result["clean_text"] = full_text
    result["extraction_success"] = True
    return result
