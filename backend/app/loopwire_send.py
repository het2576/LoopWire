"""Dispatch assembly - shared by email and web delivery.

Per user: bundle everything processed since their last dispatch, rank it
(personalization.py), persist the order (dispatch_rank) so every surface shows
the same ranking, and attach due recall questions.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import (
    DISPATCHABLE_STATUSES,
    FAILED_STATUSES,
    MAX_SENDS_PER_DAY,
    STATUS_SUMMARIZED,
    LoopwireSend,
    RecallCard,
    SavedItem,
    User,
)
from app.personalization import (
    STRONG_SIMILARITY_THRESHOLD,
    RankingContext,
    find_similar_engaged_items,
    get_ranking_context,
    rank_items,
)
from app.recall import due_cards_query
from app.timeutil import local_day_start_utc
from app.tracking import click_url, feedback_url, send_open_pixel_url

logger = logging.getLogger("loopwire.loopwire_send")

EXPLORATION_NOTE = "Outside your usual reading — included so your dispatch doesn't narrow. A 👍 or 👎 teaches it."
MAX_RECALL_IN_EMAIL = 2


@dataclass
class LoopwireItemView:
    item_id: int
    title: str
    type: str
    source_url: str
    read_url: str
    feedback_up_url: str
    feedback_down_url: str
    couldnt_extract: bool
    failure_reason: str | None = None
    summary: str | None = None
    key_takeaway: str | None = None
    relevance_note: str | None = None
    read_time_minutes: int | None = None
    is_exploration: bool = False


@dataclass
class RecallPromptView:
    card_id: int
    question: str
    source_title: str


@dataclass
class DispatchBundle:
    send: LoopwireSend
    items: list[LoopwireItemView]
    ctx: RankingContext
    recall: list[RecallPromptView] = field(default_factory=list)

    @property
    def open_pixel_url(self) -> str:
        return send_open_pixel_url(self.send.id)


def item_view(item: SavedItem) -> LoopwireItemView:
    from app.worker import friendly_reason  # local: worker imports heavy extractor deps

    failed = item.status in FAILED_STATUSES
    return LoopwireItemView(
        item_id=item.id,
        title=item.title or item.url,
        type=item.type,
        source_url=item.url,
        read_url=click_url(item.id),
        feedback_up_url=feedback_url(item.id, "up"),
        feedback_down_url=feedback_url(item.id, "down"),
        couldnt_extract=failed,
        failure_reason=friendly_reason(item.extraction_error or item.summarization_error) if failed else None,
        summary=item.summary,
        key_takeaway=item.key_takeaway,
        relevance_note=item.relevance_note,
        read_time_minutes=item.estimated_read_time_minutes,
        is_exploration=item.is_exploration,
    )


def _pending_items(db: Session, user_id: int) -> list[SavedItem]:
    return (
        db.query(SavedItem)
        .filter(SavedItem.user_id == user_id)
        .filter(SavedItem.loopwire_send_id.is_(None))
        .filter(SavedItem.status.in_(DISPATCHABLE_STATUSES))
        .order_by(SavedItem.added_at.asc())
        .all()
    )


def sent_today(db: Session, user_id: int) -> bool:
    count = (
        db.query(LoopwireSend)
        .filter(LoopwireSend.user_id == user_id, LoopwireSend.sent_at >= local_day_start_utc())
        .count()
    )
    return count >= MAX_SENDS_PER_DAY


def _upgrade_relevance_note(db: Session, user: User, item: SavedItem) -> None:
    from app.summarize import generate_grounded_relevance_note

    if not item.embedding:
        return
    similar = find_similar_engaged_items(db, user.id, item.embedding, exclude_item_id=item.id)
    strong = [(m, s) for m, s in similar if s >= STRONG_SIMILARITY_THRESHOLD]
    if not strong:
        return
    try:
        item.relevance_note = generate_grounded_relevance_note(
            title=item.title or item.url, summary=item.summary or "", similar_titles=[m.title or m.url for m, _ in strong]
        )
    except Exception:
        logger.exception("Grounded relevance note failed for item #%s - keeping the original note", item.id)


def build_loopwire_send(db: Session, user_id: int, period: str = "daily", explore: bool = True) -> DispatchBundle | None:
    items = _pending_items(db, user_id)
    if not items:
        return None

    user = db.get(User, user_id)
    assert user is not None
    ctx = get_ranking_context(db, user)
    ranked = rank_items(items, ctx, explore=explore)

    send = LoopwireSend(user_id=user_id, period=period, item_count=len(ranked))
    db.add(send)
    db.flush()

    for position, r in enumerate(ranked):
        item = r.item
        item.loopwire_send_id = send.id
        item.dispatch_rank = position
        item.is_exploration = r.is_exploration
        if item.status == STATUS_SUMMARIZED:
            if r.is_exploration:
                item.relevance_note = EXPLORATION_NOTE
            elif ctx.interest_vector is not None:
                _upgrade_relevance_note(db, user, item)

    recall_cards: list[RecallCard] = due_cards_query(db, user_id).limit(MAX_RECALL_IN_EMAIL).all() if user.recall_enabled else []
    db.commit()

    return DispatchBundle(
        send=send,
        items=[item_view(r.item) for r in ranked],
        ctx=ctx,
        recall=[RecallPromptView(c.id, c.question, c.item.title or c.item.url) for c in recall_cards],
    )


def users_with_pending_items(db: Session) -> list[int]:
    rows = (
        db.query(SavedItem.user_id)
        .filter(SavedItem.loopwire_send_id.is_(None))
        .filter(SavedItem.status.in_(DISPATCHABLE_STATUSES))
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def build_and_send_pending_for_user(db: Session, user: User, period: str) -> dict:
    from app.email_delivery import send_loopwire_email

    if sent_today(db, user.id):
        return {"user_id": user.id, "sent": False, "reason": "daily_cap_reached"}

    bundle = build_loopwire_send(db, user.id, period=period)
    if bundle is None:
        return {"user_id": user.id, "sent": False, "reason": "no_new_items"}

    try:
        email_id = send_loopwire_email(bundle, period, user.email)
    except Exception:
        logger.exception("Email delivery failed for send #%s", bundle.send.id)
        email_id = None
    bundle.send.email_sent = email_id is not None
    db.commit()

    return {
        "user_id": user.id,
        "sent": True,
        "loopwire_send_id": bundle.send.id,
        "item_count": len(bundle.items),
        "email_id": email_id,
        "adaptive": bundle.ctx.is_adaptive,
    }
