"""URL classification and first-URL extraction for Loopwire.

classify_url() maps a URL to one of the item type constants so the worker
knows which extractor to call. New types added here must also be handled in
worker.py and have a corresponding extractor in extraction.py.
"""

import re

from app.extraction import extract_youtube_video_id
from app.models import (
    ITEM_TYPE_ARTICLE,
    ITEM_TYPE_GITHUB,
    ITEM_TYPE_HN,
    ITEM_TYPE_PDF,
    ITEM_TYPE_REDDIT,
    ITEM_TYPE_UNSUPPORTED,
    ITEM_TYPE_YOUTUBE,
)

URL_RE = re.compile(r"https?://\S+")

YOUTUBE_DOMAINS = ("youtube.com", "youtu.be")

REDDIT_DOMAINS = ("reddit.com", "old.reddit.com", "www.reddit.com")

GITHUB_DOMAINS = ("github.com",)

HN_DOMAINS = ("news.ycombinator.com",)

# Domains we know we can't extract from — flagged up front rather than
# wasting a worker cycle on a guaranteed failure.
UNSUPPORTED_DOMAINS = (
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "facebook.com",
    "linkedin.com",
    "threads.net",
)


def find_first_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(").,!?") if match else None


def classify_url(url: str) -> str:
    lowered = url.lower()

    if any(domain in lowered for domain in YOUTUBE_DOMAINS):
        return ITEM_TYPE_YOUTUBE if extract_youtube_video_id(url) else ITEM_TYPE_UNSUPPORTED

    if any(domain in lowered for domain in REDDIT_DOMAINS):
        # Only classify as Reddit if it looks like a post URL (/comments/)
        if "/comments/" in lowered:
            return ITEM_TYPE_REDDIT
        return ITEM_TYPE_UNSUPPORTED  # subreddit listing, profile, etc.

    if any(domain in lowered for domain in GITHUB_DOMAINS):
        # Only repos (github.com/owner/repo), not a specific file (/blob/),
        # gist, or raw link - those are a single file's content, not a repo,
        # and get classified by their actual file type instead.
        parts = [p for p in url.split("/") if p and not p.startswith("http")]
        is_repo_root = len(parts) >= 2 and not any(
            marker in lowered for marker in ("gist", "raw", "/blob/")
        )
        if is_repo_root:
            return ITEM_TYPE_GITHUB
        if lowered.endswith(".pdf"):
            return ITEM_TYPE_PDF
        return ITEM_TYPE_ARTICLE  # fall back to article for raw/blob files

    if any(domain in lowered for domain in HN_DOMAINS):
        if "item?id=" in lowered:
            return ITEM_TYPE_HN
        return ITEM_TYPE_UNSUPPORTED  # HN homepage, user profile, etc.

    if lowered.endswith(".pdf") or "application/pdf" in lowered:
        return ITEM_TYPE_PDF

    if any(domain in lowered for domain in UNSUPPORTED_DOMAINS):
        return ITEM_TYPE_UNSUPPORTED

    return ITEM_TYPE_ARTICLE
