"""Background worker: picks up 'pending' saved_items, extracts content, and then
summarizes successfully-extracted items. Simple polling loop per PRD Phase 2/3.

Run standalone with: uv run python -m app.worker
"""

import datetime as dt
import logging
import time

import httpx

from app.config import get_settings
from app.db import SessionLocal
from app.embeddings import compute_embedding
from app.extraction import (
    extract_article,
    extract_github,
    extract_hackernews,
    extract_pdf,
    extract_reddit,
    extract_youtube,
)
from app.models import (
    ITEM_TYPE_ARTICLE,
    ITEM_TYPE_GITHUB,
    ITEM_TYPE_HN,
    ITEM_TYPE_PDF,
    ITEM_TYPE_REDDIT,
    ITEM_TYPE_YOUTUBE,
    STATUS_EXTRACTED,
    STATUS_EXTRACTION_FAILED,
    STATUS_PENDING,
    STATUS_SUMMARIZED,
    SavedItem,
)
from app.summarize import summarize_item

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("loopwire.worker")

POLL_INTERVAL_SECONDS = 30

EXTRACTABLE_TYPES = [
    ITEM_TYPE_ARTICLE,
    ITEM_TYPE_YOUTUBE,
    ITEM_TYPE_REDDIT,
    ITEM_TYPE_GITHUB,
    ITEM_TYPE_HN,
    ITEM_TYPE_PDF,
]


_FRIENDLY_EXTRACTION_REASONS = {
    "thin_content": "not enough readable text found (likely paywalled or a JS-rendered page)",
    "parse_failed": "couldn't extract readable content (likely a JS-rendered page)",
    "fetch_failed": "couldn't fetch the page (possible paywall or block)",
    "no_readme": "no README found in that repo (or it doesn't exist / is private)",
    "no_captions": "this video has no captions available",
    "transcript_fetch_failed": "YouTube blocked the caption request from our server",
    "video_unavailable": "this video is unavailable (deleted, private, or region-locked)",
    "git_lfs_pointer": "this file is stored via Git LFS and can't be fetched directly",
    "unsupported_source": "this type of link isn't supported yet",
    "invalid_url": "couldn't understand that link",
    "not_a_pdf": "that link didn't return an actual PDF",
}


def _friendly_extraction_reason(error: str | None) -> str:
    """Map an extraction_error's leading code to a short, honest, non-technical
    phrase - the raw error strings are precise but not fit for a chat message
    (multi-paragraph YouTube errors, etc.), and previously every failure showed
    the same generic text regardless of the real cause."""
    if not error:
        return "couldn't process this link"
    code = error.split(":", 1)[0].strip()
    return _FRIENDLY_EXTRACTION_REASONS.get(code, "couldn't process this link")


def _notify_extraction_failed(item: SavedItem) -> None:
    """Bonus UX item (prdv2.md, bottom section): if a link later fails
    extraction, follow up in Telegram instead of only reflecting it
    silently in the dashboard - the user gets a link forwarded and then
    just... nothing, unless we tell them."""
    chat_id = item.user.telegram_chat_id if item.user else None
    settings = get_settings()
    if not chat_id or not settings.telegram_bot_token:
        return

    title = (item.title or item.url)[:60]
    reason = _friendly_extraction_reason(item.extraction_error)
    text = (
        f"⚠️ Couldn't process \"{title}\" — {reason}. "
        "You can still open the original link from your dashboard."
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send extraction-failure notice to chat %s", chat_id)


def _run_extractor(item: SavedItem) -> dict:
    """Dispatch to the right extractor and return a normalised result dict."""
    if item.type == ITEM_TYPE_YOUTUBE:
        return extract_youtube(item.url)
    if item.type == ITEM_TYPE_REDDIT:
        return extract_reddit(item.url)
    if item.type == ITEM_TYPE_GITHUB:
        return extract_github(item.url)
    if item.type == ITEM_TYPE_HN:
        return extract_hackernews(item.url)
    if item.type == ITEM_TYPE_PDF:
        return extract_pdf(item.url)
    return extract_article(item.url)  # default: article


def process_pending_extraction(db) -> dict:
    items = (
        db.query(SavedItem)
        .filter(SavedItem.status == STATUS_PENDING)
        .filter(SavedItem.type.in_(EXTRACTABLE_TYPES))
        .all()
    )

    failed = 0
    for item in items:
        logger.info("Extracting item #%s (%s): %s", item.id, item.type, item.url)

        result = _run_extractor(item)

        # All extractors return a normalised dict — map to model fields.
        item.title = result.get("title")
        item.author = result.get("author")
        item.published_date = result.get("published_date")
        item.clean_text = result.get("clean_text")
        item.extraction_success = result["extraction_success"]
        item.extraction_error = result["error"]
        item.extracted_at = dt.datetime.now(dt.timezone.utc)
        item.status = STATUS_EXTRACTED if result["extraction_success"] else STATUS_EXTRACTION_FAILED
        if not result["extraction_success"]:
            failed += 1
            db.commit()
            _notify_extraction_failed(item)
        else:
            db.commit()

    return {"attempted": len(items), "failed": failed}


def process_pending_summarization(db) -> int:
    items = db.query(SavedItem).filter(SavedItem.status == STATUS_EXTRACTED).all()

    for item in items:
        logger.info("Summarizing item #%s: %s", item.id, item.title or item.url)
        # Each item's owning user has their own static profile (Phase A) -
        # no more global singleton.
        profile_text = item.user.interest_profile_text or "General interest, no profile configured yet."
        try:
            result = summarize_item(
                title=item.title or item.url,
                content=item.clean_text or "",
                interest_profile=profile_text,
            )
        except Exception:
            logger.exception("Summarization failed for item #%s, leaving as extracted", item.id)
            continue

        item.summary = result.summary
        item.key_takeaway = result.key_takeaway
        item.relevance_note = result.relevance_note
        item.estimated_read_time_minutes = result.estimated_read_time_minutes
        item.summarized_at = dt.datetime.now(dt.timezone.utc)
        item.status = STATUS_SUMMARIZED

        # Phase B: embed the summary once, up front, so ranking + similar-item
        # lookups at send-build time don't need to call the embedding API again.
        try:
            item.embedding = compute_embedding(result.summary)
        except Exception:
            logger.exception("Embedding failed for item #%s - it'll rank chronologically instead", item.id)
            item.embedding = None

        db.commit()

    return len(items)


def run_process_pending_cycle() -> dict:
    """Runs one extraction + summarization pass and returns stats. Shared by
    the standalone polling loop below (local dev / self-hosted always-on
    deployments) and the HTTP-triggered POST /process-pending endpoint in
    app/main.py, which is what production relies on - see SETUP.md."""
    with SessionLocal() as db:
        extraction = process_pending_extraction(db)
        summarized = process_pending_summarization(db)
    return {
        "processed": extraction["attempted"],
        "failed": extraction["failed"],
        "summarized": summarized,
    }


def run_once() -> None:
    result = run_process_pending_cycle()
    if result["processed"] or result["summarized"]:
        logger.info(
            "Cycle done: extracted=%d (failed=%d) summarized=%d",
            result["processed"],
            result["failed"],
            result["summarized"],
        )


def main() -> None:
    """Standalone polling loop - local dev or self-hosted always-on
    deployments only. Production instead calls run_process_pending_cycle()
    via an HTTP trigger (POST /process-pending), see app/main.py."""
    logger.info("Loopwire worker starting, polling every %ss", POLL_INTERVAL_SECONDS)
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Worker cycle failed")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
