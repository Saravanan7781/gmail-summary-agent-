"""Groq AI service for ultra-fast email summarization, analysis, reply drafting, and urgency sensing."""

import json
import logging
from typing import Any, Dict, List, Optional
from groq import Groq
from pydantic import BaseModel, Field

from src.config import Config

logger = logging.getLogger(__name__)


class EmailSummaryItem(BaseModel):
    id: str = Field(description="The Gmail message ID")
    sender: str = Field(description="Sender name/email")
    subject: str = Field(description="Subject of the email")
    priority: str = Field(
        description="Priority level: 'URGENT' (requires immediate reply/attention), 'IMPORTANT' (bills, accounts, work updates), 'NORMAL' (general info), or 'LOW' (newsletters, marketing)"
    )
    category: str = Field(
        description="Category: e.g., 'Action Required', 'Work', 'Finance / Receipt', 'Newsletter', 'Personal', 'Notification'"
    )
    tl_dr: str = Field(description="Concise 1-2 sentence executive summary of what this email is about")
    action_items: List[str] = Field(
        default_factory=list,
        description="Bullet list of explicit action items or tasks required from the user, if any",
    )


class InboxDigest(BaseModel):
    executive_summary: str = Field(
        description="A high-level 2-3 sentence synthesis of the user's inbox state right now"
    )
    items: List[EmailSummaryItem] = Field(
        description="Structured breakdown of each processed email"
    )


class EmailUrgencyEvaluation(BaseModel):
    is_urgent: bool = Field(
        default=False,
        description="True ONLY if this email requires prompt user attention (financial deposits/credits, money sent, verification codes/2FA, payment issues, deadlines, or VIP requests)",
    )
    reason: str = Field(
        default="General Notification",
        description="Short category tag e.g. 'Money Transfer', 'Payment Confirmation', 'Security Code', 'Urgent Deadline', 'VIP Message'",
    )
    tl_dr: str = Field(
        default="",
        description="1 punchy sentence explaining the situation",
    )
    action_required: str = Field(
        default="",
        description="Concrete action the user should take right now, if any",
    )


class GroqService:
    """Service wrapping Groq LPUs for low-latency inference."""

    def __init__(self):
        self._client: Optional[Groq] = None

    def get_client(self) -> Groq:
        """Initialize or retrieve the Groq client."""
        if self._client is None:
            if not Config.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY is not configured in .env.")
            self._client = Groq(api_key=Config.GROQ_API_KEY)
        return self._client

    def summarize_inbox(self, emails: List[Dict[str, Any]]) -> InboxDigest:
        """Generate structured digest and categorization for a batch of emails using Groq."""
        if not emails:
            return InboxDigest(
                executive_summary="Your inbox is all caught up! No unread emails found.",
                items=[],
            )

        client = self.get_client()

        emails_formatted = []
        for idx, email in enumerate(emails, start=1):
            snippet_body = email.get("body", "") or email.get("snippet", "")
            emails_formatted.append(
                f"--- Email #{idx} ---\n"
                f"ID: {email.get('id')}\n"
                f"From: {email.get('from')}\n"
                f"Date: {email.get('date')}\n"
                f"Subject: {email.get('subject')}\n"
                f"Content:\n{snippet_body[:1000]}\n"
            )

        system_prompt = (
            "You are an executive Chief of Staff analyzing incoming emails for a busy professional. "
            "Your output must be strictly valid JSON according to this schema:\n"
            "{\n"
            '  "executive_summary": "Crisp 2-sentence conversational synthesis of the inbox situation right now",\n'
            '  "items": [\n'
            "    {\n"
            '      "id": "exact Gmail message ID",\n'
            '      "sender": "Human sender name (e.g. John Doe, PepsiCo, GitHub)",\n'
            '      "subject": "email subject",\n'
            '      "priority": "URGENT | IMPORTANT | NORMAL | LOW",\n'
            '      "category": "Action Required | Work | Finance | Newsletter | Notification",\n'
            '      "tl_dr": "Strictly 1 punchy, high-signal sentence summarizing what this email is and why it matters",\n'
            '      "action_items": ["list of explicit deadlines or action items required from the user, if any"]\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user_content = "Here are the unread emails:\n\n" + "\n".join(emails_formatted)

        try:
            completion = client.chat.completions.create(
                model=Config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
                max_tokens=700,
            )

            raw_text = (completion.choices[0].message.content or "{}").strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            data = json.loads(raw_text, strict=False)
            return InboxDigest(**data)
        except Exception as e:
            logger.error("Failed to generate structured digest from Groq: %s", e)
            return self._fallback_digest(emails)

    def evaluate_email_urgency(self, email: Dict[str, Any], vip_match: Optional[str] = None) -> Optional[EmailUrgencyEvaluation]:
        """Autonomously evaluate if an unread email warrants an immediate proactive alert."""
        client = self.get_client()

        body_snippet = (email.get("body", "") or email.get("snippet", ""))[:1200]
        vip_context = f"NOTE: This sender or subject matched the user's VIP Watchlist keyword: '{vip_match}'." if vip_match else ""

        system_prompt = (
            "You are an executive Chief of Staff deciding whether an incoming email warrants sending an IMMEDIATE push notification.\n"
            "Items that warrant immediate alerts:\n"
            "- Financial transactions: money transfers, deposits, credits (e.g. 1000rs credited), payments received, bank alerts, or fraud warnings.\n"
            "- Direct personal requests: someone asking for confirmation, asking if money arrived, or urgent peer requests.\n"
            "- Security verification / 2FA codes, account lockouts, or password resets.\n"
            "- Strict same-day deadlines, emergencies, or VIP sender inquiries.\n"
            "Items that DO NOT warrant alerts: marketing promos, routine digests, social media updates, or newsletters.\n"
            "Return JSON matching the schema:\n"
            "{\n"
            '  "is_urgent": true or false,\n'
            '  "reason": "Money Transfer | Payment Confirmation | Security Alert | Urgent Deadline | VIP Inquiry | General",\n'
            '  "tl_dr": "1 punchy sentence explaining the email",\n'
            '  "action_required": "Exact action the user must take, if any"\n'
            "}"
        )

        user_content = (
            f"{vip_context}\n"
            f"From: {email.get('from')}\n"
            f"Subject: {email.get('subject')}\n"
            f"Date: {email.get('date')}\n"
            f"Content:\n{body_snippet}"
        )

        try:
            completion = client.chat.completions.create(
                model=Config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                max_tokens=400,
            )
            raw = (completion.choices[0].message.content or "{}").strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            elif raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            data = json.loads(raw, strict=False)
            eval_res = EmailUrgencyEvaluation(**data)

            if vip_match:
                eval_res.is_urgent = True
                if not eval_res.reason or eval_res.reason == "General":
                    eval_res.reason = f"⭐ VIP Watchlist: {vip_match}"
            return eval_res
        except Exception as e:
            logger.error("Failed to evaluate urgency for email %s: %s", email.get("id"), e)
            if vip_match:
                return EmailUrgencyEvaluation(
                    is_urgent=True,
                    reason=f"⭐ VIP Match ({vip_match})",
                    tl_dr=email.get("snippet", "New message from VIP sender")[:100],
                    action_required="Check email details",
                )
            return None

    def _fallback_digest(self, emails: List[Dict[str, Any]]) -> InboxDigest:
        """Fallback lightweight digest generator."""
        items = []
        for email in emails:
            items.append(
                EmailSummaryItem(
                    id=email.get("id", ""),
                    sender=email.get("from", "Unknown"),
                    subject=email.get("subject", "(No Subject)"),
                    priority="NORMAL",
                    category="General",
                    tl_dr=email.get("snippet", "No summary available")[:150],
                    action_items=[],
                )
            )
        return InboxDigest(
            executive_summary=f"Found {len(emails)} unread messages.",
            items=items,
        )

    def answer_query_about_emails(self, user_question: str, emails: List[Dict[str, Any]]) -> str:
        """Answer arbitrary questions based on matching emails in the inbox."""
        if not emails:
            return "No matching emails were found in your inbox for this inquiry."

        client = self.get_client()
        emails_context = []
        for idx, em in enumerate(emails, start=1):
            body = em.get("body", "") or em.get("snippet", "")
            emails_context.append(
                f"[Email {idx}] From: {em.get('from')} | Date: {em.get('date')} | Subject: {em.get('subject')}\n"
                f"Content: {body[:1000]}\n"
            )

        prompt = (
            f"User Question: \"{user_question}\"\n\n"
            f"Relevant Emails from Gmail:\n\n"
            f"{''.join(emails_context)}\n\n"
            "Instructions:\n"
            "1. Answer the question conversationally, clearly, and concisely (2 to 4 sentences or bullet points).\n"
            "2. Reference the sender, date, or specific details if relevant.\n"
            "3. If the emails do not contain the answer, state that clearly without guessing.\n"
            "4. Keep the tone sharp, professional, and friendly. Avoid technical jargon or raw JSON."
        )

        completion = client.chat.completions.create(
            model=Config.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful, precise executive email assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return (completion.choices[0].message.content or "").strip()

    def draft_reply(self, email: Dict[str, Any], user_instructions: Optional[str] = None) -> Dict[str, str]:
        """Generate a drafted reply based on the email content and optional instructions."""
        client = self.get_client()

        instruction_text = (
            f"User specific instructions: {user_instructions}"
            if user_instructions
            else "Write a polite, professional, and helpful reply acknowledging the key points."
        )

        system_prompt = (
            "You are an executive email assistant. Compose a draft response to an email. "
            "Output ONLY valid JSON with keys 'subject' and 'body'. Example:\n"
            '{"subject": "Re: Project Sync", "body": "Hi John,\\n\\nThanks for reaching out..."}'
        )

        user_content = (
            f"Original Email:\n"
            f"From: {email.get('from')}\n"
            f"Subject: {email.get('subject')}\n"
            f"Body:\n{email.get('body', '')[:1500]}\n\n"
            f"{instruction_text}"
        )

        completion = client.chat.completions.create(
            model=Config.GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
            max_tokens=500,
        )

        raw_draft = (completion.choices[0].message.content or "{}").strip()
        if raw_draft.startswith("```json"):
            raw_draft = raw_draft[7:]
        elif raw_draft.startswith("```"):
            raw_draft = raw_draft[3:]
        if raw_draft.endswith("```"):
            raw_draft = raw_draft[:-3]
        raw_draft = raw_draft.strip()

        data = json.loads(raw_draft, strict=False)
        return {
            "subject": data.get("subject", f"Re: {email.get('subject')}"),
            "body": data.get("body", ""),
        }
