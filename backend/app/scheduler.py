"""APScheduler-driven periodic sending (Loopwire Phase 4/6; per-user per prdv2.md Phase A).

Runs in-process with the FastAPI app. For platforms without persistent
processes, `run_loopwire_cycle()` can instead be invoked directly by a
Render/Railway cron job (see SETUP.md), or via the HTTP-triggered
/send-digest endpoint that production actually relies on.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db import SessionLocal
from app.engagement import infer_skipped_events
from app.loopwire_send import build_and_send_pending_for_user, users_with_pending_items
from app.models import User

logger = logging.getLogger("loopwire.scheduler")


def run_loopwire_cycle() -> dict:
    """One cycle across every user with pending items - builds + sends each
    user's own dispatch independently, respecting each user's own daily cap."""
    settings = get_settings()
    with SessionLocal() as db:
        # Skipped-event inference only matters for users who already have at
        # least one send to compare against.
        for user in db.query(User).filter(User.telegram_chat_id.isnot(None)).all():
            infer_skipped_events(db, user.id)

        pending_user_ids = users_with_pending_items(db)
        results = []
        for user_id in pending_user_ids:
            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                continue
            result = build_and_send_pending_for_user(db, user, settings.loopwire_period)
            results.append(result)
            if result["sent"]:
                logger.info(
                    "Loopwire send #%s sent to user #%s (%d items, email_id=%s)",
                    result["loopwire_send_id"],
                    user_id,
                    result["item_count"],
                    result["email_id"],
                )
            else:
                logger.info("User #%s not sent: %s", user_id, result["reason"])

        sent_count = sum(1 for r in results if r["sent"])
        return {
            "users_with_pending": len(pending_user_ids),
            "sent_count": sent_count,
            "results": results,
        }


def start_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    if settings.loopwire_period == "weekly":
        trigger = CronTrigger(day_of_week="mon", hour=settings.loopwire_send_hour_ist, timezone="Asia/Kolkata")
    else:
        trigger = CronTrigger(hour=settings.loopwire_send_hour_ist, timezone="Asia/Kolkata")

    scheduler.add_job(run_loopwire_cycle, trigger, id="send_loopwire", replace_existing=True)
    scheduler.start()
    logger.info(
        "Loopwire scheduler started (%s, hour=%d IST)", settings.loopwire_period, settings.loopwire_send_hour_ist
    )
    return scheduler
