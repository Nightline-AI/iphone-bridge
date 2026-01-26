"""
iPhone Bridge Dashboard
Local web UI for configuration, logs, and monitoring
"""

import os
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Paths
INSTALL_DIR = Path.home() / "iphone-bridge"
ENV_FILE = INSTALL_DIR / ".env"
LOG_DIR = Path("/var/log/iphone-bridge")


class ConfigUpdate(BaseModel):
    nightline_server_url: str
    nightline_client_id: str
    webhook_secret: str


def read_env() -> dict:
    """Read current .env configuration."""
    config = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    return config


def write_env(updates: dict):
    """Update .env file with new values."""
    lines = []
    existing_keys = set()
    
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    existing_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)
    
    # Add any new keys
    for key, value in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")
    
    ENV_FILE.write_text("\n".join(lines) + "\n")


def get_tunnel_url() -> str | None:
    """Get the current tunnel URL from config."""
    config = read_env()
    client_id = config.get("NIGHTLINE_CLIENT_ID", "")
    if client_id:
        return f"https://bridge-{client_id}.nightline.app"
    return None


def get_service_status(service_name: str) -> dict:
    """Check if a launchd service is running."""
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True
        )
        running = service_name in result.stdout
        return {"running": running, "name": service_name}
    except:
        return {"running": False, "name": service_name}


def get_last_log_lines(log_file: str, n: int = 50) -> list[str]:
    """Get last N lines from a log file."""
    log_path = LOG_DIR / log_file
    if not log_path.exists():
        return []
    try:
        result = subprocess.run(
            ["tail", "-n", str(n), str(log_path)],
            capture_output=True,
            text=True
        )
        return result.stdout.splitlines()
    except:
        return []


@router.get("/api/config")
async def get_config():
    """Get current configuration."""
    config = read_env()
    return {
        "nightline_server_url": config.get("NIGHTLINE_SERVER_URL", ""),
        "nightline_client_id": config.get("NIGHTLINE_CLIENT_ID", ""),
        "webhook_secret": config.get("WEBHOOK_SECRET", ""),
        "tunnel_url": get_tunnel_url(),
    }


@router.post("/api/config")
async def update_config(config: ConfigUpdate):
    """Update configuration and restart services."""
    write_env({
        "NIGHTLINE_SERVER_URL": config.nightline_server_url,
        "NIGHTLINE_CLIENT_ID": config.nightline_client_id,
        "WEBHOOK_SECRET": config.webhook_secret,
    })
    
    # Restart the bridge service
    subprocess.run([
        "launchctl", "kickstart", "-k",
        f"gui/{os.getuid()}/com.nightline.iphone-bridge"
    ], capture_output=True)
    
    return {"success": True, "message": "Configuration saved. Bridge restarting..."}


@router.get("/api/status")
async def get_status():
    """Get full system status."""
    return {
        "services": {
            "bridge": get_service_status("com.nightline.iphone-bridge"),
            "tunnel": get_service_status("com.nightline.cloudflare-tunnel"),
            "updater": get_service_status("com.nightline.iphone-bridge-updater"),
        },
        "tunnel_url": get_tunnel_url(),
        "config": read_env(),
    }


@router.get("/api/logs/{log_name}")
async def get_logs(log_name: str, lines: int = 100):
    """Get recent log lines."""
    valid_logs = ["bridge.log", "tunnel.log", "updater.log"]
    if log_name not in valid_logs:
        raise HTTPException(status_code=400, detail=f"Invalid log. Use: {valid_logs}")
    
    return {"lines": get_last_log_lines(log_name, lines)}


@router.post("/api/restart/{service}")
async def restart_service(service: str):
    """Restart a service."""
    services = {
        "bridge": "com.nightline.iphone-bridge",
        "tunnel": "com.nightline.cloudflare-tunnel",
        "updater": "com.nightline.iphone-bridge-updater",
    }
    
    if service not in services:
        raise HTTPException(status_code=400, detail=f"Invalid service. Use: {list(services.keys())}")
    
    service_name = services[service]
    subprocess.run([
        "launchctl", "kickstart", "-k",
        f"gui/{os.getuid()}/{service_name}"
    ], capture_output=True)
    
    return {"success": True, "message": f"{service} restarting..."}


@router.websocket("/ws/logs/{log_name}")
async def websocket_logs(websocket: WebSocket, log_name: str):
    """Stream logs via WebSocket."""
    await websocket.accept()
    
    valid_logs = ["bridge.log", "tunnel.log", "updater.log"]
    if log_name not in valid_logs:
        await websocket.close(code=4000)
        return
    
    log_path = LOG_DIR / log_name
    
    try:
        # Start tail -f process
        process = await asyncio.create_subprocess_exec(
            "tail", "-f", str(log_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        while True:
            line = await process.stdout.readline()
            if line:
                await websocket.send_text(line.decode().rstrip())
            else:
                await asyncio.sleep(0.1)
                
    except WebSocketDisconnect:
        process.terminate()
    except Exception as e:
        await websocket.close(code=4001)


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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 3rem 2rem;
        }
        
        header {
            margin-bottom: 3rem;
        }
        
        header h1 {
            font-size: 1.875rem;
            font-weight: 600;
            letter-spacing: -0.025em;
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-muted);
            font-size: 0.9375rem;
        }
        
        .status-bar {
            display: flex;
            gap: 1.5rem;
            margin-top: 1.5rem;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
            color: var(--text-secondary);
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
        }
        
        .status-dot.offline { background: var(--red); }
        
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }
        
        @media (max-width: 900px) {
            .grid { grid-template-columns: 1fr; }
        }
        
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
        }
        
        .card-header {
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .card-header h2 {
            font-size: 0.9375rem;
            font-weight: 500;
            color: var(--text);
        }
        
        .card-body {
            padding: 1.5rem;
        }
        
        .url-box {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem 1.25rem;
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 0.875rem;
            color: var(--accent);
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
        }
        
        .url-box a {
            color: inherit;
            text-decoration: none;
        }
        
        .url-box a:hover {
            text-decoration: underline;
        }
        
        .help-text {
            font-size: 0.8125rem;
            color: var(--text-muted);
        }
        
        .form-group {
            margin-bottom: 1.25rem;
        }
        
        .form-group:last-of-type {
            margin-bottom: 1.5rem;
        }
        
        label {
            display: block;
            font-size: 0.8125rem;
            font-weight: 500;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }
        
        input {
            width: 100%;
            padding: 0.625rem 0.875rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            font-family: inherit;
            font-size: 0.875rem;
            transition: border-color 0.15s;
        }
        
        input:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        input.mono {
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            font-family: inherit;
            font-size: 0.8125rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.15s;
        }
        
        .btn:hover { background: var(--accent-hover); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .btn-ghost {
            background: transparent;
            color: var(--text-secondary);
            border: 1px solid var(--border);
        }
        
        .btn-ghost:hover {
            background: var(--surface-2);
            color: var(--text);
        }
        
        .btn-sm {
            padding: 0.375rem 0.75rem;
            font-size: 0.75rem;
        }
        
        .services {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }
        
        .service-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 1rem;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
        }
        
        .service-info {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .service-name {
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        .service-status {
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        
        .logs-card {
            grid-column: 1 / -1;
        }
        
        .tabs {
            display: flex;
            gap: 0.25rem;
        }
        
        .tab {
            padding: 0.375rem 0.875rem;
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-family: inherit;
            font-size: 0.8125rem;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.15s;
        }
        
        .tab:hover { color: var(--text-secondary); }
        
        .tab.active {
            background: var(--surface-2);
            color: var(--text);
        }
        
        .logs {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            height: 320px;
            overflow-y: auto;
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 0.75rem;
            line-height: 1.7;
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
            padding: 0.75rem 1.25rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 0.875rem;
            animation: slideIn 0.2s ease;
            z-index: 1000;
        }
        
        .toast.success { border-color: var(--green); }
        .toast.error { border-color: var(--red); }
        
        @keyframes slideIn {
            from { transform: translateY(0.5rem); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        .copy-btn {
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 0.75rem;
            padding: 0.25rem 0.5rem;
        }
        
        .copy-btn:hover { color: var(--text); }
        
        .actions {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>iPhone Bridge</h1>
            <p class="subtitle">iMessage relay service</p>
            <div class="status-bar">
                <div class="status-item">
                    <span class="status-dot" id="bridge-dot"></span>
                    <span>Bridge</span>
                </div>
                <div class="status-item">
                    <span class="status-dot" id="tunnel-dot"></span>
                    <span>Tunnel</span>
                </div>
                <div class="status-item">
                    <span class="status-dot" id="updater-dot"></span>
                    <span>Auto-update</span>
                </div>
            </div>
        </header>
        
        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <h2>Public URL</h2>
                    <button class="copy-btn" onclick="copyUrl()">Copy</button>
                </div>
                <div class="card-body">
                    <div class="url-box">
                        <a href="#" id="tunnel-url" target="_blank">Loading...</a>
                    </div>
                    <p class="help-text">Use this URL in your Nightline dashboard</p>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h2>Services</h2>
                </div>
                <div class="card-body">
                    <div class="services" id="services-list"></div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h2>Configuration</h2>
                </div>
                <div class="card-body">
                    <form id="config-form">
                        <div class="form-group">
                            <label>Server URL</label>
                            <input type="url" id="server-url" placeholder="https://api.nightline.net">
                        </div>
                        <div class="form-group">
                            <label>Client ID</label>
                            <input type="text" id="client-id" class="mono">
                        </div>
                        <div class="form-group">
                            <label>Webhook Secret</label>
                            <input type="text" id="webhook-secret" class="mono">
                        </div>
                        <button type="submit" class="btn">Save & Restart</button>
                    </form>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h2>Actions</h2>
                </div>
                <div class="card-body">
                    <div class="actions">
                        <button class="btn btn-ghost" onclick="restartService('bridge')">Restart Bridge</button>
                        <button class="btn btn-ghost" onclick="restartService('tunnel')">Restart Tunnel</button>
                        <button class="btn btn-ghost" onclick="checkHealth()">Health Check</button>
                    </div>
                </div>
            </div>
            
            <div class="card logs-card">
                <div class="card-header">
                    <h2>Logs</h2>
                    <div class="tabs">
                        <button class="tab active" data-log="bridge.log">Bridge</button>
                        <button class="tab" data-log="tunnel.log">Tunnel</button>
                        <button class="tab" data-log="updater.log">Updater</button>
                    </div>
                </div>
                <div class="card-body">
                    <div class="logs" id="logs-container">
                        <div class="log-line">Connecting...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentLog = 'bridge.log';
        let ws = null;
        
        async function loadData() {
            try {
                const configRes = await fetch('/dashboard/api/config');
                const config = await configRes.json();
                
                document.getElementById('server-url').value = config.nightline_server_url || '';
                document.getElementById('client-id').value = config.nightline_client_id || '';
                document.getElementById('webhook-secret').value = config.webhook_secret || '';
                
                const tunnelUrl = config.tunnel_url || 'Not configured';
                const urlEl = document.getElementById('tunnel-url');
                urlEl.textContent = tunnelUrl;
                urlEl.href = tunnelUrl.startsWith('http') ? tunnelUrl : '#';
                
                const statusRes = await fetch('/dashboard/api/status');
                const status = await statusRes.json();
                
                updateServices(status.services);
                
            } catch (e) {
                console.error('Failed to load:', e);
            }
        }
        
        function updateServices(services) {
            const container = document.getElementById('services-list');
            const names = {
                bridge: 'Bridge Server',
                tunnel: 'Cloudflare Tunnel',
                updater: 'Auto Updater',
            };
            
            container.innerHTML = Object.entries(services).map(([key, svc]) => `
                <div class="service-row">
                    <div class="service-info">
                        <span class="status-dot ${svc.running ? '' : 'offline'}"></span>
                        <div>
                            <div class="service-name">${names[key] || key}</div>
                            <div class="service-status">${svc.running ? 'Running' : 'Stopped'}</div>
                        </div>
                    </div>
                    <button class="btn btn-ghost btn-sm" onclick="restartService('${key}')">Restart</button>
                </div>
            `).join('');
            
            document.getElementById('bridge-dot').className = 'status-dot' + (services.bridge?.running ? '' : ' offline');
            document.getElementById('tunnel-dot').className = 'status-dot' + (services.tunnel?.running ? '' : ' offline');
            document.getElementById('updater-dot').className = 'status-dot' + (services.updater?.running ? '' : ' offline');
        }
        
        function connectLogs(logName) {
            if (ws) ws.close();
            
            const container = document.getElementById('logs-container');
            container.innerHTML = '<div class="log-line">Connecting...</div>';
            
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/dashboard/ws/logs/${logName}`);
            
            ws.onopen = () => { container.innerHTML = ''; };
            
            ws.onmessage = (event) => {
                const line = document.createElement('div');
                line.className = 'log-line';
                if (event.data.includes('ERROR')) line.classList.add('error');
                else if (event.data.includes('WARNING')) line.classList.add('warning');
                line.textContent = event.data;
                container.appendChild(line);
                container.scrollTop = container.scrollHeight;
                while (container.children.length > 500) container.removeChild(container.firstChild);
            };
            
            ws.onclose = () => { setTimeout(() => connectLogs(currentLog), 2000); };
        }
        
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                currentLog = tab.dataset.log;
                connectLogs(currentLog);
            });
        });
        
        document.getElementById('config-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            try {
                const res = await fetch('/dashboard/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        nightline_server_url: document.getElementById('server-url').value,
                        nightline_client_id: document.getElementById('client-id').value,
                        webhook_secret: document.getElementById('webhook-secret').value,
                    })
                });
                
                const result = await res.json();
                showToast(result.message, 'success');
                setTimeout(loadData, 2000);
            } catch (e) {
                showToast('Failed to save', 'error');
            }
        });
        
        async function restartService(service) {
            try {
                await fetch(`/dashboard/api/restart/${service}`, { method: 'POST' });
                showToast('Restarting...', 'success');
                setTimeout(loadData, 2000);
            } catch (e) {
                showToast('Failed', 'error');
            }
        }
        
        async function checkHealth() {
            try {
                const res = await fetch('/health');
                const data = await res.json();
                showToast(`Status: ${data.status}`, data.status === 'healthy' ? 'success' : 'error');
            } catch (e) {
                showToast('Health check failed', 'error');
            }
        }
        
        function copyUrl() {
            const url = document.getElementById('tunnel-url').textContent;
            navigator.clipboard.writeText(url);
            showToast('Copied', 'success');
        }
        
        function showToast(message, type = 'success') {
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        
        loadData();
        connectLogs(currentLog);
        setInterval(loadData, 10000);
    </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard UI."""
    return DASHBOARD_HTML
