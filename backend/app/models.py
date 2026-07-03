import datetime as dt

from sqlalchemy import ARRAY, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# saved_items.type
ITEM_TYPE_ARTICLE = "article"
ITEM_TYPE_YOUTUBE = "youtube"
ITEM_TYPE_REDDIT = "reddit"
ITEM_TYPE_GITHUB = "github"
ITEM_TYPE_HN = "hn"
ITEM_TYPE_PDF = "pdf"
ITEM_TYPE_UNSUPPORTED = "unsupported"

# saved_items.status
STATUS_PENDING = "pending"
STATUS_EXTRACTED = "extracted"
STATUS_EXTRACTION_FAILED = "extraction_failed"
STATUS_SUMMARIZED = "summarized"
STATUS_SENT = "sent"

# engagement_events.event_type
EVENT_OPENED = "opened"
EVENT_CLICKED_SOURCE = "clicked_source"
EVENT_SKIPPED = "skipped"

# Per-user daily caps (Phase A, prdv2.md A.3.5) - protects shared free-tier
# API quota from one user exhausting it.
MAX_SAVED_LINKS_PER_DAY = 10
MAX_SENDS_PER_DAY = 1

# Phase B (prdv2.md B.3.3): below this many total engagement events, a
# user's interest vector is too noisy to rank on - fall back to their
# static interest_profile_text instead. Named constant so it's easy to
# tune, not a magic number buried in ranking logic.
COLD_START_ENGAGEMENT_THRESHOLD = 15

EMBEDDING_DIMENSIONS = 768


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    google_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)

    # Static fallback profile (Phase B cold-start rule uses this until enough
    # engagement data exists). Nullable - blank until the user sets it via
    # /setprofile or the dashboard settings page.
    interest_profile_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase B: weighted average of engaged items' embeddings, recomputed
    # before each send (not real-time on every event - prdv2.md B.3.2).
    # Null until the user clears the cold-start threshold.
    interest_vector: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    saved_items: Mapped[list["SavedItem"]] = relationship(back_populates="user")
    loopwire_sends: Mapped[list["LoopwireSend"]] = relationship(back_populates="user")


class ConnectionCode(Base):
    """Short-lived code linking a Telegram chat to a dashboard account
    (prdv2.md A.3.4). Validity window is enforced in code (15 min), not a
    DB constraint - no cleanup job needed at this scale."""

    __tablename__ = "connection_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()


class SavedItem(Base):
    __tablename__ = "saved_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default=ITEM_TYPE_UNSUPPORTED)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING)

    raw_message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Extraction results
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_success: Mapped[bool | None] = mapped_column(nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Summarization results
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_takeaway: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_read_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summarized_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Phase B: embedding of the summary text, computed once at summarize
    # time (prdv2.md B.3.1). Used for both ranking and finding similar
    # past-engaged items for grounded relevance notes.
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    # Delivery
    loopwire_send_id: Mapped[int | None] = mapped_column(ForeignKey("loopwire_sends.id"), nullable=True)

    user: Mapped["User"] = relationship(back_populates="saved_items")
    loopwire_send: Mapped["LoopwireSend | None"] = relationship(back_populates="items")
    engagement_events: Mapped[list["EngagementEvent"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class LoopwireSend(Base):
    """A single periodic bundle of summarized items sent out (email + web),
    scoped to one user - Phase A makes sends per-user instead of global."""

    __tablename__ = "loopwire_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    period: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_sent: Mapped[bool] = mapped_column(default=False)

    user: Mapped["User"] = relationship(back_populates="loopwire_sends")
    items: Mapped[list["SavedItem"]] = relationship(back_populates="loopwire_send")


class EngagementEvent(Base):
    __tablename__ = "engagement_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("saved_items.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["SavedItem"] = relationship(back_populates="engagement_events")
