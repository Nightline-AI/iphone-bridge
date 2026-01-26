"""
Mock iMessage components for local development/testing.

When mock_mode is enabled, these replace the real watcher and sender so you can
test the full bridge flow without iCloud sync or a real iPhone.

Provides:
- MockiMessageWatcher: Accepts injected messages via API instead of polling chat.db
- MockiMessageSender: Logs outgoing messages instead of using AppleScript
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.imessage.models import IncomingMessage
from app.imessage.sender import SendResponse, SendResult

logger = logging.getLogger(__name__)


class MockiMessageWatcher:
    """
    Mock watcher that accepts injected messages instead of polling chat.db.
    
    Usage:
        watcher = MockiMessageWatcher(on_message=handle_message)
        await watcher.start()
        
        # Inject a test message
        await watcher.inject_message("+15551234567", "Hello from test!")
    """
    
    def __init__(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        poll_interval: float = 2.0,  # Ignored in mock mode
        db_path=None,  # Ignored in mock mode
    ):
        self.on_message = on_message
        self.poll_interval = poll_interval
        self._running = False
        self._rowid_counter = 0
        self._message_history: list[IncomingMessage] = []
    
    async def start(self, skip_historical: bool = True):
        """Start the mock watcher."""
        logger.info("🧪 Mock watcher started (no chat.db polling)")
        self._running = True
    
    def stop(self):
        """Stop the mock watcher."""
        logger.info("🧪 Mock watcher stopped")
        self._running = False
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def last_rowid(self) -> int:
        return self._rowid_counter
    
    async def inject_message(
        self,
        phone: str,
        text: str,
        is_imessage: bool = True,
    ) -> IncomingMessage:
        """
        Inject a test message as if it was received from a real phone.
        
        Args:
            phone: Phone number in E.164 format (e.g., "+15551234567")
            text: Message content
            is_imessage: True for iMessage, False for SMS
        
        Returns:
            The created IncomingMessage
        """
        self._rowid_counter += 1
        
        message = IncomingMessage(
            rowid=self._rowid_counter,
            guid=f"mock-{uuid.uuid4().hex[:12]}",
            phone=phone,
            text=text,
            received_at=datetime.now(tz=timezone.utc),
            is_from_me=False,
            is_imessage=is_imessage,
        )
        
        self._message_history.append(message)
        logger.info(f"🧪 Injected mock message: {message}")
        
        # Trigger the callback (same as real watcher)
        if self._running:
            try:
                await self.on_message(message)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")
        
        return message
    
    def get_message_history(self) -> list[IncomingMessage]:
        """Get all injected messages."""
        return list(self._message_history)


class MockiMessageSender:
    """
    Mock sender that logs outgoing messages instead of using AppleScript.
    
    Usage:
        sender = MockiMessageSender()
        response = await sender.send("+15551234567", "Hello!")
        
        # Get all sent messages
        sent = sender.get_sent_messages()
    """
    
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._sent_messages: list[dict] = []
    
    async def send(self, phone: str, text: str) -> SendResponse:
        """
        Mock send - logs the message instead of actually sending.
        
        Args:
            phone: Phone number in E.164 format
            text: Message content
        
        Returns:
            Always returns success (unless phone/text is empty)
        """
        if not phone:
            return SendResponse(
                result=SendResult.INVALID_RECIPIENT,
                error="Phone number is required",
            )
        
        if not text:
            return SendResponse(
                result=SendResult.FAILED,
                error="Message text is required",
            )
        
        message = {
            "id": f"mock-sent-{uuid.uuid4().hex[:12]}",
            "phone": phone,
            "text": text,
            "sent_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        
        self._sent_messages.append(message)
        logger.info(f"🧪 Mock sent message to {phone}: {text[:50]}...")
        
        return SendResponse(result=SendResult.SUCCESS)
    
    async def send_bulk(
        self, messages: list[tuple[str, str]], delay: float = 1.0
    ) -> list[SendResponse]:
        """Send multiple messages."""
        responses = []
        for phone, text in messages:
            response = await self.send(phone, text)
            responses.append(response)
        return responses
    
    def get_sent_messages(self) -> list[dict]:
        """Get all messages that have been 'sent' through the mock."""
        return list(self._sent_messages)
    
    def clear_sent_messages(self):
        """Clear the sent message history."""
        self._sent_messages.clear()
