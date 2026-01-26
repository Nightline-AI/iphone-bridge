#!/bin/bash
# iPhone Bridge Auto-Updater
# Checks for updates and restarts if needed

set -e

INSTALL_DIR="${IPHONE_BRIDGE_DIR:-$HOME/iphone-bridge}"
LOG_FILE="/var/log/iphone-bridge/updater.log"
LOCK_FILE="/tmp/iphone-bridge-update.lock"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Prevent concurrent runs
if [[ -f "$LOCK_FILE" ]]; then
    exit 0
fi
touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

cd "$INSTALL_DIR"

# Fetch latest
git fetch origin main --quiet 2>/dev/null || git fetch origin master --quiet 2>/dev/null || {
    log "ERROR: Failed to fetch from origin"
    exit 1
}

# Check if we're behind
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master)

if [[ "$LOCAL" == "$REMOTE" ]]; then
    # No updates
    exit 0
fi

log "Update available: $LOCAL -> $REMOTE"

# Pull changes
git pull origin main --quiet 2>/dev/null || git pull origin master --quiet
log "Pulled latest changes"

# Reinstall dependencies
source "$INSTALL_DIR/.venv/bin/activate"
pip install -q fastapi "uvicorn[standard]" pydantic pydantic-settings httpx watchdog
log "Dependencies updated"

# Restart the bridge service
launchctl kickstart -k "gui/$(id -u)/com.nightline.iphone-bridge" 2>/dev/null || {
    launchctl unload "$HOME/Library/LaunchAgents/com.nightline.iphone-bridge.plist" 2>/dev/null || true
    launchctl load "$HOME/Library/LaunchAgents/com.nightline.iphone-bridge.plist"
}
log "Bridge restarted"

log "Update complete!"
