"""HTTP client for sending webhooks to Nightline server."""

import logging

import httpx

from app.config import settings
from app.imessage.models import IncomingMessage
from app.webhooks.schemas import MessageReceivedEvent

logger = logging.getLogger(__name__)


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

    async def forward_message(self, message: IncomingMessage) -> bool:
        """
        Forward an incoming message to the Nightline server.

        Args:
            message: The incoming message to forward

        Returns:
            True if successfully delivered, False otherwise
        """
        event = MessageReceivedEvent(
            phone=message.phone,
            text=message.text,
            received_at=message.received_at,
            message_id=message.guid,
            is_imessage=message.is_imessage,
        )

        url = f"{self.base_url}/webhooks/iphone-bridge/message"

        try:
            client = await self._get_client()
            response = await client.post(url, json=event.model_dump(mode="json"))

            if response.status_code == 200:
                logger.info(
                    f"Forwarded message from {message.phone} to Nightline "
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
        url = f"{self.base_url}/health"

        try:
            client = await self._get_client()
            response = await client.get(url)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Nightline server health check failed: {e}")
            return False
