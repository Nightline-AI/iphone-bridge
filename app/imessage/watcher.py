"""
iMessage Watcher - Monitors chat.db for new incoming messages.

The Messages app on macOS stores all iMessages and SMS in a SQLite database
at ~/Library/Messages/chat.db. This module polls that database for new
messages and triggers callbacks when they arrive.

Requirements:
- Mac must be signed into the same iCloud account as the iPhone
- Messages in iCloud must be enabled
- Full Disk Access must be granted to the Python process
"""

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from app.imessage.models import IncomingMessage

logger = logging.getLogger(__name__)

# Default path to the Messages database on macOS
CHAT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

# Apple's epoch starts on 2001-01-01 (vs Unix 1970-01-01)
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


class iMessageWatcher:
    """
    Polls chat.db for new messages and triggers callbacks.

    Usage:
        async def handle_message(msg: IncomingMessage):
            print(f"Received: {msg}")

        watcher = iMessageWatcher(on_message=handle_message)
        await watcher.start()  # Runs forever, polling for messages
    """

    def __init__(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        poll_interval: float = 2.0,
        db_path: Path | None = None,
    ):
        """
        Initialize the watcher.

        Args:
            on_message: Async callback triggered for each new inbound message
            poll_interval: Seconds between database polls
            db_path: Override the default chat.db path (for testing)
        """
        self.on_message = on_message
        self.poll_interval = poll_interval
        self.db_path = db_path or CHAT_DB_PATH
        self.last_rowid = 0
        self._running = False
        self._task: asyncio.Task | None = None

    def _get_connection(self) -> sqlite3.Connection:
        """Create a read-only connection to chat.db."""
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Messages database not found at {self.db_path}. "
                "Ensure Messages app has been used and Full Disk Access is enabled."
            )

        # Read-only connection to avoid any locking issues
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_latest_rowid(self, conn: sqlite3.Connection) -> int:
        """Get the highest message ROWID in the database."""
        cursor = conn.execute("SELECT MAX(ROWID) FROM message")
        result = cursor.fetchone()[0]
        return result or 0

    def _convert_apple_timestamp(self, apple_time: int) -> datetime:
        """Convert Apple's nanoseconds-since-2001 to a datetime."""
        # Apple stores time as nanoseconds since 2001-01-01
        seconds_since_apple_epoch = apple_time / 1_000_000_000
        timestamp = APPLE_EPOCH.timestamp() + seconds_since_apple_epoch
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    def _normalize_phone(self, handle_id: str) -> str:
        """
        Normalize a phone number/handle to E.164 format.

        Examples:
            "5551234567" -> "+15551234567"
            "+1 (555) 123-4567" -> "+15551234567"
            "user@icloud.com" -> "user@icloud.com" (unchanged)
        """
        # If it looks like an email, return as-is
        if "@" in handle_id:
            return handle_id

        # Strip all non-digits
        digits = re.sub(r"\D", "", handle_id)

        # Normalize to E.164
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        elif len(digits) > 11:
            return f"+{digits}"

        # Return original if we can't normalize
        return handle_id

    def _fetch_new_messages(self, conn: sqlite3.Connection) -> list[IncomingMessage]:
        """Fetch all messages with ROWID > last_rowid."""
        query = """
            SELECT 
                m.ROWID,
                m.guid,
                m.text,
                m.date,
                m.is_from_me,
                m.service,
                h.id as handle_id
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.ROWID > ?
              AND m.text IS NOT NULL
              AND m.text != ''
            ORDER BY m.ROWID ASC
            LIMIT 100
        """
        cursor = conn.execute(query, (self.last_rowid,))
        messages = []

        for row in cursor:
            try:
                received_at = self._convert_apple_timestamp(row["date"])

                # Determine if this is iMessage vs SMS
                service = row["service"] or ""
                is_imessage = "iMessage" in service

                messages.append(
                    IncomingMessage(
                        rowid=row["ROWID"],
                        guid=row["guid"],
                        phone=self._normalize_phone(row["handle_id"] or "unknown"),
                        text=row["text"],
                        received_at=received_at,
                        is_from_me=bool(row["is_from_me"]),
                        is_imessage=is_imessage,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to parse message ROWID={row['ROWID']}: {e}")

        return messages

    async def _poll_loop(self):
        """Main polling loop."""
        logger.info(f"Starting iMessage watcher, polling every {self.poll_interval}s")

        while self._running:
            try:
                with self._get_connection() as conn:
                    messages = self._fetch_new_messages(conn)

                    for msg in messages:
                        # Update last_rowid immediately to avoid reprocessing on error
                        self.last_rowid = msg.rowid

                        # Only process inbound messages (not from_me)
                        if not msg.is_from_me:
                            logger.info(f"New message: {msg}")
                            try:
                                await self.on_message(msg)
                            except Exception as e:
                                logger.error(f"Error in message callback: {e}")

            except FileNotFoundError as e:
                logger.error(str(e))
                await asyncio.sleep(30)  # Wait longer before retrying
                continue
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in poll loop: {e}")

            await asyncio.sleep(self.poll_interval)

    async def start(self, skip_historical: bool = True):
        """
        Start the message watcher.

        Args:
            skip_historical: If True, only process messages received after startup
        """
        if self._running:
            logger.warning("Watcher already running")
            return

        self._running = True

        # Initialize last_rowid
        if skip_historical:
            try:
                with self._get_connection() as conn:
                    self.last_rowid = self._get_latest_rowid(conn)
                logger.info(f"Skipping historical messages, starting from ROWID={self.last_rowid}")
            except FileNotFoundError:
                logger.warning("Database not found, will retry in poll loop")
                self.last_rowid = 0

        self._task = asyncio.create_task(self._poll_loop())

    def stop(self):
        """Stop the message watcher."""
        logger.info("Stopping iMessage watcher")
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    @property
    def is_running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._running
