"""Health and status routes."""

import platform
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from management.auth import require_auth
from management.config import settings
from management.routes.services import get_all_services, get_service_status

router = APIRouter(tags=["health"])

_start_time = time.time()


class HealthResponse(BaseModel):
    status: str  # "healthy", "degraded", "unhealthy"
    uptime_seconds: float
    services: dict
    bridge_health: Optional[dict]
    system: dict


@router.get("/health")
async def health() -> HealthResponse:
    """
    Management agent health check.
    
    No auth required - used for monitoring.
    """
    # Check services
    all_services = get_all_services()
    services = {
        name: get_service_status(label)
        for name, label in all_services.items()
    }
    
    # Try to get bridge health
    bridge_health = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:8080/health")
            if resp.status_code == 200:
                bridge_health = resp.json()
    except:
        pass
    
    # Determine status
    if not services.get("bridge") or not services.get("tunnel"):
        status = "unhealthy"
    elif bridge_health and bridge_health.get("status") == "degraded":
        status = "degraded"
    elif bridge_health and bridge_health.get("status") == "healthy":
        status = "healthy"
    else:
        status = "degraded"
    
    return HealthResponse(
        status=status,
        uptime_seconds=time.time() - _start_time,
        services=services,
        bridge_health=bridge_health,
        system={
            "hostname": platform.node(),
            "platform": platform.platform(),
        },
    )


@router.get("/api/status", dependencies=[Depends(require_auth)])
async def detailed_status() -> dict:
    """
    Detailed system status (authenticated).
    """
    health = await health()
    
    return {
        **health.model_dump(),
        "config": {
            "tunnel_url": settings.tunnel_url,
            "management_url": settings.management_url,
            "log_dir": str(settings.log_dir),
            "install_dir": str(settings.install_dir),
        },
    }
