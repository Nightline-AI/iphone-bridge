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
from management.routes import services, config, logs, health, update

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
        <h1>🔐 iPhone Bridge</h1>
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
        
        header h1 {
            font-size: 1.5rem;
            font-weight: 600;
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
        
        .update-section {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border);
        }
        
        .update-info {
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .update-available {
            color: var(--yellow);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📱 iPhone Bridge</h1>
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
                <div class="card-header">Actions</div>
                <div class="card-body">
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem;">
                        <button class="btn" onclick="restartService('bridge')">Restart Bridge</button>
                        <button class="btn" onclick="restartService('tunnel-bridge')">Restart Tunnel</button>
                    </div>
                    <div class="update-section">
                        <div class="update-info" id="update-info">
                            <span class="mono" id="current-version">...</span>
                        </div>
                        <button class="btn btn-primary" id="update-btn" onclick="performUpdate()">
                            Check for Updates
                        </button>
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
        
        async function restartService(name) {
            try {
                const res = await fetch(`/api/services/${name}/restart`, { method: 'POST', credentials: 'same-origin' });
                const data = await res.json();
                showToast(data.message, data.success ? 'success' : 'error');
                setTimeout(loadStatus, 2000);
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
            try {
                const res = await fetch('/api/update', { credentials: 'same-origin' });
                const data = await res.json();
                
                const info = document.getElementById('update-info');
                const btn = document.getElementById('update-btn');
                
                if (data.has_updates) {
                    info.innerHTML = `<span class="update-available">Update available: ${data.current_commit} → ${data.remote_commit}</span>`;
                    btn.textContent = 'Update Now';
                    btn.onclick = performUpdate;
                } else {
                    info.innerHTML = `<span class="mono">${data.current_commit}</span> (${data.current_branch})`;
                    btn.textContent = 'Check for Updates';
                    btn.onclick = checkForUpdates;
                }
            } catch (e) {
                console.error('Update check failed:', e);
            }
        }
        
        async function performUpdate() {
            const btn = document.getElementById('update-btn');
            btn.disabled = true;
            btn.textContent = 'Updating...';
            
            try {
                const res = await fetch('/api/update', { method: 'POST', credentials: 'same-origin' });
                const data = await res.json();
                
                if (data.success) {
                    showToast('Updating... page will reload', 'success');
                    setTimeout(() => window.location.reload(), 5000);
                } else {
                    showToast('Update failed', 'error');
                    btn.disabled = false;
                    btn.textContent = 'Retry Update';
                }
            } catch (e) {
                showToast('Update failed', 'error');
                btn.disabled = false;
                btn.textContent = 'Retry Update';
            }
        }
        
        document.getElementById('config-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const update = {
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
        
        // Init
        loadStatus();
        loadConfig();
        checkForUpdates();
        connectLogs(currentLog);
        setInterval(loadStatus, 10000);
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
