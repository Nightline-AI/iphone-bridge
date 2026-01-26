"""Bridge control routes - pause, resume, clear queue."""

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from management.auth import require_auth
from management.routes.config import read_env

router = APIRouter(prefix="/api/control", tags=["control"])

BRIDGE_URL = "http://localhost:8080"


def get_bridge_secret() -> str:
    """Get webhook secret from .env to authenticate with bridge."""
    env = read_env()
    return env.get("WEBHOOK_SECRET", "")


class PauseRequest(BaseModel):
    """Request to pause bridge operations."""
    pause_inbound: bool = False  # Stop receiving messages entirely
    pause_outbound: bool = False  # Stop sending messages (queue them instead)


class PauseResponse(BaseModel):
    """Response with current pause state."""
    pause_inbound: bool
    pause_outbound: bool
    outbound_queue_size: int
    message: str


class ControlStatusResponse(BaseModel):
    """Current control status."""
    pause_inbound: bool
    pause_outbound: bool
    outbound_queue_size: int
    outbound_queue: list[dict]
    retry_queue_size: int


class ClearQueueResponse(BaseModel):
    """Response after clearing queue."""
    cleared_count: int
    message: str


@router.get("/status", dependencies=[Depends(require_auth)])
async def get_control_status() -> ControlStatusResponse:
    """Get current pause state and queue status."""
    secret = get_bridge_secret()
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BRIDGE_URL}/control/status",
                headers={"X-Bridge-Secret": secret},
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return ControlStatusResponse(**data)
            else:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Bridge returned {resp.status_code}",
                )
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot connect to bridge")
    except httpx.TimeoutException:
        raise HTTPException(504, "Bridge request timed out")


@router.post("/pause", dependencies=[Depends(require_auth)])
async def pause_bridge(request: PauseRequest) -> PauseResponse:
    """
    Pause bridge operations.
    
    - pause_inbound: Won't process incoming messages at all (completely paused)
    - pause_outbound: Will receive messages but won't send any to contacts (queued)
    """
    secret = get_bridge_secret()
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BRIDGE_URL}/control/pause",
                headers={"X-Bridge-Secret": secret},
                json=request.model_dump(),
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return PauseResponse(**data)
            else:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Bridge returned {resp.status_code}",
                )
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot connect to bridge")
    except httpx.TimeoutException:
        raise HTTPException(504, "Bridge request timed out")


@router.post("/resume", dependencies=[Depends(require_auth)])
async def resume_bridge(send_queued: bool = True) -> PauseResponse:
    """
    Resume bridge operations and optionally send queued messages.
    
    Args:
        send_queued: If true (default), send all queued outbound messages.
    """
    secret = get_bridge_secret()
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:  # Longer timeout for sending queued
            resp = await client.post(
                f"{BRIDGE_URL}/control/resume",
                headers={"X-Bridge-Secret": secret},
                params={"send_queued": str(send_queued).lower()},
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return PauseResponse(**data)
            else:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Bridge returned {resp.status_code}",
                )
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot connect to bridge")
    except httpx.TimeoutException:
        raise HTTPException(504, "Bridge request timed out")


@router.post("/clear-queue", dependencies=[Depends(require_auth)])
async def clear_queue() -> ClearQueueResponse:
    """Clear all queued outbound messages without sending them."""
    secret = get_bridge_secret()
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BRIDGE_URL}/control/clear-queue",
                headers={"X-Bridge-Secret": secret},
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return ClearQueueResponse(**data)
            else:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Bridge returned {resp.status_code}",
                )
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot connect to bridge")
    except httpx.TimeoutException:
        raise HTTPException(504, "Bridge request timed out")
