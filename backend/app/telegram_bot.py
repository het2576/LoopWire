"""Telegram ingestion bot (Loopwire Phase 1; multi-tenant per prdv2.md Phase A).

Listens for any message containing a URL, classifies it, and stores a
`saved_items` row with status="pending" for the background worker to pick up.
Every command operates on the Telegram chat's *linked* Loopwire account -
chat_ids that aren't linked yet are prompted to sign up and connect.

Commands
--------
/start          — welcome message + quick help
/help           — full command reference
/connect <code> — link this Telegram chat to a dashboard account
/list [n]       — last n saved items (default 10, max 25)
/pending        — items still awaiting processing
/delete <id>    — remove a saved item by ID
/clear          — remove ALL pending items (requires confirmation)
/profile        — show interest profile
/setprofile     — update interest profile
/stats          — engagement stats by content type
/search <q>     — search saved items by title / URL keyword

Production runs this via webhook, embedded in the FastAPI app (app/main.py's
/telegram-webhook route calls build_application() from here and forwards
each update to it - no always-on process needed). For local dev without
ngrok, `main()` below still runs it in long-polling mode standalone:
    uv run python -m app.telegram_bot
"""

import datetime as dt
import logging
import re

from sqlalchemy.orm import Session
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import get_settings
from app.db import SessionLocal
from app.engagement import get_stats
from app.models import (
    ITEM_TYPE_ARTICLE,
    ITEM_TYPE_GITHUB,
    ITEM_TYPE_HN,
    ITEM_TYPE_PDF,
    ITEM_TYPE_REDDIT,
    ITEM_TYPE_UNSUPPORTED,
    ITEM_TYPE_YOUTUBE,
    MAX_SAVED_LINKS_PER_DAY,
    STATUS_EXTRACTED,
    STATUS_EXTRACTION_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SUMMARIZED,
    ConnectionCode,
    SavedItem,
    User,
)
from app.url_utils import classify_url, find_first_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("loopwire.telegram_bot")

CONNECTION_CODE_TTL_MINUTES = 15

# ── Status display ────────────────────────────────────────────────────────────

STATUS_EMOJI = {
    STATUS_PENDING: "⏳",
    STATUS_EXTRACTED: "📄",
    STATUS_EXTRACTION_FAILED: "⚠️",
    STATUS_SUMMARIZED: "✅",
    STATUS_SENT: "📬",
}

STATUS_LABEL = {
    STATUS_PENDING: "queued",
    STATUS_EXTRACTED: "extracted",
    STATUS_EXTRACTION_FAILED: "failed",
    STATUS_SUMMARIZED: "ready",
    STATUS_SENT: "sent",
}

TYPE_EMOJI = {
    ITEM_TYPE_ARTICLE: "📰",
    ITEM_TYPE_YOUTUBE: "🎥",
    ITEM_TYPE_REDDIT: "🟠",
    ITEM_TYPE_GITHUB: "🐙",
    ITEM_TYPE_HN: "🔶",
    ITEM_TYPE_PDF: "📄",
    ITEM_TYPE_UNSUPPORTED: "🔗",
}

TYPE_LABEL = {
    ITEM_TYPE_ARTICLE: "Article",
    ITEM_TYPE_YOUTUBE: "YouTube",
    ITEM_TYPE_REDDIT: "Reddit",
    ITEM_TYPE_GITHUB: "GitHub",
    ITEM_TYPE_HN: "Hacker News",
    ITEM_TYPE_PDF: "PDF",
    ITEM_TYPE_UNSUPPORTED: "Raw link",
}

NOT_LINKED_TEXT = (
    "🔒 This Telegram chat isn't connected to a Loopwire account yet\\.\n\n"
    "Sign in on the dashboard, open *Settings*, and generate a connection "
    "code — then send `/connect <code>` here\\."
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _escape(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def _resolve_user(db: Session, chat_id: int | None) -> User | None:
    if chat_id is None:
        return None
    return db.query(User).filter(User.telegram_chat_id == chat_id).first()


def _format_item_line(item: SavedItem, show_summary: bool = False) -> str:
    """Return a single formatted line (or block) for an item."""
    # item.status tracks processing state (pending/extracted/summarized/
    # extraction_failed) and is never itself set to STATUS_SENT - whether an
    # item has actually gone out is tracked separately via loopwire_send_id.
    # Combine both here so "sent" displays correctly instead of showing
    # "ready" forever after delivery.
    display_status = STATUS_SENT if item.loopwire_send_id else item.status
    status_e = STATUS_EMOJI.get(display_status, "•")
    status_l = STATUS_LABEL.get(display_status, display_status)
    type_e = TYPE_EMOJI.get(item.type, "•")
    title = (item.title or item.url)[:60]
    if len(item.title or item.url) > 60:
        title += "…"

    read_time = f" · {item.estimated_read_time_minutes}m read" if item.estimated_read_time_minutes else ""
    line = f"{status_e} {type_e} *\\#{item.id}* {_escape(title)}{_escape(read_time)} — _{_escape(status_l)}_"

    if show_summary and item.summary:
        snippet = item.summary[:120]
        ellipsis = "…" if len(item.summary) > 120 else ""
        line += f"\n    _{_escape(snippet)}{ellipsis}_"

    return line


# ── Command handlers ──────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Welcome to Loopwire\\!*\n\n"
        "Sign in on the web dashboard first, then connect this chat with "
        "`/connect <code>` \\(generated on the Settings page\\)\\.\n\n"
        "Once connected, forward or paste any article or YouTube link and "
        "I'll queue it for your next dispatch\\.\n\n"
        "*Quick commands:*\n"
        "/connect \\<code\\> — link this chat to your account\n"
        "/list — see your saved items\n"
        "/pending — items still processing\n"
        "/profile — view your interest profile\n"
        "/help — full command reference"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📡 *Loopwire Bot — Command Reference*\n\n"
        "*Account*\n"
        "/connect \\<code\\> — link this chat to your dashboard account\n\n"
        "*Bookmarks*\n"
        "/list \\[n\\] — last n items \\(default 10, max 25\\)\n"
        "/pending — items waiting to be processed\n"
        "/delete \\<id\\> — remove an item by ID\n"
        "/clear — remove all pending items\n"
        "/search \\<query\\> — search by title or URL\n\n"
        "*Profile*\n"
        "/profile — show current interest profile\n"
        "/setprofile \\<text\\> — update your interests\n\n"
        "*Stats*\n"
        "/stats — engagement breakdown by content type\n\n"
        "*Ingestion*\n"
        "Once connected, just paste or forward any URL — I'll classify and "
        "queue it automatically \\(up to "
        f"{MAX_SAVED_LINKS_PER_DAY} per day\\)\\.\n"
        "You can add a note after the link and it'll be saved as context\\."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: `/connect <code>` — get your code from the dashboard's Settings page\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    code = context.args[0].strip().upper()
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return

    with SessionLocal() as db:
        connection = db.query(ConnectionCode).filter(ConnectionCode.code == code).first()

        if connection is None:
            await update.effective_message.reply_text(
                "❌ That code wasn't recognized\\. Double\\-check it on the Settings page\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        if connection.used_at is not None:
            await update.effective_message.reply_text(
                "❌ That code has already been used\\. Generate a new one on the Settings page\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        age = dt.datetime.now(dt.timezone.utc) - connection.created_at
        if age > dt.timedelta(minutes=CONNECTION_CODE_TTL_MINUTES):
            await update.effective_message.reply_text(
                "❌ That code expired\\. Generate a new one on the Settings page\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        user = db.query(User).filter(User.id == connection.user_id).first()
        already_linked = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if already_linked is not None and already_linked.id != user.id:
            await update.effective_message.reply_text(
                "❌ This Telegram chat is already connected to a different account\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        user.telegram_chat_id = chat_id
        connection.used_at = dt.datetime.now(dt.timezone.utc)
        db.commit()

    await update.effective_message.reply_text(
        f"✅ Connected to *{_escape(user.email)}*\\! Forward any link to start saving\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = message.text or message.caption or ""
    url = find_first_url(text)
    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        if not url:
            # Give a nudge instead of silent ignore
            await message.reply_text(
                "No link detected. Paste or forward a URL and I'll queue it for your next dispatch. "
                "Use /help to see available commands."
            )
            return

        today_start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        saved_today = (
            db.query(SavedItem)
            .filter(SavedItem.user_id == user.id, SavedItem.added_at >= today_start)
            .count()
        )
        if saved_today >= MAX_SAVED_LINKS_PER_DAY:
            await message.reply_text(
                f"⚠️ You've hit today's limit of {MAX_SAVED_LINKS_PER_DAY} saved links\\. "
                "Try again tomorrow — this keeps shared API quota fair across everyone using Loopwire\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        item_type = classify_url(url)
        is_unsupported = item_type == ITEM_TYPE_UNSUPPORTED

        # Save any context text (the note/comment accompanying the link)
        raw = text.strip()

        item = SavedItem(
            user_id=user.id,
            url=url,
            type=item_type,
            status=STATUS_EXTRACTION_FAILED if is_unsupported else STATUS_PENDING,
            extraction_error=(
                "unsupported_source: no extractor available for this domain" if is_unsupported else None
            ),
            raw_message_text=raw,
            telegram_user_id=update.effective_user.id if update.effective_user else None,
            telegram_chat_id=chat_id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)

    type_e = TYPE_EMOJI.get(item_type, "🔗")
    type_l = TYPE_LABEL.get(item_type, "Link")
    short_url = url[:50] + ("…" if len(url) > 50 else "")

    if is_unsupported:
        await message.reply_text(
            f"{type_e} *Saved \\#{item.id}* — Raw link\n"
            f"`{_escape(short_url)}`\n\n"
            "⚠️ This source \\(e\\.g\\. social media\\) can't be extracted, "
            "but the link will appear in your next dispatch\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await message.reply_text(
            f"{type_e} *Saved \\#{item.id}* — {_escape(type_l)}\n"
            f"`{_escape(short_url)}`\n\n"
            "✅ Queued for extraction and summarization\\. "
            "Use /list to check status\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None

    # Optional count argument: /list 5
    limit = 10
    if context.args:
        try:
            limit = max(1, min(25, int(context.args[0])))
        except ValueError:
            pass

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        items = (
            db.query(SavedItem)
            .filter(SavedItem.user_id == user.id)
            .order_by(SavedItem.added_at.desc())
            .limit(limit)
            .all()
        )

    if not items:
        await update.effective_message.reply_text(
            "📭 No saved items yet\\. Paste or forward a URL to get started\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    lines = [f"📋 *Last {len(items)} saved item{'s' if len(items) != 1 else ''}:*\n"]
    for item in items:
        lines.append(_format_item_line(item, show_summary=True))

    lines.append("\n_/delete \\<id\\> to remove · /pending for queued items_")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def pending_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        items = (
            db.query(SavedItem)
            .filter(SavedItem.user_id == user.id)
            .filter(SavedItem.status.in_([STATUS_PENDING, STATUS_EXTRACTED]))
            .order_by(SavedItem.added_at.desc())
            .limit(25)
            .all()
        )

    if not items:
        await update.effective_message.reply_text(
            "✨ No items pending — everything has been processed\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    lines = [f"⏳ *{len(items)} item{'s' if len(items) != 1 else ''} in queue:*\n"]
    for item in items:
        lines.append(_format_item_line(item))

    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def delete_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /delete \\<id\\>  \\(get the ID from /list\\)",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Please provide a numeric item ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        item = db.query(SavedItem).filter(SavedItem.id == item_id, SavedItem.user_id == user.id).first()

        if item is None:
            await update.effective_message.reply_text(
                f"Item \\#{item_id} not found\\.", parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        title = item.title or item.url[:40]
        db.delete(item)
        db.commit()

    await update.effective_message.reply_text(
        f"🗑️ Deleted \\#{item_id} — {_escape(title)}",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def clear_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None

    # Require confirmation word: /clear confirm
    if not context.args or context.args[0].lower() != "confirm":
        await update.effective_message.reply_text(
            "⚠️ This will delete all your *pending* items\\.\n\n"
            "Type /clear confirm to proceed\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        query = db.query(SavedItem).filter(SavedItem.user_id == user.id, SavedItem.status == STATUS_PENDING)
        count = query.count()
        query.delete()
        db.commit()

    await update.effective_message.reply_text(
        f"🗑️ Cleared {count} pending item{'s' if count != 1 else ''}\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def search_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Usage: /search \\<keyword\\>", parse_mode=ParseMode.MARKDOWN_V2)
        return

    query_str = "%" + " ".join(context.args).lower() + "%"
    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        items = (
            db.query(SavedItem)
            .filter(SavedItem.user_id == user.id)
            .filter(SavedItem.title.ilike(query_str) | SavedItem.url.ilike(query_str))
            .order_by(SavedItem.added_at.desc())
            .limit(10)
            .all()
        )

    if not items:
        await update.effective_message.reply_text(
            f"🔍 No items matched *{_escape(' '.join(context.args))}*\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    lines = [f"🔍 *{len(items)} result{'s' if len(items) != 1 else ''}:*\n"]
    for item in items:
        lines.append(_format_item_line(item, show_summary=True))

    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return
        profile_text = user.interest_profile_text

    if not profile_text:
        await update.effective_message.reply_text(
            "No interest profile set yet\\.\n\n"
            "Use /setprofile \\<text\\> to tell Loopwire what you care about — "
            "this shapes how content is summarized and scored\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await update.effective_message.reply_text(
        f"📌 *Your interest profile:*\n\n{_escape(profile_text)}\n\n"
        "_Use /setprofile \\<text\\> to update it\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def set_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    new_text = " ".join(context.args).strip()
    if not new_text:
        await update.effective_message.reply_text(
            "Usage: /setprofile \\<your interests as a short paragraph\\>\n\n"
            "Example: `/setprofile I'm a product designer interested in AI, typography, "
            "indie business models, and developer tools\\.`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return

        user.interest_profile_text = new_text
        db.commit()

    await update.effective_message.reply_text(
        "✅ *Interest profile updated\\!*\n\n"
        "New summaries will reflect your stated interests\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None

    with SessionLocal() as db:
        user = _resolve_user(db, chat_id)
        if user is None:
            await update.effective_message.reply_text(NOT_LINKED_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
            return
        stats = get_stats(db, user.id)

    if not stats:
        await update.effective_message.reply_text(
            "📊 No engagement data yet — stats appear once items have been sent\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    lines = ["📊 *Engagement by content type:*\n"]
    for content_type, bucket in stats.items():
        rate = bucket["engagement_rate"]
        bar = "█" * round(rate * 10) + "░" * (10 - round(rate * 10))
        lines.append(
            f"*{_escape(content_type.title())}*\n"
            f"  Sent: {bucket['total_sent']} · Opened: {bucket['opened']} · "
            f"Clicked: {bucket['clicked_source']} · Skipped: {bucket['skipped']}\n"
            f"  `{bar}` {rate:.0%}"
        )

    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ── Application setup ─────────────────────────────────────────────────────────


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set - see SETUP.md")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("connect", connect))
    application.add_handler(CommandHandler("list", list_items))
    application.add_handler(CommandHandler("pending", pending_items))
    application.add_handler(CommandHandler("delete", delete_item))
    application.add_handler(CommandHandler("clear", clear_pending))
    application.add_handler(CommandHandler("search", search_items))
    application.add_handler(CommandHandler("profile", show_profile))
    application.add_handler(CommandHandler("setprofile", set_profile))
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def main() -> None:
    """Standalone long-polling mode - local development only. Production runs
    the bot inside the FastAPI app via a webhook instead (see app/main.py's
    /telegram-webhook route and lifespan). Telegram rejects having both a
    webhook and getUpdates polling active on the same bot token at once, so
    make sure no webhook is registered before using this (call deleteWebhook,
    or just don't set BACKEND_BASE_URL to an https URL while this is running)."""
    application = build_application()
    logger.info("Starting Loopwire Telegram bot (polling, local dev only)...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # discard messages queued while bot was offline
        poll_interval=2.0,  # 2s between polls (default is 0s — too aggressive)
    )


if __name__ == "__main__":
    main()
