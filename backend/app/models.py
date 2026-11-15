import datetime as dt

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
# Summarization raised MAX_PROCESSING_ATTEMPTS times in a row. Previously a
# poison item stayed "extracted" and was retried on every cron tick forever,
# burning LLM quota; now it's surfaced like an extraction failure.
STATUS_SUMMARIZATION_FAILED = "summarization_failed"
# Display-only: delivery is tracked via loopwire_send_id, never stored here.
STATUS_SENT = "sent"

FAILED_STATUSES = (STATUS_EXTRACTION_FAILED, STATUS_SUMMARIZATION_FAILED)
DISPATCHABLE_STATUSES = (STATUS_SUMMARIZED, *FAILED_STATUSES)

MAX_PROCESSING_ATTEMPTS = 3
# A worker that claimed an item but died (Render restart mid-pass) shouldn't
# hold it forever - after this long the claim is considered abandoned.
PROCESSING_LEASE_MINUTES = 10

# engagement_events.event_type
#
# There is deliberately no per-item "opened" event any more. The old design
# put one tracking pixel per item in the email (and marked every item opened
# on dashboard page load), so opening a 10-item dispatch logged 10 "opened"
# events at once - the signal measured "was sent", not "was read", and it
# dominated both the interest vector and the cold-start counter. Exposure is
# now tracked once per *send* (LoopwireSend.opened_at), and only actions that
# single out one item count as item-level signal.
EVENT_CLICKED_SOURCE = "clicked_source"
EVENT_FEEDBACK_UP = "feedback_up"
EVENT_FEEDBACK_DOWN = "feedback_down"
EVENT_SKIPPED = "skipped"
POSITIVE_EVENTS = (EVENT_CLICKED_SOURCE, EVENT_FEEDBACK_UP)
FEEDBACK_EVENTS = (EVENT_FEEDBACK_UP, EVENT_FEEDBACK_DOWN)

# Per-user daily caps (Phase A) - protects shared free-tier API quota.
MAX_SAVED_LINKS_PER_DAY = 10
MAX_SENDS_PER_DAY = 1

# Personalization blend (see personalization.py): the interest vector's weight
# is n / (n + ADAPTIVE_HALF_WEIGHT_SIGNALS) where n = positive signals; at n ==
# this constant history and written profile weigh equally (what the UI calls
# "adaptive"). evals/ranking_eval.py (240 simulated users, real embeddings):
# K in 1..5 is a statistical tie (gaps < the +/-0.035 95% CI), smaller K
# slightly ahead at days 7-14; 3 is the most conservative value within noise
# of the best. Re-run the sweep when real usage data exists.
ADAPTIVE_HALF_WEIGHT_SIGNALS = 3

EMBEDDING_DIMENSIONS = 768

# recall_cards.state
RECALL_DORMANT = "dormant"  # item not engaged with yet - no point quizzing unread material
RECALL_ACTIVE = "active"
RECALL_RETIRED = "retired"  # graduated past the last interval

# recall_reviews.verdict
VERDICT_CORRECT = "correct"
VERDICT_PARTIAL = "partial"
VERDICT_INCORRECT = "incorrect"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    google_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)

    interest_profile_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cached embedding of interest_profile_text so it isn't re-embedded on
    # every send; cleared whenever the text changes.
    interest_profile_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    interest_vector: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    recall_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # The card the user was last asked in Telegram; their next non-link
    # message is graded as the answer to it.
    pending_recall_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("recall_cards.id", use_alter=True, ondelete="SET NULL", name="fk_users_pending_recall_card"), nullable=True
    )

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    saved_items: Mapped[list["SavedItem"]] = relationship(back_populates="user")
    loopwire_sends: Mapped[list["LoopwireSend"]] = relationship(back_populates="user")


class ConnectionCode(Base):
    __tablename__ = "connection_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()


class SavedItem(Base):
    __tablename__ = "saved_items"
    __table_args__ = (
        # Re-forwarding the same link (common - you see it twice in two
        # different group chats) used to create a duplicate row, a duplicate
        # LLM call and a duplicate dispatch card.
        UniqueConstraint("user_id", "canonical_url", name="uq_saved_items_user_canonical_url"),
        Index("ix_saved_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default=ITEM_TYPE_UNSUPPORTED)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=STATUS_PENDING)

    raw_message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Processing bookkeeping (claim/lease so the webhook-triggered pass and the
    # cron pass can't both summarize the same item).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processing_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Extraction results
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Real media length for videos (from transcript timestamps), so read time
    # is measured, not guessed by the LLM.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_success: Mapped[bool | None] = mapped_column(nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Summarization results
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_takeaway: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_read_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summarization_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summarized_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    # Delivery
    loopwire_send_id: Mapped[int | None] = mapped_column(
        ForeignKey("loopwire_sends.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Position in the ranked dispatch (0 = top). The API used to re-sort by id,
    # so the personalized order was computed and then thrown away on display.
    dispatch_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_exploration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    user: Mapped["User"] = relationship(back_populates="saved_items")
    loopwire_send: Mapped["LoopwireSend | None"] = relationship(back_populates="items")
    engagement_events: Mapped[list["EngagementEvent"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )
    recall_cards: Mapped[list["RecallCard"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )


class LoopwireSend(Base):
    __tablename__ = "loopwire_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    period: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_sent: Mapped[bool] = mapped_column(default=False)
    # First time the user demonstrably saw this dispatch (email pixel or
    # dashboard view). Skips are only inferred for items in *seen* sends -
    # an unopened email says nothing about whether you liked its contents.
    opened_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="loopwire_sends")
    items: Mapped[list["SavedItem"]] = relationship(back_populates="loopwire_send")


class EngagementEvent(Base):
    __tablename__ = "engagement_events"
    __table_args__ = (UniqueConstraint("item_id", "event_type", name="uq_engagement_item_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("saved_items.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["SavedItem"] = relationship(back_populates="engagement_events")


class RecallCard(Base):
    """An active-recall question generated from one saved item, grounded by a
    verbatim evidence quote from the extracted text (checked in code, not
    trusted from the model). Scheduled with expanding intervals once the user
    has actually engaged with the item."""

    __tablename__ = "recall_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("saved_items.id", ondelete="CASCADE"), nullable=False, index=True)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)

    state: Mapped[str] = mapped_column(String(12), nullable=False, default=RECALL_DORMANT)
    box: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["SavedItem"] = relationship(back_populates="recall_cards")
    reviews_log: Mapped[list["RecallReview"]] = relationship(
        back_populates="card", cascade="all, delete-orphan", passive_deletes=True
    )


class RecallReview(Base):
    __tablename__ = "recall_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("recall_cards.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    grader: Mapped[str] = mapped_column(String(8), nullable=False, default="llm")  # "llm" | "self"
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    card: Mapped["RecallCard"] = relationship(back_populates="reviews_log")
