"""Engagement logging - foundation for future adaptive personalization (Phase 5/B).

v1 only logs; nothing here feeds a ranking model yet (that's prdv2.md Phase B).
Every function is scoped to a single user_id (Phase A, multi-tenant).
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    EVENT_CLICKED_SOURCE,
    EVENT_OPENED,
    EVENT_SKIPPED,
    EngagementEvent,
    LoopwireSend,
    SavedItem,
)


def log_event(db: Session, user_id: int, item_id: int, event_type: str) -> None:
    exists = (
        db.query(EngagementEvent)
        .filter(EngagementEvent.item_id == item_id, EngagementEvent.event_type == event_type)
        .first()
    )
    if exists:
        return  # opened/clicked are idempotent - one row per item is enough signal
    db.add(EngagementEvent(user_id=user_id, item_id=item_id, event_type=event_type))
    db.commit()


def infer_skipped_events(db: Session, user_id: int) -> int:
    """For this user's items belonging to any send older than their own
    latest one, log a 'skipped' event if the item was never opened or
    clicked - one full send cycle has passed with no interaction."""
    latest_send = (
        db.query(LoopwireSend)
        .filter(LoopwireSend.user_id == user_id)
        .order_by(LoopwireSend.id.desc())
        .first()
    )
    if latest_send is None:
        return 0

    stale_items = (
        db.query(SavedItem)
        .filter(SavedItem.user_id == user_id)
        .filter(SavedItem.loopwire_send_id.isnot(None))
        .filter(SavedItem.loopwire_send_id != latest_send.id)
        .all()
    )

    count = 0
    for item in stale_items:
        has_engagement = (
            db.query(EngagementEvent)
            .filter(
                EngagementEvent.item_id == item.id,
                EngagementEvent.event_type.in_([EVENT_OPENED, EVENT_CLICKED_SOURCE, EVENT_SKIPPED]),
            )
            .first()
        )
        if has_engagement:
            continue
        db.add(EngagementEvent(user_id=user_id, item_id=item.id, event_type=EVENT_SKIPPED))
        count += 1

    db.commit()
    return count


def get_stats(db: Session, user_id: int) -> dict:
    totals = (
        db.query(SavedItem.type, func.count(SavedItem.id))
        .filter(SavedItem.user_id == user_id)
        .filter(SavedItem.loopwire_send_id.isnot(None))
        .group_by(SavedItem.type)
        .all()
    )

    stats: dict[str, dict[str, int | float]] = {
        content_type: {"total_sent": total, "opened": 0, "clicked_source": 0, "skipped": 0}
        for content_type, total in totals
    }

    event_rows = (
        db.query(SavedItem.type, EngagementEvent.event_type, func.count(func.distinct(SavedItem.id)))
        .join(EngagementEvent, EngagementEvent.item_id == SavedItem.id)
        .filter(SavedItem.user_id == user_id)
        .filter(SavedItem.loopwire_send_id.isnot(None))
        .group_by(SavedItem.type, EngagementEvent.event_type)
        .all()
    )
    for content_type, event_type, count in event_rows:
        stats[content_type][event_type] = count

    for bucket in stats.values():
        total = bucket["total_sent"]
        engaged = bucket["opened"] + bucket["clicked_source"]
        bucket["engagement_rate"] = round(engaged / total, 2) if total else 0.0

    return stats
