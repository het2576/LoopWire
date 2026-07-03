"""Loopwire send assembly (Phase 4) - shared by email and web delivery paths.

Phase A (prdv2.md) makes sends per-user: each user gets their own bundle of
whatever's been summarized/failed since their own last send, and is capped
at MAX_SENDS_PER_DAY (1) per prdv2.md A.3.5.

Phase B (prdv2.md B.3) ranks that bundle by similarity to the user's real
engagement history instead of chronological order, and upgrades relevance
notes to cite concrete similar items once there's enough history to trust.
"""

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    MAX_SENDS_PER_DAY,
    STATUS_EXTRACTION_FAILED,
    STATUS_SUMMARIZED,
    LoopwireSend,
    SavedItem,
    User,
)
from app.personalization import (
    STRONG_SIMILARITY_THRESHOLD,
    find_similar_engaged_items,
    get_ranking_context,
    rank_items_by_similarity,
    total_engagement_count,
)

logger = logging.getLogger("loopwire.loopwire_send")


@dataclass
class LoopwireItemView:
    item_id: int
    title: str
    type: str
    source_url: str
    couldn_t_extract: bool
    summary: str | None = None
    key_takeaway: str | None = None
    relevance_note: str | None = None
    read_time_minutes: int | None = None


def _pending_items(db: Session, user_id: int) -> list[SavedItem]:
    return (
        db.query(SavedItem)
        .filter(SavedItem.user_id == user_id)
        .filter(SavedItem.loopwire_send_id.is_(None))
        .filter(SavedItem.status.in_([STATUS_SUMMARIZED, STATUS_EXTRACTION_FAILED]))
        .order_by(SavedItem.added_at.asc())
        .all()
    )


def _sent_today(db: Session, user_id: int) -> bool:
    """Enforces the 1-dispatch-per-user-per-day cap (prdv2.md A.3.5)."""
    today_start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        db.query(LoopwireSend)
        .filter(LoopwireSend.user_id == user_id, LoopwireSend.sent_at >= today_start)
        .count()
    )
    return count >= MAX_SENDS_PER_DAY


def _upgrade_relevance_note(db: Session, user: User, item: SavedItem) -> None:
    """Replaces a summarized item's static-bio relevance note with one
    grounded in concrete similar past-engaged items, if a strong enough
    match exists (prdv2.md B.3.5). Cold-start users and items with no
    strong match keep whatever note summarize_item() already produced."""
    from app.summarize import generate_grounded_relevance_note  # avoids a circular import at module load

    if not item.embedding:
        return

    similar = find_similar_engaged_items(db, user.id, item.embedding, exclude_item_id=item.id)
    strong_matches = [(match_item, score) for match_item, score in similar if score >= STRONG_SIMILARITY_THRESHOLD]
    if not strong_matches:
        return

    titles = [match_item.title or match_item.url for match_item, _ in strong_matches]
    try:
        item.relevance_note = generate_grounded_relevance_note(
            title=item.title or item.url,
            summary=item.summary or "",
            similar_titles=titles,
        )
    except Exception:
        logger.exception("Grounded relevance note failed for item #%s - keeping the original note", item.id)


def build_loopwire_send(db: Session, user_id: int, period: str = "daily") -> tuple[LoopwireSend, list[LoopwireItemView], bool] | None:
    """Assembles and persists a send for one user from every item of theirs
    not yet included in one, ranked by affinity to their real engagement
    history. Returns None if there's nothing new to send, otherwise
    (send, items, is_cold_start)."""

    items = _pending_items(db, user_id)
    if not items:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    vector, cold_start = get_ranking_context(db, user)
    items = rank_items_by_similarity(items, vector)

    if not cold_start:
        for item in items:
            if item.status == STATUS_SUMMARIZED:
                _upgrade_relevance_note(db, user, item)

    send = LoopwireSend(user_id=user_id, period=period, item_count=len(items))
    db.add(send)
    db.flush()  # assign send.id without committing yet

    views: list[LoopwireItemView] = []
    for item in items:
        item.loopwire_send_id = send.id
        views.append(
            LoopwireItemView(
                item_id=item.id,
                title=item.title or item.url,
                type=item.type,
                source_url=item.url,
                couldn_t_extract=item.status == STATUS_EXTRACTION_FAILED,
                summary=item.summary,
                key_takeaway=item.key_takeaway,
                relevance_note=item.relevance_note,
                read_time_minutes=item.estimated_read_time_minutes,
            )
        )

    db.commit()
    return send, views, cold_start


def users_with_pending_items(db: Session) -> list[int]:
    """Distinct user ids with at least one item ready to be bundled."""
    rows = (
        db.query(SavedItem.user_id)
        .filter(SavedItem.loopwire_send_id.is_(None))
        .filter(SavedItem.status.in_([STATUS_SUMMARIZED, STATUS_EXTRACTION_FAILED]))
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def build_and_send_pending_for_user(db: Session, user: User, period: str) -> dict:
    """Builds + emails one user's send if they have pending items and
    haven't already hit today's cap. Returns a per-user result dict."""
    from app.email_delivery import send_loopwire_email  # local import avoids a circular import at module load

    if _sent_today(db, user.id):
        return {"user_id": user.id, "sent": False, "reason": "daily_cap_reached"}

    result = build_loopwire_send(db, user.id, period=period)
    if result is None:
        return {"user_id": user.id, "sent": False, "reason": "no_new_items"}

    send, items, cold_start = result
    engagement_count = total_engagement_count(db, user.id)
    email_id = send_loopwire_email(
        items, period, user.email, cold_start=cold_start, engagement_count=engagement_count
    )
    send.email_sent = email_id is not None
    db.commit()

    return {
        "user_id": user.id,
        "sent": True,
        "loopwire_send_id": send.id,
        "item_count": len(items),
        "email_id": email_id,
        "cold_start": cold_start,
    }
