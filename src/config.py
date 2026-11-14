"""Configuration manager for Gmail Summary Agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from project root
load_dotenv(dotenv_path=BASE_DIR / ".env")


class Config:
    """Application configuration and credentials loader."""

    # Telegram configuration
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    _raw_allowed_ids = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    ALLOWED_TELEGRAM_USER_IDS: set[int] = {
        int(uid.strip())
        for uid in _raw_allowed_ids.split(",")
        if uid.strip().isdigit()
    }

    # Groq AI configuration
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()

    # Gmail OAuth file paths
    GMAIL_CREDENTIALS_PATH: Path = BASE_DIR / os.getenv(
        "GMAIL_CREDENTIALS_PATH", "credentials/credentials.json"
    )
    GMAIL_TOKEN_PATH: Path = BASE_DIR / os.getenv(
        "GMAIL_TOKEN_PATH", "credentials/token.json"
    )

    # Required Gmail API scopes
    # https://www.googleapis.com/auth/gmail.readonly: Read emails
    # https://www.googleapis.com/auth/gmail.modify: Mark as read / archive
    # https://www.googleapis.com/auth/gmail.compose: Create drafts
    GMAIL_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]

    # Scheduled Digest Settings
    ENABLE_SCHEDULED_DIGEST: bool = (
        os.getenv("ENABLE_SCHEDULED_DIGEST", "false").lower() in ("true", "1", "yes")
    )
    DAILY_DIGEST_TIME: str = os.getenv("DAILY_DIGEST_TIME", "08:30").strip()
    _raw_digest_chat = os.getenv("DIGEST_CHAT_ID", "").strip()
    DIGEST_CHAT_ID: int | None = (
        int(_raw_digest_chat) if _raw_digest_chat.lstrip("-").isdigit() else None
    )

    @classmethod
    def initialize_credentials(cls) -> None:
        """Restore credentials from environment variables if running in the cloud (e.g. Render)."""
        creds_json = os.getenv("GMAIL_CREDENTIALS_JSON", "").strip()
        if creds_json and not cls.GMAIL_CREDENTIALS_PATH.exists():
            cls.GMAIL_CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            cls.GMAIL_CREDENTIALS_PATH.write_text(creds_json, encoding="utf-8")

        token_json = os.getenv("GMAIL_TOKEN_JSON", "").strip()
        if token_json and not cls.GMAIL_TOKEN_PATH.exists():
            cls.GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            cls.GMAIL_TOKEN_PATH.write_text(token_json, encoding="utf-8")

    @classmethod
    def validate(cls) -> list[str]:
        """Validate critical configuration settings and return list of warnings/errors."""
        cls.initialize_credentials()
        issues = []
        if not cls.TELEGRAM_BOT_TOKEN or cls.TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
            issues.append("TELEGRAM_BOT_TOKEN is not set in .env")
        if not cls.GROQ_API_KEY or cls.GROQ_API_KEY == "your_groq_api_key_here":
            issues.append("GROQ_API_KEY is not set in .env")
        if not cls.GMAIL_CREDENTIALS_PATH.exists():
            issues.append(
                f"Gmail client secrets file not found at: {cls.GMAIL_CREDENTIALS_PATH} "
                "(Set GMAIL_CREDENTIALS_JSON in Render or place credentials/credentials.json)"
            )
        return issues
