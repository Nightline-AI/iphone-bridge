#!/bin/bash
# iPhone Bridge Installer
# One command to set up everything including Cloudflare Tunnel
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Nightline-AI/iphone-bridge/main/scripts/bootstrap.sh | bash -s -- \
#     --client-id CLIENT_ID \
#     --cloudflare-token YOUR_TOKEN

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

# Configuration
REPO_URL="https://github.com/Nightline-AI/iphone-bridge"
INSTALL_DIR="$HOME/iphone-bridge"
NIGHTLINE_API="https://api.nightline.net"
LOG_DIR="/var/log/iphone-bridge"
TUNNEL_DOMAIN="nightline.app"

# Parse arguments
CLIENT_ID=""
CLOUDFLARE_TOKEN=""
WEBHOOK_SECRET=""
SERVER_URL="$NIGHTLINE_API"

while [[ $# -gt 0 ]]; do
    case $1 in
        --client-id)
            CLIENT_ID="$2"
            shift 2
            ;;
        --cloudflare-token)
            CLOUDFLARE_TOKEN="$2"
            shift 2
            ;;
        --secret)
            WEBHOOK_SECRET="$2"
            shift 2
            ;;
        --server-url)
            SERVER_URL="$2"
            shift 2
            ;;
        --help)
            echo "iPhone Bridge Installer"
            echo ""
            echo "Usage:"
            echo "  curl -fsSL https://raw.githubusercontent.com/Nightline-AI/iphone-bridge/main/scripts/bootstrap.sh | bash -s -- \\"
            echo "    --client-id CLIENT_ID \\"
            echo "    --cloudflare-token YOUR_CLOUDFLARE_TOKEN"
            echo ""
            echo "Required:"
            echo "  --client-id ID           Unique identifier for this bridge (e.g., dentist-smith)"
            echo "  --cloudflare-token TOKEN Cloudflare API token (from dash.cloudflare.com)"
            echo ""
            echo "Optional:"
            echo "  --secret SECRET          Webhook secret (auto-generated if not provided)"
            echo "  --server-url URL         Nightline server URL (default: $NIGHTLINE_API)"
            echo ""
            echo "Result: https://bridge-CLIENT_ID.$TUNNEL_DOMAIN"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Validate required args
if [[ -z "$CLIENT_ID" ]]; then
    echo -e "${RED}Error: --client-id is required${NC}"
    echo ""
    echo "Usage:"
    echo "  curl ... | bash -s -- --client-id YOUR_CLIENT_ID --cloudflare-token YOUR_TOKEN"
    exit 1
fi

if [[ -z "$CLOUDFLARE_TOKEN" ]]; then
    echo -e "${RED}Error: --cloudflare-token is required${NC}"
    echo ""
    echo "Get your token at: https://dash.cloudflare.com/profile/api-tokens"
    echo "Create token with 'Edit zone DNS' template for $TUNNEL_DOMAIN"
    exit 1
fi

TUNNEL_HOSTNAME="bridge-${CLIENT_ID}.${TUNNEL_DOMAIN}"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║     📱  iPhone Bridge Installer                              ║"
echo "║                                                              ║"
echo "║     Setting up: $TUNNEL_HOSTNAME"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ===== System Checks =====

echo -e "${YELLOW}Checking system requirements...${NC}"

if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}✗ Error: This script must be run on macOS${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} macOS detected"

# Check/install Homebrew
if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Installing Homebrew...${NC}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
echo -e "${GREEN}✓${NC} Homebrew installed"

# Install Python 3.12 via Homebrew (need 3.10+ for type hints)
echo -e "${YELLOW}Installing Python 3.12...${NC}"
brew install python@3.12 2>/dev/null || true

# Use Homebrew Python explicitly (not system Python 3.9)
if [[ -f "/opt/homebrew/bin/python3.12" ]]; then
    PYTHON_CMD="/opt/homebrew/bin/python3.12"
elif [[ -f "/usr/local/bin/python3.12" ]]; then
    PYTHON_CMD="/usr/local/bin/python3.12"
else
    PYTHON_CMD=$(brew --prefix python@3.12)/bin/python3.12
fi

echo -e "${GREEN}✓${NC} Python $($PYTHON_CMD --version | cut -d' ' -f2)"

# Install cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo -e "${YELLOW}Installing cloudflared...${NC}"
    brew install cloudflared
fi
echo -e "${GREEN}✓${NC} cloudflared installed"

# ===== Clone Repository =====

echo ""
echo -e "${YELLOW}Installing iPhone Bridge...${NC}"

if [[ -d "$INSTALL_DIR" ]]; then
    cd "$INSTALL_DIR"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || true
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo -e "${GREEN}✓${NC} Repository cloned"

# ===== Install Dependencies =====

echo -e "${YELLOW}Installing dependencies...${NC}"

VENV_DIR="$INSTALL_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

rm -rf "$VENV_DIR"

echo -e "${DIM}Creating virtual environment with $PYTHON_CMD...${NC}"
if ! $PYTHON_CMD -m venv --copies "$VENV_DIR" 2>/dev/null; then
    if ! $PYTHON_CMD -m venv "$VENV_DIR" 2>/dev/null; then
        $PYTHON_CMD -m pip install --user virtualenv
        $PYTHON_CMD -m virtualenv "$VENV_DIR"
    fi
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx watchdog -q

echo -e "${GREEN}✓${NC} Dependencies installed"

# ===== Create Log Directory =====

sudo mkdir -p "$LOG_DIR" 2>/dev/null || mkdir -p "$LOG_DIR"
sudo chown $(whoami) "$LOG_DIR" 2>/dev/null || true

# ===== Generate Configuration =====

echo -e "${YELLOW}Configuring...${NC}"

if [[ -z "$WEBHOOK_SECRET" ]]; then
    WEBHOOK_SECRET=$(openssl rand -hex 32)
fi

cat > "$INSTALL_DIR/.env" << EOF
# iPhone Bridge Configuration
# Generated on $(date)
# Bridge URL: https://$TUNNEL_HOSTNAME

NIGHTLINE_SERVER_URL=$SERVER_URL
NIGHTLINE_CLIENT_ID=$CLIENT_ID
WEBHOOK_SECRET=$WEBHOOK_SECRET
POLL_INTERVAL=2.0
HOST=0.0.0.0
PORT=8080
LOG_LEVEL=INFO
PROCESS_HISTORICAL=false
MOCK_MODE=false
EOF

echo -e "${GREEN}✓${NC} Configuration created"

# ===== Install Bridge Service =====

echo -e "${YELLOW}Installing bridge service...${NC}"

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"

BRIDGE_PLIST="com.nightline.iphone-bridge.plist"
cat > "$LAUNCH_AGENTS_DIR/$BRIDGE_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightline.iphone-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>app.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8080</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/bridge.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/bridge.log</string>
</dict>
</plist>
EOF

launchctl unload "$LAUNCH_AGENTS_DIR/$BRIDGE_PLIST" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$BRIDGE_PLIST"

echo -e "${GREEN}✓${NC} Bridge service installed"

# ===== Install Auto-Updater =====

chmod +x "$INSTALL_DIR/scripts/auto-update.sh" 2>/dev/null || true

UPDATER_PLIST="com.nightline.iphone-bridge-updater.plist"
cat > "$LAUNCH_AGENTS_DIR/$UPDATER_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightline.iphone-bridge-updater</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$INSTALL_DIR/scripts/auto-update.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/updater.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/updater.log</string>
</dict>
</plist>
EOF

launchctl unload "$LAUNCH_AGENTS_DIR/$UPDATER_PLIST" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$UPDATER_PLIST"

echo -e "${GREEN}✓${NC} Auto-updater installed (checks every 5 min)"

# ===== Setup Cloudflare Tunnel =====

echo ""
echo -e "${YELLOW}Setting up Cloudflare Tunnel...${NC}"

TUNNEL_NAME="iphone-bridge-${CLIENT_ID}"
CF_DIR="$HOME/.cloudflared"
mkdir -p "$CF_DIR"

# Check if already logged in (cert.pem exists)
if [[ ! -f "$CF_DIR/cert.pem" ]]; then
    echo ""
    echo -e "${CYAN}Cloudflare login required (one-time setup)${NC}"
    echo ""
    echo "A browser window will open. Log in to Cloudflare and select '$TUNNEL_DOMAIN'."
    echo ""
    read -p "Press Enter to open browser..."
    
    cloudflared tunnel login
    
    if [[ ! -f "$CF_DIR/cert.pem" ]]; then
        echo -e "${RED}Login failed. Please try again.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} Cloudflare authenticated"
fi

# Check if tunnel already exists
EXISTING_TUNNEL=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}' || echo "")

if [[ -n "$EXISTING_TUNNEL" ]]; then
    echo -e "${DIM}Tunnel exists, using: $EXISTING_TUNNEL${NC}"
    TUNNEL_ID="$EXISTING_TUNNEL"
else
    echo -e "${DIM}Creating tunnel...${NC}"
    cloudflared tunnel create "$TUNNEL_NAME" 2>&1 | tee /tmp/cf-tunnel-create.log
    TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
fi

if [[ -z "$TUNNEL_ID" ]]; then
    echo -e "${RED}Failed to create tunnel. Please run 'cloudflared tunnel login' manually.${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Tunnel created: $TUNNEL_ID"

# Create tunnel config
cat > "$CF_DIR/config-${CLIENT_ID}.yml" << EOF
tunnel: $TUNNEL_ID
credentials-file: $CF_DIR/$TUNNEL_ID.json

ingress:
  - hostname: $TUNNEL_HOSTNAME
    service: http://localhost:8080
  - service: http_status:404
EOF

# Route DNS
echo -e "${DIM}Configuring DNS...${NC}"
cloudflared tunnel route dns "$TUNNEL_NAME" "$TUNNEL_HOSTNAME" 2>/dev/null || echo -e "${DIM}DNS route may already exist${NC}"

echo -e "${GREEN}✓${NC} DNS configured: $TUNNEL_HOSTNAME"

# Install tunnel service
TUNNEL_PLIST="com.nightline.cloudflare-tunnel-${CLIENT_ID}.plist"
cat > "$LAUNCH_AGENTS_DIR/$TUNNEL_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightline.cloudflare-tunnel-${CLIENT_ID}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/cloudflared</string>
        <string>tunnel</string>
        <string>--config</string>
        <string>$CF_DIR/config-${CLIENT_ID}.yml</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/tunnel.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/tunnel.log</string>
</dict>
</plist>
EOF

launchctl unload "$LAUNCH_AGENTS_DIR/$TUNNEL_PLIST" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$TUNNEL_PLIST"

echo -e "${GREEN}✓${NC} Tunnel service installed"

# Wait for tunnel to come up
echo -e "${DIM}Waiting for tunnel to connect...${NC}"
sleep 5

# ===== Done! =====

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}                                                              ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  ${GREEN}✓ iPhone Bridge is Live!${NC}                                  ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}                                                              ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Public URL:${NC}     ${GREEN}https://$TUNNEL_HOSTNAME${NC}"
echo ""
echo -e "  ${CYAN}Webhook Secret:${NC} ${GREEN}$WEBHOOK_SECRET${NC}"
echo ""
echo -e "  ${CYAN}Test it:${NC}        curl https://$TUNNEL_HOSTNAME/health"
echo ""
echo -e "${YELLOW}⚠  IMPORTANT: Grant Full Disk Access${NC}"
echo ""
echo "   1. Open System Settings"
echo "   2. Go to Privacy & Security → Full Disk Access"
echo "   3. Add Terminal (or your terminal app)"
echo "   4. Add: $PYTHON_BIN"
echo ""
echo -e "${CYAN}Dashboard:${NC} http://localhost:8080/dashboard"
echo ""
echo -e "${CYAN}Logs:${NC}"
echo "   Bridge:  tail -f $LOG_DIR/bridge.log"
echo "   Tunnel:  tail -f $LOG_DIR/tunnel.log"
echo "   Updates: tail -f $LOG_DIR/updater.log"
echo ""

# Open dashboard in browser
echo -e "${YELLOW}Opening dashboard in browser...${NC}"
sleep 3
open "http://localhost:8080/dashboard" 2>/dev/null || echo "Open http://localhost:8080/dashboard in your browser"
