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
from app.imessage import IncomingMessage, iMessageSender, iMessageWatcher, MockiMessageWatcher, MockiMessageSender
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
    
    client_id = settings.nightline_client_id
    if not client_id:
        logger.error("NIGHTLINE_CLIENT_ID not configured - cannot deliver message")
        return False
    
    try:
        client = await _nightline_client._get_client()
        url = f"{_nightline_client.base_url}/webhooks/iphone-bridge/{client_id}/message"
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
    
    if settings.mock_mode:
        logger.info("🧪 Starting iPhone Bridge in MOCK MODE (no real iMessage)")
    else:
        logger.info("Starting iPhone Bridge...")

    # Initialize components based on mode
    if settings.mock_mode:
        _sender = MockiMessageSender()
        _watcher = MockiMessageWatcher(
            on_message=_handle_incoming_message,
            poll_interval=settings.poll_interval,
        )
    else:
        _sender = iMessageSender()
        _watcher = iMessageWatcher(
            on_message=_handle_incoming_message,
            poll_interval=settings.poll_interval,
        )
    
    _nightline_client = NightlineClient()
    
    # Initialize message queue
    _message_queue = MessageQueue(deliver_fn=_deliver_to_nightline)
    await _message_queue.start()

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

    mode_str = "🧪 MOCK MODE" if settings.mock_mode else "PRODUCTION MODE"
    logger.info(f"iPhone Bridge started on {settings.host}:{settings.port} ({mode_str})")

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


# =====================================================
# MOCK MODE TEST ENDPOINTS
# Only available when MOCK_MODE=true
# =====================================================


class InjectMessageRequest(BaseModel):
    """Request to inject a test message."""
    phone: str
    text: str
    is_imessage: bool = True


class InjectMessageResponse(BaseModel):
    """Response after injecting a test message."""
    success: bool
    message_id: str | None = None
    error: str | None = None


@app.post("/test/inject", response_model=InjectMessageResponse)
async def inject_test_message(request: InjectMessageRequest):
    """
    [MOCK MODE ONLY] Inject a test message as if received from a phone.
    
    This simulates receiving an iMessage/SMS so you can test the full flow
    without a real iPhone connected.
    """
    if not settings.mock_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in mock mode. Set MOCK_MODE=true",
        )
    
    if not isinstance(_watcher, MockiMessageWatcher):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mock watcher not initialized",
        )
    
    try:
        message = await _watcher.inject_message(
            phone=request.phone,
            text=request.text,
            is_imessage=request.is_imessage,
        )
        return InjectMessageResponse(success=True, message_id=message.guid)
    except Exception as e:
        logger.error(f"Failed to inject message: {e}")
        return InjectMessageResponse(success=False, error=str(e))


@app.get("/test/sent")
async def get_sent_messages():
    """
    [MOCK MODE ONLY] Get all messages that would have been sent via iMessage.
    
    Returns the list of messages that the mock sender has logged.
    """
    if not settings.mock_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in mock mode. Set MOCK_MODE=true",
        )
    
    if not isinstance(_sender, MockiMessageSender):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mock sender not initialized",
        )
    
    return {
        "messages": _sender.get_sent_messages(),
        "count": len(_sender.get_sent_messages()),
    }


@app.get("/test/received")
async def get_received_messages():
    """
    [MOCK MODE ONLY] Get all messages that have been injected/received.
    
    Returns the list of messages that have been injected for testing.
    """
    if not settings.mock_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in mock mode. Set MOCK_MODE=true",
        )
    
    if not isinstance(_watcher, MockiMessageWatcher):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mock watcher not initialized",
        )
    
    messages = _watcher.get_message_history()
    return {
        "messages": [
            {
                "id": m.guid,
                "phone": m.phone,
                "text": m.text,
                "received_at": m.received_at.isoformat(),
                "is_imessage": m.is_imessage,
            }
            for m in messages
        ],
        "count": len(messages),
    }


@app.delete("/test/clear")
async def clear_test_data():
    """
    [MOCK MODE ONLY] Clear all test message data.
    """
    if not settings.mock_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in mock mode. Set MOCK_MODE=true",
        )
    
    if isinstance(_sender, MockiMessageSender):
        _sender.clear_sent_messages()
    
    return {"success": True, "message": "Test data cleared"}


# Test UI - simple HTML interface for manual testing
TEST_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>iPhone Bridge Test Console</title>
    <style>
        :root {
            --bg: #0a0a0f;
            --surface: #12121a;
            --border: #2a2a3a;
            --text: #e0e0e0;
            --text-dim: #808090;
            --accent: #00d4aa;
            --accent-dim: #00a080;
            --sent: #3b82f6;
            --received: #10b981;
            --error: #ef4444;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 2rem;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }
        
        header h1 {
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--accent);
        }
        
        .badge {
            background: var(--accent);
            color: var(--bg);
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
        }
        
        @media (max-width: 900px) {
            .grid { grid-template-columns: 1fr; }
        }
        
        .panel {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }
        
        .panel-header {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-dim);
        }
        
        .panel-body {
            padding: 1rem;
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        label {
            display: block;
            font-size: 0.75rem;
            color: var(--text-dim);
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        input, textarea {
            width: 100%;
            padding: 0.75rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 4px;
            color: var(--text);
            font-family: inherit;
            font-size: 0.875rem;
        }
        
        input:focus, textarea:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        textarea {
            resize: vertical;
            min-height: 100px;
        }
        
        button {
            background: var(--accent);
            color: var(--bg);
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 4px;
            font-family: inherit;
            font-size: 0.875rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover {
            background: var(--accent-dim);
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .messages {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .message {
            padding: 0.75rem;
            border-radius: 4px;
            margin-bottom: 0.5rem;
            font-size: 0.875rem;
        }
        
        .message.sent {
            background: rgba(59, 130, 246, 0.15);
            border-left: 3px solid var(--sent);
        }
        
        .message.received {
            background: rgba(16, 185, 129, 0.15);
            border-left: 3px solid var(--received);
        }
        
        .message-header {
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: var(--text-dim);
            margin-bottom: 0.5rem;
        }
        
        .message-text {
            word-break: break-word;
        }
        
        .empty {
            color: var(--text-dim);
            font-style: italic;
            text-align: center;
            padding: 2rem;
        }
        
        .status {
            display: flex;
            gap: 1rem;
            padding: 1rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-bottom: 2rem;
            font-size: 0.875rem;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--received);
        }
        
        .status-dot.error {
            background: var(--error);
        }
        
        .toast {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            padding: 1rem 1.5rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
            animation: slideIn 0.3s ease;
        }
        
        .toast.success { border-color: var(--received); }
        .toast.error { border-color: var(--error); }
        
        @keyframes slideIn {
            from { transform: translateY(1rem); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📱 iPhone Bridge</h1>
            <span class="badge">Mock Mode</span>
        </header>
        
        <div class="status" id="status">
            <div class="status-item">
                <span class="status-dot" id="status-dot"></span>
                <span id="status-text">Checking...</span>
            </div>
            <div class="status-item" id="nightline-status"></div>
        </div>
        
        <div class="grid">
            <div class="panel">
                <div class="panel-header">📥 Inject Incoming Message</div>
                <div class="panel-body">
                    <form id="inject-form">
                        <div class="form-group">
                            <label for="phone">Phone Number</label>
                            <input type="text" id="phone" placeholder="+15551234567" required>
                        </div>
                        <div class="form-group">
                            <label for="text">Message Text</label>
                            <textarea id="text" placeholder="Enter test message..." required></textarea>
                        </div>
                        <button type="submit">Send Test Message →</button>
                    </form>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-header">📤 Outgoing Messages (Mock)</div>
                <div class="panel-body">
                    <div class="messages" id="sent-messages">
                        <div class="empty">No messages sent yet</div>
                    </div>
                </div>
            </div>
            
            <div class="panel" style="grid-column: 1 / -1;">
                <div class="panel-header">📋 Message Log</div>
                <div class="panel-body">
                    <div class="messages" id="all-messages">
                        <div class="empty">No messages yet</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const API_BASE = window.location.origin;
        
        // Show toast notification
        function showToast(message, type = 'success') {
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        
        // Check health status
        async function checkStatus() {
            try {
                const res = await fetch(`${API_BASE}/health`);
                const data = await res.json();
                
                document.getElementById('status-dot').className = 
                    data.status === 'healthy' ? 'status-dot' : 'status-dot error';
                document.getElementById('status-text').textContent = 
                    `Bridge: ${data.status}`;
                document.getElementById('nightline-status').innerHTML = `
                    <span class="status-dot ${data.nightline.connected ? '' : 'error'}"></span>
                    <span>Nightline: ${data.nightline.connected ? 'Connected' : 'Disconnected'}</span>
                `;
            } catch (e) {
                document.getElementById('status-dot').className = 'status-dot error';
                document.getElementById('status-text').textContent = 'Bridge: Offline';
            }
        }
        
        // Load sent messages
        async function loadSentMessages() {
            try {
                const res = await fetch(`${API_BASE}/test/sent`);
                const data = await res.json();
                
                const container = document.getElementById('sent-messages');
                if (data.messages.length === 0) {
                    container.innerHTML = '<div class="empty">No messages sent yet</div>';
                    return;
                }
                
                container.innerHTML = data.messages.map(m => `
                    <div class="message sent">
                        <div class="message-header">
                            <span>→ ${m.phone}</span>
                            <span>${new Date(m.sent_at).toLocaleTimeString()}</span>
                        </div>
                        <div class="message-text">${escapeHtml(m.text)}</div>
                    </div>
                `).reverse().join('');
            } catch (e) {
                console.error('Failed to load sent messages:', e);
            }
        }
        
        // Load received/injected messages
        async function loadReceivedMessages() {
            try {
                const res = await fetch(`${API_BASE}/test/received`);
                const data = await res.json();
                
                const container = document.getElementById('all-messages');
                if (data.messages.length === 0) {
                    container.innerHTML = '<div class="empty">No messages yet</div>';
                    return;
                }
                
                container.innerHTML = data.messages.map(m => `
                    <div class="message received">
                        <div class="message-header">
                            <span>← ${m.phone}</span>
                            <span>${new Date(m.received_at).toLocaleTimeString()}</span>
                        </div>
                        <div class="message-text">${escapeHtml(m.text)}</div>
                    </div>
                `).reverse().join('');
            } catch (e) {
                console.error('Failed to load received messages:', e);
            }
        }
        
        // Escape HTML
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Handle form submission
        document.getElementById('inject-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const phone = document.getElementById('phone').value;
            const text = document.getElementById('text').value;
            
            try {
                const res = await fetch(`${API_BASE}/test/inject`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone, text, is_imessage: true })
                });
                
                const data = await res.json();
                
                if (data.success) {
                    showToast('Message injected! Check server logs for flow.');
                    document.getElementById('text').value = '';
                    loadReceivedMessages();
                    // Also reload sent in case server responded
                    setTimeout(loadSentMessages, 1000);
                } else {
                    showToast(data.error || 'Failed to inject message', 'error');
                }
            } catch (e) {
                showToast('Failed to inject message', 'error');
            }
        });
        
        // Initial load
        checkStatus();
        loadSentMessages();
        loadReceivedMessages();
        
        // Poll for updates
        setInterval(() => {
            loadSentMessages();
            loadReceivedMessages();
        }, 3000);
        
        setInterval(checkStatus, 10000);
    </script>
</body>
</html>
"""

from fastapi.responses import HTMLResponse

@app.get("/test", response_class=HTMLResponse)
async def test_ui():
    """
    [MOCK MODE ONLY] Simple web UI for testing the bridge.
    
    Open http://localhost:8080/test in your browser.
    """
    if not settings.mock_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test UI is only available in mock mode. Set MOCK_MODE=true",
        )
    
    return TEST_UI_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
