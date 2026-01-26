"""Log viewing routes."""

import asyncio
import subprocess
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from management.auth import require_auth, verify_token
from management.config import settings

router = APIRouter(prefix="/api/logs", tags=["logs"])

LOG_FILES = {
    "bridge": "bridge.log",
    "tunnel": "tunnel.log",
    "updater": "updater.log",
    "management": "management.log",
}


def get_log_path(log_name: str) -> Path:
    """Get path to a log file."""
    if log_name not in LOG_FILES:
        raise HTTPException(404, f"Unknown log: {log_name}")
    return settings.log_dir / LOG_FILES[log_name]


@router.get("/{log_name}", dependencies=[Depends(require_auth)])
async def get_logs(
    log_name: str,
    lines: int = 100,
    grep: str | None = None,
) -> dict:
    """
    Get recent log lines.
    
    Args:
        log_name: Which log to read (bridge, tunnel, updater, management)
        lines: Number of lines to return (default 100, max 1000)
        grep: Optional filter pattern
    """
    log_path = get_log_path(log_name)
    
    if not log_path.exists():
        return {"lines": [], "path": str(log_path), "exists": False}
    
    lines = min(lines, 1000)  # Cap at 1000
    
    try:
        if grep:
            # Use grep to filter
            result = subprocess.run(
                ["grep", "-i", grep, str(log_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            all_lines = result.stdout.splitlines()
            return {
                "lines": all_lines[-lines:],
                "path": str(log_path),
                "exists": True,
                "filtered": True,
                "pattern": grep,
            }
        else:
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return {
                "lines": result.stdout.splitlines(),
                "path": str(log_path),
                "exists": True,
            }
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Log read timed out")
    except Exception as e:
        raise HTTPException(500, f"Failed to read log: {e}")


@router.websocket("/ws/{log_name}")
async def stream_logs(websocket: WebSocket, log_name: str, token: str | None = None):
    """
    Stream logs via WebSocket.
    
    Connect with: ws://host/api/logs/ws/bridge?token=YOUR_TOKEN
    """
    # Verify token from query param
    if not token or not verify_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return
    
    await websocket.accept()
    
    log_path = get_log_path(log_name)
    
    if not log_path.exists():
        await websocket.send_json({"error": f"Log file not found: {log_path}"})
        await websocket.close()
        return
    
    process = None
    try:
        # Start tail -f process
        process = await asyncio.create_subprocess_exec(
            "tail", "-f", "-n", "50", str(log_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        while True:
            line = await process.stdout.readline()
            if line:
                await websocket.send_text(line.decode().rstrip())
            else:
                await asyncio.sleep(0.1)
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass
    finally:
        if process:
            process.terminate()
            try:
                await process.wait()
            except:
                pass
