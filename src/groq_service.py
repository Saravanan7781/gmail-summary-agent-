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

    @staticmethod
    def detect_urgency_heuristics(email: Dict[str, Any]) -> Optional[EmailUrgencyEvaluation]:
        """Fast, zero-token rule-based urgency classifier for financial alerts, 2FA, and strict deadlines."""
        import re
        subject = (email.get("subject") or "").lower()
        snippet = (email.get("snippet") or "").lower()
        body = (email.get("body") or "").lower()
        full_text = f"{subject} {snippet} {body[:1500]}"

        # 1. Financial transactions & receipts
        fin_keywords = [
            "credited", "debited", "deposit", "deposited", "transfer", "transferred",
            "payment", "paid", "refund", "invoice", "neft", "rtgs", "imps", "upi",
            "gpay", "phonepe", "paytm", "transaction", "bank"
        ]
        curr_pattern = r"(?:rs\.?|inr|₹|\$|€|£)\s*\d+|\d+\s*(?:rs|k|inr|bucks)"
        has_fin_word = any(kw in full_text for kw in fin_keywords)
        has_curr = bool(re.search(curr_pattern, full_text))
        is_direct_payment = any(term in full_text for term in ["credited", "deposited", "payment done", "money received", "transfer successful"])

        if (has_fin_word and has_curr) or is_direct_payment:
            raw_snippet = email.get("snippet") or email.get("subject") or "Financial transaction detected."
            return EmailUrgencyEvaluation(
                is_urgent=True,
                reason="💰 Financial Alert / Transfer",
                tl_dr=raw_snippet[:140],
                action_required="Verify bank account or transaction receipt and confirm status",
            )

        # 2. Security / 2FA / Authentication
        sec_patterns = [
            "verification code", "security code", "otp", "2fa", "two-factor",
            "password reset", "temporary password", "unauthorized login", "security alert",
            "suspicious login", "account lockout"
        ]
        if any(sp in full_text for sp in sec_patterns):
            raw_snippet = email.get("snippet") or email.get("subject") or "Security code or alert received."
            return EmailUrgencyEvaluation(
                is_urgent=True,
                reason="🔐 Security / Verification Code",
                tl_dr=raw_snippet[:140],
                action_required="Use verification code or review account security immediately",
            )

        # 3. Urgent deadlines / immediate action required
        urgent_patterns = [
            "urgent", "action required", "immediate attention", "asap", "deadline today",
            "account suspended", "payment failed", "reply fast", "respond immediately",
            "requires your immediate", "urgent action"
        ]
        if any(up in full_text for up in urgent_patterns):
            raw_snippet = email.get("snippet") or email.get("subject") or "Urgent action required."
            return EmailUrgencyEvaluation(
                is_urgent=True,
                reason="🚨 Urgent Request",
                tl_dr=raw_snippet[:140],
                action_required="Review email and respond promptly",
            )

        return None

    def evaluate_email_urgency(self, email: Dict[str, Any], vip_match: Optional[str] = None) -> Optional[EmailUrgencyEvaluation]:
        """Autonomously evaluate if an unread email warrants an immediate proactive alert.
        Uses zero-token heuristic pre-filtering to save Groq quota and guarantee zero dropped alerts."""
        heuristic_res = self.detect_urgency_heuristics(email)

        # Handle VIP matches
        if vip_match:
            if not heuristic_res:
                heuristic_res = EmailUrgencyEvaluation(
                    is_urgent=True,
                    reason=f"⭐ VIP Watchlist: {vip_match}",
                    tl_dr=email.get("snippet", "New message from VIP sender")[:140],
                    action_required="Check email details and reply",
                )
            else:
                heuristic_res.reason = f"⭐ VIP: {heuristic_res.reason}"

        # If neither heuristic nor VIP triggered, it is NOT urgent -> SKIP Groq to preserve token quota!
        if not heuristic_res or not heuristic_res.is_urgent:
            return None

        # Attempt enrichment with Groq; gracefully fall back to heuristic if Groq encounters rate limit
        try:
            client = self.get_client()
            body_snippet = (email.get("body", "") or email.get("snippet", ""))[:1000]
            vip_context = f"NOTE: This sender or subject matched the user's VIP Watchlist keyword: '{vip_match}'." if vip_match else ""

            system_prompt = (
                "You are an executive Chief of Staff deciding whether an incoming email warrants sending an IMMEDIATE push notification.\n"
                "Return JSON matching the schema:\n"
                "{\n"
                '  "is_urgent": true,\n'
                '  "reason": "Money Transfer | Payment Confirmation | Security Alert | Urgent Deadline | VIP Inquiry",\n'
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

            completion = client.chat.completions.create(
                model=Config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                max_tokens=300,
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
                if not eval_res.reason.startswith("⭐"):
                    eval_res.reason = f"⭐ VIP: {eval_res.reason}"
            elif heuristic_res and heuristic_res.is_urgent:
                eval_res.is_urgent = True
                if not eval_res.reason or eval_res.reason == "General":
                    eval_res.reason = heuristic_res.reason
            return eval_res
        except Exception as e:
            logger.info("Groq urgency enrichment skipped (%s); using reliable heuristic.", e)
            return heuristic_res

    def _fallback_digest(self, emails: List[Dict[str, Any]]) -> InboxDigest:
        """Fallback lightweight digest generator with heuristic priority ranking."""
        items = []
        urgent_count = 0
        for email in emails:
            heur = self.detect_urgency_heuristics(email)
            if heur and heur.is_urgent:
                prio = "URGENT"
                cat = heur.reason
                act = [heur.action_required] if heur.action_required else []
                urgent_count += 1
            else:
                prio = "NORMAL"
                cat = "General"
                act = []

            items.append(
                EmailSummaryItem(
                    id=email.get("id", ""),
                    sender=email.get("from", "Unknown"),
                    subject=email.get("subject", "(No Subject)"),
                    priority=prio,
                    category=cat,
                    tl_dr=email.get("snippet", "No summary available")[:150],
                    action_items=act,
                )
            )

        exec_summary = (
            f"Found {len(emails)} unread messages ({urgent_count} critical action items requiring prompt review)."
            if urgent_count > 0
            else f"Found {len(emails)} unread messages. No critical blockers detected."
        )
        return InboxDigest(
            executive_summary=exec_summary,
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
