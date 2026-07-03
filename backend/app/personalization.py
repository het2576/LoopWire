"""Adaptive personalization (Phase B, prdv2.md B.3).

Ranks a user's pending dispatch items by similarity to what they've
actually engaged with, instead of chronological order or a static bio -
falling back to the static profile for cold-start users who don't have
enough engagement history yet to trust a computed vector (B.3.3).
"""

from sqlalchemy.orm import Session

from app.embeddings import compute_embedding, cosine_similarity
from app.models import (
    COLD_START_ENGAGEMENT_THRESHOLD,
    EVENT_CLICKED_SOURCE,
    EVENT_OPENED,
    EVENT_SKIPPED,
    EngagementEvent,
    SavedItem,
    User,
)

# Weights for the interest-vector weighted average (B.3.2). Clicking through
# to the source is the strongest positive signal; opening without clicking
# is weaker positive; an explicitly-inferred skip is *subtracted*, not just
# excluded, so consistently-skipped topics actively pull the vector away.
ENGAGEMENT_WEIGHTS = {
    EVENT_CLICKED_SOURCE: 2.0,
    EVENT_OPENED: 1.0,
    EVENT_SKIPPED: -0.5,
}

# Above this cosine similarity, a past-engaged item counts as strong enough
# evidence to name directly in a relevance note ("similar to X you read
# last week"). Below it, we fall back to a generic note instead of
# stretching a weak match into a claim. Named constant so it's easy to
# recalibrate once there's real usage data to tune against.
STRONG_SIMILARITY_THRESHOLD = 0.82


def total_engagement_count(db: Session, user_id: int) -> int:
    return db.query(EngagementEvent).filter(EngagementEvent.user_id == user_id).count()


def is_cold_start(db: Session, user_id: int) -> bool:
    return total_engagement_count(db, user_id) < COLD_START_ENGAGEMENT_THRESHOLD


def compute_interest_vector(db: Session, user_id: int) -> list[float] | None:
    """Weighted average of engaged items' embeddings. Returns None if
    there's nothing to compute from yet (no embedded, engaged items)."""
    events = (
        db.query(EngagementEvent)
        .join(SavedItem, SavedItem.id == EngagementEvent.item_id)
        .filter(EngagementEvent.user_id == user_id)
        .filter(SavedItem.embedding.isnot(None))
        .all()
    )

    weighted_sum: list[float] | None = None
    total_abs_weight = 0.0

    for event in events:
        weight = ENGAGEMENT_WEIGHTS.get(event.event_type, 0.0)
        embedding = event.item.embedding
        if weight == 0.0 or not embedding:
            continue
        if weighted_sum is None:
            weighted_sum = [0.0] * len(embedding)
        elif len(embedding) != len(weighted_sum):
            continue  # shouldn't happen (fixed EMBEDDING_DIMENSIONS), but guard anyway

        for i, value in enumerate(embedding):
            weighted_sum[i] += value * weight
        # Normalize by total *magnitude* of weight, not the signed sum - if
        # skips ever outweighed positive signals, dividing by a signed sum
        # near zero (or negative) would blow up or flip the vector's
        # direction, which isn't what "weighted average" should mean here.
        total_abs_weight += abs(weight)

    if weighted_sum is None or total_abs_weight == 0:
        return None

    return [v / total_abs_weight for v in weighted_sum]


def get_ranking_context(db: Session, user: User) -> tuple[list[float] | None, bool]:
    """Returns (ranking_vector, is_cold_start). ranking_vector is None only
    when there's truly nothing to rank on (no static profile and no
    engagement history yet) - callers should fall back to chronological
    order in that case."""
    if is_cold_start(db, user.id):
        if user.interest_profile_text:
            return compute_embedding(user.interest_profile_text), True
        return None, True

    vector = compute_interest_vector(db, user.id)
    if vector is None:
        # Cleared the engagement threshold but no embedded engaged items yet
        # (e.g. all prior engagement predates Phase B) - fall back to the
        # static profile if there is one, rather than an empty vector.
        if user.interest_profile_text:
            return compute_embedding(user.interest_profile_text), True
        return None, True

    # Recomputed before each send rather than in real time on every event
    # (B.3.2) - this is the one place it's persisted.
    user.interest_vector = vector
    return vector, False


def find_similar_engaged_items(
    db: Session, user_id: int, item_embedding: list[float], exclude_item_id: int, top_k: int = 2
) -> list[tuple[SavedItem, float]]:
    """Among items this user has actually opened/clicked before, finds the
    top-k most similar to a candidate new item - concrete evidence for the
    grounded relevance note (B.3.5). Returns (item, similarity) pairs."""
    engaged_item_ids = [
        row[0]
        for row in (
            db.query(EngagementEvent.item_id)
            .filter(EngagementEvent.user_id == user_id)
            .filter(EngagementEvent.event_type.in_([EVENT_OPENED, EVENT_CLICKED_SOURCE]))
            .filter(EngagementEvent.item_id != exclude_item_id)
            .distinct()
            .all()
        )
    ]
    if not engaged_item_ids:
        return []

    candidates = (
        db.query(SavedItem)
        .filter(SavedItem.id.in_(engaged_item_ids))
        .filter(SavedItem.embedding.isnot(None))
        .all()
    )
    scored = [(item, cosine_similarity(item_embedding, item.embedding)) for item in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def rank_items_by_similarity(items: list[SavedItem], vector: list[float] | None) -> list[SavedItem]:
    """Orders pending dispatch items by similarity to the ranking vector,
    highest affinity first. Items without an embedding (e.g. extraction
    failed before summarization ever ran) sort last, keeping the "couldn't
    extract" cards at the bottom rather than randomly interleaved."""
    if vector is None:
        return items

    def score(item: SavedItem) -> float:
        if not item.embedding:
            return -1.0
        return cosine_similarity(item.embedding, vector)

    return sorted(items, key=score, reverse=True)
