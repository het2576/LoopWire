import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class LoopwireItemOut(BaseModel):
    item_id: int
    title: str
    type: str
    source_url: str
    read_url: str
    couldnt_extract: bool
    failure_reason: str | None = None
    summary: str | None = None
    key_takeaway: str | None = None
    relevance_note: str | None = None
    read_time_minutes: int | None = None
    is_exploration: bool = False
    feedback: Literal["up", "down"] | None = None


class LoopwireSendOut(BaseModel):
    id: int
    period: str
    sent_at: dt.datetime
    item_count: int
    items: list[LoopwireItemOut]


class LoopwireSendSummaryOut(BaseModel):
    id: int
    period: str
    sent_at: dt.datetime
    item_count: int


class SavedItemOut(BaseModel):
    item_id: int
    title: str
    url: str
    type: str
    status: str
    extraction_error: str | None = None
    added_at: dt.datetime
    loopwire_send_id: int | None = None


class InterestProfileOut(BaseModel):
    profile_text: str | None


class InterestProfileUpdate(BaseModel):
    profile_text: str = Field(max_length=2000)


class UserOut(BaseModel):
    id: int
    email: str
    telegram_chat_id: int | None = None
    interest_profile_text: str | None = None


class UpsertUserRequest(BaseModel):
    email: str
    google_id: str


class ConnectionCodeOut(BaseModel):
    code: str
    expires_in_minutes: int


class ProfileStatusOut(BaseModel):
    # engagement_count/threshold kept for dashboard compatibility; they now
    # count positive signals (clicks + upvotes), not raw events.
    engagement_count: int
    threshold: int
    is_adaptive: bool
    adaptive_weight: float


class FeedbackIn(BaseModel):
    vote: Literal["up", "down"]


class RecallCardOut(BaseModel):
    card_id: int
    question: str
    source_title: str
    source_url: str
    due_count: int


class RecallReviewIn(BaseModel):
    """Either type an answer (graded by the LLM) or reveal and self-grade."""

    answer: str | None = Field(default=None, max_length=2000)
    self_verdict: Literal["correct", "partial", "incorrect"] | None = None


class RecallReviewOut(BaseModel):
    verdict: Literal["correct", "partial", "incorrect"]
    feedback: str | None
    reference_answer: str
    evidence_quote: str
    next_due_at: dt.datetime | None
    retired: bool


class RecallStatsOut(BaseModel):
    reviews: int
    correct: int
    partial: int
    retention_rate: float | None
    cards_total: int
    cards_active: int
    cards_retired: int
    cards_due: int
