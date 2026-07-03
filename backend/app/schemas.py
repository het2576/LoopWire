import datetime as dt

from pydantic import BaseModel


class LoopwireItemOut(BaseModel):
    item_id: int
    title: str
    type: str
    source_url: str
    read_url: str
    couldnt_extract: bool
    summary: str | None = None
    key_takeaway: str | None = None
    relevance_note: str | None = None
    read_time_minutes: int | None = None


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
    profile_text: str


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
    engagement_count: int
    threshold: int
    is_adaptive: bool
