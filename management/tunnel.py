"""
Cloudflare Tunnel management for iPhone Bridge.

Handles automatic tunnel reconfiguration when client ID changes.
"""

import logging
import os
import subprocess
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TUNNEL_DOMAIN = "nightline.app"
CLOUDFLARED_PATH = "/opt/homebrew/bin/cloudflared"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
CLOUDFLARED_CONFIG_DIR = Path.home() / ".cloudflared"
LOG_DIR = Path("/var/log/iphone-bridge")


def is_cloudflared_installed() -> bool:
    """Check if cloudflared is installed."""
    return Path(CLOUDFLARED_PATH).exists()


def get_existing_tunnels() -> list[dict]:
    """Get list of existing Cloudflare tunnels."""
    try:
        result = subprocess.run(
            [CLOUDFLARED_PATH, "tunnel", "list", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        logger.error(f"Failed to list tunnels: {e}")
    return []


def get_tunnel_id_by_name(name: str) -> Optional[str]:
    """Get tunnel ID by name, or None if not found."""
    tunnels = get_existing_tunnels()
    for tunnel in tunnels:
        if tunnel.get("name") == name:
            return tunnel.get("id")
    return None


def create_tunnel(name: str) -> Optional[str]:
    """Create a new Cloudflare tunnel and return its ID."""
    try:
        logger.info(f"Creating tunnel: {name}")
        result = subprocess.run(
            [CLOUDFLARED_PATH, "tunnel", "create", name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            # Get the tunnel ID
            return get_tunnel_id_by_name(name)
        else:
            logger.error(f"Failed to create tunnel: {result.stderr}")
    except Exception as e:
        logger.error(f"Failed to create tunnel: {e}")
    return None


def route_dns(tunnel_name: str, hostname: str) -> bool:
    """Route DNS for a tunnel hostname."""
    try:
        logger.info(f"Routing DNS: {hostname} -> {tunnel_name}")
        result = subprocess.run(
            [CLOUDFLARED_PATH, "tunnel", "route", "dns", tunnel_name, hostname],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # DNS route might already exist, that's fine
        return True
    except Exception as e:
        logger.error(f"Failed to route DNS: {e}")
        return False


def create_tunnel_config(tunnel_id: str, hostname: str, local_port: int) -> Path:
    """Create cloudflared config file for a tunnel."""
    config_path = CLOUDFLARED_CONFIG_DIR / f"config-{hostname.split('.')[0]}.yml"
    creds_path = CLOUDFLARED_CONFIG_DIR / f"{tunnel_id}.json"
    
    config_content = f"""tunnel: {tunnel_id}
credentials-file: {creds_path}

ingress:
  - hostname: {hostname}
    service: http://localhost:{local_port}
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false
  - service: http_status:404
"""
    
    config_path.write_text(config_content)
    logger.info(f"Created tunnel config: {config_path}")
    return config_path


def create_launchd_plist(service_name: str, config_path: Path) -> Path:
    """Create launchd plist for a tunnel service."""
    plist_path = LAUNCH_AGENTS_DIR / f"{service_name}.plist"
    
    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{service_name}</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>{CLOUDFLARED_PATH}</string>
        <string>tunnel</string>
        <string>--config</string>
        <string>{config_path}</string>
        <string>run</string>
    </array>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>{LOG_DIR}/cloudflared-stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/cloudflared-stderr.log</string>
</dict>
</plist>
"""
    
    plist_path.write_text(plist_content)
    logger.info(f"Created launchd plist: {plist_path}")
    return plist_path


def unload_service(service_name: str) -> bool:
    """Unload a launchd service."""
    plist_path = LAUNCH_AGENTS_DIR / f"{service_name}.plist"
    try:
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


def load_service(service_name: str) -> bool:
    """Load a launchd service."""
    plist_path = LAUNCH_AGENTS_DIR / f"{service_name}.plist"
    try:
        result = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to load service {service_name}: {e}")
        return False


def find_tunnel_services_by_pattern(pattern: str) -> list[str]:
    """Find launchd services matching a pattern."""
    services = []
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.split("\n"):
            if pattern in line:
                parts = line.split()
                if len(parts) >= 3:
                    services.append(parts[2])  # Service name is the third column
    except Exception:
        pass
    return services


def cleanup_old_tunnel_services(old_client_id: str) -> None:
    """Stop and remove tunnel services for an old client ID."""
    old_bridge_service = f"com.nightline.cloudflare-tunnel-bridge-{old_client_id}"
    old_manage_service = f"com.nightline.cloudflare-tunnel-manage-{old_client_id}"
    
    for service in [old_bridge_service, old_manage_service]:
        logger.info(f"Cleaning up old service: {service}")
        unload_service(service)
        
        # Remove plist file
        plist_path = LAUNCH_AGENTS_DIR / f"{service}.plist"
        if plist_path.exists():
            plist_path.unlink()
            logger.info(f"Removed: {plist_path}")


def setup_tunnels_for_client(client_id: str, old_client_id: Optional[str] = None) -> dict:
    """
    Set up or reconfigure Cloudflare tunnels for a client ID.
    
    Args:
        client_id: The new client ID to configure tunnels for
        old_client_id: Optional old client ID to clean up
        
    Returns:
        dict with success status and details
    """
    if not is_cloudflared_installed():
        return {
            "success": False,
            "error": "cloudflared not installed",
            "message": "Install cloudflared with: brew install cloudflared",
        }
    
    # Check if authenticated with Cloudflare
    creds_exist = any(CLOUDFLARED_CONFIG_DIR.glob("*.json"))
    if not creds_exist:
        return {
            "success": False,
            "error": "cloudflared not authenticated",
            "message": "Run 'cloudflared tunnel login' first",
        }
    
    results = {
        "success": True,
        "bridge_tunnel": None,
        "manage_tunnel": None,
        "errors": [],
    }
    
    # Clean up old services if client ID changed
    if old_client_id and old_client_id != client_id:
        logger.info(f"Client ID changed from {old_client_id} to {client_id}, cleaning up old tunnels")
        cleanup_old_tunnel_services(old_client_id)
    
    # Set up bridge tunnel
    bridge_tunnel_name = f"bridge-{client_id}"
    bridge_hostname = f"{bridge_tunnel_name}.{TUNNEL_DOMAIN}"
    bridge_service = f"com.nightline.cloudflare-tunnel-bridge-{client_id}"
    
    bridge_tunnel_id = get_tunnel_id_by_name(bridge_tunnel_name)
    if not bridge_tunnel_id:
        bridge_tunnel_id = create_tunnel(bridge_tunnel_name)
        if not bridge_tunnel_id:
            results["errors"].append(f"Failed to create bridge tunnel")
            results["success"] = False
        else:
            route_dns(bridge_tunnel_name, bridge_hostname)
    
    if bridge_tunnel_id:
        config_path = create_tunnel_config(bridge_tunnel_id, bridge_hostname, 8080)
        plist_path = create_launchd_plist(bridge_service, config_path)
        unload_service(bridge_service)
        if load_service(bridge_service):
            results["bridge_tunnel"] = {
                "name": bridge_tunnel_name,
                "id": bridge_tunnel_id,
                "hostname": bridge_hostname,
                "service": bridge_service,
            }
        else:
            results["errors"].append("Failed to start bridge tunnel service")
    
    # Set up management tunnel
    manage_tunnel_name = f"manage-{client_id}"
    manage_hostname = f"{manage_tunnel_name}.{TUNNEL_DOMAIN}"
    manage_service = f"com.nightline.cloudflare-tunnel-manage-{client_id}"
    
    manage_tunnel_id = get_tunnel_id_by_name(manage_tunnel_name)
    if not manage_tunnel_id:
        manage_tunnel_id = create_tunnel(manage_tunnel_name)
        if not manage_tunnel_id:
            results["errors"].append(f"Failed to create management tunnel")
            results["success"] = False
        else:
            route_dns(manage_tunnel_name, manage_hostname)
    
    if manage_tunnel_id:
        config_path = create_tunnel_config(manage_tunnel_id, manage_hostname, 8081)
        plist_path = create_launchd_plist(manage_service, config_path)
        unload_service(manage_service)
        if load_service(manage_service):
            results["manage_tunnel"] = {
                "name": manage_tunnel_name,
                "id": manage_tunnel_id,
                "hostname": manage_hostname,
                "service": manage_service,
            }
        else:
            results["errors"].append("Failed to start management tunnel service")
    
    if results["errors"]:
        results["success"] = False
    
    return results


def get_current_tunnel_status(client_id: str) -> dict:
    """Get current status of tunnels for a client ID."""
    bridge_service = f"com.nightline.cloudflare-tunnel-bridge-{client_id}"
    manage_service = f"com.nightline.cloudflare-tunnel-manage-{client_id}"
    
    # Check launchctl
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        launchctl_output = result.stdout
    except Exception:
        launchctl_output = ""
    
    # Check for cloudflared process
    try:
        result = subprocess.run(
            ["pgrep", "-la", "cloudflared"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        cloudflared_processes = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except Exception:
        cloudflared_processes = []
    
    return {
        "client_id": client_id,
        "bridge_service": {
            "name": bridge_service,
            "running": bridge_service in launchctl_output,
        },
        "manage_service": {
            "name": manage_service,
            "running": manage_service in launchctl_output,
        },
        "cloudflared_processes": cloudflared_processes,
        "expected_bridge_url": f"https://bridge-{client_id}.{TUNNEL_DOMAIN}",
        "expected_manage_url": f"https://manage-{client_id}.{TUNNEL_DOMAIN}",
    }
