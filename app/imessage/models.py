"""Data models for iMessage handling."""

from dataclasses import dataclass
from datetime import datetime


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

    def __repr__(self) -> str:
        direction = "→" if self.is_from_me else "←"
        msg_type = "iMessage" if self.is_imessage else "SMS"
        preview = self.text[:50] + "..." if len(self.text) > 50 else self.text
        return f"<Message {direction} {self.phone} [{msg_type}]: {preview!r}>"
