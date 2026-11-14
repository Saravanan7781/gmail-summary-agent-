"""Telegram Bot handlers and user interaction flow for Gmail Summary Agent using Groq."""

import html
import logging
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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


def is_authorized(user_id: int) -> bool:
    """Check if the user ID is in the allowed whitelist (if configured)."""
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
            f"To access your Gmail Agent, please add this ID to "
            f"<code>ALLOWED_TELEGRAM_USER_IDS</code> in your <code>.env</code> file."
        )
        if update.message:
            await update.message.reply_html(msg)
        elif update.callback_query:
            await update.callback_query.answer("Access Denied", show_alert=True)
        return False
    return True


class GmailBot:
    """Telegram Bot Controller."""

    def __init__(self, gmail_svc: GmailService, groq_svc: GroqService):
        self.gmail = gmail_svc
        self.groq = groq_svc

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not await check_auth_or_reject(update):
            return

        user_name = update.effective_user.first_name or "there"
        gmail_auth_status = "✅ Token configured" if Config.GMAIL_TOKEN_PATH.exists() else "⚠️ OAuth required (will prompt on first run)"
        groq_status = "✅ API Key configured" if Config.GROQ_API_KEY else "❌ GROQ_API_KEY missing"

        welcome_text = (
            f"⚡ <b>Welcome, {html.escape(user_name)}!</b>\n\n"
            f"I am your <b>Gmail Summary Agent</b> powered by <b>Groq LPU Inference</b> ({html.escape(Config.GROQ_MODEL)}).\n\n"
            f"<b>Status:</b>\n"
            f"• Gmail API: {gmail_auth_status}\n"
            f"• Groq AI: {groq_status}\n\n"
            f"<b>Available Commands:</b>\n"
            f"📊 <code>/summary</code> - Lightning-fast AI digest & categorization of unread emails\n"
            f"📬 <code>/unread [count]</code> - Quick list of unread messages\n"
            f"🔍 <code>/search &lt;query&gt;</code> - Search Gmail (e.g. <code>/search invoices</code>)\n"
            f"❓ <code>/ask &lt;question&gt;</code> - Ask questions about your emails\n"
            f"⚙️ <code>/status</code> - Check agent health and settings\n\n"
            f"<i>Tip: You can also simply send me any question as a message, and I'll search your inbox to answer!</i>"
        )
        await update.message.reply_html(welcome_text)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Check system status."""
        if not await check_auth_or_reject(update):
            return

        status_lines = [
            "⚙️ <b>System Status</b>\n",
            f"• LLM Engine: <b>Groq</b>",
            f"• Model: <code>{html.escape(Config.GROQ_MODEL)}</code>",
            f"• Gmail Token: {'✅ Ready' if Config.GMAIL_TOKEN_PATH.exists() else '❌ Not authenticated'}",
            f"• Credentials file: {'✅ Present' if Config.GMAIL_CREDENTIALS_PATH.exists() else '❌ Missing credentials.json'}",
            f"• Scheduled Digest: {'✅ Enabled (' + Config.DAILY_DIGEST_TIME + ')' if Config.ENABLE_SCHEDULED_DIGEST else '⏸️ Disabled'}",
        ]
        await update.message.reply_html("\n".join(status_lines))

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Fetch unread emails and produce an intelligent Groq summary."""
        if not await check_auth_or_reject(update):
            return

        chat = update.effective_chat
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        status_msg = await update.message.reply_html("⚡ <i>Scanning inbox and synthesizing with Groq...</i>")

        try:
            unread_emails = self.gmail.fetch_unread_emails(max_results=12)

            if not unread_emails:
                await status_msg.edit_text("🎉 <b>Your inbox is clear!</b> No unread emails found.", parse_mode=ParseMode.HTML)
                return

            digest = self.groq.summarize_inbox(unread_emails)

            header_text = (
                f"📬 <b>INBOX EXECUTIVE SUMMARY</b> (via Groq)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{html.escape(digest.executive_summary)}\n\n"
                f"<i>Found {len(unread_emails)} unread emails. Highlights below:</i>"
            )
            await status_msg.edit_text(header_text, parse_mode=ParseMode.HTML)

            priority_icons = {
                "URGENT": "🔴 <b>URGENT</b>",
                "IMPORTANT": "🟡 <b>IMPORTANT</b>",
                "NORMAL": "🔵 <b>UPDATE</b>",
                "LOW": "⚪ <b>NEWSLETTER / PROMO</b>",
            }

            for item in digest.items:
                p_label = priority_icons.get(item.priority.upper(), f"📌 <b>{item.priority}</b>")
                action_text = ""
                if item.action_items:
                    bullets = "\n".join([f"  • {html.escape(act)}" for act in item.action_items])
                    action_text = f"\n<b>⚡ Action Required:</b>\n{bullets}\n"

                item_card = (
                    f"{p_label} | <i>{html.escape(item.category)}</i>\n"
                    f"<b>From:</b> {html.escape(item.sender)}\n"
                    f"<b>Subject:</b> <code>{html.escape(item.subject)}</code>\n\n"
                    f"<b>TL;DR:</b> {html.escape(item.tl_dr)}\n"
                    f"{action_text}"
                )

                keyboard = [
                    [
                        InlineKeyboardButton("✅ Mark as Read", callback_data=f"read:{item.id}"),
                        InlineKeyboardButton("✍️ Draft Reply", callback_data=f"draft:{item.id}"),
                    ],
                    [
                        InlineKeyboardButton("📄 View Full Snippet", callback_data=f"view:{item.id}")
                    ]
                ]

                await update.message.reply_html(
                    item_card,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

        except Exception as e:
            logger.exception("Error in /summary handler: %s", e)
            await status_msg.edit_text(
                f"❌ <b>Error fetching summary:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
            )

    async def unread_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Quickly list unread emails without full AI analysis."""
        if not await check_auth_or_reject(update):
            return

        limit = 10
        if context.args and context.args[0].isdigit():
            limit = min(int(context.args[0]), 25)

        await update.message.reply_chat_action(ChatAction.TYPING)
        try:
            emails = self.gmail.fetch_unread_emails(max_results=limit)
            if not emails:
                await update.message.reply_html("🎉 No unread emails!")
                return

            lines = [f"📬 <b>Unread Emails ({len(emails)}):</b>\n"]
            for i, em in enumerate(emails, 1):
                lines.append(
                    f"{i}. <b>From:</b> {html.escape(em.get('from', 'Unknown'))}\n"
                    f"   <b>Subject:</b> {html.escape(em.get('subject', 'No Subject'))}\n"
                    f"   <i>Date: {html.escape(em.get('date', ''))}</i>\n"
                )
            await update.message.reply_html("\n".join(lines))
        except Exception as e:
            logger.exception("Error in /unread: %s", e)
            await update.message.reply_html(f"❌ Error: <code>{html.escape(str(e))}</code>")

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Search emails using Gmail query syntax or keywords."""
        if not await check_auth_or_reject(update):
            return

        if not context.args:
            await update.message.reply_html("Usage: <code>/search &lt;keywords or Gmail query&gt;</code>\nExample: <code>/search flight receipts</code>")
            return

        query_str = " ".join(context.args)
        await update.message.reply_chat_action(ChatAction.TYPING)

        try:
            results = self.gmail.search_emails(query=query_str, max_results=5)
            if not results:
                await update.message.reply_html(f"No emails found matching: <code>{html.escape(query_str)}</code>")
                return

            response_lines = [f"🔍 <b>Results for:</b> <i>{html.escape(query_str)}</i>\n"]
            for em in results:
                response_lines.append(
                    f"• <b>From:</b> {html.escape(em.get('from', ''))}\n"
                    f"  <b>Subject:</b> {html.escape(em.get('subject', ''))}\n"
                    f"  <b>Snippet:</b> {html.escape(em.get('snippet', '')[:120])}...\n"
                )
            await update.message.reply_html("\n".join(response_lines))
        except Exception as e:
            logger.exception("Error in /search: %s", e)
            await update.message.reply_html(f"❌ Error: <code>{html.escape(str(e))}</code>")

    async def ask_command_or_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Natural language Q&A about emails."""
        if not await check_auth_or_reject(update):
            return

        question = update.message.text
        if question.startswith("/ask"):
            question = question[4:].strip()

        if not question:
            await update.message.reply_html("Please type your question! For example:\n<i>'Did I receive any bank statements this week?'</i>")
            return

        await update.message.reply_chat_action(ChatAction.TYPING)
        status_msg = await update.message.reply_html("⚡ <i>Searching inbox & consulting Groq...</i>")

        try:
            relevant_emails = self.gmail.search_emails(query=question, max_results=6)
            if not relevant_emails:
                relevant_emails = self.gmail.fetch_unread_emails(max_results=6)

            answer = self.groq.answer_query_about_emails(user_question=question, emails=relevant_emails)
            await status_msg.edit_text(
                f"💡 <b>Groq Answer:</b>\n\n{html.escape(answer)}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.exception("Error in ask query: %s", e)
            await status_msg.edit_text(f"❌ Error: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button actions."""
        query = update.callback_query
        if not await check_auth_or_reject(update):
            return

        await query.answer()
        data = query.data or ""

        if data.startswith("read:"):
            msg_id = data.split("read:")[1]
            success = self.gmail.mark_as_read(msg_id)
            if success:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_html(f"✅ <b>Marked as read!</b> (ID: <code>{msg_id}</code>)")
            else:
                await query.message.reply_html("❌ Failed to mark email as read.")

        elif data.startswith("draft:"):
            msg_id = data.split("draft:")[1]
            await query.message.reply_chat_action(ChatAction.TYPING)
            progress_msg = await query.message.reply_html("⚡ <i>Generating intelligent reply draft with Groq...</i>")

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
                reply_text = (
                    f"📝 <b>Draft Created in Gmail!</b>\n"
                    f"<b>To:</b> {html.escape(email.get('from', ''))}\n"
                    f"<b>Subject:</b> {html.escape(draft_content.get('subject', ''))}\n\n"
                    f"<b>Draft Content:</b>\n"
                    f"<blockquote>{html.escape(draft_content.get('body', ''))}</blockquote>\n\n"
                    f"<i>You can review and send it directly inside your Gmail app or web client.</i>"
                )
                await progress_msg.edit_text(reply_text, parse_mode=ParseMode.HTML)
            else:
                await progress_msg.edit_text("❌ Failed to save draft to Gmail.")

        elif data.startswith("view:"):
            msg_id = data.split("view:")[1]
            email = self.gmail.get_email_details(msg_id)
            if email:
                preview = (
                    f"📄 <b>Full Preview for:</b> {html.escape(email.get('subject', ''))}\n"
                    f"<b>From:</b> {html.escape(email.get('from', ''))}\n"
                    f"<b>Date:</b> {html.escape(email.get('date', ''))}\n\n"
                    f"<b>Content:</b>\n<pre>{html.escape(email.get('body', '')[:1200])}</pre>"
                )
                await query.message.reply_html(preview)
            else:
                await query.message.reply_html("❌ Could not load email details.")


def setup_bot_application(gmail_svc: GmailService, groq_svc: GroqService) -> Application:
    """Build and register all Telegram bot handlers."""
    if not Config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing in .env configuration.")

    # Configure robust network timeouts for Telegram API
    request_client = HTTPXRequest(
        connection_pool_size=10,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).request(request_client).build()
    bot_ctrl = GmailBot(gmail_svc, groq_svc)

    # Command handlers
    app.add_handler(CommandHandler("start", bot_ctrl.start_command))
    app.add_handler(CommandHandler("help", bot_ctrl.start_command))
    app.add_handler(CommandHandler("status", bot_ctrl.status_command))
    app.add_handler(CommandHandler("summary", bot_ctrl.summary_command))
    app.add_handler(CommandHandler("digest", bot_ctrl.summary_command))
    app.add_handler(CommandHandler("unread", bot_ctrl.unread_command))
    app.add_handler(CommandHandler("search", bot_ctrl.search_command))
    app.add_handler(CommandHandler("ask", bot_ctrl.ask_command_or_message))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(bot_ctrl.handle_callback_query))

    # Plain text messages -> AI Inbox Assistant
    app.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND),
            bot_ctrl.ask_command_or_message,
        )
    )

    return app
