"""Modern, elegant Telegram Bot UX with Context Memory and Smart Intent Handling."""

import datetime
import html
import logging
import re
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import Config
from src.gmail_service import GmailService
from src.groq_service import GroqService
from src.vip_manager import vip_manager

logger = logging.getLogger(__name__)

# Persistent bottom quick-action keyboard
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 Executive Summary"), KeyboardButton("📬 Unread Emails")],
        [KeyboardButton("⭐ VIP Radar"), KeyboardButton("⚙️ Status")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def is_authorized(user_id: int) -> bool:
    """Check if the user ID is in the allowed whitelist."""
    if not Config.ALLOWED_TELEGRAM_USER_IDS:
        return True
    return user_id in Config.ALLOWED_TELEGRAM_USER_IDS


async def check_auth_or_reject(update: Update) -> bool:
    """Validate user authorization and send rejection message if unauthorized."""
    user = update.effective_user
    if not user:
        return False
    if not is_authorized(user.id):
        msg = (
            f"⛔ <b>Access Denied</b>\n\n"
            f"Your Telegram User ID is: <code>{user.id}</code>\n"
            f"Add this ID to <code>ALLOWED_TELEGRAM_USER_IDS</code> in your environment variables to grant access."
        )
        if update.message:
            await update.message.reply_html(msg)
        elif update.callback_query:
            await update.callback_query.answer("Access Denied", show_alert=True)
        return False
    return True


def clean_sender_name(raw_sender: str) -> str:
    """Extract clean sender name."""
    if "<" in raw_sender:
        name_part = raw_sender.split("<")[0].strip().strip('"').strip("'")
        if name_part:
            return name_part
    return raw_sender.split("@")[0].strip()


class GmailBot:
    """Telegram Bot Controller with modern executive UI, context memory, and smart intent handling."""

    def __init__(self, gmail_svc: GmailService, groq_svc: GroqService):
        self.gmail = gmail_svc
        self.groq = groq_svc

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not await check_auth_or_reject(update):
            return

        user_name = update.effective_user.first_name or "there"
        welcome_text = (
            f"👋 <b>Welcome back, {html.escape(user_name)}!</b>\n\n"
            f"I am your personal <b>Gmail Chief of Staff</b> powered by <b>Groq LPU</b>.\n\n"
            f"<b>Core Capabilities:</b>\n"
            f"• 🚨 <b>Proactive VIP Radar</b>: Automatically monitoring for critical alerts and VIP senders every 5 min.\n"
            f"• 📊 <b>Executive Summary</b>: Consolidated inbox pulse without notification spam.\n"
            f"• ✍️ <b>Natural AI Replies</b>: Ask me to draft replies directly in chat (*'Draft a reply to Saravanan saying...'*)!\n"
            f"• 💬 <b>Natural Chat</b>: Ask me any question about your emails.\n\n"
            f"<i>Tap any button below or ask a question directly!</i>"
        )
        await update.message.reply_html(welcome_text, reply_markup=MAIN_KEYBOARD)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Check system status."""
        if not await check_auth_or_reject(update):
            return

        watchlist = vip_manager.get_watchlist()
        vip_count = len(watchlist)
        seen_count = vip_manager.get_seen_count()
        status_text = (
            f"⚙️ <b>ASSISTANT TELEMETRY & HEALTH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Host Environment:</b> 🟢 Render Cloud (24/7 Web Service)\n"
            f"• <b>AI Inference:</b> Groq LPU (<code>{html.escape(Config.GROQ_MODEL)}</code>)\n"
            f"• <b>Urgency Engine:</b> 🟢 Zero-Token Fast Path Active\n"
            f"• <b>Gmail OAuth:</b> {'🟢 Authenticated & Connected' if Config.GMAIL_TOKEN_PATH.exists() else '❌ Not Authenticated'}\n"
            f"• <b>VIP Radar:</b> 🟢 Active (Continuous 5-Min Sweep | {vip_count} watched)\n"
            f"• <b>Morning Briefing:</b> {'☀️ Daily at ' + Config.DAILY_DIGEST_TIME + ' IST' if Config.ENABLE_SCHEDULED_DIGEST else '⏸️ Inactive'}\n"
            f"• <b>Timezone:</b> 🇮🇳 {Config.TIMEZONE} (UTC+05:30)\n"
            f"• <b>Alert Deduplication:</b> 🛡️ {seen_count} Signatures Cached\n"
            f"• <b>Authorized User ID:</b> <code>{update.effective_user.id}</code>"
        )
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh Pulse", callback_data="refresh_summary"),
                InlineKeyboardButton("⚡ Scan VIP Radar", callback_data="radar_scan_now"),
            ]
        ]
        await update.message.reply_html(status_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def vip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Manage VIP Radar watchlist and view proactive radar telemetry."""
        if not await check_auth_or_reject(update):
            return

        if context.args:
            sub = context.args[0].lower()
            if sub == "add" and len(context.args) > 1:
                target = " ".join(context.args[1:]).strip()
                if vip_manager.add_vip(target):
                    await update.message.reply_html(f"⭐ <b>Added to VIP Watchlist:</b> <code>{html.escape(target)}</code>\n<i>I will instantly alert you whenever they email!</i>")
                else:
                    await update.message.reply_html(f"ℹ️ <code>{html.escape(target)}</code> is already on your VIP list.")
                return
            elif (sub in ("remove", "del")) and len(context.args) > 1:
                target = " ".join(context.args[1:]).strip()
                if vip_manager.remove_vip(target):
                    await update.message.reply_html(f"🗑️ <b>Removed from VIP Watchlist:</b> <code>{html.escape(target)}</code>")
                else:
                    await update.message.reply_html(f"ℹ️ Could not find <code>{html.escape(target)}</code> on your list.")
                return

        watchlist = vip_manager.get_watchlist()
        seen_count = vip_manager.get_seen_count()
        if watchlist:
            items_list = "\n".join([f"  {idx}. <code>{html.escape(v)}</code>" for idx, v in enumerate(watchlist, 1)])
        else:
            items_list = "  <i>No custom senders yet. (Autonomous triggers still detect payments, security & deadlines!)</i>"

        text = (
            f"🚨 <b>VIP RADAR COMMAND CENTER</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Scanner State:</b> 🟢 Active (Continuous 5-Min Sweeps)\n"
            f"• <b>Timezone:</b> 🇮🇳 {Config.TIMEZONE} (IST)\n"
            f"• <b>Alert Signatures Cached:</b> 🛡️ {seen_count}\n\n"
            f"<b>Autonomous Trigger Matrix:</b>\n"
            f"  ✅ Real-time Financial Credits & UPI/Bank Transfers\n"
            f"  ✅ 2FA & Security Verification Codes\n"
            f"  ✅ Urgent Deadlines & Time-Sensitive Direct Inquiries\n\n"
            f"⭐ <b>Active VIP Watchlist ({len(watchlist)}):</b>\n"
            f"{items_list}\n\n"
            f"<b>How to Manage:</b>\n"
            f"• Add sender/domain: <code>/vip add saravanan</code>\n"
            f"• Remove sender: <code>/vip remove saravanan</code>"
        )

        keyboard = [
            [
                InlineKeyboardButton("⚡ Scan Radar Right Now", callback_data="radar_scan_now"),
                InlineKeyboardButton("🧹 Reset Alert Cache", callback_data="reset_radar_cache"),
            ],
            [
                InlineKeyboardButton("📊 Executive Pulse", callback_data="refresh_summary"),
                InlineKeyboardButton("📬 Unread Emails", callback_data="open_unread_list"),
            ]
        ]
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Generate a sleek, consolidated executive inbox summary."""
        if not await check_auth_or_reject(update):
            return

        chat = update.effective_chat
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        status_msg = await update.message.reply_html("⚡ <i>Analyzing inbox telemetry and preparing executive briefing...</i>")

        try:
            unread_emails = self.gmail.fetch_unread_emails(max_results=12)
            tz = ZoneInfo(Config.TIMEZONE)
            timestamp = datetime.datetime.now(tz).strftime("%I:%M %p • %d %b")

            if not unread_emails:
                inbox_zero = (
                    "🎉 <b>INBOX ZERO ACHIEVED</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕒 <i>Checked at {timestamp} IST</i>\n\n"
                    "Your inbox is completely clear! No unread messages.\n"
                    "Proactive VIP Radar is actively standing by."
                )
                keyboard = [
                    [InlineKeyboardButton("⚡ Scan VIP Radar", callback_data="radar_scan_now")],
                    [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_summary")]
                ]
                await status_msg.edit_text(inbox_zero, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
                return

            digest = self.groq.summarize_inbox(unread_emails)

            context.user_data["cached_items"] = {
                item.id: item for item in digest.items
            }
            context.user_data["cached_emails"] = {
                em["id"]: em for em in unread_emails
            }
            if unread_emails:
                context.user_data["last_active_email"] = unread_emails[0]

            urgent = [i for i in digest.items if i.priority.upper() == "URGENT"]
            important = [i for i in digest.items if i.priority.upper() == "IMPORTANT"]
            normal_or_low = [i for i in digest.items if i.priority.upper() not in ("URGENT", "IMPORTANT")]

            lines = [
                "⚡ <b>EXECUTIVE INBOX PULSE</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"📊 <b>Unread:</b> {len(unread_emails)}  │  🚨 <b>Critical:</b> {len(urgent)}  │  📌 <b>Important:</b> {len(important)}",
                f"🕒 <i>Synced: {timestamp} IST</i>\n",
                "🎯 <b>EXECUTIVE SYNTHESIS:</b>",
                f"<i>{html.escape(digest.executive_summary)}</i>\n",
            ]

            if urgent:
                lines.append(f"🚨 <b>CRITICAL ACTION REQUIRED ({len(urgent)}):</b>")
                for it in urgent:
                    sender = clean_sender_name(it.sender)
                    lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(it.tl_dr)}")
                    if it.action_items:
                        lines.append(f"  👉 <i>{html.escape(it.action_items[0])}</i>")
                lines.append("")

            if important:
                lines.append(f"📌 <b>NOTABLE UPDATES ({len(important)}):</b>")
                for it in important:
                    sender = clean_sender_name(it.sender)
                    lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(it.tl_dr)}")
                lines.append("")

            if normal_or_low:
                lines.append(f"☕ <b>ROUTINE & NEWSLETTERS ({len(normal_or_low)}):</b>")
                for it in normal_or_low[:3]:
                    sender = clean_sender_name(it.sender)
                    lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(it.tl_dr)}")
                if len(normal_or_low) > 3:
                    lines.append(f"• <i>...and {len(normal_or_low) - 3} more automated notifications</i>")
                lines.append("")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("👇 <i>Select an email below to view details or generate an instant AI reply:</i>")

            keyboard = []
            row = []
            for idx, it in enumerate(digest.items[:8], start=1):
                clean_name = clean_sender_name(it.sender)[:13]
                icon = "🔴" if it.priority.upper() == "URGENT" else ("🟡" if it.priority.upper() == "IMPORTANT" else "✉️")
                btn = InlineKeyboardButton(f"{icon} {idx}. {clean_name}", callback_data=f"open:{it.id}")
                row.append(btn)
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            keyboard.append([
                InlineKeyboardButton("🔄 Refresh Pulse", callback_data="refresh_summary"),
                InlineKeyboardButton("⚡ VIP Radar Scan", callback_data="radar_scan_now"),
            ])
            keyboard.append([
                InlineKeyboardButton("🧹 Mark All Low Read", callback_data="mark_all_low"),
            ])

            await status_msg.edit_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        except Exception as e:
            logger.exception("Error in /summary handler: %s", e)
            await status_msg.edit_text(
                f"❌ <b>Error:</b> <code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
            )

    async def unread_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Quick visual list of unread emails."""
        if not await check_auth_or_reject(update):
            return

        chat = update.effective_chat
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        try:
            emails = self.gmail.fetch_unread_emails(max_results=10)
            if not emails:
                await update.message.reply_html("🎉 <b>All caught up!</b> No unread emails.", reply_markup=MAIN_KEYBOARD)
                return

            context.user_data["cached_emails"] = {em["id"]: em for em in emails}
            if emails:
                context.user_data["last_active_email"] = emails[0]

            lines = [
                "📬 <b>INBOX UNREAD QUEUE</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Found <b>{len(emails)} unread messages</b> in your inbox:\n"
            ]
            for i, em in enumerate(emails, 1):
                sender = clean_sender_name(em.get("from", "Unknown"))
                subj = em.get("subject", "(No Subject)")
                snip = (em.get("snippet", ""))[:75]
                heur = self.groq.detect_urgency_heuristics(em)
                vip_m = vip_manager.matches_vip(sender, subj)
                badge = "🔴" if (heur and heur.is_urgent) or vip_m else "✉️"
                lines.append(f"{badge} <b>{i}. {html.escape(sender)}</b>\n   └ <code>{html.escape(subj[:60])}</code>\n   <i>{html.escape(snip)}...</i>")

            keyboard = [
                [
                    InlineKeyboardButton("📊 Generate Executive Pulse", callback_data="refresh_summary"),
                    InlineKeyboardButton("⚡ Scan VIP Radar", callback_data="radar_scan_now"),
                ]
            ]

            await update.message.reply_html(
                "\n\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as e:
            logger.exception("Error in /unread: %s", e)
            await update.message.reply_html(f"❌ Error: <code>{html.escape(str(e))}</code>")

    def _find_target_email_for_draft(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[Optional[Dict[str, Any]], str]:
        """Intelligently locate the email the user wants to reply to and extract custom instructions."""
        lower_text = text.lower()
        last_active = context.user_data.get("last_active_email")

        # Extract instructions (everything after 'like', 'saying', 'that', 'with', 'telling')
        instruction = text
        for marker in ("like ", "saying ", "that ", "with ", "telling "):
            if marker in lower_text:
                parts = re.split(marker, text, flags=re.IGNORECASE, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    instruction = parts[1].strip()
                break

        # Check if text mentions a person's name or keywords
        potential_names = []
        for word in lower_text.replace(",", " ").split():
            if word not in (
                "draft", "a", "reply", "to", "email", "mail", "like", "saying",
                "i", "ive", "i've", "have", "received", "formally", "please",
                "the", "and", "previously", "marked", "it", "as", "read", "him", "her", "them"
            ) and len(word) > 2:
                potential_names.append(word)

        # 1. Check if last_active_email matches any extracted name
        if last_active:
            last_from = (last_active.get("from", "")).lower()
            last_subj = (last_active.get("subject", "")).lower()
            if not potential_names or any(name in last_from or name in last_subj for name in potential_names):
                return last_active, instruction

        # 2. Search recent emails (both read and unread from the past 4 days)
        for name in potential_names:
            matches = self.gmail.get_recent_emails(max_results=5, query=name)
            if matches:
                context.user_data["last_active_email"] = matches[0]
                return matches[0], instruction

        # 3. Fallback to general search
        if potential_names:
            search_query = " ".join(potential_names[:2])
            matches = self.gmail.search_emails(query=search_query, max_results=3)
            if matches:
                context.user_data["last_active_email"] = matches[0]
                return matches[0], instruction

        # 4. Fallback to last_active_email if available
        if last_active:
            return last_active, instruction

        return None, instruction

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages, bottom menu taps, and smart drafting requests."""
        if not await check_auth_or_reject(update):
            return

        text = update.message.text.strip()
        lower_text = text.lower()

        # 1. Route bottom keyboard buttons
        if text == "📊 Executive Summary":
            await self.summary_command(update, context)
            return
        elif text == "📬 Unread Emails":
            await self.unread_command(update, context)
            return
        elif text == "⭐ VIP Radar":
            await self.vip_command(update, context)
            return
        elif text == "⚙️ Status":
            await self.status_command(update, context)
            return

        # 2. Check if user is asking to draft a reply
        draft_triggers = ("draft a reply", "draft reply", "reply to", "write a reply", "respond to")
        is_draft_request = any(trig in lower_text for trig in draft_triggers)

        if is_draft_request:
            await update.message.reply_chat_action(ChatAction.TYPING)
            progress_msg = await update.message.reply_html("✍️ <i>Finding target email and composing draft with Groq...</i>")

            target_email, instructions = self._find_target_email_for_draft(text, context)

            if not target_email:
                await progress_msg.edit_text(
                    "🤔 <i>I couldn't locate the specific email to reply to.</i>\n\n"
                    "Try specifying the sender's name or subject (e.g. <code>Draft a reply to Saravanan saying...</code>), "
                    "or tap <b>[✍️ Draft AI Reply]</b> directly on any email card!",
                    parse_mode=ParseMode.HTML,
                )
                return

            draft_content = self.groq.draft_reply(target_email, user_instructions=instructions)
            draft_id = self.gmail.create_draft(
                to=target_email.get("from", ""),
                subject=draft_content.get("subject", ""),
                body_text=draft_content.get("body", ""),
                in_reply_to=target_email.get("message_id_header"),
                thread_id=target_email.get("thread_id"),
            )

            if draft_id:
                sender_display = clean_sender_name(target_email.get("from", ""))
                reply_card = (
                    f"✍️ <b>Draft Created in Gmail!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>In Reply To:</b> {html.escape(sender_display)} (<code>{html.escape(target_email.get('subject', ''))}</code>)\n"
                    f"<b>Subject:</b> <code>{html.escape(draft_content.get('subject', ''))}</code>\n\n"
                    f"<b>Draft Content:</b>\n"
                    f"<blockquote>{html.escape(draft_content.get('body', ''))}</blockquote>\n\n"
                    f"💾 <i>Saved to your Gmail Drafts folder. You can review and send it anytime!</i>"
                )
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Mark as Read", callback_data=f"read:{target_email.get('id')}"),
                        InlineKeyboardButton("📄 View Email Content", callback_data=f"view:{target_email.get('id')}"),
                    ]
                ]
                await progress_msg.edit_text(reply_card, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await progress_msg.edit_text("❌ Failed to save draft to Gmail.")
            return

        # 3. Natural language inquiry about inbox
        question = text.removeprefix("/ask").strip()
        await update.message.reply_chat_action(ChatAction.TYPING)
        status_msg = await update.message.reply_html("🔍 <i>Searching your inbox & consulting Groq...</i>")

        try:
            # Smart context collection:
            # 1. Fetch recent emails (both read & unread from past 4 days)
            recent_inbox = self.gmail.get_recent_emails(max_results=8)

            # 2. Extract potential keywords from user question to perform targeted search
            search_keywords = [
                w for w in question.lower().replace("?", "").replace(",", "").split()
                if w not in ("show", "me", "important", "mails", "mail", "emails", "the", "first", "1st", "you", "think", "is", "it", "are", "from", "any", "what", "did", "get")
                and len(w) > 2
            ]

            targeted_emails = []
            if search_keywords:
                search_term = " ".join(search_keywords[:2])
                targeted_emails = self.gmail.search_emails(query=search_term, max_results=5)

            # Combine and deduplicate emails
            combined_emails = []
            seen_ids = set()
            for em in (targeted_emails + recent_inbox):
                if em.get("id") and em["id"] not in seen_ids:
                    seen_ids.add(em["id"])
                    combined_emails.append(em)

            answer = self.groq.answer_query_about_emails(user_question=question, emails=combined_emails[:8])
            response_text = (
                f"💡 <b>Inbox Intelligence</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{html.escape(answer)}"
            )
            await status_msg.edit_text(response_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Error in natural language query: %s", e)
            await status_msg.edit_text(f"❌ Error: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle interactive inline buttons."""
        query = update.callback_query
        if not await check_auth_or_reject(update):
            return

        await query.answer()
        data = query.data or ""

        if data == "refresh_summary":
            await self.summary_command(update, context)
            return

        elif data == "open_unread_list":
            await self.unread_command(update, context)
            return

        elif data == "reset_radar_cache":
            cleared = vip_manager.clear_seen_alerts()
            await query.message.reply_html(
                f"🧹 <b>VIP Alert Cache Cleared!</b>\n"
                f"Reset {cleared} deduplicated signatures. Proactive radar can now re-alert on previous messages if desired."
            )
            return

        elif data == "radar_scan_now":
            await query.message.reply_chat_action(ChatAction.TYPING)
            progress = await query.message.reply_html("⚡ <i>Scanning inbox with VIP Radar...</i>")
            # Fetch unread emails
            unread = self.gmail.fetch_unread_emails(max_results=10)
            found_alerts = 0
            for em in unread:
                vip_m = vip_manager.matches_vip(em.get("from", ""), em.get("subject", ""))
                eval_res = self.groq.evaluate_email_urgency(em, vip_match=vip_m)
                if eval_res and eval_res.is_urgent:
                    found_alerts += 1
                    # Save into context memory!
                    context.user_data["last_active_email"] = em
                    clean_name = clean_sender_name(em.get("from", ""))
                    alert_card = (
                        f"🚨 <b>VIP RADAR: Live Alert</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 <b>From:</b> {html.escape(clean_name)}\n"
                        f"✉️ <b>Subject:</b> <code>{html.escape(em.get('subject', ''))}</code>\n"
                        f"⚡ <b>Trigger:</b> <i>{html.escape(eval_res.reason)}</i>\n\n"
                        f"📌 <b>Takeaway:</b>\n{html.escape(eval_res.tl_dr)}\n"
                    )
                    if eval_res.action_required:
                        alert_card += f"\n👉 <b>Action Needed:</b> <i>{html.escape(eval_res.action_required)}</i>\n"

                    keyboard = [
                        [
                            InlineKeyboardButton("✍️ Draft AI Reply", callback_data=f"draft:{em.get('id')}"),
                            InlineKeyboardButton("✅ Mark Read", callback_data=f"read:{em.get('id')}"),
                        ],
                        [
                            InlineKeyboardButton("⭐ Add Sender to VIP", callback_data=f"add_vip_sender:{em.get('id')}"),
                            InlineKeyboardButton("📄 View Content", callback_data=f"view:{em.get('id')}"),
                        ]
                    ]
                    await query.message.reply_html(alert_card, reply_markup=InlineKeyboardMarkup(keyboard))
            if found_alerts == 0:
                await progress.edit_text(
                    f"✅ <b>Radar Scan Complete:</b> Checked {len(unread)} unread emails. No urgent or VIP triggers detected right now.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await progress.delete()

        elif data.startswith("open:"):
            msg_id = data.split("open:")[1]
            cached_items = context.user_data.get("cached_items", {})
            item = cached_items.get(msg_id)
            email = self.gmail.get_email_details(msg_id)

            if not email:
                await query.message.reply_html("❌ Could not load email details.")
                return

            # Store in context memory
            context.user_data["last_active_email"] = email

            sender = email.get("from", "Unknown")
            subject = email.get("subject", "(No Subject)")
            date = email.get("date", "")
            tldr = item.tl_dr if item else email.get("snippet", "")
            actions = ("\n<b>⚡ Action Item:</b> " + ", ".join(item.action_items)) if item and item.action_items else ""

            card = (
                f"📩 <b>Email Detail</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>From:</b> {html.escape(sender)}\n"
                f"<b>Subject:</b> <code>{html.escape(subject)}</code>\n"
                f"<b>Date:</b> {html.escape(date)}\n\n"
                f"<b>Summary:</b>\n{html.escape(tldr)}\n"
                f"{actions}"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✍️ Draft AI Reply", callback_data=f"draft:{msg_id}"),
                    InlineKeyboardButton("✅ Mark Read", callback_data=f"read:{msg_id}"),
                ],
                [
                    InlineKeyboardButton("⭐ Add Sender to VIP", callback_data=f"add_vip_sender:{msg_id}"),
                    InlineKeyboardButton("📄 View Full Content", callback_data=f"view:{msg_id}"),
                ],
                [
                    InlineKeyboardButton("⬅️ Back to Summary", callback_data="refresh_summary")
                ]
            ]
            await query.message.reply_html(card, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("add_vip_sender:"):
            msg_id = data.split("add_vip_sender:")[1]
            email = self.gmail.get_email_details(msg_id)
            if email:
                sender_raw = email.get("from", "")
                clean_name = clean_sender_name(sender_raw)
                vip_manager.add_vip(clean_name)
                await query.message.reply_html(f"⭐ <b>Added '{html.escape(clean_name)}' to VIP Radar!</b>\n<i>You'll be alerted immediately whenever they email.</i>")
            else:
                await query.message.reply_html("❌ Could not determine sender.")

        elif data.startswith("read:"):
            msg_id = data.split("read:")[1]
            email = self.gmail.get_email_details(msg_id)
            if email:
                context.user_data["last_active_email"] = email

            success = self.gmail.mark_as_read(msg_id)
            if success:
                keyboard = [
                    [
                        InlineKeyboardButton("✍️ Draft AI Reply", callback_data=f"draft:{msg_id}"),
                        InlineKeyboardButton("📊 Back to Pulse", callback_data="refresh_summary"),
                    ]
                ]
                await query.message.reply_html(f"✅ <b>Marked as read in Gmail!</b>", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.message.reply_html("❌ Failed to mark email as read.")

        elif data.startswith("draft:"):
            msg_id = data.split("draft:")[1]
            await query.message.reply_chat_action(ChatAction.TYPING)
            progress_msg = await query.message.reply_html("✍️ <i>Composing intelligent reply with Groq...</i>")

            email = self.gmail.get_email_details(msg_id)
            if not email:
                await progress_msg.edit_text("❌ Could not retrieve email details.")
                return

            context.user_data["last_active_email"] = email
            draft_content = self.groq.draft_reply(email)
            draft_id = self.gmail.create_draft(
                to=email.get("from", ""),
                subject=draft_content.get("subject", ""),
                body_text=draft_content.get("body", ""),
                in_reply_to=email.get("message_id_header"),
                thread_id=email.get("thread_id"),
            )

            if draft_id:
                reply_card = (
                    f"✍️ <b>Draft Created in Gmail!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>To:</b> {html.escape(clean_sender_name(email.get('from', '')))}\n"
                    f"<b>Subject:</b> <code>{html.escape(draft_content.get('subject', ''))}</code>\n\n"
                    f"<b>Draft Content:</b>\n"
                    f"<blockquote>{html.escape(draft_content.get('body', ''))}</blockquote>\n\n"
                    f"💾 <i>Saved to your Gmail Drafts folder. You can review and send it anytime!</i>"
                )
                await progress_msg.edit_text(reply_card, parse_mode=ParseMode.HTML)
            else:
                await progress_msg.edit_text("❌ Failed to save draft to Gmail.")

        elif data.startswith("view:"):
            msg_id = data.split("view:")[1]
            email = self.gmail.get_email_details(msg_id)
            if email:
                context.user_data["last_active_email"] = email
                body = email.get("body", "") or email.get("snippet", "")
                preview = (
                    f"📄 <b>Full Content:</b> {html.escape(email.get('subject', ''))}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{html.escape(body[:1500])}"
                )
                keyboard = [
                    [InlineKeyboardButton("✍️ Draft Reply", callback_data=f"draft:{msg_id}")]
                ]
                await query.message.reply_html(preview, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.message.reply_html("❌ Could not load email details.")

        elif data == "mark_all_low":
            cached_items = context.user_data.get("cached_items", {})
            marked_count = 0
            for item_id, item in cached_items.items():
                if item.priority.upper() not in ("URGENT", "IMPORTANT"):
                    if self.gmail.mark_as_read(item_id):
                        marked_count += 1
            await query.message.reply_html(f"🧹 <b>Marked {marked_count} low-priority emails as read!</b>")


def setup_bot_application(gmail_svc: GmailService, groq_svc: GroqService) -> Application:
    """Build and register all Telegram bot handlers."""
    if not Config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing in .env configuration.")

    request_client = HTTPXRequest(
        connection_pool_size=10,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).request(request_client).build()
    bot_ctrl = GmailBot(gmail_svc, groq_svc)

    app.add_handler(CommandHandler("start", bot_ctrl.start_command))
    app.add_handler(CommandHandler("help", bot_ctrl.start_command))
    app.add_handler(CommandHandler("status", bot_ctrl.status_command))
    app.add_handler(CommandHandler("vip", bot_ctrl.vip_command))
    app.add_handler(CommandHandler("summary", bot_ctrl.summary_command))
    app.add_handler(CommandHandler("digest", bot_ctrl.summary_command))
    app.add_handler(CommandHandler("unread", bot_ctrl.unread_command))
    app.add_handler(CommandHandler("ask", bot_ctrl.handle_message))

    app.add_handler(CallbackQueryHandler(bot_ctrl.handle_callback_query))

    # All regular text messages & bottom keyboard button taps
    app.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND),
            bot_ctrl.handle_message,
        )
    )

    return app
