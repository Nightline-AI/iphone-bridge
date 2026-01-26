# Remote Access to iPhone Bridge Macs

This guide covers how to set up secure remote access to your Mac Mini fleet running iPhone Bridge.

## Overview of Options

| Solution | Best For | Complexity | Cost |
|----------|----------|------------|------|
| **Tailscale** | Remote management + API access | Easy | Free |
| **Cloudflare Tunnel** | Exposing bridge to Nightline server | Medium | Free |
| **SSH + Tailscale** | Terminal access for debugging | Easy | Free |
| **Apple Remote Desktop** | GUI management of fleet | Easy | $80 |
| **Jump Host / Bastion** | Enterprise security | Complex | Varies |

---

## Recommended Setup: Tailscale + Cloudflare Tunnel

Use **both** for the best of both worlds:
- **Tailscale**: Remote management, SSH, debugging
- **Cloudflare Tunnel**: Expose bridge API to Nightline server

---

## 1. Tailscale (Recommended for Remote Access)

Tailscale creates a secure mesh VPN between all your devices. Zero port forwarding, works through any NAT.

### Install on Each Mac Mini

```bash
# Install
brew install tailscale

# Start and authenticate
tailscale up

# Follow the browser link to authenticate with your Tailscale account
```

### Benefits

- **SSH from anywhere**: `ssh user@mac-mini-1.tailnet-name.ts.net`
- **Access health endpoints**: `curl http://mac-mini-1:8080/health`
- **File transfers**: `scp`, `rsync` work normally
- **No port forwarding** needed
- **Works through firewalls** and NAT
- **Free** for up to 100 devices

### Fleet Management with Tailscale

```bash
# See all your machines
tailscale status

# Example output:
# 100.x.x.1  mac-mini-1      shaanfulton@ macOS  -
# 100.x.x.2  mac-mini-2      shaanfulton@ macOS  -
# 100.x.x.3  my-laptop       shaanfulton@ macOS  -
```

### SSH Configuration

Add to `~/.ssh/config` on your laptop:

```ssh-config
# iPhone Bridge Mac Minis
Host bridge-*
    User nightline
    IdentityFile ~/.ssh/nightline_bridge_key

Host bridge-1
    HostName mac-mini-1.tailnet-name.ts.net

Host bridge-2
    HostName mac-mini-2.tailnet-name.ts.net

# Wildcard for all bridges
Host *.ts.net
    User nightline
    IdentityFile ~/.ssh/nightline_bridge_key
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Now you can: `ssh bridge-1`

---

## 2. Cloudflare Tunnel (Recommended for Nightline Connection)

Cloudflare Tunnel exposes your local bridge to the internet without opening ports.

### Install on Each Mac Mini

```bash
# Install cloudflared
brew install cloudflared

# Authenticate (do this once)
cloudflared tunnel login

# Create a tunnel (name it with the client ID)
cloudflared tunnel create bridge-client-abc123

# Configure DNS routing
cloudflared tunnel route dns bridge-client-abc123 bridge-abc123.nightline.ai
```

### Create Tunnel Config

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /Users/nightline/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: bridge-abc123.nightline.ai
    service: http://localhost:8080
  - service: http_status:404
```

### Install as System Service

```bash
# Install cloudflared service
sudo cloudflared service install

# Or create a launchd plist similar to iphone-bridge
```

### LaunchDaemon for cloudflared

Save as `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cloudflare.cloudflared</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/cloudflared</string>
        <string>tunnel</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/cloudflared/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/cloudflared/stderr.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/nightline</string>
    <key>UserName</key>
    <string>nightline</string>
</dict>
</plist>
```

Load it:
```bash
sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```

---

## 3. SSH-Only Access (Simplest)

If you just need terminal access for debugging:

### Enable SSH on Mac Mini

```bash
# Enable Remote Login
sudo systemsetup -setremotelogin on

# Or via System Settings:
# System Settings → General → Sharing → Remote Login
```

### With Tailscale

```bash
# SSH directly via Tailscale IP
ssh nightline@100.x.x.x

# Or via Tailscale hostname
ssh nightline@mac-mini-1.tailnet-name.ts.net
```

### Without Tailscale (Port Forwarding)

On your router, forward port 22 (or a custom port) to the Mac Mini. **Less secure**.

```bash
ssh -p 2222 nightline@your-public-ip.com
```

---

## 4. Apple Remote Desktop

For GUI-based fleet management:

1. **Enable Screen Sharing** on each Mac Mini:
   - System Settings → General → Sharing → Screen Sharing

2. **Buy Apple Remote Desktop** from the Mac App Store ($79.99)

3. **Add Macs** via IP or Bonjour

4. **Features**:
   - See all screens at once
   - Run commands on multiple Macs
   - Push files/packages
   - Collect reports

### With Tailscale

Use Tailscale IPs in Apple Remote Desktop for access from anywhere.

---

## 5. Fleet Management Scripts

### Check All Bridges Script

```bash
#!/bin/bash
# check-all-bridges.sh

BRIDGES=(
    "bridge-1:mac-mini-1.tailnet.ts.net"
    "bridge-2:mac-mini-2.tailnet.ts.net"
)

echo "iPhone Bridge Fleet Status"
echo "=========================="
echo ""

for entry in "${BRIDGES[@]}"; do
    NAME="${entry%%:*}"
    HOST="${entry##*:}"
    
    STATUS=$(curl -s --connect-timeout 5 "http://$HOST:8080/health" 2>/dev/null)
    
    if [[ -n "$STATUS" ]]; then
        HEALTH=$(echo "$STATUS" | jq -r '.status')
        UPTIME=$(echo "$STATUS" | jq -r '.uptime_seconds | . / 3600 | floor')
        RECV=$(echo "$STATUS" | jq -r '.stats.messages_received')
        
        case "$HEALTH" in
            healthy)  ICON="✅" ;;
            degraded) ICON="⚠️" ;;
            *)        ICON="❌" ;;
        esac
        
        echo "$ICON $NAME: $HEALTH (${UPTIME}h uptime, $RECV msgs)"
    else
        echo "❌ $NAME: UNREACHABLE"
    fi
done
```

### Restart All Bridges

```bash
#!/bin/bash
# restart-all-bridges.sh

BRIDGES=(
    "nightline@mac-mini-1.tailnet.ts.net"
    "nightline@mac-mini-2.tailnet.ts.net"
)

for HOST in "${BRIDGES[@]}"; do
    echo "Restarting $HOST..."
    ssh "$HOST" "launchctl kickstart -k gui/\$(id -u)/com.nightline.iphone-bridge"
done

echo "Done!"
```

### Update All Bridges

```bash
#!/bin/bash
# update-all-bridges.sh

BRIDGES=(
    "nightline@mac-mini-1.tailnet.ts.net"
    "nightline@mac-mini-2.tailnet.ts.net"
)

for HOST in "${BRIDGES[@]}"; do
    echo "Updating $HOST..."
    ssh "$HOST" << 'EOF'
        cd ~/iphone-bridge
        git pull
        poetry install
        launchctl kickstart -k gui/$(id -u)/com.nightline.iphone-bridge
EOF
done

echo "Done!"
```

---

## 6. Monitoring

### UptimeRobot / Uptime Kuma

Monitor the `/health` endpoint:

- **URL**: `http://bridge-abc123.nightline.ai/health`
- **Expected**: JSON with `"status": "healthy"`
- **Alert on**: `degraded` or `unhealthy`

### Prometheus + Grafana

Export metrics from the health endpoint and visualize in Grafana.

### Simple Alerting Script

```bash
#!/bin/bash
# monitor-bridges.sh - run via cron every 5 minutes

WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK"

BRIDGES=(
    "bridge-1:https://bridge-abc123.nightline.ai/health"
)

for entry in "${BRIDGES[@]}"; do
    NAME="${entry%%:*}"
    URL="${entry##*:}"
    
    STATUS=$(curl -s --connect-timeout 10 "$URL" | jq -r '.status' 2>/dev/null)
    
    if [[ "$STATUS" != "healthy" ]]; then
        curl -X POST "$WEBHOOK_URL" \
            -H 'Content-Type: application/json' \
            -d "{\"text\":\"🚨 iPhone Bridge Alert: $NAME is $STATUS\"}"
    fi
done
```

---

## 7. Security Best Practices

### SSH Hardening

On each Mac Mini, edit `/etc/ssh/sshd_config`:

```
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers nightline
```

### Firewall

```bash
# Enable firewall
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on

# Allow only specific services (Tailscale handles the rest)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/sbin/sshd
```

### Webhook Secret Rotation

Rotate secrets periodically:

```bash
# Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# Update .env
sed -i '' "s/WEBHOOK_SECRET=.*/WEBHOOK_SECRET=$NEW_SECRET/" ~/iphone-bridge/.env

# Restart bridge
launchctl kickstart -k gui/$(id -u)/com.nightline.iphone-bridge

# Update Nightline dashboard with new secret
echo "New secret: $NEW_SECRET"
```

---

## Quick Start Checklist

1. [ ] Install Tailscale on all Mac Minis
2. [ ] Install Tailscale on your management laptop
3. [ ] Set up SSH keys for passwordless access
4. [ ] Create Cloudflare Tunnels for each bridge
5. [ ] Configure Nightline dashboard with tunnel URLs
6. [ ] Set up monitoring (UptimeRobot recommended)
7. [ ] Create fleet management scripts
8. [ ] Document all bridge hostnames/IPs
