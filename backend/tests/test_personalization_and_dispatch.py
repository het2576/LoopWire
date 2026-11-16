import datetime as dt

import pytest

from app import models
from app.embeddings import cosine_similarity
from app.engagement import infer_skipped_events, log_event, mark_send_opened
from app.loopwire_send import EXPLORATION_NOTE, build_loopwire_send, sent_today
from app.personalization import (
    RankingContext,
    adaptive_weight,
    get_ranking_context,
    rank_items,
    weighted_interest_vector,
)
from tests.conftest import topic_vec

NOW = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr("app.personalization.compute_embedding", lambda text: topic_vec(0))
    monkeypatch.setattr("app.summarize.generate_grounded_relevance_note",
                        lambda title, summary, similar_titles: f"Like {similar_titles[0]}")


# ── pure ranking math ─────────────────────────────────────────────────────────

def test_negative_only_history_yields_no_direction():
    """v1: 15 skips made a user 'adaptive' with a vector of pure negatives."""
    signals = [(topic_vec(1), "skipped", NOW)] * 20
    assert weighted_interest_vector(signals, NOW) is None


def test_feedback_outweighs_click_and_down_pulls_away():
    up = weighted_interest_vector([(topic_vec(1), "feedback_up", NOW), (topic_vec(2), "clicked_source", NOW)], NOW)
    assert cosine_similarity(up, topic_vec(1)) > cosine_similarity(up, topic_vec(2))
    mixed = weighted_interest_vector([(topic_vec(1), "clicked_source", NOW), (topic_vec(2), "feedback_down", NOW)], NOW)
    assert cosine_similarity(mixed, topic_vec(2)) < 0


def test_recency_decay_prefers_recent_interest():
    old = NOW - dt.timedelta(days=180)
    vec = weighted_interest_vector([(topic_vec(1), "clicked_source", old), (topic_vec(2), "clicked_source", NOW)], NOW)
    assert cosine_similarity(vec, topic_vec(2)) > cosine_similarity(vec, topic_vec(1))


def test_adaptive_weight_is_smooth():
    assert adaptive_weight(0) == 0.0
    assert adaptive_weight(models.ADAPTIVE_HALF_WEIGHT_SIGNALS) == 0.5
    assert 0.9 < adaptive_weight(50) < 1.0


class _Item:
    def __init__(self, id, topic=None, status=models.STATUS_SUMMARIZED):
        self.id, self.status = id, status
        self.embedding = topic_vec(topic) if topic is not None else None


def test_rank_items_orders_by_score_and_puts_failures_last():
    ctx = RankingContext(interest_vector=topic_vec(1), profile_vector=None, alpha=1.0, n_positive=10)
    items = [_Item(1, 2), _Item(2, None, models.STATUS_EXTRACTION_FAILED), _Item(3, 1), _Item(4, None)]
    ranked = [r.item.id for r in rank_items(items, ctx, explore=False)]
    assert ranked == [3, 1, 4, 2]


def test_exploration_slot_only_when_adaptive_and_enough_items():
    adaptive = RankingContext(interest_vector=topic_vec(1), profile_vector=topic_vec(1), alpha=0.8, n_positive=20)
    items = [_Item(i, 1 if i < 4 else 9) for i in range(1, 6)]  # item 5 is off-topic
    ranked = rank_items(items, adaptive)
    assert ranked[2].item.id == 5 and ranked[2].is_exploration
    assert sum(r.is_exploration for r in ranked) == 1

    cold = RankingContext(interest_vector=None, profile_vector=topic_vec(1), alpha=0.0, n_positive=0)
    assert not any(r.is_exploration for r in rank_items(items, cold))
    assert not any(r.is_exploration for r in rank_items(items[:3], adaptive))


# ── signals in the DB ─────────────────────────────────────────────────────────

def test_skips_only_inferred_for_opened_sends(db, make_user, make_item):
    user = make_user()
    two_days_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    unopened, opened = (models.LoopwireSend(user_id=user.id, item_count=1, sent_at=two_days_ago) for _ in range(2))
    latest = models.LoopwireSend(user_id=user.id, item_count=1)  # sent just now: still inside the grace window
    db.add_all([unopened, opened, latest])
    db.commit()
    a = make_item(user, loopwire_send_id=unopened.id)
    b = make_item(user, loopwire_send_id=opened.id)
    c = make_item(user, loopwire_send_id=opened.id)
    make_item(user, loopwire_send_id=opened.id, status=models.STATUS_EXTRACTION_FAILED)
    make_item(user, loopwire_send_id=latest.id)
    mark_send_opened(db, opened.id)
    log_event(db, user.id, c.id, models.EVENT_CLICKED_SOURCE)

    assert infer_skipped_events(db, user.id) == 1
    skipped = {e.item_id for e in db.query(models.EngagementEvent).filter_by(event_type="skipped")}
    assert skipped == {b.id}
    assert a.id not in skipped
    assert infer_skipped_events(db, user.id) == 0  # idempotent

    log_event(db, user.id, b.id, models.EVENT_FEEDBACK_UP)  # explicit beats inferred
    db.expire_all()
    assert {e.event_type for e in db.query(models.EngagementEvent).filter_by(item_id=b.id)} == {"feedback_up"}


def test_previous_dispatch_skips_reach_the_next_ranking(db, make_user, make_item):
    """Regression: the cron cycle infers skips *before* building the next
    dispatch. Yesterday's opened-but-ignored item must count by then, even
    though yesterday's send is still the user's latest one."""
    user = make_user()
    yesterday = models.LoopwireSend(user_id=user.id, item_count=2,
                                    sent_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=24))
    db.add(yesterday)
    db.commit()
    read, ignored = make_item(user, loopwire_send_id=yesterday.id), make_item(user, loopwire_send_id=yesterday.id)
    mark_send_opened(db, yesterday.id)
    log_event(db, user.id, read.id, models.EVENT_CLICKED_SOURCE)

    assert infer_skipped_events(db, user.id) == 1
    assert {e.item_id for e in db.query(models.EngagementEvent).filter_by(event_type="skipped")} == {ignored.id}


def test_cold_start_ranks_by_profile_then_blends_history(db, make_user, make_item):
    user = make_user(profile="I like topic zero")
    ctx = get_ranking_context(db, user)
    assert ctx.alpha == 0 and ctx.interest_vector is None and ctx.profile_vector == topic_vec(0)

    for _ in range(models.ADAPTIVE_HALF_WEIGHT_SIGNALS):
        log_event(db, user.id, make_item(user, topic=3).id, models.EVENT_CLICKED_SOURCE)
    ctx = get_ranking_context(db, user)
    assert ctx.alpha == 0.5 and ctx.is_adaptive
    assert cosine_similarity(ctx.interest_vector, topic_vec(3)) > 0.99


# ── dispatch assembly ─────────────────────────────────────────────────────────

def test_build_send_persists_rank_and_upgrades_notes(db, make_user, make_item):
    user = make_user(profile="topic zero")
    for _ in range(6):
        it = make_item(user, topic=3, title="Past favourite")
        it.loopwire_send_id = None
        log_event(db, user.id, it.id, models.EVENT_CLICKED_SOURCE)
    # mark history as already sent so it's not re-bundled
    old = models.LoopwireSend(user_id=user.id, item_count=6, sent_at=NOW - dt.timedelta(days=2))
    db.add(old)
    db.commit()
    db.query(models.SavedItem).update({"loopwire_send_id": old.id})
    db.commit()

    on_topic = make_item(user, topic=3, relevance_note="General interest")
    off_topic = make_item(user, topic=7, relevance_note="General interest")
    failed = make_item(user, status=models.STATUS_EXTRACTION_FAILED, extraction_error="http_404: gone")

    bundle = build_loopwire_send(db, user.id, explore=False)
    assert [v.item_id for v in bundle.items] == [on_topic.id, off_topic.id, failed.id]
    db.refresh(on_topic)
    assert on_topic.dispatch_rank == 0 and on_topic.relevance_note == "Like Past favourite"
    db.refresh(off_topic)
    assert off_topic.relevance_note == "General interest"  # no strong match -> untouched
    assert bundle.items[2].failure_reason == "the page doesn't exist anymore (dead link)"
    assert build_loopwire_send(db, user.id) is None  # nothing left


def test_exploration_pick_gets_honest_note(db, make_user, make_item):
    user = make_user()
    for _ in range(8):
        log_event(db, user.id, make_item(user, topic=3, loopwire_send_id=None).id, models.EVENT_FEEDBACK_UP)
    old = models.LoopwireSend(user_id=user.id, item_count=8)
    db.add(old)
    db.commit()
    db.query(models.SavedItem).update({"loopwire_send_id": old.id})
    db.commit()
    for _ in range(4):
        make_item(user, topic=3)
    explorer = make_item(user, topic=9)
    bundle = build_loopwire_send(db, user.id)
    pick = next(v for v in bundle.items if v.is_exploration)
    assert pick.item_id == explorer.id and pick.relevance_note == EXPLORATION_NOTE


def test_daily_cap_uses_local_day(db, make_user, monkeypatch):
    user = make_user()
    # 23:00 IST yesterday == 17:30 UTC yesterday: different local day
    db.add(models.LoopwireSend(user_id=user.id, item_count=1,
                               sent_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1, hours=1)))
    db.commit()
    assert not sent_today(db, user.id)
    db.add(models.LoopwireSend(user_id=user.id, item_count=1))
    db.commit()
    assert sent_today(db, user.id)


def test_email_is_escaped_and_uses_one_send_pixel(db, make_user, make_item):
    from app.email_delivery import render_loopwire_html, render_loopwire_text

    user = make_user()
    make_item(user, title='<img src=x onerror="alert(1)">Evil', summary="<a href='http://phish'>click</a>")
    make_item(user)
    bundle = build_loopwire_send(db, user.id)
    html = render_loopwire_html(bundle, "daily")
    assert "<img src=x" not in html and "<a href='http://phish'>" not in html
    assert html.count("/track/send/") == 1 and "/track/opened/" not in html
    assert "/r/1\"" not in html and "/r/2\"" not in html  # no bare sequential ids
    assert html.count("/f/") == 4  # up + down per summarized item
    text = render_loopwire_text(bundle, "daily")
    assert "More like this:" in text
