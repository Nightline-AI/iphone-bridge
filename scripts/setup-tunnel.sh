#!/bin/bash
# Setup Cloudflare Tunnel + Tailscale for iPhone Bridge
# Run: ./scripts/setup-tunnel.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="${IPHONE_BRIDGE_DIR:-$HOME/iphone-bridge}"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        iPhone Bridge Remote Access Setup                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Load config
if [[ -f "$INSTALL_DIR/.env" ]]; then
    source "$INSTALL_DIR/.env" 2>/dev/null || true
fi

CLIENT_ID="${NIGHTLINE_CLIENT_ID:-}"

if [[ -z "$CLIENT_ID" ]]; then
    echo -e "${YELLOW}Enter your Nightline Client ID:${NC}"
    read CLIENT_ID
fi

TUNNEL_NAME="bridge-$CLIENT_ID"
TUNNEL_HOSTNAME="${TUNNEL_NAME}.nightline.ai"

# ===== Tailscale Setup =====

echo ""
echo -e "${CYAN}1. Tailscale Setup (for remote management)${NC}"
echo ""

if command -v tailscale &>/dev/null; then
    echo -e "${GREEN}✓${NC} Tailscale already installed"
    
    if tailscale status &>/dev/null; then
        TS_IP=$(tailscale ip -4 2>/dev/null || echo "N/A")
        TS_NAME=$(tailscale status --self --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null || echo "N/A")
        echo -e "${GREEN}✓${NC} Tailscale connected"
        echo "  IP: $TS_IP"
        echo "  Hostname: $TS_NAME"
    else
        echo -e "${YELLOW}Tailscale installed but not connected.${NC}"
        echo "Run: tailscale up"
    fi
else
    echo -e "${YELLOW}Installing Tailscale...${NC}"
    brew install tailscale
    
    echo ""
    echo -e "${YELLOW}Start Tailscale with:${NC}"
    echo "  tailscale up"
    echo ""
    echo "Then re-run this script."
fi

# ===== Cloudflare Tunnel Setup =====

echo ""
echo -e "${CYAN}2. Cloudflare Tunnel Setup (for Nightline connection)${NC}"
echo ""

if ! command -v cloudflared &>/dev/null; then
    echo -e "${YELLOW}Installing cloudflared...${NC}"
    brew install cloudflared
fi

echo -e "${GREEN}✓${NC} cloudflared installed"

# Check if already authenticated
CF_CREDS="$HOME/.cloudflared"
if [[ ! -d "$CF_CREDS" ]] || [[ -z "$(ls -A $CF_CREDS/*.json 2>/dev/null)" ]]; then
    echo ""
    echo -e "${YELLOW}Cloudflare authentication required.${NC}"
    echo "This will open a browser to authenticate with Cloudflare."
    echo ""
    read -p "Press Enter to continue..."
    
    cloudflared tunnel login
fi

echo -e "${GREEN}✓${NC} Cloudflare authenticated"

# Check if tunnel exists
EXISTING_TUNNEL=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "import json,sys; tunnels=json.load(sys.stdin); print(next((t['id'] for t in tunnels if t['name']=='$TUNNEL_NAME'), ''))" 2>/dev/null || echo "")

if [[ -n "$EXISTING_TUNNEL" ]]; then
    echo -e "${GREEN}✓${NC} Tunnel '$TUNNEL_NAME' already exists (ID: $EXISTING_TUNNEL)"
    TUNNEL_ID="$EXISTING_TUNNEL"
else
    echo -e "${YELLOW}Creating tunnel '$TUNNEL_NAME'...${NC}"
    cloudflared tunnel create "$TUNNEL_NAME"
    
    TUNNEL_ID=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "import json,sys; tunnels=json.load(sys.stdin); print(next((t['id'] for t in tunnels if t['name']=='$TUNNEL_NAME'), ''))" 2>/dev/null)
    echo -e "${GREEN}✓${NC} Tunnel created (ID: $TUNNEL_ID)"
fi

# Create config file
CLOUDFLARED_CONFIG="$HOME/.cloudflared/config-$TUNNEL_NAME.yml"

echo -e "${YELLOW}Creating tunnel config...${NC}"

cat > "$CLOUDFLARED_CONFIG" << EOF
tunnel: $TUNNEL_ID
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $TUNNEL_HOSTNAME
    service: http://localhost:8080
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false
  - service: http_status:404
EOF

echo -e "${GREEN}✓${NC} Config created at $CLOUDFLARED_CONFIG"

# Route DNS (may fail if already exists)
echo -e "${YELLOW}Configuring DNS...${NC}"
cloudflared tunnel route dns "$TUNNEL_NAME" "$TUNNEL_HOSTNAME" 2>/dev/null || echo -e "${DIM}DNS route may already exist${NC}"

# Create launchd plist for cloudflared
PLIST_NAME="com.cloudflare.tunnel-$CLIENT_ID.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo -e "${YELLOW}Installing cloudflared as system service...${NC}"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cloudflare.tunnel-$CLIENT_ID</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/cloudflared</string>
        <string>tunnel</string>
        <string>--config</string>
        <string>$CLOUDFLARED_CONFIG</string>
        <string>run</string>
    </array>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>/var/log/iphone-bridge/cloudflared-stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>/var/log/iphone-bridge/cloudflared-stderr.log</string>
</dict>
</plist>
EOF

# Load the service
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo -e "${GREEN}✓${NC} Cloudflare Tunnel service installed"

# ===== Summary =====

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗"
echo -e "║  ${GREEN}✓ Remote Access Setup Complete!${NC}                              ${CYAN}║"
echo -e "╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Your bridge is now accessible at:${NC}"
echo ""
echo -e "  Public URL: ${GREEN}https://$TUNNEL_HOSTNAME${NC}"
echo "    (Use this in Nightline dashboard)"
echo ""

if tailscale status &>/dev/null; then
    TS_IP=$(tailscale ip -4 2>/dev/null)
    TS_NAME=$(tailscale status --self --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null)
    echo -e "  Tailscale: ${GREEN}http://$TS_NAME:8080${NC}"
    echo "    (Use for SSH/remote debugging)"
fi

echo ""
echo -e "${CYAN}Service commands:${NC}"
echo ""
echo "  Tunnel logs:    tail -f /var/log/iphone-bridge/cloudflared-stderr.log"
echo "  Restart tunnel: launchctl kickstart -k gui/\$(id -u)/com.cloudflare.tunnel-$CLIENT_ID"
echo ""
echo -e "${CYAN}Test the public endpoint:${NC}"
echo ""
echo "  curl https://$TUNNEL_HOSTNAME/health"
echo ""
