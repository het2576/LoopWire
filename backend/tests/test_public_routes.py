"""Public (unauthenticated) engagement routes: signed links, bot filtering,
scanner-safe feedback, per-send open pixel."""

from app import models, tracking
from app.models import EngagementEvent, LoopwireSend

BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130"}


def _events(db, item_id):
    db.expire_all()
    return sorted(e.event_type for e in db.query(EngagementEvent).filter_by(item_id=item_id))


def test_sequential_ids_no_longer_work(client, make_user, make_item):
    """v1: GET /r/<int> redirected to any user's saved URL (IDOR)."""
    item = make_item(make_user(), url="https://secret.example.com/private-doc")
    for path in (f"/r/{item.id}", f"/r/{item.id}.forged", f"/track/opened/{item.id}.png"):
        r = client.get(path, follow_redirects=False, headers=BROWSER)
        assert r.status_code == 404, path


def test_signed_click_redirects_and_logs(client, db, make_user, make_item):
    item = make_item(make_user(), url="https://example.com/a")
    r = client.get(f"/r/{tracking.sign(tracking.PURPOSE_CLICK, item.id)}", follow_redirects=False, headers=BROWSER)
    assert r.status_code == 307
    assert r.headers["location"] == "https://example.com/a"
    assert _events(db, item.id) == ["clicked_source"]


def test_click_token_cannot_be_reused_for_other_purpose(client, make_user, make_item):
    item = make_item(make_user())
    feedback_token = tracking.sign(tracking.PURPOSE_FEEDBACK, item.id)
    assert client.get(f"/r/{feedback_token}", follow_redirects=False).status_code == 404


def test_link_scanners_do_not_count_as_clicks(client, db, make_user, make_item):
    item = make_item(make_user())
    token = tracking.sign(tracking.PURPOSE_CLICK, item.id)
    for ua in ("Microsoft SafeLinks Bot", "Proofpoint URL Defense", "python-requests/2.31", "Slackbot-LinkExpanding"):
        assert client.get(f"/r/{token}", follow_redirects=False, headers={"User-Agent": ua}).status_code == 307
    assert client.head(f"/r/{token}", headers=BROWSER, follow_redirects=False).status_code == 307
    assert _events(db, item.id) == []


def test_feedback_get_is_confirmation_only(client, db, make_user, make_item):
    item = make_item(make_user(), title="<script>alert(1)</script>")
    token = tracking.sign(tracking.PURPOSE_FEEDBACK, item.id)
    r = client.get(f"/f/{token}/up")
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text  # escaped
    assert _events(db, item.id) == []  # scanner prefetch can't vote

    assert client.post(f"/f/{token}/up").status_code == 200
    assert _events(db, item.id) == ["feedback_up"]
    client.post(f"/f/{token}/down")
    assert _events(db, item.id) == ["feedback_down"]  # flip, not both
    assert client.post(f"/f/{token}/sideways").status_code == 404


def test_send_pixel_marks_send_opened_once(client, db, make_user):
    user = make_user()
    send = LoopwireSend(user_id=user.id, period="daily", item_count=0)
    db.add(send)
    db.commit()
    r = client.get(f"/track/send/{tracking.sign(tracking.PURPOSE_SEND_OPEN, send.id)}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    db.refresh(send)
    first = send.opened_at
    assert first is not None
    client.get(f"/track/send/{tracking.sign(tracking.PURPOSE_SEND_OPEN, send.id)}.png")
    db.refresh(send)
    assert send.opened_at == first
    # bad token: still returns a pixel (never break email rendering), records nothing
    assert client.get("/track/send/1.bad.png").status_code == 200


def test_cron_endpoints_fail_closed(client):
    for path in ("/send-digest", "/process-pending"):
        assert client.post(path).status_code == 401
        assert client.post(f"{path}?key=wrong").status_code == 401
        assert client.post(path, headers={"X-Cron-Key": "wrong"}).status_code == 401


def test_cron_endpoints_accept_header_and_run_async(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.run_process_pending_cycle", lambda: calls.append("pp") or {"processed": 0})
    monkeypatch.setattr("app.main.run_loopwire_cycle",
                        lambda: calls.append("send") or {"sent_count": 0, "users_with_pending": 0})
    r = client.post("/process-pending", headers={"X-Cron-Key": "test-process-secret"})
    assert r.status_code == 202
    r = client.post("/send-digest?key=test-send-secret&wait=true")
    assert r.status_code == 200 and r.json()["status"] == "no_new_items"
    assert calls == ["pp", "send"]


def test_tracking_tokens_roundtrip_and_reject_tampering():
    token = tracking.sign(tracking.PURPOSE_CLICK, 42)
    assert tracking.verify(tracking.PURPOSE_CLICK, token) == 42
    assert tracking.verify(tracking.PURPOSE_FEEDBACK, token) is None
    _, sig = token.split(".")
    assert tracking.verify(tracking.PURPOSE_CLICK, f"43.{sig}") is None
    for junk in ("", "42", "abc.def", ".", "42."):
        assert tracking.verify(tracking.PURPOSE_CLICK, junk) is None
    assert models.EVENT_CLICKED_SOURCE in models.POSITIVE_EVENTS
