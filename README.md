# iPhone Bridge

A Mac Mini server that bridges iMessage/SMS communication between an iPhone and the Nightline server.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mac Mini                                  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                  iPhone Bridge Server                     │  │
│   │                                                           │  │
│   │   📥 Monitors chat.db for incoming messages               │  │
│   │   📤 Sends messages via AppleScript                       │  │
│   │   🔄 Forwards to/from Nightline server                    │  │
│   └──────────────────────────────────────────────────────────┘  │
│                           │                                      │
│   ┌───────────────────────┼───────────────────────────────────┐ │
│   │  Messages.app         │    iCloud Sync                     │ │
│   │  (chat.db) ◄──────────┼────────────────► iPhone            │ │
│   └───────────────────────┼───────────────────────────────────┘ │
└───────────────────────────┼─────────────────────────────────────┘
                            │ HTTPS webhooks
                            ▼
                ┌───────────────────────┐
                │   Nightline Server    │
                └───────────────────────┘
```

## Requirements

- **macOS 13+ (Ventura or later)** on Mac Mini
- **Python 3.11+**
- **iPhone** signed into the same iCloud account as the Mac
- **Messages in iCloud** enabled on both devices
- **Full Disk Access** granted to Terminal/Python

## Quick Start

### One-Line Install (Recommended)

```bash
curl -fsSL https://install.nightline.ai/iphone-bridge | bash
```

Or with your client ID:

```bash
curl -fsSL https://install.nightline.ai/iphone-bridge | bash -s -- --client-id YOUR_CLIENT_ID
```

This will:

- Install all dependencies (Python, Poetry)
- Clone and configure the bridge
- Generate a secure webhook secret
- Install as a system service that starts on boot

### Manual Installation

#### 1. Clone and Configure

```bash
# Clone the repository
git clone https://github.com/nightline/iphone-bridge.git
cd iphone-bridge

# Copy environment template
cp .env.example .env

# Edit configuration
nano .env
```

### 2. Configure Environment

Edit `.env` with your settings:

```env
# Nightline server URL
NIGHTLINE_SERVER_URL=https://api.nightline.ai

# Generate a secure random secret (share this with Nightline server)
WEBHOOK_SECRET=your-secure-random-string-here

# Polling interval (seconds)
POLL_INTERVAL=2.0

# Server binding
HOST=0.0.0.0
PORT=8080
```

### 3. Install Dependencies

```bash
# Using Poetry (recommended)
poetry install

# Or using pip
pip install fastapi uvicorn pydantic pydantic-settings httpx watchdog
```

### 4. Grant Full Disk Access

The bridge needs to read `~/Library/Messages/chat.db`. Grant Full Disk Access:

1. Open **System Settings**
2. Go to **Privacy & Security** → **Full Disk Access**
3. Add **Terminal** (or your terminal app)
4. If using Poetry, also add the Python executable from your virtual environment

### 5. Run the Server

```bash
# Development (with auto-reload)
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# Production
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### 6. Install as System Service (Optional)

To run the bridge automatically on boot:

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

## API Endpoints

### Health Check

```bash
curl http://localhost:8080/health
```

Response:

```json
{
  "status": "healthy",
  "watcher_running": true,
  "version": "0.1.0",
  "uptime_seconds": 3600.5
}
```

### Send Message

```bash
curl -X POST http://localhost:8080/send \
  -H "Content-Type: application/json" \
  -H "X-Bridge-Secret: your-webhook-secret" \
  -d '{
    "phone": "+15551234567",
    "text": "Hello from Nightline!"
  }'
```

Response:

```json
{
  "success": true,
  "message_id": "bridge-abc123def456"
}
```

### Detailed Status

```bash
curl http://localhost:8080/status
```

## Webhook Contract

### Bridge → Nightline (Incoming Messages)

When a message is received on the iPhone, the bridge forwards it:

```http
POST /webhooks/iphone-bridge/message
X-Bridge-Secret: <shared_secret>
Content-Type: application/json

{
  "event": "message.received",
  "phone": "+15551234567",
  "text": "Hey can I reschedule tomorrow?",
  "received_at": "2026-01-24T14:30:00Z",
  "message_id": "abc123-guid",
  "is_imessage": true
}
```

### Nightline → Bridge (Send Messages)

```http
POST /send
X-Bridge-Secret: <shared_secret>
Content-Type: application/json

{
  "phone": "+15551234567",
  "text": "Of course! When works better for you?"
}
```

## Configuration Options

| Variable               | Default                 | Description                          |
| ---------------------- | ----------------------- | ------------------------------------ |
| `NIGHTLINE_SERVER_URL` | `http://localhost:8000` | URL of the Nightline server          |
| `WEBHOOK_SECRET`       | (required)              | Shared secret for authentication     |
| `POLL_INTERVAL`        | `2.0`                   | Seconds between chat.db polls        |
| `HOST`                 | `0.0.0.0`               | Server bind address                  |
| `PORT`                 | `8080`                  | Server port                          |
| `LOG_LEVEL`            | `INFO`                  | Logging level                        |
| `PROCESS_HISTORICAL`   | `false`                 | Process messages from before startup |

## Troubleshooting

### "Messages database not found"

- Ensure Messages.app has been opened at least once
- Check that `~/Library/Messages/chat.db` exists
- Grant Full Disk Access to Terminal/Python

### "Failed to send message"

- Ensure Messages.app is signed into iCloud
- Check that the recipient has iMessage enabled
- Try sending manually from Messages.app first

### Messages not syncing from iPhone

- Enable **Messages in iCloud** on both devices:
  - iPhone: Settings → [Your Name] → iCloud → Messages
  - Mac: Messages → Settings → iMessage → Enable Messages in iCloud
- Wait a few minutes for sync to complete

### Service not starting

Check the logs:

```bash
tail -f /var/log/iphone-bridge/stderr.log
```

Common issues:

- Python path incorrect in launchd plist
- Missing Full Disk Access permission
- Port 8080 already in use

## Management CLI

After installation, use `bridge-ctl` to manage your bridge:

```bash
# Add to PATH (do once)
export PATH="$HOME/iphone-bridge/scripts:$PATH"
# Or symlink: ln -s ~/iphone-bridge/scripts/bridge-ctl /usr/local/bin/bridge-ctl

# Check status
bridge-ctl status

# View logs
bridge-ctl logs

# Restart
bridge-ctl restart

# Edit configuration
bridge-ctl config

# Update to latest version
bridge-ctl update

# Set up remote access tunnels
bridge-ctl tunnel
```

## Network Setup

The Nightline server needs to reach this bridge. Options:

1. **Cloudflare Tunnel** (recommended): Zero-trust access without opening ports
2. **Tailscale/WireGuard**: VPN between Mac Mini and Nightline server
3. **Port forwarding**: Open port 8080 on your router (less secure)
4. **Static IP**: If Mac Mini has a public IP

See [Remote Access Guide](docs/REMOTE_ACCESS.md) for detailed setup instructions.

### Quick Cloudflare Tunnel Setup

```bash
# Install cloudflared
brew install cloudflared

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create iphone-bridge

# Route tunnel to local server
cloudflared tunnel route dns iphone-bridge bridge.nightline.ai

# Run tunnel
cloudflared tunnel run --url http://localhost:8080 iphone-bridge
```

## Development

### Running Tests

```bash
poetry run pytest
```

### Code Formatting

```bash
poetry run ruff format .
poetry run ruff check --fix .
```

### Project Structure

```
iphone-bridge/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Settings
│   ├── imessage/
│   │   ├── __init__.py
│   │   ├── watcher.py       # chat.db monitor
│   │   ├── sender.py        # AppleScript sender
│   │   └── models.py        # Data classes
│   └── webhooks/
│       ├── __init__.py
│       ├── client.py        # Nightline HTTP client
│       └── schemas.py       # Pydantic models
├── scripts/
│   ├── install.sh           # Service installation
│   └── uninstall.sh         # Service removal
├── pyproject.toml
├── .env.example
└── README.md
```

## Security Considerations

- **Webhook Secret**: Use a strong, random secret shared between bridge and Nightline
- **HTTPS**: Always use HTTPS for webhook communication
- **Firewall**: Restrict access to the bridge's port
- **Full Disk Access**: Only grant to necessary applications
- **PHI/HIPAA**: If handling health data, ensure appropriate security measures

## License

Proprietary - Nightline AI, Inc.
