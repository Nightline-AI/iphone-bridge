#!/bin/bash
# iPhone Bridge Bootstrap Installer
# Run with: curl -fsSL https://raw.githubusercontent.com/Nightline-AI/iphone-bridge/main/scripts/bootstrap.sh | bash
#
# Or for a specific client:
# curl -fsSL https://raw.githubusercontent.com/Nightline-AI/iphone-bridge/main/scripts/bootstrap.sh | bash -s -- --client-id abc123

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/Nightline-AI/iphone-bridge"
INSTALL_DIR="$HOME/iphone-bridge"
NIGHTLINE_API="https://api.nightline.ai"
LOG_DIR="/var/log/iphone-bridge"
PLIST_NAME="com.nightline.iphone-bridge.plist"

# Parse arguments
CLIENT_ID=""
WEBHOOK_SECRET=""
SERVER_URL="$NIGHTLINE_API"
SKIP_SERVICE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --client-id)
            CLIENT_ID="$2"
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
        --no-service)
            SKIP_SERVICE=true
            shift
            ;;
        --ngrok)
            SETUP_NGROK=true
            shift
            ;;
        --ngrok-token)
            NGROK_TOKEN="$2"
            shift 2
            ;;
        --help)
            echo "iPhone Bridge Installer"
            echo ""
            echo "Usage: curl -fsSL https://tinyurl.com/288nshhu | bash -s -- [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --client-id ID      Your Nightline client ID (can be set later in .env)"
            echo "  --secret SECRET     Webhook secret (auto-generated if not provided)"
            echo "  --server-url URL    Nightline server URL (default: $NIGHTLINE_API)"
            echo "  --no-service        Don't install as system service"
            echo "  --ngrok             Set up ngrok tunnel for public URL"
            echo "  --ngrok-token TOKEN Your ngrok auth token (get from ngrok.com)"
            echo "  --help              Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║     📱  iPhone Bridge Installer                              ║"
echo "║                                                              ║"
echo "║     Bridges your iPhone's iMessage to Nightline              ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ===== System Checks =====

echo -e "${YELLOW}Checking system requirements...${NC}"

# Check macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}✗ Error: This script must be run on macOS${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} macOS detected"

# Check macOS version (13+ required for latest Messages features)
MACOS_VERSION=$(sw_vers -productVersion | cut -d'.' -f1)
if [[ "$MACOS_VERSION" -lt 13 ]]; then
    echo -e "${YELLOW}⚠ Warning: macOS 13+ recommended (found $MACOS_VERSION)${NC}"
else
    echo -e "${GREEN}✓${NC} macOS version: $(sw_vers -productVersion)"
fi

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Installing Homebrew...${NC}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add Homebrew to PATH for Apple Silicon
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
echo -e "${GREEN}✓${NC} Homebrew installed"

# Install/check Python 3.11+
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Installing Python 3.12...${NC}"
    brew install python@3.12
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
if [[ "$PYTHON_MINOR" -lt 11 ]]; then
    echo -e "${YELLOW}Installing Python 3.12...${NC}"
    brew install python@3.12
    # Use newly installed Python
    PYTHON_PATH="/opt/homebrew/bin/python3.12"
else
    PYTHON_PATH=$(which python3)
fi
echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION"

# Install Poetry
if ! command -v poetry &> /dev/null; then
    echo -e "${YELLOW}Installing Poetry...${NC}"
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}✓${NC} Poetry installed"

# ===== Clone Repository =====

echo ""
echo -e "${YELLOW}Installing iPhone Bridge...${NC}"

if [[ -d "$INSTALL_DIR" ]]; then
    echo -e "${YELLOW}Updating existing installation...${NC}"
    cd "$INSTALL_DIR"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || true
else
    echo -e "${YELLOW}Cloning repository...${NC}"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ===== Install Dependencies =====

echo -e "${YELLOW}Installing dependencies...${NC}"
poetry install --no-interaction
POETRY_PYTHON=$(poetry env info --path)/bin/python
echo -e "${GREEN}✓${NC} Dependencies installed"

# ===== Generate Configuration =====

echo ""
echo -e "${YELLOW}Configuring iPhone Bridge...${NC}"

# Generate webhook secret if not provided
if [[ -z "$WEBHOOK_SECRET" ]]; then
    WEBHOOK_SECRET=$(openssl rand -hex 32)
    echo -e "${CYAN}Generated webhook secret (save this!):${NC}"
    echo -e "${GREEN}$WEBHOOK_SECRET${NC}"
fi

# Create .env file
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cat > "$INSTALL_DIR/.env" << EOF
# iPhone Bridge Configuration
# Generated on $(date)

# Nightline Server URL
NIGHTLINE_SERVER_URL=$SERVER_URL

# Your Nightline Client ID (get this from your Nightline dashboard)
NIGHTLINE_CLIENT_ID=${CLIENT_ID}

# Webhook Authentication Secret (share this with Nightline)
WEBHOOK_SECRET=$WEBHOOK_SECRET

# Message polling interval (seconds)
POLL_INTERVAL=2.0

# Server binding
HOST=0.0.0.0
PORT=8080

# Logging level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

# Process historical messages on startup (true/false)
PROCESS_HISTORICAL=false

# Mock mode for testing without real iMessage (true/false)
MOCK_MODE=false
EOF
    echo -e "${GREEN}✓${NC} Configuration created at $INSTALL_DIR/.env"
else
    echo -e "${GREEN}✓${NC} Existing configuration preserved"
fi

# ===== Create Log Directory =====

echo -e "${YELLOW}Creating log directory...${NC}"
sudo mkdir -p "$LOG_DIR" 2>/dev/null || mkdir -p "$LOG_DIR"
sudo chown $(whoami) "$LOG_DIR" 2>/dev/null || true
echo -e "${GREEN}✓${NC} Log directory: $LOG_DIR"

# ===== Install System Service =====

if [[ "$SKIP_SERVICE" != "true" ]]; then
    echo ""
    echo -e "${YELLOW}Installing system service...${NC}"
    
    LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
    mkdir -p "$LAUNCH_AGENTS_DIR"

    cat > "$LAUNCH_AGENTS_DIR/$PLIST_NAME" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightline.iphone-bridge</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>$POETRY_PYTHON</string>
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
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    
    <key>ThrottleInterval</key>
    <integer>10</integer>
    
    <key>StandardOutPath</key>
    <string>$LOG_DIR/stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/stderr.log</string>
</dict>
</plist>
EOF

    # Load service
    launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
    launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
    
    sleep 2
    if launchctl list | grep -q "com.nightline.iphone-bridge"; then
        echo -e "${GREEN}✓${NC} Service installed and running"
    else
        echo -e "${YELLOW}⚠${NC} Service may not have started"
    fi
fi

# ===== Final Instructions =====

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${GREEN}✓ Installation Complete!${NC}                                   ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}⚠  IMPORTANT: Grant Full Disk Access${NC}"
echo ""
echo "   The bridge needs to read your Messages database. Do this ONCE:"
echo ""
echo "   1. Open System Settings"
echo "   2. Go to Privacy & Security → Full Disk Access"
echo "   3. Click + and add Terminal (or your terminal app)"
echo "   4. Also add: $POETRY_PYTHON"
echo ""

if [[ -z "$CLIENT_ID" ]]; then
    echo -e "${YELLOW}⚠  Configure your Client ID${NC}"
    echo ""
    echo "   Edit $INSTALL_DIR/.env and set:"
    echo "   NIGHTLINE_CLIENT_ID=your-client-id-here"
    echo ""
fi

echo -e "${CYAN}Useful Commands:${NC}"
echo ""
echo "   Health check:   curl http://localhost:8080/health"
echo "   View logs:      tail -f $LOG_DIR/stderr.log"
echo "   Restart:        launchctl kickstart -k gui/\$(id -u)/com.nightline.iphone-bridge"
echo "   Stop:           launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"
echo "   Start:          launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo ""
echo -e "${CYAN}Webhook Secret (save this for Nightline dashboard):${NC}"
echo -e "${GREEN}$WEBHOOK_SECRET${NC}"
echo ""

# ===== ngrok Setup (Optional) =====

if [[ "$SETUP_NGROK" == "true" ]]; then
    echo ""
    echo -e "${CYAN}Setting up ngrok tunnel...${NC}"
    
    # Install ngrok
    if ! command -v ngrok &>/dev/null; then
        echo -e "${YELLOW}Installing ngrok...${NC}"
        brew install ngrok
    fi
    echo -e "${GREEN}✓${NC} ngrok installed"
    
    # Configure ngrok auth token
    if [[ -n "$NGROK_TOKEN" ]]; then
        ngrok config add-authtoken "$NGROK_TOKEN"
        echo -e "${GREEN}✓${NC} ngrok authenticated"
    elif [[ ! -f "$HOME/.config/ngrok/ngrok.yml" ]] && [[ ! -f "$HOME/Library/Application Support/ngrok/ngrok.yml" ]]; then
        echo ""
        echo -e "${YELLOW}ngrok requires authentication.${NC}"
        echo "Get your free auth token at: https://dashboard.ngrok.com/get-started/your-authtoken"
        echo ""
        read -p "Enter your ngrok auth token (or press Enter to skip): " NGROK_TOKEN
        if [[ -n "$NGROK_TOKEN" ]]; then
            ngrok config add-authtoken "$NGROK_TOKEN"
            echo -e "${GREEN}✓${NC} ngrok authenticated"
        else
            echo -e "${YELLOW}Skipping ngrok setup. Run manually later: ngrok http 8080${NC}"
            SETUP_NGROK=false
        fi
    fi
    
    if [[ "$SETUP_NGROK" == "true" ]]; then
        # Create ngrok launchd plist
        NGROK_PLIST="$HOME/Library/LaunchAgents/com.ngrok.iphone-bridge.plist"
        
        cat > "$NGROK_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ngrok.iphone-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/ngrok</string>
        <string>http</string>
        <string>8080</string>
        <string>--log</string>
        <string>stdout</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/ngrok.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/ngrok.log</string>
</dict>
</plist>
EOF
        
        # Load ngrok service
        launchctl unload "$NGROK_PLIST" 2>/dev/null || true
        launchctl load "$NGROK_PLIST"
        
        echo -e "${GREEN}✓${NC} ngrok tunnel service installed"
        
        # Wait for ngrok to start and get URL
        echo -e "${YELLOW}Waiting for ngrok tunnel...${NC}"
        sleep 3
        
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import json,sys; data=json.load(sys.stdin); print(data['tunnels'][0]['public_url'] if data.get('tunnels') else '')" 2>/dev/null || echo "")
        
        if [[ -n "$NGROK_URL" ]]; then
            echo ""
            echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${CYAN}║${NC}  ${GREEN}🌐 Your Bridge is Live!${NC}                                    ${CYAN}║${NC}"
            echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            echo -e "  Public URL: ${GREEN}$NGROK_URL${NC}"
            echo ""
            echo -e "  ${CYAN}Add this to your Nightline dashboard as the Bridge URL${NC}"
            echo ""
            echo -e "  Test it:    curl $NGROK_URL/health"
            echo ""
            echo -e "${YELLOW}⚠  Note: Free ngrok URLs change on restart.${NC}"
            echo "   For a stable URL, upgrade ngrok or use Cloudflare Tunnel."
            echo ""
        else
            echo -e "${YELLOW}Could not get ngrok URL automatically.${NC}"
            echo "Check: curl http://localhost:4040/api/tunnels"
            echo "Or view: open http://localhost:4040"
        fi
    fi
else
    echo -e "${CYAN}Next Step: Expose your bridge to the internet${NC}"
    echo ""
    echo "  Option 1 - ngrok (easiest):"
    echo "    curl -fsSL https://tinyurl.com/288nshhu | bash -s -- --ngrok"
    echo ""
    echo "  Option 2 - Manual ngrok:"
    echo "    brew install ngrok"
    echo "    ngrok http 8080"
    echo ""
    echo "  Option 3 - Cloudflare Tunnel (production):"
    echo "    ~/iphone-bridge/scripts/setup-tunnel.sh"
    echo ""
fi
