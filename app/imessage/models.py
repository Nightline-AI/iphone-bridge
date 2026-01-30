"""Data models for iMessage handling."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Attachment:
    """Represents an attachment (image, video, etc.) in an iMessage."""
    
    filename: str  # Original filename (e.g., "IMG_1234.jpg")
    path: str  # Full local path to the file
    mime_type: str  # MIME type (e.g., "image/jpeg")
    size_bytes: int  # File size in bytes
    transfer_name: str | None = None  # Apple's internal transfer name
    
    @property
    def is_image(self) -> bool:
        """Check if this is an image attachment."""
        return self.mime_type.startswith("image/")
    
    @property
    def is_video(self) -> bool:
        """Check if this is a video attachment."""
        return self.mime_type.startswith("video/")
    
    @property
    def exists(self) -> bool:
        """Check if the file exists on disk."""
        return Path(self.path).exists()
    
    def __repr__(self) -> str:
        return f"<Attachment {self.filename} ({self.mime_type}, {self.size_bytes} bytes)>"


@dataclass
class IncomingMessage:
    """Represents an incoming iMessage/SMS from chat.db."""

    rowid: int
    guid: str
    phone: str  # Normalized to E.164 format
    text: str
    received_at: datetime
    is_from_me: bool
    is_imessage: bool = True  # vs SMS
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        """Check if this message has any attachments."""
        return len(self.attachments) > 0
    
    @property
    def image_attachments(self) -> list[Attachment]:
        """Get only image attachments."""
        return [a for a in self.attachments if a.is_image]

    def __repr__(self) -> str:
        direction = "→" if self.is_from_me else "←"
        msg_type = "iMessage" if self.is_imessage else "SMS"
        preview = self.text[:50] + "..." if len(self.text) > 50 else self.text
        attach_str = f" +{len(self.attachments)} attachments" if self.attachments else ""
        return f"<Message {direction} {self.phone} [{msg_type}]: {preview!r}{attach_str}>"
