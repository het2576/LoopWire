"""Authenticated dashboard API: auth bridge, tenant isolation, ranking order,
feedback, recall endpoints."""

import datetime as dt

from app.models import LoopwireSend, RecallCard
from tests.conftest import auth_headers


def test_auth_bridge_rejects_missing_or_wrong_secret(client, make_user):
    user = make_user()
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"X-Internal-Secret": "nope", "X-User-Id": str(user.id)}).status_code == 401
    assert client.get("/api/me", headers={"X-Internal-Secret": "test-internal-secret"}).status_code == 401
    assert client.get("/api/me", headers={"X-Internal-Secret": "test-internal-secret", "X-User-Id": "x"}).status_code == 401
    assert client.get("/api/me", headers=auth_headers(user)).json()["email"] == user.email


def test_tenant_isolation(client, db, make_user, make_item):
    alice, bob = make_user(), make_user()
    item = make_item(alice)
    send = LoopwireSend(user_id=alice.id, item_count=1)
    db.add(send)
    db.commit()
    item.loopwire_send_id = send.id
    db.commit()

    assert client.get(f"/api/loopwire-sends/{send.id}", headers=auth_headers(bob)).status_code == 404
    assert client.get("/api/loopwire-sends/latest", headers=auth_headers(bob)).status_code == 404
    assert client.get("/api/items", headers=auth_headers(bob)).json() == []
    assert client.post(f"/api/items/{item.id}/feedback", json={"vote": "up"},
                       headers=auth_headers(bob)).status_code == 404
    assert client.post(f"/api/loopwire-sends/{send.id}/viewed", headers=auth_headers(bob)).status_code == 404
    assert len(client.get("/api/items", headers=auth_headers(alice)).json()) == 1


def test_dispatch_is_returned_in_ranked_order_not_id_order(client, db, make_user, make_item):
    """v1 re-sorted by id, discarding the personalized ranking on the dashboard."""
    user = make_user()
    send = LoopwireSend(user_id=user.id, item_count=3)
    db.add(send)
    db.commit()
    items = [make_item(user) for _ in range(3)]
    for item, rank in zip(items, [2, 0, 1], strict=True):
        item.loopwire_send_id, item.dispatch_rank = send.id, rank
    db.commit()
    body = client.get("/api/loopwire-sends/latest", headers=auth_headers(user)).json()
    assert [i["item_id"] for i in body["items"]] == [items[1].id, items[2].id, items[0].id]
    assert all(i["read_url"].startswith("https://api.test/r/") and "." in i["read_url"].rsplit("/", 1)[1]
               for i in body["items"])


def test_feedback_roundtrip_shows_on_dispatch(client, db, make_user, make_item):
    user = make_user()
    send = LoopwireSend(user_id=user.id, item_count=1)
    db.add(send)
    db.commit()
    item = make_item(user, loopwire_send_id=send.id, dispatch_rank=0)
    assert client.post(f"/api/items/{item.id}/feedback", json={"vote": "down"}, headers=auth_headers(user)).is_success
    body = client.get("/api/loopwire-sends/latest", headers=auth_headers(user)).json()
    assert body["items"][0]["feedback"] == "down"
    assert client.post(f"/api/items/{item.id}/feedback", json={"vote": "meh"},
                       headers=auth_headers(user)).status_code == 422


def test_viewing_dispatch_is_send_level_exposure(client, db, make_user, make_item):
    user = make_user()
    send = LoopwireSend(user_id=user.id, item_count=1)
    db.add(send)
    db.commit()
    make_item(user, loopwire_send_id=send.id)
    client.get("/api/loopwire-sends/latest", headers=auth_headers(user))
    db.refresh(send)
    assert send.opened_at is None  # reading the API is not "seen"
    client.post(f"/api/loopwire-sends/{send.id}/viewed", headers=auth_headers(user))
    db.refresh(send)
    assert send.opened_at is not None


def test_profile_update_invalidates_cached_embedding(client, db, make_user):
    user = make_user(profile="old")
    user.interest_profile_embedding = [0.1] * 768
    db.commit()
    r = client.put("/api/interest-profile", json={"profile_text": "new interests"}, headers=auth_headers(user))
    assert r.json()["profile_text"] == "new interests"
    db.refresh(user)
    assert user.interest_profile_embedding is None


def test_profile_status_counts_only_positive_signals(client, db, make_user, make_item):
    from app.engagement import log_event

    user = make_user()
    for _ in range(6):
        log_event(db, user.id, make_item(user).id, "skipped")
    status = client.get("/api/profile-status", headers=auth_headers(user)).json()
    assert status["engagement_count"] == 0 and status["is_adaptive"] is False  # v1 counted skips
    from app.models import ADAPTIVE_HALF_WEIGHT_SIGNALS as k

    for _ in range(k):
        log_event(db, user.id, make_item(user).id, "clicked_source")
    status = client.get("/api/profile-status", headers=auth_headers(user)).json()
    assert status["engagement_count"] == k and status["is_adaptive"] is True
    assert status["adaptive_weight"] == 0.5


def test_recall_endpoints(client, db, make_user, make_item, monkeypatch):
    user, other = make_user(), make_user()
    item = make_item(user, title="Deep Work")
    card = RecallCard(user_id=user.id, item_id=item.id, question="Q?", answer="A", evidence_quote="quote",
                      state="active", due_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    db.add(card)
    db.commit()

    assert client.get("/api/recall/next", headers=auth_headers(other)).status_code == 404
    nxt = client.get("/api/recall/next", headers=auth_headers(user)).json()
    assert nxt["card_id"] == card.id and nxt["due_count"] == 1

    assert client.post(f"/api/recall/{card.id}/review", json={"self_verdict": "correct"},
                       headers=auth_headers(other)).status_code == 404
    assert client.post(f"/api/recall/{card.id}/review", json={}, headers=auth_headers(user)).status_code == 422

    from app.recall import GradeResult

    monkeypatch.setattr("app.routers.api.grade_answer",
                        lambda *a, **k: GradeResult(verdict="partial", feedback="Close."))
    r = client.post(f"/api/recall/{card.id}/review", json={"answer": "kinda A"}, headers=auth_headers(user)).json()
    assert r["verdict"] == "partial" and r["reference_answer"] == "A" and r["next_due_at"]
    stats = client.get("/api/recall/stats", headers=auth_headers(user)).json()
    assert stats["reviews"] == 1 and stats["retention_rate"] == 0.5
