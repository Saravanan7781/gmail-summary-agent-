"""Main application entry point for Gmail Summary Agent powered by Groq."""

import argparse
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.bot import setup_bot_application
from src.config import Config
from src.gmail_service import GmailService
from src.groq_service import GroqService
from src.scheduler import register_scheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("gmail-agent")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler to satisfy Render's health checks on the free tier."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "healthy", "service": "gmail-summary-agent"}')

    def log_message(self, format, *args):
        pass  # Suppress noisy HTTP health logs


def start_health_check_server():
    """Start HTTP server if PORT environment variable is present (e.g. Render / Cloud)."""
    raw_port = os.getenv("PORT", "").strip()
    if not raw_port or not raw_port.isdigit():
        return
    port = int(raw_port)
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        logger.info("Cloud health-check HTTP server listening on port %d", port)
    except Exception as e:
        logger.warning("Could not bind health-check server to port %d: %s", port, e)


def run_auth_flow_only(gmail_svc: GmailService) -> None:
    """Helper to run the initial Google OAuth browser flow."""
    logger.info("Starting Google OAuth2 authentication flow...")
    try:
        service = gmail_svc.get_service()
        profile = service.users().getProfile(userId="me").execute()
        email_addr = profile.get("emailAddress", "unknown")
        logger.info("Successfully authenticated! Connected to Gmail account: %s", email_addr)
        print(f"\n[SUCCESS] Connected to Gmail account: {email_addr}")
        print(f"Token saved to: {Config.GMAIL_TOKEN_PATH}\n")
    except Exception as e:
        logger.error("Authentication failed: %s", e)
        print(f"\n[ERROR] Authentication failed: {e}\n")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Gmail Summary Agent powered by Groq LPUs and Telegram")
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Run Google OAuth2 authentication in browser to generate credentials/token.json and exit",
    )
    args = parser.parse_args()

    # Restore credentials if provided via cloud environment variables
    Config.initialize_credentials()

    # Instantiate services
    gmail_svc = GmailService()
    groq_svc = GroqService()

    # Handle --auth-only mode
    if args.auth_only:
        run_auth_flow_only(gmail_svc)
        return

    # Validate configuration
    issues = Config.validate()
    if issues:
        print("\n" + "=" * 60)
        print("  ⚠️  CONFIGURATION CHECK")
        print("=" * 60)
        for issue in issues:
            print(f"  • {issue}")
        print("=" * 60)
        print("Please check your .env or Render environment variables.\n")

        # If critical keys are missing, stop with guidance
        if not Config.TELEGRAM_BOT_TOKEN or Config.TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
            print("[STOPPED] Please configure TELEGRAM_BOT_TOKEN before running.\n")
            sys.exit(1)

    # Start health-check server if running on Render / Cloud
    start_health_check_server()

    # Initialize and start Telegram Bot
    logger.info("Starting Telegram Bot Application with Groq...")
    app = setup_bot_application(gmail_svc, groq_svc)

    # Register scheduled tasks if enabled
    register_scheduler(app, gmail_svc, groq_svc)

    logger.info("Bot is polling for updates... Press Ctrl+C to terminate.")
    app.run_polling(
        bootstrap_retries=5,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
