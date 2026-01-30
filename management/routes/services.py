"""Service control routes."""

import os
import subprocess
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from management.auth import require_auth

router = APIRouter(prefix="/api/services", tags=["services"])

# Service definitions
# Note: Tunnel services are client-specific, these are base patterns
SERVICES = {
    "bridge": "com.nightline.iphone-bridge",
    "updater": "com.nightline.iphone-bridge-updater",
    "management": "com.nightline.management-agent",
}


def get_tunnel_services() -> dict[str, str]:
    """Get tunnel service labels (client-specific).
    
    Checks both naming patterns:
    - New (bootstrap.sh): com.nightline.cloudflare-tunnel-bridge-{client_id}
    - Old (setup-tunnel.sh): com.cloudflare.tunnel-{client_id}
    """
    from management.config import settings
    client_id = settings.nightline_client_id
    if client_id:
        return {
            "tunnel-bridge": f"com.nightline.cloudflare-tunnel-bridge-{client_id}",
            "tunnel-manage": f"com.nightline.cloudflare-tunnel-manage-{client_id}",
        }
    return {}


def is_cloudflared_running() -> bool:
    """Check if cloudflared process is running (regardless of launchd)."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "cloudflared"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_alternate_tunnel_status() -> bool:
    """Check for tunnels under alternate naming patterns."""
    from management.config import settings
    client_id = settings.nightline_client_id
    
    # Check old naming pattern: com.cloudflare.tunnel-{client_id}
    if client_id:
        try:
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            old_pattern = f"com.cloudflare.tunnel-{client_id}"
            if old_pattern in result.stdout:
                return True
        except Exception:
            pass
    
    # Fallback: check if cloudflared process is running at all
    return is_cloudflared_running()


class ServiceStatus(BaseModel):
    name: str
    label: str
    running: bool


class ServiceAction(BaseModel):
    success: bool
    message: str


def get_service_status(label: str, check_alternate: bool = False) -> bool:
    """Check if a launchd service is running.
    
    Args:
        label: The launchd service label to check
        check_alternate: If True and service not found, check alternate tunnel patterns
    """
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if label in result.stdout:
            return True
        
        # For tunnel services, check alternate patterns if primary not found
        if check_alternate and "tunnel" in label:
            return get_alternate_tunnel_status()
        
        return False
    except Exception:
        return False


def restart_service(label: str) -> tuple[bool, str]:
    """Restart a launchd service."""
    try:
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Service restarting"
        return False, result.stderr or "Failed to restart"
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def stop_service(label: str) -> tuple[bool, str]:
    """Stop a launchd service."""
    try:
        plist_path = f"{os.path.expanduser('~')}/Library/LaunchAgents/{label}.plist"
        result = subprocess.run(
            ["launchctl", "unload", plist_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Service stopped"
        return False, result.stderr or "Failed to stop"
    except Exception as e:
        return False, str(e)


def start_service(label: str) -> tuple[bool, str]:
    """Start a launchd service."""
    try:
        plist_path = f"{os.path.expanduser('~')}/Library/LaunchAgents/{label}.plist"
        result = subprocess.run(
            ["launchctl", "load", plist_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Service started"
        return False, result.stderr or "Failed to start"
    except Exception as e:
        return False, str(e)


@router.get("", dependencies=[Depends(require_auth)])
async def list_services() -> dict[str, ServiceStatus]:
    """Get status of all services."""
    all_services = {**SERVICES, **get_tunnel_services()}
    return {
        name: ServiceStatus(
            name=name,
            label=label,
            running=get_service_status(label, check_alternate="tunnel" in name),
        )
        for name, label in all_services.items()
    }


def get_all_services() -> dict[str, str]:
    """Get all service labels including tunnels."""
    return {**SERVICES, **get_tunnel_services()}


@router.get("/{service}", dependencies=[Depends(require_auth)])
async def get_service(service: str) -> ServiceStatus:
    """Get status of a specific service."""
    all_services = get_all_services()
    if service not in all_services:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    
    label = all_services[service]
    return ServiceStatus(
        name=service,
        label=label,
        running=get_service_status(label, check_alternate="tunnel" in service),
    )


@router.post("/{service}/restart", dependencies=[Depends(require_auth)])
async def restart(service: str) -> ServiceAction:
    """Restart a service."""
    all_services = get_all_services()
    if service not in all_services:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    
    success, message = restart_service(all_services[service])
    return ServiceAction(success=success, message=message)


@router.post("/{service}/stop", dependencies=[Depends(require_auth)])
async def stop(service: str) -> ServiceAction:
    """Stop a service."""
    all_services = get_all_services()
    if service not in all_services:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    
    if service == "management":
        raise HTTPException(
            status_code=400,
            detail="Cannot stop management agent from itself. Use SSH.",
        )
    
    success, message = stop_service(all_services[service])
    return ServiceAction(success=success, message=message)


@router.post("/{service}/start", dependencies=[Depends(require_auth)])
async def start(service: str) -> ServiceAction:
    """Start a service."""
    all_services = get_all_services()
    if service not in all_services:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    
    success, message = start_service(all_services[service])
    return ServiceAction(success=success, message=message)


class TunnelDiagnostics(BaseModel):
    """Diagnostic info for tunnel debugging."""
    client_id: str | None
    cloudflared_process_running: bool
    cloudflared_pids: list[int]
    launchctl_services: list[str]
    plist_files: list[str]
    expected_service_names: dict[str, str]
    tunnel_log_tail: str | None


@router.get("/diagnostics/tunnel", dependencies=[Depends(require_auth)])
async def tunnel_diagnostics() -> TunnelDiagnostics:
    """Get detailed tunnel diagnostics for debugging."""
    from management.config import settings
    client_id = settings.nightline_client_id
    
    # Check cloudflared process
    cloudflared_pids = []
    try:
        result = subprocess.run(
            ["pgrep", "-x", "cloudflared"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            cloudflared_pids = [int(p) for p in result.stdout.strip().split("\n") if p]
    except Exception:
        pass
    
    # Get all launchctl services matching our patterns
    launchctl_services = []
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if "cloudflare" in line.lower() or "nightline" in line.lower():
                launchctl_services.append(line.strip())
    except Exception:
        pass
    
    # List plist files
    plist_files = []
    launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    try:
        for f in os.listdir(launch_agents_dir):
            if "cloudflare" in f.lower() or "nightline" in f.lower():
                plist_files.append(f)
    except Exception:
        pass
    
    # Expected service names
    expected = {}
    if client_id:
        expected = {
            "tunnel-bridge (new)": f"com.nightline.cloudflare-tunnel-bridge-{client_id}",
            "tunnel-manage (new)": f"com.nightline.cloudflare-tunnel-manage-{client_id}",
            "tunnel (old)": f"com.cloudflare.tunnel-{client_id}",
        }
    
    # Get tunnel log tail
    log_tail = None
    log_paths = [
        "/var/log/iphone-bridge/cloudflared-stderr.log",
        "/var/log/iphone-bridge/cloudflared-stdout.log",
    ]
    for log_path in log_paths:
        try:
            if os.path.exists(log_path):
                result = subprocess.run(
                    ["tail", "-30", log_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout:
                    log_tail = result.stdout
                    break
        except Exception:
            pass
    
    return TunnelDiagnostics(
        client_id=client_id,
        cloudflared_process_running=len(cloudflared_pids) > 0,
        cloudflared_pids=cloudflared_pids,
        launchctl_services=launchctl_services,
        plist_files=plist_files,
        expected_service_names=expected,
        tunnel_log_tail=log_tail,
    )
