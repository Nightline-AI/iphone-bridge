"""
Status Tracker - Tracks delivery and read receipts for sent messages.

When we send a message via iMessage, we can track:
- date_delivered: When the message reached their device
- date_read: When they opened/read it (if read receipts enabled)

This module maintains a set of "pending" messages and checks for status updates.
It's designed to work with the existing poll loop in iMessageWatcher.

Note:
- Only works for iMessage. SMS does not support delivery/read receipts.
- Read receipts only work if the recipient has them enabled.
- Delivered status is more reliable (works if their device receives the message).
"""

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# How long to track messages before giving up (24 hours)
TRACKING_WINDOW_HOURS = 24

# Apple's epoch starts on 2001-01-01 (vs Unix 1970-01-01)
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


@dataclass
class TrackedMessage:
    """A sent message being tracked for delivery/read status."""
    
    phone: str
    text: str
    sent_at: datetime
    is_imessage: bool = True
    guid: str | None = None  # Filled in once we find it in chat.db
    delivered_at: datetime | None = None
    read_at: datetime | None = None


@dataclass
class StatusUpdate:
    """Represents a delivery/read status change for a sent message."""
    
    guid: str
    phone: str
    status: str  # "delivered" or "read"
    timestamp: datetime
    is_imessage: bool = True


class StatusTracker:
    """
    Tracks sent messages and detects delivery/read status changes.
    
    Usage:
        tracker = StatusTracker(on_status_change=my_callback)
        
        # When you send a message, register it:
        tracker.track(phone="+15551234567", text="Hello!")
        
        # The watcher calls this during each poll:
        await tracker.check_status_updates(db_connection)
    """
    
    def __init__(
        self,
        on_status_change: Callable[[StatusUpdate], Awaitable[None]] | None = None,
    ):
        """
        Initialize the status tracker.
        
        Args:
            on_status_change: Async callback triggered when a status changes
        """
        self.on_status_change = on_status_change
        self._tracked: list[TrackedMessage] = []
    
    def track(self, phone: str, text: str, is_imessage: bool = True) -> None:
        """
        Start tracking a sent message for delivery/read updates.
        
        Call this after successfully sending a message via AppleScript.
        We'll match it to the actual message in chat.db by phone + text + timestamp.
        
        Args:
            phone: The recipient phone number (E.164 format)
            text: The message text (used to match in chat.db)
            is_imessage: Whether this was sent as iMessage (SMS doesn't have receipts)
        """
        if not is_imessage:
            logger.debug(f"Not tracking SMS message to {phone} (no delivery receipts)")
            return
        
        msg = TrackedMessage(
            phone=phone,
            text=text,
            sent_at=datetime.now(timezone.utc),
            is_imessage=is_imessage,
        )
        self._tracked.append(msg)
        logger.debug(f"Tracking message to {phone} for delivery status")
    
    def _cleanup_old(self) -> None:
        """Remove messages older than the tracking window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=TRACKING_WINDOW_HOURS)
        before = len(self._tracked)
        self._tracked = [m for m in self._tracked if m.sent_at > cutoff]
        removed = before - len(self._tracked)
        if removed > 0:
            logger.debug(f"Cleaned up {removed} old tracked messages")
    
    async def check_status_updates(self, conn: sqlite3.Connection) -> list[StatusUpdate]:
        """
        Check for delivery/read status changes on tracked messages.
        
        Called during each poll cycle by the watcher.
        
        Args:
            conn: SQLite connection to chat.db
            
        Returns:
            List of status updates detected
        """
        self._cleanup_old()
        
        if not self._tracked:
            return []
        
        updates: list[StatusUpdate] = []
        
        # First, try to resolve any tracked messages without GUIDs
        await self._resolve_pending_guids(conn)
        
        # Then check status for messages we have GUIDs for
        messages_with_guids = [m for m in self._tracked if m.guid]
        
        if not messages_with_guids:
            return []
        
        guids = [m.guid for m in messages_with_guids]
        placeholders = ",".join("?" * len(guids))
        
        query = f"""
            SELECT 
                guid,
                date_delivered,
                date_read,
                service
            FROM message
            WHERE guid IN ({placeholders})
              AND is_from_me = 1
        """
        cursor = conn.execute(query, guids)
        
        for row in cursor:
            guid = row["guid"]
            tracked = next((m for m in self._tracked if m.guid == guid), None)
            if not tracked:
                continue
            
            # Check for delivery update
            if row["date_delivered"] and not tracked.delivered_at:
                delivered_at = self._convert_apple_timestamp(row["date_delivered"])
                tracked.delivered_at = delivered_at
                
                update = StatusUpdate(
                    guid=guid,
                    phone=tracked.phone,
                    status="delivered",
                    timestamp=delivered_at,
                    is_imessage=tracked.is_imessage,
                )
                updates.append(update)
                logger.info(f"Message {guid[:8]}... delivered to {tracked.phone}")
                
                if self.on_status_change:
                    try:
                        await self.on_status_change(update)
                    except Exception as e:
                        logger.error(f"Error in status change callback: {e}")
            
            # Check for read update
            if row["date_read"] and not tracked.read_at:
                read_at = self._convert_apple_timestamp(row["date_read"])
                tracked.read_at = read_at
                
                update = StatusUpdate(
                    guid=guid,
                    phone=tracked.phone,
                    status="read",
                    timestamp=read_at,
                    is_imessage=tracked.is_imessage,
                )
                updates.append(update)
                logger.info(f"Message {guid[:8]}... read by {tracked.phone}")
                
                if self.on_status_change:
                    try:
                        await self.on_status_change(update)
                    except Exception as e:
                        logger.error(f"Error in status change callback: {e}")
                
                # Once read, remove from tracking (final state)
                self._tracked = [m for m in self._tracked if m.guid != guid]
        
        return updates
    
    async def _resolve_pending_guids(self, conn: sqlite3.Connection) -> None:
        """
        Try to match tracked messages (without GUIDs) to actual messages in chat.db.
        
        When we send via AppleScript, we don't get the GUID back. We find it
        by looking for recent outgoing messages to the same phone number with
        matching text.
        """
        pending = [m for m in self._tracked if not m.guid]
        if not pending:
            return
        
        # Look for recent outgoing messages (last 5 minutes)
        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        apple_time = self._datetime_to_apple_timestamp(five_min_ago)
        
        query = """
            SELECT 
                m.guid,
                m.text,
                m.date,
                h.id as handle_id
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.is_from_me = 1
              AND m.date > ?
              AND m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT 50
        """
        cursor = conn.execute(query, (apple_time,))
        
        for row in cursor:
            # Try to match to a pending message
            row_phone = self._normalize_phone(row["handle_id"] or "")
            row_text = row["text"] or ""
            
            for tracked in pending:
                if tracked.guid:  # Already resolved
                    continue
                
                # Match by phone and text
                if row_phone == tracked.phone and row_text == tracked.text:
                    tracked.guid = row["guid"]
                    logger.debug(f"Resolved message to {tracked.phone} -> GUID {row['guid'][:8]}...")
                    break
    
    def _convert_apple_timestamp(self, apple_time: int) -> datetime:
        """Convert Apple's nanoseconds-since-2001 to datetime."""
        if apple_time == 0:
            return datetime.now(timezone.utc)
        seconds = apple_time / 1_000_000_000
        timestamp = APPLE_EPOCH.timestamp() + seconds
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    
    def _datetime_to_apple_timestamp(self, dt: datetime) -> int:
        """Convert datetime to Apple's nanoseconds-since-2001."""
        seconds = dt.timestamp() - APPLE_EPOCH.timestamp()
        return int(seconds * 1_000_000_000)
    
    def _normalize_phone(self, handle_id: str) -> str:
        """Normalize phone number to E.164 format."""
        if "@" in handle_id:
            return handle_id
        digits = re.sub(r"\D", "", handle_id)
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        elif len(digits) > 11:
            return f"+{digits}"
        return handle_id
    
    @property
    def tracking_count(self) -> int:
        """Number of messages currently being tracked."""
        return len(self._tracked)
    
    def get_stats(self) -> dict:
        """Get tracking statistics."""
        with_guid = sum(1 for m in self._tracked if m.guid)
        return {
            "total_tracked": len(self._tracked),
            "pending_resolution": len(self._tracked) - with_guid,
            "with_guid": with_guid,
        }
