#!/bin/bash
# iPhone Bridge Uninstallation Script

set -e

PLIST_NAME="com.nightline.iphone-bridge.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="/var/log/iphone-bridge"

echo "============================================"
echo "  iPhone Bridge Uninstallation Script"
echo "============================================"
echo ""

# Stop the service
echo "Stopping service..."
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
echo "✓ Service stopped"

# Remove the plist
if [[ -f "$LAUNCH_AGENTS_DIR/$PLIST_NAME" ]]; then
    rm "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
    echo "✓ Removed launchd plist"
fi

# Ask about logs
echo ""
read -p "Remove log directory ($LOG_DIR)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo rm -rf "$LOG_DIR"
    echo "✓ Removed log directory"
fi

echo ""
echo "============================================"
echo "  Uninstallation Complete!"
echo "============================================"
echo ""
echo "Note: The application files were not removed."
echo "Delete them manually if desired."
echo ""
