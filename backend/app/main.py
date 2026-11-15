import base64
import datetime as dt
import hmac
import logging
import re
from contextlib import asynccontextmanager
from html import escape

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import Application

from app.config import get_settings
from app.db import get_db
from app.engagement import log_event, mark_send_opened
from app.models import (
    EVENT_CLICKED_SOURCE,
    EVENT_FEEDBACK_DOWN,
    EVENT_FEEDBACK_UP,
    SavedItem,
)
from app.routers.api import router as api_router
from app.scheduler import run_loopwire_cycle
from app.telegram_bot import build_application
from app.tracking import PURPOSE_CLICK, PURPOSE_FEEDBACK, PURPOSE_SEND_OPEN, verify
from app.worker import run_process_pending_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("loopwire.main")

# Corporate mail security (Outlook SafeLinks, Proofpoint, Mimecast, Gmail's
# image proxy...) fetches every link in an email before the human does. Those
# fetches must not count as engagement, or every item looks clicked.
_BOT_UA = re.compile(
    r"bot|crawler|spider|preview|scanner|safelinks|proofpoint|mimecast|barracuda|"
    r"python-requests|httpx|curl|wget|headless|facebookexternalhit|slackbot",
    re.IGNORECASE,
)


def _is_automated(request: Request) -> bool:
    return request.method == "HEAD" or bool(_BOT_UA.search(request.headers.get("user-agent", "")))


def _cron_key_ok(expected: str, query_key: str, header_key: str | None) -> bool:
    supplied = header_key or query_key
    return bool(expected) and bool(supplied) and hmac.compare_digest(supplied, expected)

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
    startup_time = dt.datetime.now(dt.UTC)
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

        backend_base = settings.backend_base_url.rstrip("/")
        webhook_url = f"{backend_base}/telegram-webhook"
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

dashboard_origin = settings.dashboard_base_url.rstrip("/")
allowed_origins = [dashboard_origin, f"{dashboard_origin}/"] if dashboard_origin else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/db-ping")
def db_ping(db: Session = Depends(get_db)):
    """Readiness probe: keeps the Supabase free tier from pausing by making a
    real DB query, and doubles as the only external signal that the database
    is actually reachable. Hit this via an external cron (e.g. cron-job.org)
    every 5-6 days - more often is fine and costs nothing.

    /health deliberately does NOT touch the DB: it stays a pure liveness probe
    so Render's health check doesn't cycle the service on a transient Supabase
    blip. That split means /health alone cannot tell you the app is working -
    this endpoint is the one to alert on.

    Returns 503 (not 200) when the DB is unreachable. This matters: cron/uptime
    monitors decide success from the HTTP status, so returning 200 with
    {"ok": false} - as this did before - meant a paused Supabase project looked
    like a passing check and nothing ever alarmed.
    """
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": "reachable"}
    except Exception as e:
        # Full detail to the logs only. The response stays generic because this
        # route is unauthenticated, and SQLAlchemy connection errors routinely
        # echo back the DSN (host, user, sometimes credentials).
        logger.exception("db-ping failed - database unreachable")
        return JSONResponse(
            status_code=503,
            content={"ok": False, "db": "unreachable", "error": type(e).__name__},
        )


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
def send_digest(
    background: BackgroundTasks,
    key: str = "",
    wait: bool = False,
    x_cron_key: str | None = Header(default=None),
):
    """Builds and sends a Loopwire dispatch on demand. Protected by a shared
    secret query param so it can be safely pinged by an external cron (e.g.
    cron-job.org) instead of relying on an internal always-on scheduler that
    a free-tier service sleeping through would miss. A blank configured
    secret always rejects - there is no "unprotected" mode. Prefer the
    X-Cron-Key header (query strings end up in access logs).

    Runs in the background by default: a dispatch makes several LLM calls
    per user and cron-job.org gives up after 30s. Pass wait=true to block."""
    if not _cron_key_ok(settings.send_loopwire_secret, key, x_cron_key):
        raise HTTPException(status_code=401, detail="Invalid or missing key")

    if not wait:
        background.add_task(run_loopwire_cycle)
        return JSONResponse(status_code=202, content={"status": "accepted"})
    result = run_loopwire_cycle()
    return {
        "status": "sent" if result["sent_count"] else "no_new_items",
        "users_processed": result["users_with_pending"],
        "sent_count": result["sent_count"],
    }


@app.post("/process-pending")
def process_pending(
    background: BackgroundTasks,
    key: str = "",
    wait: bool = False,
    x_cron_key: str | None = Header(default=None),
):
    """Runs one extraction + summarization pass over pending items on demand.
    Protected the same way as /send-digest, and for the same reason - this
    replaces an always-on polling worker with an external cron ping (e.g.
    every 5-10 minutes via cron-job.org), so new links get processed close
    to real-time without needing a continuously running background process."""
    if not _cron_key_ok(settings.process_pending_secret, key, x_cron_key):
        raise HTTPException(status_code=401, detail="Invalid or missing key")

    if not wait:
        background.add_task(run_process_pending_cycle)
        return JSONResponse(status_code=202, content={"status": "accepted"})
    return run_process_pending_cycle()


@app.api_route("/r/{token}", methods=["GET", "HEAD"])
def read_source(token: str, request: Request, db: Session = Depends(get_db)):
    """Click-through redirect (email + dashboard). The token is an HMAC-signed
    item id (tracking.py): public, because email clients can't authenticate,
    but not enumerable."""
    item_id = verify(PURPOSE_CLICK, token)
    item = db.get(SavedItem, item_id) if item_id is not None else None
    if item is None:
        raise HTTPException(status_code=404, detail="Link not found")
    if not _is_automated(request):
        log_event(db, item.user_id, item.id, EVENT_CLICKED_SOURCE)
    return RedirectResponse(url=item.url, status_code=307)


_FEEDBACK_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Loopwire</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f2e9;color:#12161b;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;padding:16px;">
<div style="max-width:420px;text-align:center;">{body}</div></body></html>"""


def _feedback_event(vote: str) -> str:
    if vote == "up":
        return EVENT_FEEDBACK_UP
    if vote == "down":
        return EVENT_FEEDBACK_DOWN
    raise HTTPException(status_code=404, detail="Unknown vote")


@app.get("/f/{token}/{vote}", response_class=HTMLResponse)
def feedback_confirm(token: str, vote: str, db: Session = Depends(get_db)):
    """GET only renders a one-click confirmation: link scanners prefetch GETs,
    so recording on GET would cast every vote in every email automatically."""
    _feedback_event(vote)
    item_id = verify(PURPOSE_FEEDBACK, token)
    item = db.get(SavedItem, item_id) if item_id is not None else None
    if item is None:
        raise HTTPException(status_code=404, detail="Link not found")
    label = "&#128077; More like this" if vote == "up" else "&#128078; Less like this"
    body = (
        f'<p style="font-size:14px;color:#6b7680;">{escape(item.title or item.url)}</p>'
        f'<form method="post"><button type="submit" style="font-size:17px;padding:12px 22px;border:0;'
        f'border-radius:8px;background:#12161b;color:#fff;cursor:pointer;">{label}</button></form>'
    )
    return _FEEDBACK_PAGE.format(body=body)


@app.post("/f/{token}/{vote}", response_class=HTMLResponse)
def feedback_record(token: str, vote: str, db: Session = Depends(get_db)):
    event = _feedback_event(vote)
    item_id = verify(PURPOSE_FEEDBACK, token)
    item = db.get(SavedItem, item_id) if item_id is not None else None
    if item is None:
        raise HTTPException(status_code=404, detail="Link not found")
    log_event(db, item.user_id, item.id, event)
    msg = "Got it — more like this." if vote == "up" else "Got it — less like this."
    return _FEEDBACK_PAGE.format(body=f'<p style="font-size:18px;">{msg}</p>'
                                       '<p style="font-size:13px;color:#6b7680;">You can close this tab.</p>')


@app.get("/track/send/{token}.png")
def track_send_opened(token: str, db: Session = Depends(get_db)):
    """One pixel per dispatch (not per item): marks the send as seen, which is
    what makes later skip inference legitimate."""
    send_id = verify(PURPOSE_SEND_OPEN, token)
    if send_id is not None:
        mark_send_opened(db, send_id)
    return Response(content=TRANSPARENT_PIXEL, media_type="image/png",
                    headers={"Cache-Control": "no-store, max-age=0"})
