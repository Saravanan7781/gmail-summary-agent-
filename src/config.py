"""Configuration manager for Gmail Summary Agent."""

import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

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
    def _write_clean_json(cls, raw_content: str, destination: Path) -> bool:
        """Safely parse and re-format JSON, handling quotes, control chars, or base64."""
        import base64

        content = raw_content.strip()
        if not content:
            return False

        # Attempt base64 decode if not plain JSON
        if not content.startswith("{"):
            try:
                decoded = base64.b64decode(content).decode("utf-8")
                if decoded.strip().startswith("{"):
                    content = decoded.strip()
            except Exception:
                pass

        # Strip wrapping quotes if added by shell or env parser
        if (content.startswith('"') and content.endswith('"')) or (
            content.startswith("'") and content.endswith("'")
        ):
            content = content[1:-1].strip()

        # Parse with strict=False to forgive unescaped newlines/tabs
        parsed = None
        try:
            parsed = json.loads(content, strict=False)
        except Exception:
            try:
                unescaped = content.encode("utf-8").decode("unicode_escape")
                parsed = json.loads(unescaped, strict=False)
            except Exception as e:
                logger.warning("Could not parse JSON for %s: %s", destination.name, e)

        destination.parent.mkdir(parents=True, exist_ok=True)
        if parsed is not None:
            with open(destination, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2)
            return True
        else:
            destination.write_text(content, encoding="utf-8")
            return True

    @classmethod
    def initialize_credentials(cls) -> None:
        """Restore credentials from environment variables if running in the cloud (e.g. Render)."""
        creds_json = (
            os.getenv("GMAIL_CREDENTIALS_JSON", "").strip()
            or os.getenv("GMAIL_CREDENTIALS_BASE64", "").strip()
        )
        if creds_json:
            cls._write_clean_json(creds_json, cls.GMAIL_CREDENTIALS_PATH)

        token_json = (
            os.getenv("GMAIL_TOKEN_JSON", "").strip()
            or os.getenv("GMAIL_TOKEN_BASE64", "").strip()
        )
        if token_json:
            cls._write_clean_json(token_json, cls.GMAIL_TOKEN_PATH)

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
