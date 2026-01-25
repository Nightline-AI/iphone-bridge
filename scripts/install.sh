#!/bin/bash
# iPhone Bridge Installation Script
# Run this on the Mac Mini to install the bridge as a system service

set -e

# Configuration
INSTALL_DIR="${INSTALL_DIR:-/Users/$(whoami)/iphone-bridge}"
LOG_DIR="/var/log/iphone-bridge"
PLIST_NAME="com.nightline.iphone-bridge.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "============================================"
echo "  iPhone Bridge Installation Script"
echo "============================================"
echo ""
echo "Install directory: $INSTALL_DIR"
echo "Log directory: $LOG_DIR"
echo ""

# Check if running on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: This script must be run on macOS"
    exit 1
fi

# Check for Python 3.11+
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    echo "Error: Python 3.11+ is required (found $PYTHON_VERSION)"
    echo "Install with: brew install python@3.11"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION detected"

# Create log directory
echo ""
echo "Creating log directory..."
sudo mkdir -p "$LOG_DIR"
sudo chown $(whoami) "$LOG_DIR"
echo "✓ Log directory created at $LOG_DIR"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
cd "$INSTALL_DIR"

if command -v poetry &> /dev/null; then
    poetry install --no-interaction
    PYTHON_PATH=$(poetry env info --path)/bin/python
else
    echo "Poetry not found, using pip..."
    python3 -m pip install -r requirements.txt 2>/dev/null || \
    python3 -m pip install fastapi uvicorn pydantic pydantic-settings httpx watchdog
    PYTHON_PATH=$(which python3)
fi

echo "✓ Dependencies installed"

# Check for .env file
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    echo ""
    echo "⚠ Warning: No .env file found"
    echo "  Copy .env.example to .env and configure it:"
    echo "  cp $INSTALL_DIR/.env.example $INSTALL_DIR/.env"
    echo ""
fi

# Generate launchd plist with correct paths
echo ""
echo "Generating launchd configuration..."

cat > "$LAUNCH_AGENTS_DIR/$PLIST_NAME" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightline.iphone-bridge</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
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
        <string>/usr/local/bin:/usr/bin:/bin</string>
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

echo "✓ launchd plist created at $LAUNCH_AGENTS_DIR/$PLIST_NAME"

# Unload existing service if running
echo ""
echo "Loading service..."
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
echo "✓ Service loaded"

# Check if service is running
sleep 2
if launchctl list | grep -q "com.nightline.iphone-bridge"; then
    echo "✓ Service is running"
else
    echo "⚠ Service may not have started. Check logs:"
    echo "  tail -f $LOG_DIR/stderr.log"
fi

echo ""
echo "============================================"
echo "  Installation Complete!"
echo "============================================"
echo ""
echo "Service commands:"
echo "  Start:   launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo "  Stop:    launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"
echo "  Restart: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo ""
echo "View logs:"
echo "  tail -f $LOG_DIR/stdout.log"
echo "  tail -f $LOG_DIR/stderr.log"
echo ""
echo "Health check:"
echo "  curl http://localhost:8080/health"
echo ""
echo "IMPORTANT: Grant Full Disk Access to Terminal/Python in:"
echo "  System Settings → Privacy & Security → Full Disk Access"
echo ""
