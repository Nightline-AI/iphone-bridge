"""
iPhone Bridge - Main FastAPI Application

This server runs on a Mac Mini and bridges iMessage/SMS communication
between an iPhone and the Nightline server.

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

import asyncio
import logging
import os
import platform
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.imessage import IncomingMessage, iMessageSender, iMessageWatcher
from app.webhooks import NightlineClient, SendMessageRequest, SendMessageResponse
from app.services.queue import MessageQueue

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
_message_queue: MessageQueue | None = None

# Stats
_stats = {
    "messages_received": 0,
    "messages_sent": 0,
    "messages_forwarded": 0,
    "messages_failed": 0,
    "last_message_at": None,
}


async def _deliver_to_nightline(payload: dict) -> bool:
    """Deliver a message payload to Nightline (used by queue)."""
    if not _nightline_client:
        return False
    
    try:
        client = await _nightline_client._get_client()
        url = f"{_nightline_client.base_url}/api/webhooks/iphone-bridge/message"
        response = await client.post(url, json=payload)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Delivery failed: {e}")
        return False


async def _handle_incoming_message(message: IncomingMessage):
    """Callback for when a new message is received."""
    global _stats
    _stats["messages_received"] += 1
    _stats["last_message_at"] = time.time()
    
    logger.info(f"Processing incoming message: {message}")

    if _nightline_client:
        payload = {
            "event": "message.received",
            "phone": message.phone,
            "text": message.text,
            "received_at": message.received_at.isoformat(),
            "message_id": message.guid,
            "is_imessage": message.is_imessage,
        }
        
        success = await _nightline_client.forward_message(message)
        
        if success:
            _stats["messages_forwarded"] += 1
        else:
            _stats["messages_failed"] += 1
            # Queue for retry
            if _message_queue:
                _message_queue.enqueue(message.guid, payload)
    else:
        logger.warning("Nightline client not initialized, message not forwarded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    global _start_time, _watcher, _sender, _nightline_client, _message_queue

    # Startup
    _start_time = time.time()
    logger.info("Starting iPhone Bridge...")

    # Initialize components
    _sender = iMessageSender()
    _nightline_client = NightlineClient()
    
    # Initialize message queue
    _message_queue = MessageQueue(deliver_fn=_deliver_to_nightline)
    await _message_queue.start()

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

    if _message_queue:
        _message_queue.stop()

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

# CORS middleware
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


# --- Health Endpoint (for UptimeRobot) ---

class HealthResponse(BaseModel):
    """Comprehensive health response for monitoring."""
    status: str  # "healthy", "degraded", "unhealthy"
    version: str
    uptime_seconds: float
    
    # Component status
    watcher: dict
    sender: dict
    nightline: dict
    queue: dict
    
    # Stats
    stats: dict
    
    # System info
    system: dict


def _check_chat_db_access() -> tuple[bool, str]:
    """Check if we can access chat.db."""
    chat_db = Path.home() / "Library" / "Messages" / "chat.db"
    if not chat_db.exists():
        return False, "chat.db not found"
    try:
        # Try to open it
        import sqlite3
        conn = sqlite3.connect(f"file:{chat_db}?mode=ro", uri=True)
        conn.close()
        return True, "ok"
    except Exception as e:
        return False, str(e)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Comprehensive health check for monitoring.
    
    Returns detailed status of all components.
    Use status field for alerting:
    - "healthy": Everything working
    - "degraded": Some components have issues but bridge is operational
    - "unhealthy": Critical failure
    """
    now = time.time()
    uptime = now - _start_time
    
    # Check chat.db access
    chat_db_ok, chat_db_msg = _check_chat_db_access()
    
    # Check Nightline connectivity
    nightline_ok = False
    if _nightline_client:
        try:
            nightline_ok = await _nightline_client.health_check()
        except:
            pass
    
    # Determine overall status
    watcher_ok = _watcher.is_running if _watcher else False
    queue_size = _message_queue.size if _message_queue else 0
    
    if not watcher_ok or not chat_db_ok:
        overall_status = "unhealthy"
    elif not nightline_ok or queue_size > 100:
        overall_status = "degraded"
    else:
        overall_status = "healthy"
    
    return HealthResponse(
        status=overall_status,
        version="0.1.0",
        uptime_seconds=uptime,
        watcher={
            "running": watcher_ok,
            "last_rowid": _watcher.last_rowid if _watcher else 0,
            "poll_interval_seconds": settings.poll_interval,
            "chat_db_accessible": chat_db_ok,
            "chat_db_status": chat_db_msg,
        },
        sender={
            "available": _sender is not None,
        },
        nightline={
            "url": settings.nightline_server_url,
            "connected": nightline_ok,
        },
        queue={
            "running": _message_queue.is_running if _message_queue else False,
            **(_message_queue.get_stats() if _message_queue else {"size": 0}),
        },
        stats={
            "messages_received": _stats["messages_received"],
            "messages_sent": _stats["messages_sent"],
            "messages_forwarded": _stats["messages_forwarded"],
            "messages_failed": _stats["messages_failed"],
            "last_message_seconds_ago": (
                now - _stats["last_message_at"] 
                if _stats["last_message_at"] 
                else None
            ),
        },
        system={
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
    )


# --- Simple health check for load balancers ---

@app.get("/ping")
async def ping():
    """Simple ping endpoint. Returns 200 if server is up."""
    return {"pong": True}


# --- Send Message ---

@app.post(
    "/send",
    response_model=SendMessageResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
async def send_message(request: SendMessageRequest):
    """
    Send an iMessage/SMS.
    
    Requires X-Bridge-Secret header for authentication.
    """
    global _stats
    
    if not _sender:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message sender not initialized",
        )

    logger.info(f"Received send request: to={request.phone}, text={request.text[:50]}...")

    response = await _sender.send(request.phone, request.text)

    if response.success:
        _stats["messages_sent"] += 1
        message_id = f"bridge-{uuid.uuid4().hex[:12]}"
        return SendMessageResponse(success=True, message_id=message_id)
    else:
        return SendMessageResponse(success=False, error=response.error)


# --- Status endpoint (more details than health) ---

@app.get("/status")
async def detailed_status():
    """Detailed status for debugging (no auth required)."""
    return await health_check()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
