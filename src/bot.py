"""Modern, elegant Telegram Bot UX for Gmail Summary Agent using Groq."""

import html
import logging
import re
from typing import Any, Dict, List, Optional
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

logger = logging.getLogger(__name__)

# Persistent bottom quick-action keyboard
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 Executive Summary"), KeyboardButton("📬 Unread Emails")],
        [KeyboardButton("🔍 Search Inbox"), KeyboardButton("⚙️ Status")],
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
    """Extract human-readable sender name (e.g. 'Abarna' from 'Abarna <abarna@gmail.com>')."""
    if "<" in raw_sender:
        name_part = raw_sender.split("<")[0].strip().strip('"').strip("'")
        if name_part:
            return name_part
    return raw_sender.split("@")[0].strip()


class GmailBot:
    """Telegram Bot Controller with modern executive UI."""

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
            f"Here is what I can do for you:\n"
            f"• 📊 <b>Executive Summary</b>: Unified inbox pulse and prioritized breakdown.\n"
            f"• ✍️ <b>One-Click AI Drafts</b>: Context-aware replies composed directly into Gmail.\n"
            f"• 💬 <b>Natural Chat</b>: Ask me any question about your emails.\n\n"
            f"<i>Tap any button below or simply ask me a question!</i>"
        )
        await update.message.reply_html(welcome_text, reply_markup=MAIN_KEYBOARD)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Check system status."""
        if not await check_auth_or_reject(update):
            return

        status_text = (
            f"⚙️ <b>Assistant Health & Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>AI Inference:</b> Groq ({html.escape(Config.GROQ_MODEL)})\n"
            f"• <b>Gmail OAuth:</b> {'✅ Connected' if Config.GMAIL_TOKEN_PATH.exists() else '❌ Not Authenticated'}\n"
            f"• <b>Scheduled Digest:</b> {'✅ Active (' + Config.DAILY_DIGEST_TIME + ')' if Config.ENABLE_SCHEDULED_DIGEST else '⏸️ Inactive'}\n"
            f"• <b>Authorized User:</b> <code>{update.effective_user.id}</code>"
        )
        await update.message.reply_html(status_text, reply_markup=MAIN_KEYBOARD)

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Generate a sleek, consolidated executive inbox summary."""
        if not await check_auth_or_reject(update):
            return

        chat = update.effective_chat
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        status_msg = await update.message.reply_html("⚡ <i>Reading your inbox and preparing executive briefing...</i>")

        try:
            unread_emails = self.gmail.fetch_unread_emails(max_results=10)

            if not unread_emails:
                await status_msg.edit_text("🎉 <b>Inbox Zero!</b> You have no unread emails right now.", parse_mode=ParseMode.HTML)
                return

            digest = self.groq.summarize_inbox(unread_emails)

            # Cache the items in user_data for interactive inspection
            context.user_data["cached_items"] = {
                item.id: item for item in digest.items
            }
            context.user_data["cached_emails"] = {
                em["id"]: em for em in unread_emails
            }

            # Group items by priority
            urgent = [i for i in digest.items if i.priority.upper() == "URGENT"]
            important = [i for i in digest.items if i.priority.upper() == "IMPORTANT"]
            normal_or_low = [i for i in digest.items if i.priority.upper() not in ("URGENT", "IMPORTANT")]

            lines = [
                "✨ <b>Executive Inbox Briefing</b>",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"<i>{html.escape(digest.executive_summary)}</i>\n",
            ]

            if urgent:
                lines.append("🚨 <b>Action Required:</b>")
                for it in urgent:
                    sender = clean_sender_name(it.sender)
                    lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(it.tl_dr)}")
                    if it.action_items:
                        lines.append(f"  👉 <i>{html.escape(it.action_items[0])}</i>")
                lines.append("")

            if important:
                lines.append("📌 <b>Important Updates:</b>")
                for it in important:
                    sender = clean_sender_name(it.sender)
                    lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(it.tl_dr)}")
                lines.append("")

            if normal_or_low:
                lines.append("☕ <b>Low Priority & Updates:</b>")
                for it in normal_or_low[:4]:
                    sender = clean_sender_name(it.sender)
                    lines.append(f"• <b>{html.escape(sender)}</b>: {html.escape(it.tl_dr)}")
                if len(normal_or_low) > 4:
                    lines.append(f"• <i>...and {len(normal_or_low) - 4} more notifications</i>")
                lines.append("")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("👇 <i>Tap an email below to view details or draft a reply:</i>")

            # Build compact inline keyboard buttons (2 per row)
            keyboard = []
            row = []
            for idx, it in enumerate(digest.items[:8], start=1):
                clean_name = clean_sender_name(it.sender)[:14]
                icon = "🔴" if it.priority.upper() == "URGENT" else ("🟡" if it.priority.upper() == "IMPORTANT" else "✉️")
                btn = InlineKeyboardButton(f"{icon} {idx}. {clean_name}", callback_data=f"open:{it.id}")
                row.append(btn)
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            # Action row at the bottom
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh Summary", callback_data="refresh_summary"),
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
        """Quick, beautiful list of unread emails."""
        if not await check_auth_or_reject(update):
            return

        await update.message.reply_chat_action(ChatAction.TYPING)
        try:
            emails = self.gmail.fetch_unread_emails(max_results=8)
            if not emails:
                await update.message.reply_html("🎉 <b>All caught up!</b> No unread emails.", reply_markup=MAIN_KEYBOARD)
                return

            lines = [f"📬 <b>Recent Unread Emails ({len(emails)}):</b>\n"]
            for i, em in enumerate(emails, 1):
                sender = clean_sender_name(em.get("from", "Unknown"))
                subj = em.get("subject", "(No Subject)")
                lines.append(f"<b>{i}. {html.escape(sender)}</b>\n   └ <code>{html.escape(subj[:60])}</code>")

            keyboard = [
                [InlineKeyboardButton("📊 Generate Full Summary", callback_data="refresh_summary")]
            ]

            await update.message.reply_html(
                "\n\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as e:
            logger.exception("Error in /unread: %s", e)
            await update.message.reply_html(f"❌ Error: <code>{html.escape(str(e))}</code>")

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Search emails using query syntax or keywords."""
        if not await check_auth_or_reject(update):
            return

        if not context.args:
            await update.message.reply_html(
                "🔍 <b>How to Search:</b>\n"
                "Type <code>/search &lt;keywords&gt;</code> or simply type your question in chat!\n\n"
                "<i>Examples:</i>\n"
                "• <code>/search flights</code>\n"
                "• <code>/search from:pepsico</code>\n"
                "• <i>'Did I get any receipts from Amazon?'</i>",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        query_str = " ".join(context.args)
        await update.message.reply_chat_action(ChatAction.TYPING)

        try:
            results = self.gmail.search_emails(query=query_str, max_results=5)
            if not results:
                await update.message.reply_html(f"No emails found matching: <code>{html.escape(query_str)}</code>")
                return

            lines = [f"🔍 <b>Search results for:</b> <i>{html.escape(query_str)}</i>\n"]
            for i, em in enumerate(results, 1):
                sender = clean_sender_name(em.get("from", "Unknown"))
                subj = em.get("subject", "(No Subject)")
                lines.append(f"<b>{i}. {html.escape(sender)}</b>: {html.escape(subj)}\n   <i>{html.escape(em.get('snippet', '')[:90])}...</i>")

            await update.message.reply_html("\n\n".join(lines))
        except Exception as e:
            logger.exception("Error in /search: %s", e)
            await update.message.reply_html(f"❌ Error: <code>{html.escape(str(e))}</code>")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages and bottom menu button taps."""
        if not await check_auth_or_reject(update):
            return

        text = update.message.text.strip()

        # Route bottom keyboard buttons
        if text == "📊 Executive Summary":
            await self.summary_command(update, context)
            return
        elif text == "📬 Unread Emails":
            await self.unread_command(update, context)
            return
        elif text == "⚙️ Status":
            await self.status_command(update, context)
            return
        elif text == "🔍 Search Inbox":
            await self.search_command(update, context)
            return

        # Natural language question about inbox
        question = text.removeprefix("/ask").strip()
        await update.message.reply_chat_action(ChatAction.TYPING)
        status_msg = await update.message.reply_html("🔍 <i>Searching your inbox & consulting Groq...</i>")

        try:
            relevant_emails = self.gmail.search_emails(query=question, max_results=6)
            if not relevant_emails:
                relevant_emails = self.gmail.fetch_unread_emails(max_results=6)

            answer = self.groq.answer_query_about_emails(user_question=question, emails=relevant_emails)
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
        """Handle modern interactive inline buttons."""
        query = update.callback_query
        if not await check_auth_or_reject(update):
            return

        await query.answer()
        data = query.data or ""

        if data == "refresh_summary":
            await self.summary_command(update, context)
            return

        elif data.startswith("open:"):
            msg_id = data.split("open:")[1]
            cached_items = context.user_data.get("cached_items", {})
            item = cached_items.get(msg_id)
            email = self.gmail.get_email_details(msg_id)

            if not email:
                await query.message.reply_html("❌ Could not load email details.")
                return

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
                    InlineKeyboardButton("📄 View Full Content", callback_data=f"view:{msg_id}"),
                    InlineKeyboardButton("⬅️ Back to Summary", callback_data="refresh_summary"),
                ]
            ]
            await query.message.reply_html(card, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("read:"):
            msg_id = data.split("read:")[1]
            success = self.gmail.mark_as_read(msg_id)
            if success:
                await query.message.reply_html(f"✅ <b>Marked as read in Gmail!</b>")
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
                body = email.get("body", "") or email.get("snippet", "")
                preview = (
                    f"📄 <b>Full Preview:</b> {html.escape(email.get('subject', ''))}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{html.escape(body[:1500])}"
                )
                await query.message.reply_html(preview)
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
    app.add_handler(CommandHandler("summary", bot_ctrl.summary_command))
    app.add_handler(CommandHandler("digest", bot_ctrl.summary_command))
    app.add_handler(CommandHandler("unread", bot_ctrl.unread_command))
    app.add_handler(CommandHandler("search", bot_ctrl.search_command))
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
