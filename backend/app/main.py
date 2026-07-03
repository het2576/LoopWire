import base64
import datetime as dt
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import Application

from app.config import get_settings
from app.db import get_db
from app.engagement import log_event
from app.models import EVENT_CLICKED_SOURCE, EVENT_OPENED, SavedItem
from app.routers.api import router as api_router
from app.scheduler import run_loopwire_cycle
from app.telegram_bot import build_application
from app.worker import run_process_pending_cycle

logger = logging.getLogger("loopwire.main")

# 1x1 transparent PNG, used as an email open-tracking pixel.
TRANSPARENT_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

settings = get_settings()

# Set on startup if a Telegram bot token is configured; the webhook route
# reads it via the module-level reference (FastAPI's single-process model
# makes this safe - no per-request app instances).
telegram_app: Application | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_time = dt.datetime.now(dt.timezone.utc)
    logger.info(
        "Loopwire API cold start at %s UTC - if a request feels slow right after "
        "a period of inactivity, check this timestamp against the request time "
        "to confirm it's Render spinning the free-tier service back up.",
        startup_time.isoformat(),
    )

    global telegram_app
    if settings.telegram_bot_token:
        telegram_app = build_application()
        await telegram_app.initialize()
        await telegram_app.start()

        webhook_url = f"{settings.backend_base_url}/telegram-webhook"
        if not webhook_url.startswith("https://"):
            # Telegram rejects non-HTTPS webhook URLs outright. This is the
            # expected case for plain local dev (BACKEND_BASE_URL defaults to
            # http://localhost:8000) - point it at an ngrok https URL to test
            # the webhook flow locally, see SETUP.md. Everything else in the
            # app (dashboard API, /send-digest, etc.) still works without it.
            logger.warning(
                "BACKEND_BASE_URL (%s) is not https - skipping Telegram webhook "
                "registration. Use an ngrok https URL to test webhooks locally.",
                settings.backend_base_url,
            )
        else:
            try:
                await telegram_app.bot.set_webhook(
                    url=webhook_url,
                    secret_token=settings.telegram_webhook_secret or None,
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                logger.info("Telegram webhook registered at %s", webhook_url)
            except Exception:
                logger.exception(
                    "Failed to register Telegram webhook at %s - bot will not "
                    "receive updates until this is fixed and the app restarts.",
                    webhook_url,
                )
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set - webhook not registered, bot inactive")

    yield

    if telegram_app is not None:
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="Loopwire API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dashboard_base_url],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """Receives Telegram update payloads once a webhook is registered (see
    lifespan startup above). Replaces long-polling so the bot can live inside
    a normal Render web service instead of an always-on background process."""
    if settings.telegram_webhook_secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid secret token")

    if telegram_app is None:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}


@app.post("/send-digest")
def send_digest(key: str = ""):
    """Builds and sends a Loopwire dispatch on demand. Protected by a shared
    secret query param so it can be safely pinged by an external cron (e.g.
    cron-job.org) instead of relying on an internal always-on scheduler that
    a free-tier service sleeping through would miss. A blank configured
    secret always rejects - there is no "unprotected" mode."""
    if not settings.send_loopwire_secret or key != settings.send_loopwire_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing key")

    result = run_loopwire_cycle()
    return {
        "status": "sent" if result["sent_count"] else "no_new_items",
        "users_processed": result["users_with_pending"],
        "sent_count": result["sent_count"],
    }


@app.post("/process-pending")
def process_pending(key: str = ""):
    """Runs one extraction + summarization pass over pending items on demand.
    Protected the same way as /send-digest, and for the same reason - this
    replaces an always-on polling worker with an external cron ping (e.g.
    every 5-10 minutes via cron-job.org), so new links get processed close
    to real-time without needing a continuously running background process."""
    if not settings.process_pending_secret or key != settings.process_pending_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing key")

    result = run_process_pending_cycle()
    return {"processed": result["processed"], "failed": result["failed"]}


@app.get("/r/{item_id}")
def read_source(item_id: int, db: Session = Depends(get_db)):
    """Click-through redirect used by both the email and the dashboard. Logs a
    clicked_source engagement event before sending the reader to the original
    link. Stays public/unauthenticated (email clients can't send custom
    headers) - item_id alone is enough to identify the record and its owner."""
    item = db.query(SavedItem).filter(SavedItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    log_event(db, item.user_id, item_id, EVENT_CLICKED_SOURCE)
    return RedirectResponse(url=item.url, status_code=307)


@app.get("/track/opened/{item_id}.png")
def track_opened(item_id: int, db: Session = Depends(get_db)):
    """Invisible tracking pixel embedded in Loopwire emails to log 'opened'."""
    item = db.query(SavedItem).filter(SavedItem.id == item_id).first()
    if item is not None:
        log_event(db, item.user_id, item_id, EVENT_OPENED)
    return Response(content=TRANSPARENT_PIXEL, media_type="image/png")
