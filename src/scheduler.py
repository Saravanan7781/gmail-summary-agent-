"""Automated background scheduler for daily briefings and proactive VIP Radar alerts."""

import datetime
import html
import logging
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from src.config import Config
from src.gmail_service import GmailService
from src.groq_service import GroqService
from src.vip_manager import vip_manager

logger = logging.getLogger(__name__)


def clean_sender_name(raw_sender: str) -> str:
    """Extract clean sender name for concise notifications."""
    if "<" in raw_sender:
        name_part = raw_sender.split("<")[0].strip().strip('"').strip("'")
        if name_part:
            return name_part
    return raw_sender.split("@")[0].strip()


async def run_vip_radar_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proactive background radar: runs every 5 minutes checking for VIP or urgent emails."""
    chat_id = Config.DIGEST_CHAT_ID or (
        list(Config.ALLOWED_TELEGRAM_USER_IDS)[0]
        if Config.ALLOWED_TELEGRAM_USER_IDS
        else None
    )
    if not chat_id:
        return

    gmail_svc: GmailService = context.bot_data.get("gmail_service")
    groq_svc: GroqService = context.bot_data.get("groq_service")
    if not gmail_svc or not groq_svc:
        return

    try:
        # Check latest 8 unread emails
        unread = gmail_svc.fetch_unread_emails(max_results=8)
        for email in unread:
            msg_id = email.get("id")
            if not msg_id or vip_manager.has_alerted(msg_id):
                continue

            sender = email.get("from", "")
            subject = email.get("subject", "")

            # Check if matches VIP watchlist keyword / email
            vip_match = vip_manager.matches_vip(sender, subject)

            # Analyze urgency with Groq
            urgency_eval = groq_svc.evaluate_email_urgency(email, vip_match=vip_match)

            if urgency_eval and urgency_eval.is_urgent:
                # Mark as alerted so we never duplicate alerts
                vip_manager.mark_alerted(msg_id)

                clean_name = clean_sender_name(sender)
                alert_text = (
                    f"🚨 <b>VIP RADAR ALERT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>From:</b> {html.escape(clean_name)}\n"
                    f"<b>Subject:</b> <code>{html.escape(subject)}</code>\n"
                    f"<b>Trigger:</b> <i>{html.escape(urgency_eval.reason)}</i>\n\n"
                    f"<b>Takeaway:</b>\n{html.escape(urgency_eval.tl_dr)}\n"
                )
                if urgency_eval.action_required:
                    alert_text += f"\n<b>⚡ Action:</b> <i>{html.escape(urgency_eval.action_required)}</i>\n"

                keyboard = [
                    [
                        InlineKeyboardButton("✍️ Draft AI Reply", callback_data=f"draft:{msg_id}"),
                        InlineKeyboardButton("✅ Mark Read", callback_data=f"read:{msg_id}"),
                    ],
                    [
                        InlineKeyboardButton("📄 View Full Content", callback_data=f"view:{msg_id}"),
                        InlineKeyboardButton("🔕 Mute Senders", callback_data=f"mute_sender:{msg_id}")
                    ]
                ]

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=alert_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                logger.info("VIP Radar alert dispatched for message %s (%s)", msg_id, urgency_eval.reason)

    except Exception as e:
        logger.exception("Error in VIP radar job: %s", e)


async def run_daily_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job that executes daily and delivers morning inbox briefing."""
    chat_id = Config.DIGEST_CHAT_ID or (
        list(Config.ALLOWED_TELEGRAM_USER_IDS)[0]
        if Config.ALLOWED_TELEGRAM_USER_IDS
        else None
    )

    if not chat_id:
        return

    logger.info("Running daily scheduled email digest for chat ID %s...", chat_id)
    gmail_svc: GmailService = context.bot_data.get("gmail_service")
    groq_svc: GroqService = context.bot_data.get("groq_service")
    if not gmail_svc or not groq_svc:
        return

    try:
        unread = gmail_svc.fetch_unread_emails(max_results=10)
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
            f"<i>You have {len(unread)} unread emails. Highlights below:</i>"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=header,
            parse_mode=ParseMode.HTML,
        )

        for item in digest.items[:4]:
            p_icon = "🔴" if item.priority.upper() == "URGENT" else ("🟡" if item.priority.upper() == "IMPORTANT" else "🔵")
            card = (
                f"{p_icon} <b>{html.escape(item.subject)}</b>\n"
                f"<b>From:</b> {html.escape(clean_sender_name(item.sender))}\n"
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
    """Register daily scheduled job and proactive VIP Radar in the Telegram job queue."""
    if not app.job_queue:
        logger.warning("JobQueue is not enabled in python-telegram-bot application.")
        return

    # Store service references in bot_data for callbacks
    app.bot_data["gmail_service"] = gmail_svc
    app.bot_data["groq_service"] = groq_svc

    # 1. Proactive VIP Radar: Runs every 5 minutes (300s)
    app.job_queue.run_repeating(
        run_vip_radar_job,
        interval=300,
        first=15,
        name="vip_radar_job",
    )
    logger.info("Proactive VIP Radar scheduled (checking every 5 minutes).")

    # 2. Daily morning briefing
    if Config.ENABLE_SCHEDULED_DIGEST:
        try:
            hour, minute = map(int, Config.DAILY_DIGEST_TIME.split(":"))
            scheduled_time = datetime.time(hour=hour, minute=minute)
        except Exception as e:
            logger.error("Invalid DAILY_DIGEST_TIME format: %s. Defaulting to 08:30.", e)
            scheduled_time = datetime.time(hour=8, minute=30)

        app.job_queue.run_daily(
            run_daily_digest_job,
            time=scheduled_time,
            name="daily_digest_job",
        )
        logger.info("Daily scheduled digest set for %s.", scheduled_time)
