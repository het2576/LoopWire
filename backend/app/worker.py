"""Processing pipeline: pending -> extracted -> summarized (+ embedding, recall cards).

Concurrency: a link arriving on Telegram triggers a pass immediately while
the cron-driven /process-pending can run at the same moment. v1 had no
locking, so both passes could extract and summarize the same item (double
LLM spend, racing writes). Items are now *claimed* with SELECT ... FOR UPDATE
SKIP LOCKED plus a lease timestamp, so each item is processed by exactly one
pass, and a claim abandoned by a crashed process expires after
PROCESSING_LEASE_MINUTES.

Run standalone (local dev): uv run python -m app.worker
"""

import datetime as dt
import logging
import math
import time

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.embeddings import compute_embedding
from app.extraction import (
    count_words,
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
    MAX_PROCESSING_ATTEMPTS,
    PROCESSING_LEASE_MINUTES,
    STATUS_EXTRACTED,
    STATUS_EXTRACTION_FAILED,
    STATUS_PENDING,
    STATUS_SUMMARIZATION_FAILED,
    STATUS_SUMMARIZED,
    SavedItem,
)
from app.recall import create_cards_for_item
from app.summarize import summarize_item

logger = logging.getLogger("loopwire.worker")

POLL_INTERVAL_SECONDS = 30
BATCH_LIMIT = 15  # per pass; keeps one HTTP-triggered pass bounded

# Average adult silent reading speed for non-fiction (Brysbaert, 2019).
WORDS_PER_MINUTE = 238

EXTRACTABLE_TYPES = [
    ITEM_TYPE_ARTICLE,
    ITEM_TYPE_YOUTUBE,
    ITEM_TYPE_REDDIT,
    ITEM_TYPE_GITHUB,
    ITEM_TYPE_HN,
    ITEM_TYPE_PDF,
]

_FRIENDLY_REASONS = {
    "thin_content": "not enough readable text found (likely paywalled or a JS-rendered page)",
    "parse_failed": "couldn't extract readable content (likely a JS-rendered page)",
    "fetch_failed": "couldn't fetch the page",
    "http_404": "the page doesn't exist anymore (dead link)",
    "http_410": "the page doesn't exist anymore (dead link)",
    "http_401": "the site requires a login or blocks automated readers",
    "http_402": "the article is behind a paywall",
    "paywalled": "it's behind a paywall - only a short preview was readable",
    "http_403": "the site blocked the request (paywall or bot protection)",
    "http_429": "the site rate-limited us - try re-sending later",
    "blocked_url": "that address points somewhere Loopwire won't fetch (private network)",
    "too_large": "the file is too large to process",
    "no_readme": "no README found in that repo (or it doesn't exist / is private)",
    "no_captions": "this video has no captions available",
    "transcript_fetch_failed": "YouTube blocked the caption request from our server",
    "video_unavailable": "this video is unavailable (deleted, private, or region-locked)",
    "git_lfs_pointer": "this file is stored via Git LFS and can't be fetched directly",
    "unsupported_source": "this type of link isn't supported yet",
    "invalid_url": "couldn't understand that link",
    "not_a_pdf": "that link didn't return an actual PDF",
    "summarization_failed": "the summarizer kept failing on this one",
}


def friendly_reason(error: str | None) -> str:
    if not error:
        return "couldn't process this link"
    code = error.split(":", 1)[0].strip()
    if code.startswith("http_") and code not in _FRIENDLY_REASONS:
        return "the site returned an error"
    return _FRIENDLY_REASONS.get(code, "couldn't process this link")


def compute_read_time_minutes(word_count: int | None, duration_seconds: int | None) -> int | None:
    if duration_seconds:
        return max(1, math.ceil(duration_seconds / 60))
    if word_count:
        return max(1, round(word_count / WORDS_PER_MINUTE))
    return None


def embedding_text(title: str | None, summary: str) -> str:
    return f"{title}\n{summary}" if title else summary


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _notify_failed(item: SavedItem, reason_source: str | None) -> None:
    """Follow up in Telegram when a link that was acknowledged as "queued"
    later fails, instead of leaving the user with silence."""
    chat_id = item.user.telegram_chat_id if item.user else None
    settings = get_settings()
    if not chat_id or not settings.telegram_bot_token:
        return
    title = (item.title or item.url)[:60]
    text = (
        f"⚠️ Couldn't process \"{title}\" — {friendly_reason(reason_source)}. "
        "It'll still appear in your next dispatch as a raw link."
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except httpx.HTTPError:
        logger.exception("Failed to send failure notice to chat %s", chat_id)


def claim_items(db: Session, status: str, user_id: int | None, limit: int = BATCH_LIMIT) -> list[int]:
    now = _now()
    lease_cutoff = now - dt.timedelta(minutes=PROCESSING_LEASE_MINUTES)
    q = (
        select(SavedItem.id)
        .where(SavedItem.status == status)
        .where(or_(SavedItem.processing_started_at.is_(None), SavedItem.processing_started_at < lease_cutoff))
        .order_by(SavedItem.added_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if status == STATUS_PENDING:
        q = q.where(SavedItem.type.in_(EXTRACTABLE_TYPES))
    if user_id is not None:
        q = q.where(SavedItem.user_id == user_id)
    ids = list(db.scalars(q).all())
    if ids:
        db.execute(update(SavedItem).where(SavedItem.id.in_(ids)).values(processing_started_at=now))
    db.commit()
    return ids


def run_extractor(item: SavedItem) -> dict:
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
    return extract_article(item.url)


def extract_one(db: Session, item: SavedItem) -> bool:
    """Returns True on successful extraction."""
    logger.info("Extracting item #%s (%s): %s", item.id, item.type, item.url)
    try:
        result = run_extractor(item)
    except Exception as exc:
        logger.exception("Extractor crashed on item #%s", item.id)
        item.attempts += 1
        item.processing_started_at = None
        if item.attempts >= MAX_PROCESSING_ATTEMPTS:
            item.status = STATUS_EXTRACTION_FAILED
            item.extraction_error = f"internal_error: {type(exc).__name__}"
            db.commit()
            _notify_failed(item, item.extraction_error)
        else:
            db.commit()
        return False

    item.title = result.get("title") or item.title
    item.author = result.get("author")
    item.published_date = result.get("published_date")
    item.clean_text = result.get("clean_text")
    item.word_count = count_words(item.clean_text)
    item.duration_seconds = result.get("duration_seconds")
    item.estimated_read_time_minutes = compute_read_time_minutes(item.word_count, item.duration_seconds)
    item.extraction_success = result["extraction_success"]
    item.extraction_error = result["error"]
    item.extracted_at = _now()
    item.processing_started_at = None
    item.attempts = 0
    item.status = STATUS_EXTRACTED if result["extraction_success"] else STATUS_EXTRACTION_FAILED
    db.commit()
    if not result["extraction_success"]:
        _notify_failed(item, item.extraction_error)
    return bool(result["extraction_success"])


def summarize_one(db: Session, item: SavedItem) -> bool:
    logger.info("Summarizing item #%s: %s", item.id, item.title or item.url)
    profile_text = item.user.interest_profile_text or "No interests stated yet."
    try:
        result = summarize_item(title=item.title or item.url, content=item.clean_text or "",
                                interest_profile=profile_text)
    except Exception as exc:
        item.attempts += 1
        item.processing_started_at = None
        item.summarization_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        logger.exception("Summarization failed for item #%s (attempt %d)", item.id, item.attempts)
        if item.attempts >= MAX_PROCESSING_ATTEMPTS:
            item.status = STATUS_SUMMARIZATION_FAILED
            db.commit()
            _notify_failed(item, "summarization_failed")
        else:
            db.commit()
        return False

    item.summary = result.summary
    item.key_takeaway = result.key_takeaway
    item.relevance_note = result.relevance_note
    item.summarized_at = _now()
    item.summarization_error = None
    item.status = STATUS_SUMMARIZED
    item.processing_started_at = None

    if not result.content_is_thin and item.clean_text:
        kept, dropped = create_cards_for_item(db, item, result.recall_cards, item.clean_text)
        if dropped:
            logger.info("Item #%s: dropped %d ungrounded recall card(s), kept %d", item.id, dropped, kept)

    try:
        item.embedding = compute_embedding(embedding_text(item.title, result.summary))
    except Exception:
        logger.exception("Embedding failed for item #%s - it'll rank after embedded items", item.id)
        item.embedding = None
    db.commit()
    return True


def process_pending_extraction(db: Session, user_id: int | None = None) -> dict:
    ids = claim_items(db, STATUS_PENDING, user_id)
    failed = 0
    for item_id in ids:
        item = db.get(SavedItem, item_id)
        if item is not None and not extract_one(db, item):
            failed += 1
    return {"attempted": len(ids), "failed": failed}


def process_pending_summarization(db: Session, user_id: int | None = None) -> int:
    ids = claim_items(db, STATUS_EXTRACTED, user_id)
    done = 0
    for item_id in ids:
        item = db.get(SavedItem, item_id)
        if item is not None and summarize_one(db, item):
            done += 1
    return done


def run_process_pending_cycle(user_id: int | None = None) -> dict:
    with SessionLocal() as db:
        extraction = process_pending_extraction(db, user_id=user_id)
        summarized = process_pending_summarization(db, user_id=user_id)
    return {"processed": extraction["attempted"], "failed": extraction["failed"], "summarized": summarized}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("Loopwire worker starting, polling every %ss", POLL_INTERVAL_SECONDS)
    while True:
        try:
            result = run_process_pending_cycle()
            if result["processed"] or result["summarized"]:
                logger.info("Cycle done: %s", result)
        except Exception:
            logger.exception("Worker cycle failed")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
