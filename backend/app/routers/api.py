import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.auth import get_current_user, verify_internal_secret
from app.db import get_db
from app.engagement import get_stats, log_event, mark_send_opened
from app.loopwire_send import item_view
from app.models import (
    ADAPTIVE_HALF_WEIGHT_SIGNALS,
    EVENT_FEEDBACK_DOWN,
    EVENT_FEEDBACK_UP,
    FEEDBACK_EVENTS,
    RECALL_RETIRED,
    ConnectionCode,
    EngagementEvent,
    LoopwireSend,
    RecallCard,
    SavedItem,
    User,
)
from app.personalization import adaptive_weight, positive_signal_count
from app.recall import apply_review, due_cards_query, grade_answer, retention_stats
from app.schemas import (
    ConnectionCodeOut,
    FeedbackIn,
    InterestProfileOut,
    InterestProfileUpdate,
    LoopwireItemOut,
    LoopwireSendOut,
    LoopwireSendSummaryOut,
    ProfileStatusOut,
    RecallCardOut,
    RecallReviewIn,
    RecallReviewOut,
    RecallStatsOut,
    SavedItemOut,
    UpsertUserRequest,
    UserOut,
)
from app.worker import run_process_pending_cycle

router = APIRouter(prefix="/api")

CONNECTION_CODE_TTL_MINUTES = 15
CODE_ALPHABET = string.ascii_uppercase + string.digits


def _send_to_out(db: Session, send: LoopwireSend) -> LoopwireSendOut:
    # Order by the persisted dispatch rank - v1 sorted by id here, which threw
    # the personalized ranking away on the dashboard.
    items = sorted(send.items, key=lambda i: (i.dispatch_rank is None, i.dispatch_rank or 0, i.id))
    votes = {
        item_id: ("up" if event == EVENT_FEEDBACK_UP else "down")
        for item_id, event in db.query(EngagementEvent.item_id, EngagementEvent.event_type)
        .filter(EngagementEvent.item_id.in_([i.id for i in items]))
        .filter(EngagementEvent.event_type.in_(FEEDBACK_EVENTS))
        .all()
    }
    out_items = []
    for item in items:
        v = item_view(item)
        out_items.append(
            LoopwireItemOut(
                item_id=v.item_id,
                title=v.title,
                type=v.type,
                source_url=v.source_url,
                read_url=v.read_url,
                couldnt_extract=v.couldnt_extract,
                failure_reason=v.failure_reason,
                summary=v.summary,
                key_takeaway=v.key_takeaway,
                relevance_note=v.relevance_note,
                read_time_minutes=v.read_time_minutes,
                is_exploration=v.is_exploration,
                feedback=votes.get(item.id),  # type: ignore[arg-type]
            )
        )
    return LoopwireSendOut(id=send.id, period=send.period, sent_at=send.sent_at, item_count=send.item_count,
                           items=out_items)


# ── First-login provisioning (no user_id yet - internal-secret only) ────────


@router.post("/auth/upsert-user", response_model=UserOut)
def upsert_user(payload: UpsertUserRequest, db: Session = Depends(get_db), _=Depends(verify_internal_secret)):
    user = db.query(User).filter(User.google_id == payload.google_id).first()
    if user is None:
        user = User(email=payload.email, google_id=payload.google_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ── Authenticated routes (every query below is scoped to current_user) ─────


def _own_send(db: Session, send_id: int, user: User) -> LoopwireSend:
    send = db.query(LoopwireSend).filter(LoopwireSend.id == send_id, LoopwireSend.user_id == user.id).first()
    if send is None:
        raise HTTPException(status_code=404, detail="Send not found")
    return send


@router.get("/loopwire-sends/latest", response_model=LoopwireSendOut)
def latest_loopwire_send(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    send = (
        db.query(LoopwireSend).filter(LoopwireSend.user_id == current_user.id).order_by(LoopwireSend.id.desc()).first()
    )
    if send is None:
        raise HTTPException(status_code=404, detail="No sends have gone out yet")
    return _send_to_out(db, send)


@router.get("/loopwire-sends", response_model=list[LoopwireSendSummaryOut])
def list_loopwire_sends(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(LoopwireSend).filter(LoopwireSend.user_id == current_user.id).order_by(LoopwireSend.id.desc()).all()


@router.get("/loopwire-sends/{send_id}", response_model=LoopwireSendOut)
def get_loopwire_send(send_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _send_to_out(db, _own_send(db, send_id, current_user))


@router.post("/loopwire-sends/{send_id}/viewed")
def mark_send_viewed(send_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The dashboard showing a dispatch = the user saw it (send-level exposure,
    never per-item 'opened')."""
    mark_send_opened(db, _own_send(db, send_id, current_user).id)
    return {"ok": True}


@router.get("/items", response_model=list[SavedItemOut])
def list_items(
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SavedItem).filter(SavedItem.user_id == current_user.id).order_by(SavedItem.added_at.desc())
    if status == "sent":
        query = query.filter(SavedItem.loopwire_send_id.isnot(None))
    elif status:
        query = query.filter(SavedItem.status == status, SavedItem.loopwire_send_id.is_(None))
    items = query.limit(max(1, min(limit, 200))).all()
    return [
        SavedItemOut(
            item_id=item.id,
            title=item.title or item.url,
            url=item.url,
            type=item.type,
            status=item.status,
            extraction_error=item.extraction_error or item.summarization_error,
            added_at=item.added_at,
            loopwire_send_id=item.loopwire_send_id,
        )
        for item in items
    ]


@router.post("/items/process")
def process_my_items(current_user: User = Depends(get_current_user)):
    return run_process_pending_cycle(user_id=current_user.id)


@router.post("/items/{item_id}/feedback")
def item_feedback(
    item_id: int, payload: FeedbackIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    item = db.query(SavedItem).filter(SavedItem.id == item_id, SavedItem.user_id == current_user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    log_event(db, current_user.id, item_id, EVENT_FEEDBACK_UP if payload.vote == "up" else EVENT_FEEDBACK_DOWN)
    return {"ok": True, "vote": payload.vote}


@router.get("/stats")
def stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_stats(db, current_user.id)


@router.get("/interest-profile", response_model=InterestProfileOut)
def get_interest_profile(current_user: User = Depends(get_current_user)):
    return InterestProfileOut(profile_text=current_user.interest_profile_text)


@router.put("/interest-profile", response_model=InterestProfileOut)
def update_interest_profile(
    payload: InterestProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    text = payload.profile_text.strip() or None
    if text != current_user.interest_profile_text:
        current_user.interest_profile_text = text
        current_user.interest_profile_embedding = None  # re-embedded lazily at next dispatch
        db.commit()
    return InterestProfileOut(profile_text=current_user.interest_profile_text)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/connect-code", response_model=ConnectionCodeOut)
def create_connection_code(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    db.add(ConnectionCode(code=code, user_id=current_user.id))
    db.commit()
    return ConnectionCodeOut(code=code, expires_in_minutes=CONNECTION_CODE_TTL_MINUTES)


@router.get("/profile-status", response_model=ProfileStatusOut)
def profile_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    n = positive_signal_count(db, current_user.id)
    return ProfileStatusOut(
        engagement_count=n,
        threshold=ADAPTIVE_HALF_WEIGHT_SIGNALS,
        is_adaptive=n >= ADAPTIVE_HALF_WEIGHT_SIGNALS,
        adaptive_weight=round(adaptive_weight(n), 3),
    )


# ── Active recall ─────────────────────────────────────────────────────────────


@router.get("/recall/next", response_model=RecallCardOut)
def recall_next(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = due_cards_query(db, current_user.id)
    card = q.first()
    if card is None:
        raise HTTPException(status_code=404, detail="Nothing due")
    return RecallCardOut(card_id=card.id, question=card.question, source_title=card.item.title or card.item.url,
                         source_url=card.item.url, due_count=q.count())


@router.post("/recall/{card_id}/review", response_model=RecallReviewOut)
async def recall_review(
    card_id: int, payload: RecallReviewIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    card = db.query(RecallCard).filter(RecallCard.id == card_id, RecallCard.user_id == current_user.id).first()
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    if payload.self_verdict:
        verdict, feedback, grader = payload.self_verdict, None, "self"
    elif payload.answer is not None:
        result = await run_in_threadpool(grade_answer, card.question, card.answer, card.evidence_quote, payload.answer)
        verdict, feedback, grader = result.verdict, result.feedback, "llm"
    else:
        raise HTTPException(status_code=422, detail="Provide an answer or a self_verdict")
    apply_review(db, card, verdict, user_answer=payload.answer, feedback=feedback, grader=grader)
    db.commit()
    return RecallReviewOut(verdict=verdict, feedback=feedback, reference_answer=card.answer,  # type: ignore[arg-type]
                           evidence_quote=card.evidence_quote, next_due_at=card.due_at,
                           retired=card.state == RECALL_RETIRED)


@router.get("/recall/stats", response_model=RecallStatsOut)
def recall_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return retention_stats(db, current_user.id)
