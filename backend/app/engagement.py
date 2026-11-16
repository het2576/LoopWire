"""Engagement logging - the data personalization and recall run on.

Signal semantics (see models.py for why per-item "opened" is gone):
- clicked_source  item-level, implicit, strong positive (you chose this one)
- feedback_up     item-level, explicit positive (strongest)
- feedback_down   item-level, explicit negative
- skipped         inferred, weak negative - ONLY for items in a dispatch the
                  user is known to have opened. An unopened email says nothing
                  about its items, so it no longer penalizes them.
Every function is scoped to a single user_id.
"""

import datetime as dt

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    EVENT_CLICKED_SOURCE,
    EVENT_FEEDBACK_DOWN,
    EVENT_FEEDBACK_UP,
    EVENT_SKIPPED,
    POSITIVE_EVENTS,
    STATUS_SUMMARIZED,
    EngagementEvent,
    LoopwireSend,
    SavedItem,
)
from app.recall import activate_cards_for_item

# How long a dispatch's items get before no-click counts as a skip. Long enough to
# read a dispatch over a day; short enough that the next daily dispatch's ranking
# already sees the previous one's skips (the cron cycle infers right before it
# builds the new dispatch).
SKIP_GRACE = dt.timedelta(hours=12)

_OPPOSITE = {EVENT_FEEDBACK_UP: EVENT_FEEDBACK_DOWN, EVENT_FEEDBACK_DOWN: EVENT_FEEDBACK_UP}


def log_event(db: Session, user_id: int, item_id: int, event_type: str) -> bool:
    """Idempotent (one row per item+event via a unique constraint, so two
    concurrent clicks can't double-count). Returns True if newly recorded."""
    if event_type in _OPPOSITE:
        db.query(EngagementEvent).filter(
            EngagementEvent.item_id == item_id, EngagementEvent.event_type == _OPPOSITE[event_type]
        ).delete(synchronize_session=False)
    if event_type in (EVENT_CLICKED_SOURCE, EVENT_FEEDBACK_UP, EVENT_FEEDBACK_DOWN):
        # An explicit action overrides an earlier inferred skip.
        db.query(EngagementEvent).filter(
            EngagementEvent.item_id == item_id, EngagementEvent.event_type == EVENT_SKIPPED
        ).delete(synchronize_session=False)

    stmt = (
        pg_insert(EngagementEvent)
        .values(user_id=user_id, item_id=item_id, event_type=event_type)
        .on_conflict_do_nothing(constraint="uq_engagement_item_event")
        .returning(EngagementEvent.id)
    )
    inserted = db.execute(stmt).first() is not None
    if inserted and event_type in POSITIVE_EVENTS:
        activate_cards_for_item(db, user_id, item_id)
    db.commit()
    return inserted


def mark_send_opened(db: Session, send_id: int) -> None:
    send = db.get(LoopwireSend, send_id)
    if send is not None and send.opened_at is None:
        send.opened_at = dt.datetime.now(dt.UTC)
        db.commit()


def infer_skipped_events(db: Session, user_id: int, now: dt.datetime | None = None) -> int:
    """For summarized items in *opened* sends at least SKIP_GRACE old, log
    'skipped' if there was no click and no feedback.

    This used to exclude "the user's latest send" instead of using a time
    window. The cycle runs this *before* building the next dispatch, when the
    previous dispatch is still the latest - so its skips landed two dispatches
    late and never reached the ranking they were meant to inform.
    """
    cutoff = (now or dt.datetime.now(dt.UTC)) - SKIP_GRACE
    engaged_item_ids = (
        db.query(EngagementEvent.item_id).filter(EngagementEvent.user_id == user_id).distinct().scalar_subquery()
    )
    stale_items = (
        db.query(SavedItem.id)
        .join(LoopwireSend, LoopwireSend.id == SavedItem.loopwire_send_id)
        .filter(SavedItem.user_id == user_id)
        .filter(SavedItem.status == STATUS_SUMMARIZED)
        .filter(LoopwireSend.sent_at <= cutoff)
        .filter(LoopwireSend.opened_at.isnot(None))
        .filter(SavedItem.id.notin_(engaged_item_ids))
        .all()
    )
    for (item_id,) in stale_items:
        db.execute(
            pg_insert(EngagementEvent)
            .values(user_id=user_id, item_id=item_id, event_type=EVENT_SKIPPED)
            .on_conflict_do_nothing(constraint="uq_engagement_item_event")
        )
    db.commit()
    return len(stale_items)


def get_stats(db: Session, user_id: int) -> dict:
    totals = (
        db.query(SavedItem.type, func.count(SavedItem.id))
        .filter(SavedItem.user_id == user_id, SavedItem.loopwire_send_id.isnot(None))
        .group_by(SavedItem.type)
        .all()
    )
    stats: dict[str, dict[str, int | float]] = {
        content_type: {
            "total_sent": total,
            EVENT_CLICKED_SOURCE: 0,
            EVENT_FEEDBACK_UP: 0,
            EVENT_FEEDBACK_DOWN: 0,
            EVENT_SKIPPED: 0,
        }
        for content_type, total in totals
    }
    event_rows = (
        db.query(SavedItem.type, EngagementEvent.event_type, func.count(func.distinct(SavedItem.id)))
        .join(EngagementEvent, EngagementEvent.item_id == SavedItem.id)
        .filter(SavedItem.user_id == user_id, SavedItem.loopwire_send_id.isnot(None))
        .group_by(SavedItem.type, EngagementEvent.event_type)
        .all()
    )
    for content_type, event_type, count in event_rows:
        if content_type in stats:
            stats[content_type][event_type] = count

    positive_by_type: dict[str, int] = {
        content_type: count
        for content_type, count in db.query(SavedItem.type, func.count(func.distinct(SavedItem.id)))
        .join(EngagementEvent, EngagementEvent.item_id == SavedItem.id)
        .filter(SavedItem.user_id == user_id, SavedItem.loopwire_send_id.isnot(None))
        .filter(EngagementEvent.event_type.in_(POSITIVE_EVENTS))
        .group_by(SavedItem.type)
        .all()
    }
    for content_type, bucket in stats.items():
        total = bucket["total_sent"]
        bucket["engagement_rate"] = round(positive_by_type.get(content_type, 0) / total, 2) if total else 0.0
    return stats
