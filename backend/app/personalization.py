"""Adaptive personalization.

score(item) = a * cos(item, interest_vector) + (1 - a) * cos(item, profile_vector)
a = n_pos / (n_pos + ADAPTIVE_HALF_WEIGHT_SIGNALS)

What changed vs. v1 and why (evals/ranking_eval.py quantifies each):
- Signals: per-item "opened" is gone (it fired for every item whenever the
  email/dashboard loaded, so the vector converged to "the average of
  everything you were sent"). Clicks, explicit feedback and exposure-aware
  skips remain.
- Cold start is a smooth blend, not a hard switch at 15 events. v1 counted
  skips toward the threshold, so a user who ignored everything became
  "adaptive" with a vector made purely of negative weights.
- Recency decay: interests drift; a click from six months ago shouldn't weigh
  the same as yesterday's.
- Optional exploration slot so the dispatch can't collapse onto one topic -
  every item is delivered anyway, but position drives attention, and without
  a chance to engage with off-profile items the model can never learn you
  like them.
"""

import datetime as dt
import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.embeddings import compute_embedding, cosine_similarity
from app.models import (
    ADAPTIVE_HALF_WEIGHT_SIGNALS,
    EVENT_CLICKED_SOURCE,
    EVENT_FEEDBACK_DOWN,
    EVENT_FEEDBACK_UP,
    EVENT_SKIPPED,
    POSITIVE_EVENTS,
    STATUS_SUMMARIZED,
    EngagementEvent,
    SavedItem,
    User,
)

logger = logging.getLogger("loopwire.personalization")

SIGNAL_WEIGHTS = {
    EVENT_FEEDBACK_UP: 2.0,
    EVENT_CLICKED_SOURCE: 1.0,
    EVENT_SKIPPED: -0.3,
    EVENT_FEEDBACK_DOWN: -1.5,
}
RECENCY_HALF_LIFE_DAYS = 45.0

# Above this cosine similarity a past item is named in the relevance note
# ("similar to X, which you clicked"). Calibrated in evals/ranking_eval.py on
# gemini-embedding-001: same-topic pairs median 0.77, cross-topic 0.72. At 0.82
# precision is 1.00 but recall 7% (rarely fires, never wrong); 0.80 doubles
# recall at 0.76 precision. The note makes a factual claim, so precision wins.
STRONG_SIMILARITY_THRESHOLD = 0.82

EXPLORATION_SLOT = 2  # 0-based position the exploration pick is moved to
MIN_ITEMS_FOR_EXPLORATION = 4


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def positive_signal_count(db: Session, user_id: int) -> int:
    return (
        db.query(EngagementEvent.item_id)
        .filter(EngagementEvent.user_id == user_id, EngagementEvent.event_type.in_(POSITIVE_EVENTS))
        .distinct()
        .count()
    )


def adaptive_weight(n_positive: int) -> float:
    return n_positive / (n_positive + ADAPTIVE_HALF_WEIGHT_SIGNALS) if n_positive > 0 else 0.0


def weighted_interest_vector(
    signals: list[tuple[list[float], str, dt.datetime]], now: dt.datetime
) -> list[float] | None:
    """Pure function (shared by the app and the offline ranking eval).
    signals = (embedding, event_type, timestamp). Returns None unless there's
    net positive evidence - negatives alone define what you *don't* want,
    which isn't a direction to rank toward."""
    acc: np.ndarray | None = None
    total_abs = 0.0
    total_pos = 0.0
    for embedding, event_type, ts in signals:
        weight = SIGNAL_WEIGHTS.get(event_type, 0.0)
        if weight == 0.0 or not embedding:
            continue
        vec = np.asarray(embedding, dtype=float)
        norm = np.linalg.norm(vec)
        if norm == 0:
            continue
        age_days = max((now - ts).total_seconds() / 86400.0, 0.0) if ts else 0.0
        w = weight * 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        acc = vec / norm * w if acc is None else acc + vec / norm * w
        total_abs += abs(w)
        if w > 0:
            total_pos += w
    if acc is None or total_pos == 0.0:
        return None
    return (acc / total_abs).tolist()


def compute_interest_vector(db: Session, user_id: int, now: dt.datetime | None = None) -> list[float] | None:
    rows = (
        db.query(SavedItem.embedding, EngagementEvent.event_type, EngagementEvent.timestamp)
        .join(EngagementEvent, EngagementEvent.item_id == SavedItem.id)
        .filter(EngagementEvent.user_id == user_id, SavedItem.embedding.isnot(None))
        .all()
    )
    return weighted_interest_vector([(e, t, ts) for e, t, ts in rows], now or _now())


def profile_embedding(db: Session, user: User) -> list[float] | None:
    if not user.interest_profile_text:
        return None
    if user.interest_profile_embedding is None:
        try:
            user.interest_profile_embedding = compute_embedding(user.interest_profile_text)
        except Exception:
            # A failed embedding call (quota, outage) must not cost the user their
            # dispatch: rank without the written profile and retry next time.
            logger.exception("Profile embedding failed for user #%s - ranking without it", user.id)
            return None
    return user.interest_profile_embedding


@dataclass
class RankingContext:
    interest_vector: list[float] | None
    profile_vector: list[float] | None
    alpha: float
    n_positive: int

    @property
    def is_adaptive(self) -> bool:
        return self.interest_vector is not None and self.alpha >= 0.5

    @property
    def has_signal(self) -> bool:
        return self.interest_vector is not None or self.profile_vector is not None


def score(ctx: RankingContext, embedding: list[float] | None) -> float | None:
    if not embedding or not ctx.has_signal:
        return None
    if ctx.interest_vector is None:
        return cosine_similarity(embedding, ctx.profile_vector)
    if ctx.profile_vector is None:
        return cosine_similarity(embedding, ctx.interest_vector)
    return ctx.alpha * cosine_similarity(embedding, ctx.interest_vector) + (1 - ctx.alpha) * cosine_similarity(
        embedding, ctx.profile_vector
    )


def get_ranking_context(db: Session, user: User) -> RankingContext:
    n_pos = positive_signal_count(db, user.id)
    interest = compute_interest_vector(db, user.id) if n_pos else None
    if interest is not None:
        user.interest_vector = interest  # persisted for inspection/debugging
    return RankingContext(
        interest_vector=interest,
        profile_vector=profile_embedding(db, user),
        alpha=adaptive_weight(n_pos) if interest is not None else 0.0,
        n_positive=n_pos,
    )


@dataclass
class RankedItem:
    item: SavedItem
    score: float | None
    is_exploration: bool = False


def rank_items(items: list[SavedItem], ctx: RankingContext, explore: bool = True) -> list[RankedItem]:
    """Highest affinity first. Unembedded summarized items follow in
    chronological order, and items that couldn't be processed go last so the
    "couldn't extract" cards never interleave with real reading."""
    scored: list[RankedItem] = []
    unscored: list[RankedItem] = []
    failed: list[RankedItem] = []
    for item in items:
        if item.status != STATUS_SUMMARIZED:
            failed.append(RankedItem(item, None))
            continue
        s = score(ctx, item.embedding)
        (scored if s is not None else unscored).append(RankedItem(item, s))
    scored.sort(key=lambda r: r.score, reverse=True)  # type: ignore[arg-type, return-value]

    if explore and ctx.is_adaptive and len(scored) >= MIN_ITEMS_FOR_EXPLORATION:
        # Lowest-affinity item, promoted to a visible-but-not-top slot.
        pick = scored.pop()
        pick.is_exploration = True
        scored.insert(min(EXPLORATION_SLOT, len(scored)), pick)

    return scored + unscored + failed


def find_similar_engaged_items(
    db: Session, user_id: int, item_embedding: list[float], exclude_item_id: int, top_k: int = 2
) -> list[tuple[SavedItem, float]]:
    """Among items the user clicked through to or upvoted (not merely was
    sent), the top-k most similar to a candidate - evidence for the grounded
    relevance note."""
    engaged_ids = (
        db.query(EngagementEvent.item_id)
        .filter(EngagementEvent.user_id == user_id, EngagementEvent.event_type.in_(POSITIVE_EVENTS))
        .filter(EngagementEvent.item_id != exclude_item_id)
        .distinct()
        .scalar_subquery()
    )
    candidates = (
        db.query(SavedItem).filter(SavedItem.id.in_(engaged_ids), SavedItem.embedding.isnot(None)).all()
    )
    scored = [(item, cosine_similarity(item_embedding, item.embedding)) for item in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
