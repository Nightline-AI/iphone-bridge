"""HTTP client for sending webhooks to Nightline server."""

import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.imessage.models import IncomingMessage
from app.webhooks.schemas import AttachmentInfo, MessageReceivedEvent, MessageStatusEvent

if TYPE_CHECKING:
    from app.imessage.status_tracker import StatusUpdate

logger = logging.getLogger(__name__)

# Maximum file size to embed as base64 (5MB)
MAX_INLINE_ATTACHMENT_SIZE = 5 * 1024 * 1024


class NightlineClient:
    """
    Client for communicating with the Nightline server.

    Handles authentication and retry logic for webhook delivery.
    """

    def __init__(
        self,
        base_url: str | None = None,
        secret: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize the Nightline client.

        Args:
            base_url: Nightline server URL (defaults to settings)
            secret: Webhook secret for authentication (defaults to settings)
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or settings.nightline_server_url).rstrip("/")
        self.secret = secret or settings.webhook_secret
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "Content-Type": "application/json",
                    "X-Bridge-Secret": self.secret,
                    "User-Agent": "NightlineIphoneBridge/0.1.0",
                },
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _encode_attachment(self, attachment) -> AttachmentInfo | None:
        """
        Encode an attachment for sending to Nightline.
        
        Args:
            attachment: Attachment object from IncomingMessage
            
        Returns:
            AttachmentInfo if successful, None if attachment can't be read
        """
        try:
            path = Path(attachment.path)
            if not path.exists():
                logger.warning(f"Attachment file not found: {attachment.path}")
                return None
            
            file_size = path.stat().st_size
            
            # Only encode small files inline
            if file_size <= MAX_INLINE_ATTACHMENT_SIZE:
                with open(path, "rb") as f:
                    data = f.read()
                data_base64 = base64.b64encode(data).decode("utf-8")
                
                return AttachmentInfo(
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                    size_bytes=attachment.size_bytes,
                    data_base64=data_base64,
                )
            else:
                # For large files, just send metadata
                # The server can request the file separately if needed
                logger.info(f"Attachment too large for inline encoding: {attachment.filename} ({file_size} bytes)")
                return AttachmentInfo(
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                    size_bytes=attachment.size_bytes,
                    data_base64=None,
                    url=None,  # Could implement a download endpoint in the future
                )
                
        except Exception as e:
            logger.error(f"Failed to encode attachment {attachment.filename}: {e}")
            return None

    async def forward_message(self, message: IncomingMessage) -> bool:
        """
        Forward an incoming message to the Nightline server.

        Args:
            message: The incoming message to forward

        Returns:
            True if successfully delivered, False otherwise
        """
        # Encode any attachments
        attachment_infos = []
        for attachment in message.attachments:
            info = self._encode_attachment(attachment)
            if info:
                attachment_infos.append(info)
        
        event = MessageReceivedEvent(
            phone=message.phone,
            text=message.text,
            received_at=message.received_at,
            message_id=message.guid,
            is_imessage=message.is_imessage,
            attachments=attachment_infos,
        )

        # Include client_id in the URL path
        client_id = settings.nightline_client_id
        if not client_id:
            logger.error("NIGHTLINE_CLIENT_ID not configured - cannot forward message")
            return False
        
        url = f"{self.base_url}/webhooks/iphone-bridge/{client_id}/message"

        try:
            client = await self._get_client()
            response = await client.post(url, json=event.model_dump(mode="json"))

            if response.status_code == 200:
                attach_str = f" with {len(attachment_infos)} attachments" if attachment_infos else ""
                logger.info(
                    f"Forwarded message from {message.phone} to Nightline{attach_str} "
                    f"(id={message.guid})"
                )
                return True

            logger.error(
                f"Failed to forward message: HTTP {response.status_code} - "
                f"{response.text}"
            )
            return False

        except httpx.TimeoutException:
            logger.error(f"Timeout forwarding message to {url}")
            return False
        except httpx.ConnectError as e:
            logger.error(f"Connection error forwarding message: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error forwarding message: {e}")
            return False

    async def health_check(self) -> bool:
        """
        Check if the Nightline server is reachable.

        Returns:
            True if server responds, False otherwise
        """
        url = f"{self.base_url}/webhooks/iphone-bridge/{settings.nightline_client_id}/health"

        try:
            client = await self._get_client()
            response = await client.get(url)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Nightline server health check failed: {e}")
            return False
    
    async def send_status_update(self, update: "StatusUpdate") -> bool:
        """
        Send a delivery/read status update to the Nightline server.
        
        Called when we detect that a sent message was delivered or read.
        
        Args:
            update: The status update to send
            
        Returns:
            True if successfully delivered, False otherwise
        """
        event = MessageStatusEvent(
            event=f"message.{update.status}",  # "message.delivered" or "message.read"
            phone=update.phone,
            message_id=update.guid,
            timestamp=update.timestamp.isoformat(),
            is_imessage=update.is_imessage,
        )
        
        client_id = settings.nightline_client_id
        if not client_id:
            logger.error("NIGHTLINE_CLIENT_ID not configured - cannot send status update")
            return False
        
        url = f"{self.base_url}/webhooks/iphone-bridge/{client_id}/status"
        
        try:
            client = await self._get_client()
            response = await client.post(url, json=event.model_dump(mode="json"))
            
            if response.status_code == 200:
                logger.info(
                    f"Sent {update.status} status for message to {update.phone} "
                    f"(id={update.guid[:8]}...)"
                )
                return True
            
            logger.error(
                f"Failed to send status update: HTTP {response.status_code} - "
                f"{response.text}"
            )
            return False
        
        except httpx.TimeoutException:
            logger.error(f"Timeout sending status update to {url}")
            return False
        except httpx.ConnectError as e:
            logger.error(f"Connection error sending status update: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending status update: {e}")
            return False