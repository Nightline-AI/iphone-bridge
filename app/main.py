"""
iPhone Bridge - Main FastAPI Application

This server runs on a Mac Mini and bridges iMessage/SMS communication
between an iPhone and the Nightline server.

Features:
- Monitors incoming messages from chat.db
- Forwards messages to Nightline via webhooks
- Receives send requests from Nightline
- Sends outbound messages via AppleScript

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.imessage import IncomingMessage, iMessageSender, iMessageWatcher
from app.webhooks import NightlineClient, SendMessageRequest, SendMessageResponse
from app.webhooks.schemas import HealthResponse

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global state
_start_time: float = 0
_watcher: iMessageWatcher | None = None
_sender: iMessageSender | None = None
_nightline_client: NightlineClient | None = None


async def _handle_incoming_message(message: IncomingMessage):
    """Callback for when a new message is received."""
    logger.info(f"Processing incoming message: {message}")

    if _nightline_client:
        success = await _nightline_client.forward_message(message)
        if not success:
            logger.error(f"Failed to forward message {message.guid} to Nightline")
    else:
        logger.warning("Nightline client not initialized, message not forwarded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    global _start_time, _watcher, _sender, _nightline_client

    # Startup
    _start_time = time.time()
    logger.info("Starting iPhone Bridge...")

    # Initialize components
    _sender = iMessageSender()
    _nightline_client = NightlineClient()

    _watcher = iMessageWatcher(
        on_message=_handle_incoming_message,
        poll_interval=settings.poll_interval,
    )

    # Start the message watcher
    await _watcher.start(skip_historical=not settings.process_historical)

    # Check Nightline server connectivity
    if await _nightline_client.health_check():
        logger.info(f"Connected to Nightline server at {settings.nightline_server_url}")
    else:
        logger.warning(
            f"Could not connect to Nightline server at {settings.nightline_server_url}. "
            "Messages will be queued until connection is restored."
        )

    logger.info(f"iPhone Bridge started on {settings.host}:{settings.port}")

    yield

    # Shutdown
    logger.info("Shutting down iPhone Bridge...")

    if _watcher:
        _watcher.stop()

    if _nightline_client:
        await _nightline_client.close()

    logger.info("iPhone Bridge stopped")


# Create FastAPI app
app = FastAPI(
    title="iPhone Bridge",
    description="Mac Mini bridge for iPhone iMessage/SMS forwarding to Nightline",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware (for local development/testing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Authentication ---


async def verify_webhook_secret(
    x_bridge_secret: str | None = Header(None, alias="X-Bridge-Secret"),
):
    """Verify the webhook secret for authenticated endpoints."""
    if not x_bridge_secret or x_bridge_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Bridge-Secret header",
        )


# --- Endpoints ---


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns the current status of the bridge including:
    - Whether the message watcher is running
    - Server uptime
    - Version info
    """
    return HealthResponse(
        status="healthy",
        watcher_running=_watcher.is_running if _watcher else False,
        uptime_seconds=time.time() - _start_time,
    )


@app.post(
    "/send",
    response_model=SendMessageResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
async def send_message(request: SendMessageRequest):
    """
    Send an iMessage/SMS.

    This endpoint is called by the Nightline server to send outbound messages.
    The message is sent via AppleScript through the Messages app.

    Requires X-Bridge-Secret header for authentication.
    """
    if not _sender:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message sender not initialized",
        )

    logger.info(f"Received send request: to={request.phone}, text={request.text[:50]}...")

    response = await _sender.send(request.phone, request.text)

    if response.success:
        # Generate a message ID for tracking
        message_id = f"bridge-{uuid.uuid4().hex[:12]}"
        return SendMessageResponse(success=True, message_id=message_id)
    else:
        return SendMessageResponse(success=False, error=response.error)


@app.get("/status")
async def detailed_status():
    """
    Get detailed status information (for debugging).

    Returns information about:
    - Watcher state
    - Nightline server connectivity
    - Configuration (non-sensitive)
    """
    nightline_connected = False
    if _nightline_client:
        nightline_connected = await _nightline_client.health_check()

    return {
        "bridge": {
            "status": "running",
            "uptime_seconds": time.time() - _start_time,
            "version": "0.1.0",
        },
        "watcher": {
            "running": _watcher.is_running if _watcher else False,
            "last_rowid": _watcher.last_rowid if _watcher else 0,
            "poll_interval": settings.poll_interval,
        },
        "nightline": {
            "url": settings.nightline_server_url,
            "connected": nightline_connected,
        },
    }


# --- Development/Testing Endpoints ---


@app.post("/test/send", dependencies=[Depends(verify_webhook_secret)])
async def test_send(phone: str, text: str = "Test message from iPhone Bridge"):
    """
    Test endpoint for sending a message (development only).

    Sends a test message and returns the full response.
    """
    if not _sender:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message sender not initialized",
        )

    response = await _sender.send(phone, text)
    return {
        "result": response.result.value,
        "error": response.error,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
