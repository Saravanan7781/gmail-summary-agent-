"""Gmail API integration service for authentication, fetching, searching, and managing emails."""

import base64
import logging
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import Config

logger = logging.getLogger(__name__)


class GmailService:
    """Service to interact with Google Gmail API."""

    def __init__(self):
        self._service = None

    def get_service(self):
        """Authenticate and return the Gmail API client instance."""
        if self._service is not None:
            return self._service

        creds = None
        # Load existing user token if available
        if Config.GMAIL_TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(Config.GMAIL_TOKEN_PATH), Config.GMAIL_SCOPES
                )
            except Exception as e:
                logger.warning("Failed to load existing token.json: %s", e)

        # If there are no (valid) credentials available, prompt the user to log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Gmail access token...")
                creds.refresh(Request())
            else:
                if not Config.GMAIL_CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Missing Gmail client secrets credentials file at: {Config.GMAIL_CREDENTIALS_PATH}. "
                        "Please download credentials.json from Google Cloud Console."
                    )
                logger.info("Initiating browser OAuth flow for Gmail...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(Config.GMAIL_CREDENTIALS_PATH), Config.GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for the next run
            Config.GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(Config.GMAIL_TOKEN_PATH, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
            logger.info("Saved refreshed/new Gmail token to %s", Config.GMAIL_TOKEN_PATH)

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_unread_emails(self, max_results: int = 15, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch unread emails, optionally filtered by a custom search query."""
        service = self.get_service()
        search_query = "is:unread"
        if query:
            search_query += f" {query}"

        results = service.users().messages().list(
            userId="me", q=search_query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        email_list = []
        for msg in messages:
            details = self.get_email_details(msg["id"])
            if details:
                email_list.append(details)
        return email_list

    def search_emails(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search emails using arbitrary Gmail search syntax (e.g. 'from:google', 'receipts')."""
        service = self.get_service()
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        email_list = []
        for msg in messages:
            details = self.get_email_details(msg["id"])
            if details:
                email_list.append(details)
        return email_list

    def get_email_details(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed information for a specific message by ID."""
        service = self.get_service()
        try:
            msg = service.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        except Exception as e:
            logger.error("Failed to fetch message %s: %s", message_id, e)
            return None

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        header_dict = {h["name"].lower(): h["value"] for h in headers if "name" in h and "value" in h}
        subject = header_dict.get("subject", "(No Subject)")
        sender = header_dict.get("from", "Unknown Sender")
        date_str = header_dict.get("date", "")
        message_id_header = header_dict.get("message-id", "")

        # Extract plain text or HTML body
        body_text = self._extract_body(payload)
        snippet = msg.get("snippet", "")

        return {
            "id": message_id,
            "thread_id": msg.get("threadId"),
            "subject": subject,
            "from": sender,
            "date": date_str,
            "message_id_header": message_id_header,
            "snippet": snippet,
            "body": body_text[:4000] if body_text else snippet,  # Cap text to 4k characters
            "labels": msg.get("labelIds", []),
        }

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Recursively extract and clean plain text from email payload parts."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if body_data:
            decoded = base64.urlsafe_b64decode(body_data.encode("ASCII")).decode("utf-8", errors="replace")
            if "html" in mime_type:
                soup = BeautifulSoup(decoded, "html.parser")
                return soup.get_text(separator=" ", strip=True)
            return decoded.strip()

        # Handle multipart payloads
        parts = payload.get("parts", [])
        plain_texts = []
        html_texts = []

        for part in parts:
            part_mime = part.get("mimeType", "")
            part_data = part.get("body", {}).get("data")
            if part_data:
                decoded = base64.urlsafe_b64decode(part_data.encode("ASCII")).decode("utf-8", errors="replace")
                if part_mime == "text/plain":
                    plain_texts.append(decoded.strip())
                elif part_mime == "text/html":
                    soup = BeautifulSoup(decoded, "html.parser")
                    html_texts.append(soup.get_text(separator=" ", strip=True))
            elif "parts" in part:
                # Nested multipart
                nested_text = self._extract_body(part)
                if nested_text:
                    plain_texts.append(nested_text)

        if plain_texts:
            return "\n\n".join(plain_texts)
        if html_texts:
            return "\n\n".join(html_texts)
        return ""

    def mark_as_read(self, message_id: str) -> bool:
        """Mark an email as read by removing the UNREAD label."""
        service = self.get_service()
        try:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            logger.info("Marked message %s as read.", message_id)
            return True
        except Exception as e:
            logger.error("Error marking message %s as read: %s", message_id, e)
            return False

    def create_draft(
        self,
        to: str,
        subject: str,
        body_text: str,
        in_reply_to: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        """Create a draft reply or new message in Gmail."""
        service = self.get_service()
        try:
            message = MIMEText(body_text)
            message["to"] = to
            message["subject"] = subject
            if in_reply_to:
                message["In-Reply-To"] = in_reply_to
                message["References"] = in_reply_to

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            draft_body: Dict[str, Any] = {"message": {"raw": raw}}
            if thread_id:
                draft_body["message"]["threadId"] = thread_id

            draft = service.users().drafts().create(userId="me", body=draft_body).execute()
            draft_id = draft.get("id")
            logger.info("Draft created successfully with ID: %s", draft_id)
            return draft_id
        except Exception as e:
            logger.error("Error creating draft: %s", e)
            return None
