"""Configuration management routes."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from management.auth import require_auth
from management.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


class BridgeConfig(BaseModel):
    nightline_server_url: str
    nightline_client_id: str
    webhook_secret: str
    poll_interval: float
    log_level: str


class ConfigResponse(BaseModel):
    config: BridgeConfig
    tunnel_url: Optional[str]
    management_url: Optional[str]


class ConfigUpdate(BaseModel):
    nightline_server_url: Optional[str] = None
    nightline_client_id: Optional[str] = None
    webhook_secret: Optional[str] = None
    poll_interval: Optional[float] = None
    log_level: Optional[str] = None


def read_env() -> dict[str, str]:
    """Read current .env configuration."""
    config = {}
    env_path = settings.env_file_path
    
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    return config


def write_env(updates: dict[str, str]) -> None:
    """Update .env file with new values, preserving comments and structure."""
    env_path = settings.env_file_path
    lines = []
    updated_keys = set()

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    updated_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)

    # Add new keys that weren't in the file
    for key, value in updates.items():
        if key not in updated_keys:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


@router.get("", dependencies=[Depends(require_auth)])
async def get_config() -> ConfigResponse:
    """Get current bridge configuration."""
    env = read_env()
    
    return ConfigResponse(
        config=BridgeConfig(
            nightline_server_url=env.get("NIGHTLINE_SERVER_URL", ""),
            nightline_client_id=env.get("NIGHTLINE_CLIENT_ID", ""),
            webhook_secret=env.get("WEBHOOK_SECRET", ""),
            poll_interval=float(env.get("POLL_INTERVAL", "2.0")),
            log_level=env.get("LOG_LEVEL", "INFO"),
        ),
        tunnel_url=settings.tunnel_url,
        management_url=settings.management_url,
    )


@router.patch("", dependencies=[Depends(require_auth)])
async def update_config(update: ConfigUpdate) -> dict:
    """
    Update bridge configuration.
    
    Only updates provided fields. Restart bridge after updating.
    """
    updates = {}
    
    if update.nightline_server_url is not None:
        updates["NIGHTLINE_SERVER_URL"] = update.nightline_server_url
    if update.nightline_client_id is not None:
        updates["NIGHTLINE_CLIENT_ID"] = update.nightline_client_id
    if update.webhook_secret is not None:
        updates["WEBHOOK_SECRET"] = update.webhook_secret
    if update.poll_interval is not None:
        updates["POLL_INTERVAL"] = str(update.poll_interval)
    if update.log_level is not None:
        if update.log_level.upper() not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            raise HTTPException(400, "Invalid log level")
        updates["LOG_LEVEL"] = update.log_level.upper()

    if not updates:
        raise HTTPException(400, "No updates provided")

    write_env(updates)
    
    return {
        "success": True,
        "message": "Configuration updated. Restart bridge to apply changes.",
        "updated_keys": list(updates.keys()),
    }
