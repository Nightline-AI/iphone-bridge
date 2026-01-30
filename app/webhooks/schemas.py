"""Pydantic schemas for webhook payloads."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class WebhookEvent(str, Enum):
    """Types of webhook events sent to Nightline."""

    MESSAGE_RECEIVED = "message.received"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_READ = "message.read"
    MESSAGE_FAILED = "message.failed"


class AttachmentInfo(BaseModel):
    """Information about a message attachment."""
    
    filename: str = Field(..., description="Original filename")
    mime_type: str = Field(..., description="MIME type (e.g., image/jpeg)")
    size_bytes: int = Field(..., description="File size in bytes")
    # Note: We send the base64 encoded data separately for large files,
    # or as a URL if the server is configured to serve attachments
    data_base64: str | None = Field(None, description="Base64 encoded file data (for small files)")
    url: str | None = Field(None, description="URL to download attachment (for large files)")


class MessageReceivedEvent(BaseModel):
    """Payload sent to Nightline when a message is received."""

    event: WebhookEvent = WebhookEvent.MESSAGE_RECEIVED
    phone: str = Field(..., description="Phone number in E.164 format")
    text: str = Field(..., description="Message content")
    received_at: datetime = Field(..., description="When the message was received")
    message_id: str = Field(..., description="Unique message identifier (GUID)")
    is_imessage: bool = Field(True, description="True if iMessage, False if SMS")
    attachments: list[AttachmentInfo] = Field(default_factory=list, description="List of attachments")


class MessageStatusEvent(BaseModel):
    """Payload sent to Nightline when a message status changes (delivered/read)."""

    event: str = Field(..., description="message.delivered or message.read")
    phone: str = Field(..., description="Recipient phone number in E.164 format")
    message_id: str = Field(..., description="Message GUID from chat.db")
    timestamp: str = Field(..., description="ISO timestamp of status change")
    is_imessage: bool = Field(True, description="True if iMessage")


class SendMessageRequest(BaseModel):
    """Request to send a message (from Nightline to bridge)."""

    phone: str = Field(..., description="Recipient phone number in E.164 format")
    text: str = Field(..., description="Message content to send")
    reply_to: str | None = Field(None, description="Optional message ID this is replying to")


class SendAttachmentRequest(BaseModel):
    """Request to send an attachment (from Nightline to bridge)."""

    phone: str = Field(..., description="Recipient phone number in E.164 format")
    filename: str = Field(..., description="Filename for the attachment")
    data_base64: str = Field(..., description="Base64 encoded file data")
    mime_type: str = Field("application/octet-stream", description="MIME type of the file")
    caption: str | None = Field(None, description="Optional text caption to send with attachment")


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
