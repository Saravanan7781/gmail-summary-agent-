"""VIP Watchlist and Alert State Manager for Proactive VIP Radar."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Set

from src.config import BASE_DIR

logger = logging.getLogger(__name__)

VIP_FILE = BASE_DIR / "data" / "vip_watchlist.json"
SEEN_ALERTS_FILE = BASE_DIR / "data" / "seen_alerts.json"


class VIPManager:
    """Manages VIP senders, domains, and deduplication of alert notifications."""

    def __init__(self):
        self._watchlist: Set[str] = set()
        self._seen_alert_ids: Set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load watchlist and seen alerts from disk and environment defaults."""
        # 1. Load from environment variable (e.g. Render / .env)
        env_vips = os.getenv("VIP_WATCHLIST", "").strip()
        if env_vips:
            for item in env_vips.split(","):
                cleaned = item.strip().lower()
                if cleaned:
                    self._watchlist.add(cleaned)

        # 2. Load from persistent JSON file if available
        if VIP_FILE.exists():
            try:
                data = json.loads(VIP_FILE.read_text(encoding="utf-8"), strict=False)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str) and item.strip():
                            self._watchlist.add(item.strip().lower())
            except Exception as e:
                logger.warning("Error reading vip_watchlist.json: %s", e)

        # 3. Load seen alert IDs to prevent duplicate alerts
        if SEEN_ALERTS_FILE.exists():
            try:
                data = json.loads(SEEN_ALERTS_FILE.read_text(encoding="utf-8"), strict=False)
                if isinstance(data, list):
                    self._seen_alert_ids = set(data)
            except Exception as e:
                logger.warning("Error reading seen_alerts.json: %s", e)

    def _save_watchlist(self) -> None:
        """Persist watchlist to disk."""
        try:
            VIP_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(VIP_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self._watchlist)), f, indent=2)
        except Exception as e:
            logger.error("Failed to save vip_watchlist.json: %s", e)

    def _save_seen_alerts(self) -> None:
        """Persist seen alert IDs to disk."""
        try:
            SEEN_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Retain only latest 250 IDs
            recent_ids = list(self._seen_alert_ids)[-250:]
            with open(SEEN_ALERTS_FILE, "w", encoding="utf-8") as f:
                json.dump(recent_ids, f, indent=2)
        except Exception as e:
            logger.error("Failed to save seen_alerts.json: %s", e)

    def get_watchlist(self) -> List[str]:
        """Return sorted list of watched keywords / emails / domains."""
        return sorted(list(self._watchlist))

    def add_vip(self, entry: str) -> bool:
        """Add an email, domain, or name to the VIP watchlist."""
        cleaned = entry.strip().lower()
        if not cleaned or cleaned in self._watchlist:
            return False
        self._watchlist.add(cleaned)
        self._save_watchlist()
        return True

    def remove_vip(self, entry: str) -> bool:
        """Remove an item from the VIP watchlist."""
        cleaned = entry.strip().lower()
        if cleaned in self._watchlist:
            self._watchlist.remove(cleaned)
            self._save_watchlist()
            return True
        return False

    def matches_vip(self, sender: str, subject: str = "") -> Optional[str]:
        """Check if sender or subject matches any entry in the VIP watchlist."""
        sender_lower = (sender or "").lower()
        subject_lower = (subject or "").lower()

        for vip in self._watchlist:
            if vip in sender_lower or vip in subject_lower:
                return vip
        return None

    def has_alerted(self, msg_id: str) -> bool:
        """Check if an alert has already been dispatched for this message ID."""
        return msg_id in self._seen_alert_ids

    def mark_alerted(self, msg_id: str) -> None:
        """Mark a message ID as alerted."""
        self._seen_alert_ids.add(msg_id)
        self._save_seen_alerts()


# Global singleton instance
vip_manager = VIPManager()
