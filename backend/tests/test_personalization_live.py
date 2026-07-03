"""Live test for Phase B adaptive ranking (prdv2.md B.3.6).

Creates a throwaway test user, simulates ~20 engagement events with a clear
topical pattern (consistently engaging with AI/ML content, skipping
unrelated content), then confirms the computed interest vector correctly
ranks a new AI-related item above an unrelated one in the next build.

This hits the real Gemini embedding API (cheap, but real - not mocked).
Prints everything so a human can manually eyeball the ranking makes sense,
per the PRD's acceptance bar ("don't just trust that the code ran without
errors").

Run with: uv run python tests/test_personalization_live.py
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.embeddings import compute_embedding
from app.models import (
    EVENT_CLICKED_SOURCE,
    EVENT_OPENED,
    EVENT_SKIPPED,
    ITEM_TYPE_ARTICLE,
    STATUS_SUMMARIZED,
    EngagementEvent,
    SavedItem,
    User,
)
from app.personalization import (
    STRONG_SIMILARITY_THRESHOLD,
    get_ranking_context,
    is_cold_start,
    rank_items_by_similarity,
    total_engagement_count,
)

TEST_EMAIL = "phase-b-ranking-test@example.com"
TEST_GOOGLE_ID = "phase-b-ranking-test-google-id"

# 10 AI/ML-themed summaries (will be opened/clicked - positive signal) and
# 10 clearly unrelated summaries (will be skipped - negative signal).
AI_SUMMARIES = [
    "A deep dive into transformer attention mechanisms and how self-attention scales with sequence length.",
    "How large language models are fine-tuned using reinforcement learning from human feedback.",
    "An overview of retrieval-augmented generation and why grounding LLM outputs in real documents reduces hallucination.",
    "Comparing vector databases for storing embeddings at scale, from pgvector to dedicated ANN indexes.",
    "A practical guide to prompt engineering for structured JSON output from Gemini and GPT models.",
    "Why chain-of-thought prompting improves reasoning benchmarks in modern language models.",
    "The tradeoffs between fine-tuning and in-context learning for domain-specific AI applications.",
    "How diffusion models generate images by iteratively denoising random noise.",
    "An explainer on mixture-of-experts architectures and their role in scaling large models efficiently.",
    "Benchmarking open-source LLMs against proprietary APIs on coding and reasoning tasks.",
]
UNRELATED_SUMMARIES = [
    "A step-by-step recipe for making sourdough bread from a homemade starter.",
    "Tips for improving your golf swing and lowering your handicap this season.",
    "A history of the Renaissance art movement and its major painters in Florence.",
    "How to train for your first marathon in sixteen weeks as a beginner runner.",
    "A guide to identifying common houseplant pests and treating them naturally.",
    "The best budget travel destinations in Southeast Asia for backpackers.",
    "How professional chefs sharpen and maintain kitchen knives at home.",
    "A beginner's guide to birdwatching in North American wetlands.",
    "The rules and scoring system of competitive curling explained.",
    "How to properly season and care for a cast iron skillet for decades of use.",
]

# Two brand-new, not-yet-sent items: one AI-related, one unrelated - the
# actual thing we're ranking.
NEW_AI_ITEM_SUMMARY = "A new technique for reducing GPU memory usage during LLM inference using quantization."
NEW_UNRELATED_ITEM_SUMMARY = "A guide to composting kitchen scraps for a home vegetable garden."


def main() -> None:
    with SessionLocal() as db:
        # Clean slate for repeatable runs.
        existing = db.query(User).filter(User.google_id == TEST_GOOGLE_ID).first()
        if existing:
            db.query(EngagementEvent).filter(EngagementEvent.user_id == existing.id).delete()
            db.query(SavedItem).filter(SavedItem.user_id == existing.id).delete()
            db.delete(existing)
            db.commit()

        user = User(email=TEST_EMAIL, google_id=TEST_GOOGLE_ID)
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created test user #{user.id}")

        # Past items: 10 AI (engaged) + 10 unrelated (skipped).
        for i, summary in enumerate(AI_SUMMARIES):
            item = SavedItem(
                user_id=user.id, url=f"https://example.com/ai-{i}", type=ITEM_TYPE_ARTICLE,
                status=STATUS_SUMMARIZED, title=f"AI article {i}", summary=summary,
                estimated_read_time_minutes=5, summarized_at=dt.datetime.now(dt.timezone.utc),
                embedding=compute_embedding(summary),
            )
            db.add(item)
            db.flush()
            event_type = EVENT_CLICKED_SOURCE if i % 2 == 0 else EVENT_OPENED
            db.add(EngagementEvent(user_id=user.id, item_id=item.id, event_type=event_type))

        for i, summary in enumerate(UNRELATED_SUMMARIES):
            item = SavedItem(
                user_id=user.id, url=f"https://example.com/unrelated-{i}", type=ITEM_TYPE_ARTICLE,
                status=STATUS_SUMMARIZED, title=f"Unrelated article {i}", summary=summary,
                estimated_read_time_minutes=5, summarized_at=dt.datetime.now(dt.timezone.utc),
                embedding=compute_embedding(summary),
            )
            db.add(item)
            db.flush()
            db.add(EngagementEvent(user_id=user.id, item_id=item.id, event_type=EVENT_SKIPPED))

        db.commit()

        count = total_engagement_count(db, user.id)
        cold = is_cold_start(db, user.id)
        print(f"Total engagement events: {count} (cold_start={cold}, threshold=15)")
        assert not cold, "Test setup should clear the cold-start threshold"

        # The two new candidate items - not yet sent, not yet engaged with.
        new_ai_item = SavedItem(
            user_id=user.id, url="https://example.com/new-ai-item", type=ITEM_TYPE_ARTICLE,
            status=STATUS_SUMMARIZED, title="New: LLM inference optimization", summary=NEW_AI_ITEM_SUMMARY,
            estimated_read_time_minutes=4, summarized_at=dt.datetime.now(dt.timezone.utc),
            embedding=compute_embedding(NEW_AI_ITEM_SUMMARY),
        )
        new_unrelated_item = SavedItem(
            user_id=user.id, url="https://example.com/new-unrelated-item", type=ITEM_TYPE_ARTICLE,
            status=STATUS_SUMMARIZED, title="New: composting guide", summary=NEW_UNRELATED_ITEM_SUMMARY,
            estimated_read_time_minutes=4, summarized_at=dt.datetime.now(dt.timezone.utc),
            embedding=compute_embedding(NEW_UNRELATED_ITEM_SUMMARY),
        )
        db.add(new_ai_item)
        db.add(new_unrelated_item)
        db.commit()

        # Exercise the real ranking path.
        vector, cold_start_flag = get_ranking_context(db, user)
        db.commit()  # persists user.interest_vector, set as a side effect of get_ranking_context
        print(f"is_cold_start for ranking: {cold_start_flag}")
        assert vector is not None, "Expected a real computed interest vector, not None"

        candidates = [new_unrelated_item, new_ai_item]  # deliberately unrelated-first, to prove reordering happens
        ranked = rank_items_by_similarity(candidates, vector)

        print("\n=== Ranking result (highest affinity first) ===")
        for item in ranked:
            from app.embeddings import cosine_similarity

            score = cosine_similarity(item.embedding, vector)
            print(f"  {score:.4f}  {item.title}")

        top_item = ranked[0]
        print(f"\nTop-ranked item: {top_item.title!r}")
        if top_item.id == new_ai_item.id:
            print("PASS: the AI-related item correctly ranked above the unrelated one.")
        else:
            print("FAIL: the unrelated item ranked first - ranking is not behaving as expected.")

        print(f"\n(STRONG_SIMILARITY_THRESHOLD for grounded relevance notes is {STRONG_SIMILARITY_THRESHOLD})")

        # Cleanup - this is a throwaway test user.
        db.query(EngagementEvent).filter(EngagementEvent.user_id == user.id).delete()
        db.query(SavedItem).filter(SavedItem.user_id == user.id).delete()
        db.delete(user)
        db.commit()
        print("\nCleaned up test user and data.")


if __name__ == "__main__":
    main()
