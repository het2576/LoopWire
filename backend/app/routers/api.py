import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user, verify_internal_secret
from app.config import get_settings
from app.db import get_db
from app.engagement import get_stats, log_event
from app.models import COLD_START_ENGAGEMENT_THRESHOLD, EVENT_OPENED, ConnectionCode, LoopwireSend, SavedItem, User
from app.personalization import is_cold_start, total_engagement_count
from app.schemas import (
    ConnectionCodeOut,
    InterestProfileOut,
    InterestProfileUpdate,
    LoopwireItemOut,
    LoopwireSendOut,
    LoopwireSendSummaryOut,
    ProfileStatusOut,
    SavedItemOut,
    UpsertUserRequest,
    UserOut,
)

router = APIRouter(prefix="/api")

CONNECTION_CODE_TTL_MINUTES = 15
CODE_ALPHABET = string.ascii_uppercase + string.digits


def _send_to_out(send: LoopwireSend, items: list[SavedItem]) -> LoopwireSendOut:
    settings = get_settings()
    return LoopwireSendOut(
        id=send.id,
        period=send.period,
        sent_at=send.sent_at,
        item_count=send.item_count,
        items=[
            LoopwireItemOut(
                item_id=item.id,
                title=item.title or item.url,
                type=item.type,
                source_url=item.url,
                read_url=f"{settings.backend_base_url}/r/{item.id}",
                couldnt_extract=item.status == "extraction_failed",
                summary=item.summary,
                key_takeaway=item.key_takeaway,
                relevance_note=item.relevance_note,
                read_time_minutes=item.estimated_read_time_minutes,
            )
            for item in sorted(items, key=lambda i: i.id)
        ],
    )


# ── First-login provisioning (no user_id yet - internal-secret only) ────────


@router.post("/auth/upsert-user", response_model=UserOut)
def upsert_user(payload: UpsertUserRequest, db: Session = Depends(get_db), _=Depends(verify_internal_secret)):
    """Called by NextAuth's jwt callback on first sign-in. Creates the User
    row if it doesn't exist yet, otherwise returns the existing one."""
    user = db.query(User).filter(User.google_id == payload.google_id).first()
    if user is None:
        user = User(email=payload.email, google_id=payload.google_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ── Authenticated routes (every query below is scoped to current_user) ─────


@router.get("/loopwire-sends/latest", response_model=LoopwireSendOut)
def latest_loopwire_send(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    send = (
        db.query(LoopwireSend)
        .filter(LoopwireSend.user_id == current_user.id)
        .order_by(LoopwireSend.id.desc())
        .first()
    )
    if send is None:
        raise HTTPException(status_code=404, detail="No sends have gone out yet")
    return _send_to_out(send, send.items)


@router.get("/loopwire-sends", response_model=list[LoopwireSendSummaryOut])
def list_loopwire_sends(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sends = (
        db.query(LoopwireSend)
        .filter(LoopwireSend.user_id == current_user.id)
        .order_by(LoopwireSend.id.desc())
        .all()
    )
    return sends


@router.get("/loopwire-sends/{send_id}", response_model=LoopwireSendOut)
def get_loopwire_send(send_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    send = (
        db.query(LoopwireSend)
        .filter(LoopwireSend.id == send_id, LoopwireSend.user_id == current_user.id)
        .first()
    )
    if send is None:
        raise HTTPException(status_code=404, detail="Send not found")
    return _send_to_out(send, send.items)


@router.get("/items", response_model=list[SavedItemOut])
def list_items(
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every saved item this user has ever forwarded, regardless of whether
    it's been bundled into a dispatch yet - the dashboard's "Wire" page."""
    query = db.query(SavedItem).filter(SavedItem.user_id == current_user.id).order_by(SavedItem.added_at.desc())
    if status == "sent":
        # "sent" isn't a status value that's ever actually stored (see
        # STATUS_SENT note in models.py) - delivery is tracked separately via
        # loopwire_send_id, so filter on that instead.
        query = query.filter(SavedItem.loopwire_send_id.isnot(None))
    elif status:
        # Any other filter means "still in this processing state and not yet
        # delivered" - once sent, an item belongs in the "sent" filter only.
        query = query.filter(SavedItem.status == status, SavedItem.loopwire_send_id.is_(None))
    items = query.limit(min(limit, 200)).all()
    return [
        SavedItemOut(
            item_id=item.id,
            title=item.title or item.url,
            url=item.url,
            type=item.type,
            status=item.status,
            extraction_error=item.extraction_error,
            added_at=item.added_at,
            loopwire_send_id=item.loopwire_send_id,
        )
        for item in items
    ]


@router.post("/items/{item_id}/opened")
def mark_opened(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(SavedItem).filter(SavedItem.id == item_id, SavedItem.user_id == current_user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    log_event(db, current_user.id, item_id, EVENT_OPENED)
    return {"ok": True}


@router.get("/stats")
def stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_stats(db, current_user.id)


@router.get("/interest-profile", response_model=InterestProfileOut)
def get_interest_profile(current_user: User = Depends(get_current_user)):
    return InterestProfileOut(profile_text=current_user.interest_profile_text)


@router.put("/interest-profile", response_model=InterestProfileOut)
def update_interest_profile(
    payload: InterestProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.interest_profile_text = payload.profile_text
    db.commit()
    return InterestProfileOut(profile_text=current_user.interest_profile_text)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/connect-code", response_model=ConnectionCodeOut)
def create_connection_code(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Generates a short-lived code the user sends to the Telegram bot via
    /connect <code> to link their chat_id to this account."""
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    db.add(ConnectionCode(code=code, user_id=current_user.id))
    db.commit()
    return ConnectionCodeOut(code=code, expires_in_minutes=CONNECTION_CODE_TTL_MINUTES)


@router.get("/profile-status", response_model=ProfileStatusOut)
def profile_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Cold-start progress (prdv2.md bonus UX item) - how close this user is
    to enough engagement history for adaptive ranking to kick in."""
    count = total_engagement_count(db, current_user.id)
    return ProfileStatusOut(
        engagement_count=count,
        threshold=COLD_START_ENGAGEMENT_THRESHOLD,
        is_adaptive=not is_cold_start(db, current_user.id),
    )
