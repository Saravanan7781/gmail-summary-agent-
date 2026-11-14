"""Automated background scheduler for scheduled daily briefings using Groq."""

import datetime
import html
import logging
from typing import Optional
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from src.config import Config
from src.gmail_service import GmailService
from src.groq_service import GroqService

logger = logging.getLogger(__name__)


async def run_daily_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job that executes daily and delivers inbox briefing."""
    chat_id = Config.DIGEST_CHAT_ID or (
        list(Config.ALLOWED_TELEGRAM_USER_IDS)[0]
        if Config.ALLOWED_TELEGRAM_USER_IDS
        else None
    )

    if not chat_id:
        logger.warning("Scheduled digest skipped: No DIGEST_CHAT_ID or ALLOWED_TELEGRAM_USER_IDS configured.")
        return

    logger.info("Running daily scheduled email digest for chat ID %s...", chat_id)

    gmail_svc: GmailService = context.bot_data.get("gmail_service")
    groq_svc: GroqService = context.bot_data.get("groq_service")

    if not gmail_svc or not groq_svc:
        logger.error("Services not available in bot_data.")
        return

    try:
        unread = gmail_svc.fetch_unread_emails(max_results=12)
        if not unread:
            await context.bot.send_message(
                chat_id=chat_id,
                text="☀️ <b>Good Morning!</b>\nYour Gmail inbox is clear with 0 unread messages.",
                parse_mode=ParseMode.HTML,
            )
            return

        digest = groq_svc.summarize_inbox(unread)

        header = (
            f"☀️ <b>DAILY MORNING INBOX DIGEST</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{html.escape(digest.executive_summary)}\n\n"
            f"<i>You have {len(unread)} unread emails. Here are the highlights:</i>"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=header,
            parse_mode=ParseMode.HTML,
        )

        for item in digest.items[:5]:  # Top 5 highlights in daily digest
            p_icon = "🔴" if item.priority.upper() == "URGENT" else ("🟡" if item.priority.upper() == "IMPORTANT" else "🔵")
            card = (
                f"{p_icon} <b>{html.escape(item.subject)}</b>\n"
                f"<b>From:</b> {html.escape(item.sender)}\n"
                f"<b>TL;DR:</b> {html.escape(item.tl_dr)}\n"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=card,
                parse_mode=ParseMode.HTML,
            )

    except Exception as e:
        logger.exception("Error executing scheduled daily digest: %s", e)


def register_scheduler(app: Application, gmail_svc: GmailService, groq_svc: GroqService) -> None:
    """Register daily scheduled job in the Telegram Application job queue."""
    if not Config.ENABLE_SCHEDULED_DIGEST:
        logger.info("Scheduled daily digest is disabled in config.")
        return

    if not app.job_queue:
        logger.warning("JobQueue is not enabled in python-telegram-bot application.")
        return

    try:
        hour, minute = map(int, Config.DAILY_DIGEST_TIME.split(":"))
        scheduled_time = datetime.time(hour=hour, minute=minute)
    except Exception as e:
        logger.error("Invalid DAILY_DIGEST_TIME format: %s. Defaulting to 08:30.", e)
        scheduled_time = datetime.time(hour=8, minute=30)

    # Store service references in bot_data for job callback
    app.bot_data["gmail_service"] = gmail_svc
    app.bot_data["groq_service"] = groq_svc

    app.job_queue.run_daily(
        run_daily_digest_job,
        time=scheduled_time,
        name="daily_digest_job",
    )
    logger.info("Scheduled daily inbox digest configured for %s daily.", scheduled_time)
