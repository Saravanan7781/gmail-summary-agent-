"""Automated background scheduler for daily briefings and proactive VIP Radar alerts."""

import datetime
import html
import logging
from typing import Optional
from zoneinfo import ZoneInfo
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

            # Analyze urgency using hybrid heuristic + Groq engine
            urgency_eval = groq_svc.evaluate_email_urgency(email, vip_match=vip_match)

            if urgency_eval and urgency_eval.is_urgent:
                # Mark as alerted so we never duplicate alerts
                vip_manager.mark_alerted(msg_id)

                clean_name = clean_sender_name(sender)
                alert_text = (
                    f"🚨 <b>VIP RADAR ALERT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>From:</b> {html.escape(clean_name)}\n"
                    f"✉️ <b>Subject:</b> <code>{html.escape(subject)}</code>\n"
                    f"⚡ <b>Trigger:</b> <i>{html.escape(urgency_eval.reason)}</i>\n\n"
                    f"📌 <b>Takeaway:</b>\n{html.escape(urgency_eval.tl_dr)}\n"
                )
                if urgency_eval.action_required:
                    alert_text += f"\n👉 <b>Action Needed:</b> <i>{html.escape(urgency_eval.action_required)}</i>\n"

                keyboard = [
                    [
                        InlineKeyboardButton("✍️ Draft AI Reply", callback_data=f"draft:{msg_id}"),
                        InlineKeyboardButton("✅ Mark Read", callback_data=f"read:{msg_id}"),
                    ],
                    [
                        InlineKeyboardButton("📄 View Content", callback_data=f"view:{msg_id}"),
                        InlineKeyboardButton("⭐ Add Sender to VIP", callback_data=f"add_vip_sender:{msg_id}")
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
    """Scheduled job that executes daily and delivers a single, cohesive morning inbox briefing."""
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
        unread = gmail_svc.fetch_unread_emails(max_results=12)
        tz = ZoneInfo(Config.TIMEZONE)
        now_str = datetime.datetime.now(tz).strftime("%A, %d %b • %I:%M %p")

        if not unread:
            clean_morning = (
                f"☀️ <b>MORNING EXECUTIVE BRIEFING</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <i>{now_str} IST</i>\n\n"
                f"🎉 <b>Inbox Zero!</b> You have no unread emails right now.\n"
                f"Enjoy your productive day!"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=clean_morning,
                parse_mode=ParseMode.HTML,
            )
            return

        digest = groq_svc.summarize_inbox(unread)
        urgent = [i for i in digest.items if i.priority.upper() == "URGENT"]
        important = [i for i in digest.items if i.priority.upper() == "IMPORTANT"]
        routine = [i for i in digest.items if i.priority.upper() not in ("URGENT", "IMPORTANT")]

        lines = [
            "☀️ <b>MORNING EXECUTIVE BRIEFING</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 <i>{now_str} IST</i>\n",
            f"📊 <b>Inbox Health:</b> {len(unread)} Unread | 🚨 {len(urgent)} Critical | 📌 {len(important)} Important\n",
            "🎯 <b>Executive Synthesis:</b>",
            f"<i>{html.escape(digest.executive_summary)}</i>\n",
        ]

        if urgent:
            lines.append("🚨 <b>CRITICAL ACTION REQUIRED:</b>")
            for item in urgent[:3]:
                sender = clean_sender_name(item.sender)
                lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(item.tl_dr)}")
                if item.action_items:
                    lines.append(f"  👉 <i>{html.escape(item.action_items[0])}</i>")
            lines.append("")

        if important:
            lines.append("📌 <b>NOTABLE HIGHLIGHTS:</b>")
            for item in important[:3]:
                sender = clean_sender_name(item.sender)
                lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(item.tl_dr)}")
            lines.append("")

        if routine:
            lines.append(f"☕ <i>+{len(routine)} routine notifications & newsletters.</i>\n")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("👇 <i>Open your command center below to take action:</i>")

        keyboard = [
            [
                InlineKeyboardButton("📊 Open Executive Dashboard", callback_data="refresh_summary"),
                InlineKeyboardButton("⚡ Scan VIP Radar", callback_data="radar_scan_now"),
            ]
        ]

        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
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

    # 2. Daily morning briefing with proper timezone
    if Config.ENABLE_SCHEDULED_DIGEST:
        try:
            tz = ZoneInfo(Config.TIMEZONE)
            hour, minute = map(int, Config.DAILY_DIGEST_TIME.split(":"))
            scheduled_time = datetime.time(hour=hour, minute=minute, tzinfo=tz)
        except Exception as e:
            logger.error("Invalid DAILY_DIGEST_TIME format: %s. Defaulting to 08:30 IST.", e)
            tz = ZoneInfo("Asia/Kolkata")
            scheduled_time = datetime.time(hour=8, minute=30, tzinfo=tz)

        app.job_queue.run_daily(
            run_daily_digest_job,
            time=scheduled_time,
            name="daily_digest_job",
        )
        logger.info("Daily scheduled digest set for %s in timezone %s.", scheduled_time, Config.TIMEZONE)
