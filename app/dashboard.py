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
    <title>iPhone Bridge Dashboard</title>
    <style>
        :root {
            --bg: #0c0c0f;
            --surface: #16161c;
            --surface-2: #1c1c24;
            --border: #2a2a35;
            --text: #e4e4e7;
            --text-dim: #71717a;
            --accent: #22d3ee;
            --accent-dim: #0891b2;
            --green: #22c55e;
            --red: #ef4444;
            --yellow: #eab308;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'SF Pro Text', -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
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
        
        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .logo-icon {
            font-size: 2rem;
        }
        
        .logo h1 {
            font-size: 1.5rem;
            font-weight: 600;
            background: linear-gradient(135deg, var(--accent), #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .status-badges {
            display: flex;
            gap: 0.75rem;
        }
        
        .badge {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 9999px;
            font-size: 0.8rem;
        }
        
        .badge .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
        }
        
        .badge .dot.error { background: var(--red); }
        .badge .dot.warning { background: var(--yellow); }
        
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }
        
        @media (max-width: 1000px) {
            .grid { grid-template-columns: 1fr; }
        }
        
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }
        
        .card-header {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .card-header h2 {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .card-body {
            padding: 1.25rem;
        }
        
        .url-display {
            background: var(--surface-2);
            padding: 1rem;
            border-radius: 8px;
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 0.9rem;
            color: var(--accent);
            word-break: break-all;
            margin-bottom: 1rem;
        }
        
        .url-display a {
            color: inherit;
            text-decoration: none;
        }
        
        .url-display a:hover {
            text-decoration: underline;
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        label {
            display: block;
            font-size: 0.75rem;
            font-weight: 500;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }
        
        input, select {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-family: inherit;
            font-size: 0.9rem;
            transition: border-color 0.2s;
        }
        
        input:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        input.mono {
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 0.85rem;
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.65rem 1.25rem;
            background: var(--accent);
            color: var(--bg);
            border: none;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .btn:hover { background: var(--accent-dim); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .btn-secondary {
            background: var(--surface-2);
            color: var(--text);
            border: 1px solid var(--border);
        }
        
        .btn-secondary:hover {
            background: var(--border);
        }
        
        .btn-sm {
            padding: 0.4rem 0.75rem;
            font-size: 0.75rem;
        }
        
        .logs {
            background: #0a0a0c;
            border-radius: 8px;
            padding: 1rem;
            height: 350px;
            overflow-y: auto;
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 0.75rem;
            line-height: 1.6;
        }
        
        .log-line {
            white-space: pre-wrap;
            word-break: break-all;
        }
        
        .log-line.error { color: var(--red); }
        .log-line.warning { color: var(--yellow); }
        .log-line.info { color: var(--text-dim); }
        
        .tabs {
            display: flex;
            gap: 0.25rem;
            margin-bottom: 1rem;
        }
        
        .tab {
            padding: 0.5rem 1rem;
            background: transparent;
            border: none;
            color: var(--text-dim);
            font-family: inherit;
            font-size: 0.8rem;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.2s;
        }
        
        .tab:hover { color: var(--text); }
        .tab.active {
            background: var(--surface-2);
            color: var(--accent);
        }
        
        .services {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }
        
        .service {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 1rem;
            background: var(--surface-2);
            border-radius: 8px;
        }
        
        .service-info {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .service-status {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--green);
        }
        
        .service-status.stopped { background: var(--red); }
        
        .toast {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            padding: 1rem 1.5rem;
            background: var(--surface);
            border: 1px solid var(--green);
            border-radius: 8px;
            animation: slideIn 0.3s ease;
        }
        
        .toast.error { border-color: var(--red); }
        
        @keyframes slideIn {
            from { transform: translateY(1rem); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        .copy-btn {
            background: none;
            border: none;
            color: var(--text-dim);
            cursor: pointer;
            padding: 0.25rem;
        }
        
        .copy-btn:hover { color: var(--accent); }
        
        .full-width { grid-column: 1 / -1; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <span class="logo-icon">📱</span>
                <h1>iPhone Bridge</h1>
            </div>
            <div class="status-badges">
                <div class="badge">
                    <span class="dot" id="bridge-status-dot"></span>
                    <span>Bridge</span>
                </div>
                <div class="badge">
                    <span class="dot" id="tunnel-status-dot"></span>
                    <span>Tunnel</span>
                </div>
            </div>
        </header>
        
        <div class="grid">
            <!-- Tunnel URL Card -->
            <div class="card">
                <div class="card-header">
                    <h2>🌐 Public URL</h2>
                    <button class="copy-btn" onclick="copyUrl()">📋 Copy</button>
                </div>
                <div class="card-body">
                    <div class="url-display">
                        <a href="#" id="tunnel-url" target="_blank">Loading...</a>
                    </div>
                    <p style="color: var(--text-dim); font-size: 0.8rem;">
                        Add this URL to your Nightline dashboard as the Bridge URL
                    </p>
                </div>
            </div>
            
            <!-- Services Card -->
            <div class="card">
                <div class="card-header">
                    <h2>⚡ Services</h2>
                </div>
                <div class="card-body">
                    <div class="services" id="services-list">
                        <!-- Populated by JS -->
                    </div>
                </div>
            </div>
            
            <!-- Configuration Card -->
            <div class="card">
                <div class="card-header">
                    <h2>⚙️ Configuration</h2>
                </div>
                <div class="card-body">
                    <form id="config-form">
                        <div class="form-group">
                            <label>Nightline Server URL</label>
                            <input type="url" id="server-url" placeholder="https://api.nightline.ai">
                        </div>
                        <div class="form-group">
                            <label>Client ID</label>
                            <input type="text" id="client-id" class="mono" placeholder="your-client-id">
                        </div>
                        <div class="form-group">
                            <label>Webhook Secret</label>
                            <input type="text" id="webhook-secret" class="mono" placeholder="your-secret">
                        </div>
                        <button type="submit" class="btn">💾 Save & Restart</button>
                    </form>
                </div>
            </div>
            
            <!-- Quick Actions Card -->
            <div class="card">
                <div class="card-header">
                    <h2>🔧 Quick Actions</h2>
                </div>
                <div class="card-body">
                    <div style="display: flex; flex-wrap: wrap; gap: 0.75rem;">
                        <button class="btn btn-secondary" onclick="restartService('bridge')">🔄 Restart Bridge</button>
                        <button class="btn btn-secondary" onclick="restartService('tunnel')">🔄 Restart Tunnel</button>
                        <button class="btn btn-secondary" onclick="checkHealth()">❤️ Health Check</button>
                        <button class="btn btn-secondary" onclick="forceUpdate()">⬆️ Force Update</button>
                    </div>
                </div>
            </div>
            
            <!-- Logs Card (Full Width) -->
            <div class="card full-width">
                <div class="card-header">
                    <h2>📋 Logs</h2>
                    <div class="tabs">
                        <button class="tab active" data-log="bridge.log">Bridge</button>
                        <button class="tab" data-log="tunnel.log">Tunnel</button>
                        <button class="tab" data-log="updater.log">Updater</button>
                    </div>
                </div>
                <div class="card-body">
                    <div class="logs" id="logs-container">
                        <div class="log-line info">Connecting to logs...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentLog = 'bridge.log';
        let ws = null;
        
        // Load initial data
        async function loadData() {
            try {
                // Load config
                const configRes = await fetch('/dashboard/api/config');
                const config = await configRes.json();
                
                document.getElementById('server-url').value = config.nightline_server_url || '';
                document.getElementById('client-id').value = config.nightline_client_id || '';
                document.getElementById('webhook-secret').value = config.webhook_secret || '';
                
                const tunnelUrl = config.tunnel_url || 'Not configured';
                const urlEl = document.getElementById('tunnel-url');
                urlEl.textContent = tunnelUrl;
                urlEl.href = tunnelUrl.startsWith('http') ? tunnelUrl : '#';
                
                // Load status
                const statusRes = await fetch('/dashboard/api/status');
                const status = await statusRes.json();
                
                updateServices(status.services);
                
            } catch (e) {
                console.error('Failed to load data:', e);
            }
        }
        
        function updateServices(services) {
            const container = document.getElementById('services-list');
            const serviceNames = {
                bridge: { name: 'Bridge Server', icon: '🖥️' },
                tunnel: { name: 'Cloudflare Tunnel', icon: '🌐' },
                updater: { name: 'Auto Updater', icon: '🔄' },
            };
            
            container.innerHTML = Object.entries(services).map(([key, svc]) => {
                const info = serviceNames[key] || { name: key, icon: '⚙️' };
                return `
                    <div class="service">
                        <div class="service-info">
                            <span class="service-status ${svc.running ? '' : 'stopped'}"></span>
                            <span>${info.icon} ${info.name}</span>
                        </div>
                        <button class="btn btn-secondary btn-sm" onclick="restartService('${key}')">Restart</button>
                    </div>
                `;
            }).join('');
            
            // Update header badges
            document.getElementById('bridge-status-dot').className = 
                'dot ' + (services.bridge?.running ? '' : 'error');
            document.getElementById('tunnel-status-dot').className = 
                'dot ' + (services.tunnel?.running ? '' : 'error');
        }
        
        // Connect to log websocket
        function connectLogs(logName) {
            if (ws) ws.close();
            
            const container = document.getElementById('logs-container');
            container.innerHTML = '<div class="log-line info">Connecting...</div>';
            
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/dashboard/ws/logs/${logName}`);
            
            ws.onopen = () => {
                container.innerHTML = '';
            };
            
            ws.onmessage = (event) => {
                const line = document.createElement('div');
                line.className = 'log-line';
                
                if (event.data.includes('ERROR')) line.classList.add('error');
                else if (event.data.includes('WARNING')) line.classList.add('warning');
                else if (event.data.includes('INFO')) line.classList.add('info');
                
                line.textContent = event.data;
                container.appendChild(line);
                container.scrollTop = container.scrollHeight;
                
                // Limit lines
                while (container.children.length > 500) {
                    container.removeChild(container.firstChild);
                }
            };
            
            ws.onclose = () => {
                // Reconnect after 2s
                setTimeout(() => connectLogs(currentLog), 2000);
            };
        }
        
        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                currentLog = tab.dataset.log;
                connectLogs(currentLog);
            });
        });
        
        // Config form
        document.getElementById('config-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const data = {
                nightline_server_url: document.getElementById('server-url').value,
                nightline_client_id: document.getElementById('client-id').value,
                webhook_secret: document.getElementById('webhook-secret').value,
            };
            
            try {
                const res = await fetch('/dashboard/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await res.json();
                showToast(result.message);
                
                // Reload after restart
                setTimeout(loadData, 2000);
                
            } catch (e) {
                showToast('Failed to save config', true);
            }
        });
        
        async function restartService(service) {
            try {
                const res = await fetch(`/dashboard/api/restart/${service}`, { method: 'POST' });
                const result = await res.json();
                showToast(result.message);
                setTimeout(loadData, 2000);
            } catch (e) {
                showToast('Failed to restart', true);
            }
        }
        
        async function checkHealth() {
            try {
                const res = await fetch('/health');
                const data = await res.json();
                showToast(`Status: ${data.status}`);
            } catch (e) {
                showToast('Health check failed', true);
            }
        }
        
        async function forceUpdate() {
            showToast('Checking for updates...');
            // Trigger the update script
            await fetch('/dashboard/api/restart/updater', { method: 'POST' });
        }
        
        function copyUrl() {
            const url = document.getElementById('tunnel-url').textContent;
            navigator.clipboard.writeText(url);
            showToast('URL copied!');
        }
        
        function showToast(message, isError = false) {
            const toast = document.createElement('div');
            toast.className = `toast ${isError ? 'error' : ''}`;
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        
        // Initial load
        loadData();
        connectLogs(currentLog);
        
        // Refresh status every 10s
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
