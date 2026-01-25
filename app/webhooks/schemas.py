"""Pydantic schemas for webhook payloads."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class WebhookEvent(str, Enum):
    """Types of webhook events sent to Nightline."""

    MESSAGE_RECEIVED = "message.received"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_FAILED = "message.failed"


class MessageReceivedEvent(BaseModel):
    """Payload sent to Nightline when a message is received."""

    event: WebhookEvent = WebhookEvent.MESSAGE_RECEIVED
    phone: str = Field(..., description="Phone number in E.164 format")
    text: str = Field(..., description="Message content")
    received_at: datetime = Field(..., description="When the message was received")
    message_id: str = Field(..., description="Unique message identifier (GUID)")
    is_imessage: bool = Field(True, description="True if iMessage, False if SMS")


class SendMessageRequest(BaseModel):
    """Request to send a message (from Nightline to bridge)."""

    phone: str = Field(..., description="Recipient phone number in E.164 format")
    text: str = Field(..., description="Message content to send")
    reply_to: str | None = Field(None, description="Optional message ID this is replying to")


class SendMessageResponse(BaseModel):
    """Response after attempting to send a message."""

    success: bool
    message_id: str | None = Field(None, description="Message ID if sent successfully")
    error: str | None = Field(None, description="Error message if failed")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    watcher_running: bool
    version: str = "0.1.0"
    uptime_seconds: float
