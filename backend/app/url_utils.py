"""URL parsing, canonicalization, classification and SSRF safety.

classify_url() maps a URL to one of the item type constants so the worker
knows which extractor to call. Matching is done on the parsed *hostname*:
the previous substring match (`"x.com" in url`) classified vox.com,
blog.dropbox.com, linux.com, etc. as unsupported social links, and any
article whose query string mentioned youtube.com as a YouTube video.
"""

import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models import (
    ITEM_TYPE_ARTICLE,
    ITEM_TYPE_GITHUB,
    ITEM_TYPE_HN,
    ITEM_TYPE_PDF,
    ITEM_TYPE_REDDIT,
    ITEM_TYPE_UNSUPPORTED,
    ITEM_TYPE_YOUTUBE,
)

URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)

YOUTUBE_ID_RE = re.compile(r"^[\w-]{11}$")

YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
REDDIT_DOMAINS = ("reddit.com", "redd.it")
GITHUB_DOMAINS = ("github.com",)
HN_DOMAINS = ("news.ycombinator.com",)

# Domains we know we can't extract from - flagged up front rather than
# wasting a worker cycle (and a Telegram failure notice) on a sure failure.
UNSUPPORTED_DOMAINS = (
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
    "linkedin.com",
    "threads.net",
    "bsky.app",
)

# Query params that identify the *visit*, not the document. Stripped for
# dedupe so the same article shared from two places is one item.
_TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "pk_", "hsa_")
_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "ref", "ref_src", "ref_url",
    "s", "si", "source", "share", "feature", "spm", "mkt_tok", "_hsenc", "_hsmi",
}


def find_first_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None
    url = match.group(0)
    # Trailing punctuation from prose ("see https://x.y/z.") - but keep a
    # closing paren if the URL itself opened one (Wikipedia links).
    while url and url[-1] in ".,!?;:":
        url = url[:-1]
    if url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    return url


def hostname(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.").removeprefix("m.")


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def extract_youtube_video_id(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = hostname(url)
    if not _host_matches(host, YOUTUBE_DOMAINS):
        return None
    path_parts = [p for p in parts.path.split("/") if p]
    candidate: str | None = None
    if host == "youtu.be":
        candidate = path_parts[0] if path_parts else None
    elif path_parts[:1] == ["watch"]:
        candidate = dict(parse_qsl(parts.query)).get("v")
    elif len(path_parts) >= 2 and path_parts[0] in ("shorts", "live", "embed", "v"):
        candidate = path_parts[1]
    if candidate and YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def canonicalize_url(url: str) -> str:
    """Normalized form used only for duplicate detection (the original URL is
    what's stored and fetched)."""
    video_id = extract_youtube_video_id(url)
    if video_id:
        return f"youtube:{video_id}"
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", hostname(url), path, urlencode(sorted(query)), ""))


def classify_url(url: str) -> str:
    host = hostname(url)
    path = urlsplit(url).path.lower() if host else ""

    if _host_matches(host, YOUTUBE_DOMAINS):
        return ITEM_TYPE_YOUTUBE if extract_youtube_video_id(url) else ITEM_TYPE_UNSUPPORTED

    if _host_matches(host, REDDIT_DOMAINS):
        return ITEM_TYPE_REDDIT if "/comments/" in path else ITEM_TYPE_UNSUPPORTED

    if _host_matches(host, GITHUB_DOMAINS) and host == "github.com":
        segments = [p for p in path.split("/") if p]
        if len(segments) == 2:
            return ITEM_TYPE_GITHUB
        if path.endswith(".pdf"):
            return ITEM_TYPE_PDF
        if len(segments) > 2 and segments[2] in ("blob", "raw"):
            return ITEM_TYPE_ARTICLE  # a single file: fetched raw via extract_article
        if len(segments) > 2 and segments[2] == "tree":
            return ITEM_TYPE_GITHUB
        return ITEM_TYPE_ARTICLE if len(segments) > 2 else ITEM_TYPE_UNSUPPORTED

    if _host_matches(host, HN_DOMAINS):
        return ITEM_TYPE_HN if path == "/item" and "id=" in urlsplit(url).query else ITEM_TYPE_UNSUPPORTED

    if _host_matches(host, UNSUPPORTED_DOMAINS):
        return ITEM_TYPE_UNSUPPORTED

    if path.endswith(".pdf") or (host == "arxiv.org" and path.startswith("/pdf/")):
        return ITEM_TYPE_PDF

    if not host:
        return ITEM_TYPE_UNSUPPORTED

    return ITEM_TYPE_ARTICLE


# ── SSRF guard ────────────────────────────────────────────────────────────────

class UnsafeURLError(ValueError):
    pass


def assert_public_url(url: str) -> None:
    """Rejects URLs that resolve to private, loopback, link-local or reserved
    addresses before the server fetches them. Every saved link is fetched
    server-side, so without this a user could point the extractor at
    http://169.254.169.254/ (cloud metadata) or internal services and have the
    summary echo the response back to them."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeURLError(f"unparseable url: {exc}") from None
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("missing host")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURLError(f"dns_failed: {exc}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURLError(f"resolves to non-public address {ip}")
