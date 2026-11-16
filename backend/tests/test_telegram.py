"""Telegram handlers driven with minimal fake Update objects."""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import models, telegram_bot
from app.recall import GradeResult


def _update(chat_id: int, text: str):
    message = SimpleNamespace(text=text, caption=None, reply_text=AsyncMock())
    return SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=chat_id),
                           effective_user=SimpleNamespace(id=chat_id)), message


@pytest.fixture(autouse=True)
def _no_background_processing(monkeypatch):
    monkeypatch.setattr(telegram_bot, "_process_user_queue", AsyncMock())


async def test_unlinked_chat_is_prompted(db):
    update, message = _update(999, "https://example.com/a")
    await telegram_bot.handle_message(update, SimpleNamespace(args=[]))
    assert "isn't connected" in message.reply_text.call_args.args[0]
    assert db.query(models.SavedItem).count() == 0


async def test_duplicate_link_is_not_saved_twice(db, make_user):
    make_user(chat_id=111)
    u1, _ = _update(111, "look https://example.com/post?utm_source=x")
    await telegram_bot.handle_message(u1, SimpleNamespace(args=[]))
    u2, m2 = _update(111, "again https://www.example.com/post/")
    await telegram_bot.handle_message(u2, SimpleNamespace(args=[]))
    assert db.query(models.SavedItem).count() == 1
    assert "Already saved" in m2.reply_text.call_args.args[0]


async def test_unsupported_link_saved_as_failed(db, make_user):
    make_user(chat_id=112)
    update, _ = _update(112, "https://x.com/someone/status/1")
    await telegram_bot.handle_message(update, SimpleNamespace(args=[]))
    item = db.query(models.SavedItem).one()
    assert item.type == "unsupported" and item.status == models.STATUS_EXTRACTION_FAILED


async def test_quiz_then_answer_is_graded_and_scheduled(db, make_user, make_item, monkeypatch):
    user = make_user(chat_id=113)
    item = make_item(user, title="Deep Work")
    card = models.RecallCard(user_id=user.id, item_id=item.id, question="Why plateau?", answer="Comfort",
                             evidence_quote="q", state="active",
                             due_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
    db.add(card)
    db.commit()

    update, message = _update(113, "/quiz")
    await telegram_bot.quiz(update, SimpleNamespace(args=[]))
    assert "Why plateau" in message.reply_text.call_args.args[0]

    monkeypatch.setattr(telegram_bot, "grade_answer",
                        lambda *a: GradeResult(verdict="correct", feedback="Nailed it."))
    update, message = _update(113, "because they stay comfortable")
    await telegram_bot.handle_message(update, SimpleNamespace(args=[]))
    reply = message.reply_text.call_args.args[0]
    assert "Nailed it." in reply and "Answer: Comfort" in reply
    db.expire_all()
    card = db.get(models.RecallCard, card.id)
    assert card.box == 1 and card.reviews == 1
    assert db.get(models.User, user.id).pending_recall_card_id is None
    assert db.query(models.SavedItem).count() == 1  # the answer was not treated as a link


async def test_quiz_with_nothing_due(db, make_user):
    make_user(chat_id=114)
    update, message = _update(114, "/quiz")
    await telegram_bot.quiz(update, SimpleNamespace(args=[]))
    assert "No recall questions yet" in message.reply_text.call_args.args[0]
