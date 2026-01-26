"""
Management Agent - Isolated admin interface for iPhone Bridge

Run with:
    uvicorn management.main:app --host 0.0.0.0 --port 8081
"""

import logging

from fastapi import FastAPI, Request, Response, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from management.config import settings
from management.auth import verify_token, require_auth
from management.routes import services, config, logs, health, update, control

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="iPhone Bridge Management",
    description="Admin interface for iPhone Bridge",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(services.router)
app.include_router(config.router)
app.include_router(logs.router)
app.include_router(update.router)
app.include_router(control.router)


# ============================================================
# Login Flow
# ============================================================

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - iPhone Bridge</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #09090b;
            color: #fafafa;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .card {
            background: #18181b;
            border: 1px solid #27272a;
            border-radius: 12px;
            padding: 2.5rem;
            width: 100%;
            max-width: 400px;
        }
        
        h1 {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            text-align: center;
        }
        
        .subtitle {
            color: #71717a;
            font-size: 0.875rem;
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .form-group {
            margin-bottom: 1.5rem;
        }
        
        label {
            display: block;
            font-size: 0.8125rem;
            font-weight: 500;
            color: #a1a1aa;
            margin-bottom: 0.5rem;
        }
        
        input {
            width: 100%;
            padding: 0.75rem 1rem;
            background: #09090b;
            border: 1px solid #3f3f46;
            border-radius: 6px;
            color: #fafafa;
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 0.875rem;
        }
        
        input:focus {
            outline: none;
            border-color: #3b82f6;
        }
        
        button {
            width: 100%;
            padding: 0.75rem;
            background: #3b82f6;
            color: white;
            border: none;
            border-radius: 6px;
            font-family: inherit;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
        }
        
        button:hover { background: #2563eb; }
        
        .error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid #ef4444;
            color: #ef4444;
            padding: 0.75rem;
            border-radius: 6px;
            font-size: 0.875rem;
            margin-bottom: 1.5rem;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>iPhone Bridge</h1>
        <p class="subtitle">Enter your management token</p>
        
        {{ERROR}}
        
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="token">Management Token</label>
                <input type="password" id="token" name="token" 
                       placeholder="Enter token..." required autofocus>
            </div>
            <button type="submit">Unlock</button>
        </form>
    </div>
</body>
</html>
"""


@app.get("/login", response_class=HTMLResponse)
async def login_page(error: str = ""):
    """Show login page."""
    error_html = ""
    if error:
        error_html = f'<div class="error">{error}</div>'
    return LOGIN_HTML.replace("{{ERROR}}", error_html)


@app.post("/login")
async def login(response: Response, token: str = Form(...)):
    """Handle login form submission."""
    if not verify_token(token):
        return RedirectResponse(
            url="/login?error=Invalid+token",
            status_code=303,
        )
    
    # Set session cookie
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=True,  # Requires HTTPS
        samesite="strict",
        max_age=settings.cookie_max_age,
    )
    return response


@app.get("/logout")
async def logout():
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(settings.cookie_name)
    return response


# ============================================================
# Dashboard UI
# ============================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>iPhone Bridge</title>
    <style>
        :root {
            --bg: #09090b;
            --surface: #18181b;
            --surface-2: #27272a;
            --border: #3f3f46;
            --text: #fafafa;
            --text-secondary: #a1a1aa;
            --text-muted: #71717a;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --green: #22c55e;
            --red: #ef4444;
            --yellow: #eab308;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
        }
        
        .header-left {
            display: flex;
            flex-direction: column;
            gap: 0.375rem;
        }
        
        header h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }
        
        .identifier-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.375rem;
            padding: 0.25rem 0.5rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
            font-family: 'SF Mono', monospace;
            font-size: 0.75rem;
            color: var(--text-muted);
            cursor: pointer;
            width: fit-content;
        }
        
        .identifier-badge:hover {
            color: var(--text-secondary);
            border-color: var(--text-muted);
        }
        
        .identifier-badge .copy-icon {
            opacity: 0.5;
            flex-shrink: 0;
        }
        
        .identifier-badge:hover .copy-icon {
            opacity: 1;
        }
        
        .identifier-badge svg {
            display: block;
        }
        
        .header-right {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .status-badge {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.375rem 0.75rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 9999px;
            font-size: 0.8125rem;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
        }
        
        .status-dot.offline { background: var(--red); }
        .status-dot.degraded { background: var(--yellow); }
        
        .logout-btn {
            color: var(--text-muted);
            text-decoration: none;
            font-size: 0.8125rem;
        }
        
        .logout-btn:hover { color: var(--text); }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1.5rem;
        }
        
        @media (max-width: 900px) {
            .grid { grid-template-columns: 1fr; }
        }
        
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
        }
        
        .card-header {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
            font-weight: 500;
            font-size: 0.875rem;
        }
        
        .card-body {
            padding: 1.25rem;
        }
        
        .url-display {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.75rem 1rem;
            font-family: 'SF Mono', monospace;
            font-size: 0.8125rem;
            color: var(--accent);
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }
        
        .url-display a {
            color: inherit;
            text-decoration: none;
        }
        
        .url-display a:hover { text-decoration: underline; }
        
        .copy-btn {
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 0.75rem;
        }
        
        .copy-btn:hover { color: var(--text); }
        
        .help-text {
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .service-list {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        .service-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 1rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
        }
        
        .service-info {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .service-name {
            font-weight: 500;
            font-size: 0.875rem;
        }
        
        .service-status {
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .btn {
            padding: 0.375rem 0.75rem;
            background: var(--surface-2);
            color: var(--text-secondary);
            border: 1px solid var(--border);
            border-radius: 4px;
            font-family: inherit;
            font-size: 0.75rem;
            cursor: pointer;
        }
        
        .btn:hover {
            background: var(--border);
            color: var(--text);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .btn-primary {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        
        .btn-primary:hover { background: var(--accent-hover); }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        .form-group:last-of-type {
            margin-bottom: 1.25rem;
        }
        
        label {
            display: block;
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-bottom: 0.375rem;
        }
        
        input[type="text"], input[type="url"], input[type="number"] {
            width: 100%;
            padding: 0.5rem 0.75rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 4px;
            color: var(--text);
            font-family: inherit;
            font-size: 0.8125rem;
        }
        
        input:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        .mono { font-family: 'SF Mono', monospace; }
        
        .logs-card { grid-column: 1 / -1; }
        
        .log-tabs {
            display: flex;
            gap: 0.25rem;
        }
        
        .log-tab {
            padding: 0.375rem 0.75rem;
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-family: inherit;
            font-size: 0.75rem;
            cursor: pointer;
            border-radius: 4px;
        }
        
        .log-tab:hover { color: var(--text-secondary); }
        .log-tab.active {
            background: var(--surface-2);
            color: var(--text);
        }
        
        .logs {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 1rem;
            height: 300px;
            overflow-y: auto;
            font-family: 'SF Mono', monospace;
            font-size: 0.6875rem;
            line-height: 1.6;
        }
        
        .log-line {
            white-space: pre-wrap;
            word-break: break-all;
            color: var(--text-muted);
        }
        
        .log-line.error { color: var(--red); }
        .log-line.warning { color: var(--yellow); }
        
        .toast {
            position: fixed;
            bottom: 1.5rem;
            right: 1.5rem;
            padding: 0.75rem 1rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.8125rem;
            animation: slideIn 0.2s ease;
        }
        
        .toast.success { border-color: var(--green); }
        .toast.error { border-color: var(--red); }
        
        @keyframes slideIn {
            from { transform: translateY(0.5rem); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        .health-bar {
            display: flex;
            gap: 1.5rem;
            padding: 1rem 1.25rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }
        
        .health-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.8125rem;
            color: var(--text-secondary);
        }
        
        .queue-badge {
            background: var(--surface-2);
            padding: 0.125rem 0.5rem;
            border-radius: 4px;
            font-family: 'SF Mono', monospace;
            font-size: 0.75rem;
        }
        
        .queue-badge.warning {
            background: rgba(234, 179, 8, 0.2);
            color: var(--yellow);
        }
        
        .action-group {
            margin-bottom: 1.25rem;
        }
        
        .action-group:last-child {
            margin-bottom: 0;
        }
        
        .action-label {
            font-size: 0.6875rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }
        
        .action-buttons {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        
        .update-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        
        .update-status {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.8125rem;
            color: var(--text-secondary);
        }
        
        .update-status.up-to-date {
            color: var(--green);
        }
        
        .update-status.has-update {
            color: var(--yellow);
        }
        
        .update-status .version {
            font-family: 'SF Mono', monospace;
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .spinner {
            width: 14px;
            height: 14px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        /* Bridge Control Styles */
        .control-status {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 1rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            margin-bottom: 1.25rem;
        }
        
        .control-indicator {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
        }
        
        .control-queue {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .status-dot.paused {
            background: var(--yellow);
        }
        
        .btn-danger {
            background: var(--red);
            color: white;
            border-color: var(--red);
        }
        
        .btn-danger:hover {
            background: #dc2626;
        }
        
        .btn-warning {
            background: var(--yellow);
            color: #000;
            border-color: var(--yellow);
        }
        
        .btn-warning:hover {
            background: #ca8a04;
        }
        
        .btn.active {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        
        /* Queue modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        
        .modal {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            width: 100%;
            max-width: 600px;
            max-height: 80vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        
        .modal-header {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .modal-header h3 {
            font-size: 1rem;
            font-weight: 500;
        }
        
        .modal-close {
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 1.25rem;
        }
        
        .modal-close:hover {
            color: var(--text);
        }
        
        .modal-body {
            padding: 1.25rem;
            overflow-y: auto;
        }
        
        .queue-item {
            padding: 0.75rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 4px;
            margin-bottom: 0.5rem;
            font-size: 0.8125rem;
        }
        
        .queue-item-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.25rem;
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .queue-item-text {
            color: var(--text);
        }
        
        .empty-queue {
            text-align: center;
            color: var(--text-muted);
            padding: 2rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-left">
                <h1 id="bridge-name">iPhone Bridge</h1>
                <div class="identifier-badge" onclick="copyIdentifier()" title="Click to copy">
                    <span id="bridge-id">Loading...</span>
                    <svg class="copy-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </div>
            </div>
            <div class="header-right">
                <a href="/logout" class="logout-btn">Logout</a>
            </div>
        </header>
        
        <!-- Health Status Bar -->
        <div class="health-bar" id="health-bar">
            <div class="health-item">
                <span class="status-dot" id="h-bridge"></span>
                <span>Bridge</span>
            </div>
            <div class="health-item">
                <span class="status-dot" id="h-nightline"></span>
                <span>Nightline</span>
            </div>
            <div class="health-item">
                <span class="status-dot" id="h-chatdb"></span>
                <span>Chat.db</span>
            </div>
            <div class="health-item">
                <span class="status-dot" id="h-tunnel"></span>
                <span>Tunnel</span>
            </div>
            <div class="health-item" id="queue-info">
                <span class="queue-badge">0</span>
                <span>Queued</span>
            </div>
        </div>
        
        <div class="grid">
            <div class="card">
                <div class="card-header">Public URL</div>
                <div class="card-body">
                    <div class="url-display">
                        <a href="#" id="tunnel-url" target="_blank">Loading...</a>
                        <button class="copy-btn" onclick="copyUrl('tunnel-url')">Copy</button>
                    </div>
                    <p class="help-text">Bridge endpoint for Nightline server</p>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">Services</div>
                <div class="card-body">
                    <div class="service-list" id="services"></div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">Configuration</div>
                <div class="card-body">
                    <form id="config-form">
                        <div class="form-group">
                            <label>Display Name</label>
                            <input type="text" id="display-name" name="display_name" placeholder="e.g., Reception Mac Pro">
                        </div>
                        <div class="form-group">
                            <label>Server URL</label>
                            <input type="url" id="server-url" name="nightline_server_url">
                        </div>
                        <div class="form-group">
                            <label>Client ID</label>
                            <input type="text" id="client-id" name="nightline_client_id" class="mono">
                        </div>
                        <div class="form-group">
                            <label>Webhook Secret</label>
                            <input type="text" id="webhook-secret" name="webhook_secret" class="mono">
                        </div>
                        <button type="submit" class="btn btn-primary">Save & Restart</button>
                    </form>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">Bridge Control</div>
                <div class="card-body">
                    <div class="control-status" id="control-status">
                        <div class="control-indicator">
                            <span class="status-dot" id="control-dot"></span>
                            <span id="control-mode">Loading...</span>
                        </div>
                        <div class="control-queue" id="control-queue">
                            <span class="queue-badge" id="outbound-queue-badge">0</span>
                            <span>outbound queued</span>
                        </div>
                    </div>
                    <div class="action-group">
                        <div class="action-label">Pause Mode</div>
                        <div class="action-buttons">
                            <button class="btn" id="btn-pause-outbound" onclick="pauseBridge('outbound')">
                                Pause Outbound
                            </button>
                            <button class="btn" id="btn-pause-inbound" onclick="pauseBridge('inbound')">
                                Pause All
                            </button>
                            <button class="btn btn-primary" id="btn-resume" onclick="resumeBridge()">
                                Resume
                            </button>
                        </div>
                    </div>
                    <div class="action-group">
                        <div class="action-label">Queue</div>
                        <div class="action-buttons">
                            <button class="btn" id="btn-clear-queue" onclick="clearQueue()">Clear Outbound Queue</button>
                            <button class="btn" onclick="viewQueue()">View Queue</button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">Actions</div>
                <div class="card-body">
                    <div class="action-group">
                        <div class="action-label">Services</div>
                        <div class="action-buttons">
                            <button class="btn" onclick="restartService('bridge')">Restart Bridge</button>
                            <button class="btn" onclick="restartService('tunnel-bridge')">Restart Tunnel</button>
                            <button class="btn" onclick="restartService('management')">Restart Management</button>
                        </div>
                    </div>
                    <div class="action-group">
                        <div class="action-label">Software</div>
                        <div class="update-row">
                            <div class="update-status" id="update-status">
                                <span class="spinner"></span>
                                <span>Checking...</span>
                            </div>
                            <button class="btn" id="update-btn" style="display: none;">Update</button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card logs-card">
                <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <span>Logs</span>
                    <div class="log-tabs">
                        <button class="log-tab active" data-log="bridge">Bridge</button>
                        <button class="log-tab" data-log="tunnel">Tunnel</button>
                        <button class="log-tab" data-log="updater">Updater</button>
                        <button class="log-tab" data-log="management">Management</button>
                    </div>
                </div>
                <div class="card-body">
                    <div class="logs" id="logs"></div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Auth is handled via httponly cookie - sent automatically with requests
        const headers = {};
        
        let currentLog = 'bridge';
        let logWs = null;
        
        async function loadStatus() {
            try {
                const res = await fetch('/health', { credentials: 'same-origin' });
                const data = await res.json();
                
                // Update health bar indicators
                const setHealth = (id, ok) => {
                    const el = document.getElementById(id);
                    el.className = 'status-dot' + (ok ? '' : ' offline');
                };
                
                // Bridge service running
                setHealth('h-bridge', data.services?.bridge);
                
                // Nightline connection
                const nightlineOk = data.bridge_health?.nightline?.connected;
                setHealth('h-nightline', nightlineOk);
                
                // Chat.db access  
                const chatDbOk = data.bridge_health?.watcher?.chat_db_accessible;
                setHealth('h-chatdb', chatDbOk);
                
                // Tunnel running
                setHealth('h-tunnel', data.services?.['tunnel-bridge']);
                
                // Queue size
                const queueSize = data.bridge_health?.queue?.size || 0;
                const queueBadge = document.querySelector('.queue-badge');
                queueBadge.textContent = queueSize;
                queueBadge.className = 'queue-badge' + (queueSize > 10 ? ' warning' : '');
                
                // Update services list
                const svcContainer = document.getElementById('services');
                const svcNames = { 
                    bridge: 'Bridge Server', 
                    'tunnel-bridge': 'Bridge Tunnel',
                    'tunnel-manage': 'Management Tunnel',
                    updater: 'Auto Updater' 
                };
                
                svcContainer.innerHTML = Object.entries(data.services)
                    .filter(([k]) => k !== 'management')
                    .map(([name, running]) => `
                        <div class="service-item">
                            <div class="service-info">
                                <span class="status-dot ${running ? '' : 'offline'}"></span>
                                <div>
                                    <div class="service-name">${svcNames[name] || name}</div>
                                    <div class="service-status">${running ? 'Running' : 'Stopped'}</div>
                                </div>
                            </div>
                            <button class="btn" onclick="restartService('${name}')">Restart</button>
                        </div>
                    `).join('');
                    
            } catch (e) {
                console.error('Status load failed:', e);
            }
        }
        
        async function loadConfig() {
            try {
                const res = await fetch('/api/config', { credentials: 'same-origin' });
                const data = await res.json();
                
                // Update header with display name and identifier
                const displayName = data.config.display_name || 'iPhone Bridge';
                const clientId = data.config.nightline_client_id || '';
                
                document.getElementById('bridge-name').textContent = displayName;
                document.getElementById('bridge-id').textContent = clientId 
                    ? `bridge-${clientId.substring(0, 8)}` 
                    : 'Not configured';
                
                // Update form fields
                document.getElementById('display-name').value = data.config.display_name || '';
                document.getElementById('server-url').value = data.config.nightline_server_url || '';
                document.getElementById('client-id').value = data.config.nightline_client_id || '';
                document.getElementById('webhook-secret').value = data.config.webhook_secret || '';
                
                const tunnelUrl = data.tunnel_url || 'Not configured';
                const urlEl = document.getElementById('tunnel-url');
                urlEl.textContent = tunnelUrl;
                urlEl.href = tunnelUrl.startsWith('http') ? tunnelUrl : '#';
            } catch (e) {
                console.error('Config load failed:', e);
            }
        }
        
        function copyIdentifier() {
            const idEl = document.getElementById('bridge-id');
            navigator.clipboard.writeText(idEl.textContent);
            showToast('Identifier copied', 'success');
        }
        
        async function restartService(name) {
            if (name === 'management') {
                if (!confirm('This will restart the management agent. You may need to refresh the page. Continue?')) {
                    return;
                }
            }
            
            try {
                const res = await fetch(`/api/services/${name}/restart`, { method: 'POST', credentials: 'same-origin' });
                const data = await res.json();
                showToast(data.message, data.success ? 'success' : 'error');
                
                if (name === 'management' && data.success) {
                    showToast('Reconnecting...', 'success');
                    setTimeout(() => window.location.reload(), 3000);
                } else {
                    setTimeout(loadStatus, 2000);
                }
            } catch (e) {
                showToast('Failed to restart', 'error');
            }
        }
        
        async function checkBridgeHealth() {
            try {
                const res = await fetch('http://localhost:8080/health');
                const data = await res.json();
                showToast(`Bridge: ${data.status}`, data.status === 'healthy' ? 'success' : 'error');
            } catch (e) {
                showToast('Bridge unreachable', 'error');
            }
        }
        
        async function checkForUpdates() {
            const status = document.getElementById('update-status');
            const btn = document.getElementById('update-btn');
            
            status.className = 'update-status';
            status.innerHTML = '<span class="spinner"></span><span>Checking for updates...</span>';
            btn.style.display = 'none';
            
            try {
                const res = await fetch('/api/update', { credentials: 'same-origin' });
                const data = await res.json();
                
                if (data.has_updates) {
                    status.className = 'update-status has-update';
                    status.innerHTML = `Update available <span class="version">${data.current_commit} → ${data.remote_commit}</span>`;
                    btn.style.display = 'inline-block';
                    btn.textContent = 'Update Now';
                    btn.className = 'btn btn-primary';
                    btn.disabled = false;
                    btn.onclick = performUpdate;
                } else {
                    status.className = 'update-status up-to-date';
                    status.innerHTML = `Up to date <span class="version">${data.current_commit}</span>`;
                    btn.style.display = 'inline-block';
                    btn.textContent = 'Check';
                    btn.className = 'btn';
                    btn.disabled = false;
                    btn.onclick = checkForUpdates;
                }
            } catch (e) {
                status.className = 'update-status';
                status.innerHTML = 'Failed to check for updates';
                btn.style.display = 'block';
                btn.textContent = 'Retry';
                btn.onclick = checkForUpdates;
            }
        }
        
        async function performUpdate() {
            const status = document.getElementById('update-status');
            const btn = document.getElementById('update-btn');
            
            status.className = 'update-status';
            status.innerHTML = '<span class="spinner"></span><span>Updating...</span>';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/update', { method: 'POST', credentials: 'same-origin' });
                const data = await res.json();
                
                if (data.success) {
                    status.innerHTML = '<span class="spinner"></span><span>Restarting services...</span>';
                    setTimeout(() => window.location.reload(), 5000);
                } else {
                    status.innerHTML = 'Update failed';
                    btn.disabled = false;
                    btn.textContent = 'Retry';
                }
            } catch (e) {
                status.innerHTML = 'Update failed';
                btn.disabled = false;
                btn.textContent = 'Retry';
            }
        }
        
        document.getElementById('config-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const update = {
                display_name: document.getElementById('display-name').value,
                nightline_server_url: document.getElementById('server-url').value,
                nightline_client_id: document.getElementById('client-id').value,
                webhook_secret: document.getElementById('webhook-secret').value,
            };
            
            try {
                const res = await fetch('/api/config', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(update),
                });
                const data = await res.json();
                
                if (data.success) {
                    // Update header immediately with new display name
                    if (update.display_name) {
                        document.getElementById('bridge-name').textContent = update.display_name;
                    }
                    showToast('Config saved. Restarting bridge...', 'success');
                    await restartService('bridge');
                } else {
                    showToast(data.detail || 'Failed to save', 'error');
                }
            } catch (e) {
                showToast('Failed to save config', 'error');
            }
        });
        
        function connectLogs(logName) {
            if (logWs) logWs.close();
            
            const container = document.getElementById('logs');
            container.innerHTML = '<div class="log-line">Connecting...</div>';
            
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            logWs = new WebSocket(`${protocol}//${window.location.host}/api/logs/ws/${logName}`);
            
            logWs.onopen = () => { container.innerHTML = ''; };
            
            logWs.onmessage = (event) => {
                const line = document.createElement('div');
                line.className = 'log-line';
                if (event.data.includes('ERROR')) line.classList.add('error');
                else if (event.data.includes('WARNING')) line.classList.add('warning');
                line.textContent = event.data;
                container.appendChild(line);
                container.scrollTop = container.scrollHeight;
                while (container.children.length > 500) container.removeChild(container.firstChild);
            };
            
            logWs.onclose = () => {
                setTimeout(() => connectLogs(currentLog), 3000);
            };
        }
        
        document.querySelectorAll('.log-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.log-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                currentLog = tab.dataset.log;
                connectLogs(currentLog);
            });
        });
        
        function copyUrl(id) {
            const text = document.getElementById(id).textContent;
            navigator.clipboard.writeText(text);
            showToast('Copied', 'success');
        }
        
        function showToast(message, type = 'success') {
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        
        // ============================================
        // Bridge Control Functions
        // ============================================
        
        let controlState = {
            pause_inbound: false,
            pause_outbound: false,
            outbound_queue_size: 0,
        };
        
        async function loadControlStatus() {
            try {
                const res = await fetch('/api/control/status', { credentials: 'same-origin' });
                if (res.ok) {
                    const data = await res.json();
                    controlState = data;
                    updateControlUI();
                }
            } catch (e) {
                console.error('Failed to load control status:', e);
            }
        }
        
        function updateControlUI() {
            const dot = document.getElementById('control-dot');
            const mode = document.getElementById('control-mode');
            const queueBadge = document.getElementById('outbound-queue-badge');
            const btnPauseOutbound = document.getElementById('btn-pause-outbound');
            const btnPauseInbound = document.getElementById('btn-pause-inbound');
            const btnResume = document.getElementById('btn-resume');
            const btnClearQueue = document.getElementById('btn-clear-queue');
            
            // Update queue badge
            queueBadge.textContent = controlState.outbound_queue_size;
            queueBadge.className = 'queue-badge' + (controlState.outbound_queue_size > 0 ? ' warning' : '');
            
            // Update status indicator
            if (controlState.pause_inbound) {
                dot.className = 'status-dot paused';
                mode.textContent = 'Paused (All)';
                btnPauseInbound.classList.add('active');
                btnPauseOutbound.classList.remove('active');
            } else if (controlState.pause_outbound) {
                dot.className = 'status-dot paused';
                mode.textContent = 'Paused (Outbound)';
                btnPauseOutbound.classList.add('active');
                btnPauseInbound.classList.remove('active');
            } else {
                dot.className = 'status-dot';
                mode.textContent = 'Running';
                btnPauseOutbound.classList.remove('active');
                btnPauseInbound.classList.remove('active');
            }
            
            // Enable/disable buttons
            btnResume.disabled = !controlState.pause_inbound && !controlState.pause_outbound;
            btnClearQueue.disabled = controlState.outbound_queue_size === 0;
        }
        
        async function pauseBridge(type) {
            const payload = {
                pause_inbound: type === 'inbound',
                pause_outbound: type === 'outbound' || type === 'inbound',
            };
            
            try {
                const res = await fetch('/api/control/pause', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(payload),
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    controlState = {
                        ...controlState,
                        pause_inbound: data.pause_inbound,
                        pause_outbound: data.pause_outbound,
                        outbound_queue_size: data.outbound_queue_size,
                    };
                    updateControlUI();
                    showToast(data.message, 'success');
                } else {
                    showToast(data.detail || 'Failed to pause', 'error');
                }
            } catch (e) {
                showToast('Failed to pause bridge', 'error');
            }
        }
        
        async function resumeBridge() {
            const sendQueued = controlState.outbound_queue_size > 0 
                ? confirm(`Send ${controlState.outbound_queue_size} queued messages?`)
                : true;
            
            try {
                const res = await fetch(`/api/control/resume?send_queued=${sendQueued}`, {
                    method: 'POST',
                    credentials: 'same-origin',
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    controlState = {
                        ...controlState,
                        pause_inbound: data.pause_inbound,
                        pause_outbound: data.pause_outbound,
                        outbound_queue_size: data.outbound_queue_size,
                    };
                    updateControlUI();
                    showToast(data.message, 'success');
                } else {
                    showToast(data.detail || 'Failed to resume', 'error');
                }
            } catch (e) {
                showToast('Failed to resume bridge', 'error');
            }
        }
        
        async function clearQueue() {
            if (!confirm('Clear all queued messages without sending? This cannot be undone.')) {
                return;
            }
            
            try {
                const res = await fetch('/api/control/clear-queue', {
                    method: 'POST',
                    credentials: 'same-origin',
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    controlState.outbound_queue_size = 0;
                    updateControlUI();
                    showToast(data.message, 'success');
                } else {
                    showToast(data.detail || 'Failed to clear queue', 'error');
                }
            } catch (e) {
                showToast('Failed to clear queue', 'error');
            }
        }
        
        async function viewQueue() {
            try {
                const res = await fetch('/api/control/status', { credentials: 'same-origin' });
                const data = await res.json();
                
                // Create modal
                const overlay = document.createElement('div');
                overlay.className = 'modal-overlay';
                overlay.onclick = (e) => {
                    if (e.target === overlay) overlay.remove();
                };
                
                const queueItems = data.outbound_queue.length > 0
                    ? data.outbound_queue.map(item => `
                        <div class="queue-item">
                            <div class="queue-item-header">
                                <span>To: ${item.phone}</span>
                                <span>${new Date(item.queued_at * 1000).toLocaleTimeString()}</span>
                            </div>
                            <div class="queue-item-text">${escapeHtml(item.text_preview)}</div>
                        </div>
                    `).join('')
                    : '<div class="empty-queue">No messages in queue</div>';
                
                overlay.innerHTML = `
                    <div class="modal">
                        <div class="modal-header">
                            <h3>Outbound Queue (${data.outbound_queue.length})</h3>
                            <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">×</button>
                        </div>
                        <div class="modal-body">
                            ${queueItems}
                        </div>
                    </div>
                `;
                
                document.body.appendChild(overlay);
            } catch (e) {
                showToast('Failed to load queue', 'error');
            }
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // ============================================
        // Init
        // ============================================
        loadStatus();
        loadConfig();
        loadControlStatus();
        checkForUpdates();
        connectLogs(currentLog);
        setInterval(loadStatus, 10000);
        setInterval(loadControlStatus, 5000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve dashboard UI."""
    # Check for session cookie
    token = request.cookies.get(settings.cookie_name)
    
    if not token or not verify_token(token):
        return RedirectResponse(url="/login", status_code=303)
    
    return DASHBOARD_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "management.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
