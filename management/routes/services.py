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
    """Get tunnel service labels (client-specific)."""
    from management.config import settings
    client_id = settings.nightline_client_id
    if client_id:
        return {
            "tunnel-bridge": f"com.nightline.cloudflare-tunnel-bridge-{client_id}",
            "tunnel-manage": f"com.nightline.cloudflare-tunnel-manage-{client_id}",
        }
    return {}


class ServiceStatus(BaseModel):
    name: str
    label: str
    running: bool


class ServiceAction(BaseModel):
    success: bool
    message: str


def get_service_status(label: str) -> bool:
    """Check if a launchd service is running."""
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return label in result.stdout
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
            running=get_service_status(label),
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
        running=get_service_status(label),
    )


@router.post("/{service}/restart", dependencies=[Depends(require_auth)])
async def restart(service: str) -> ServiceAction:
    """Restart a service."""
    all_services = get_all_services()
    if service not in all_services:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    
    # Don't allow restarting management from itself
    if service == "management":
        raise HTTPException(
            status_code=400,
            detail="Cannot restart management agent from itself. Use SSH.",
        )
    
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
