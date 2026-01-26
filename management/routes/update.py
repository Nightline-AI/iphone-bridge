"""Update management routes."""

import subprocess
import os
from pathlib import Path

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel

from management.auth import require_auth
from management.config import settings

router = APIRouter(prefix="/api/update", tags=["update"])


class UpdateStatus(BaseModel):
    current_commit: str
    current_branch: str
    has_updates: bool
    remote_commit: str | None = None


class UpdateResult(BaseModel):
    success: bool
    message: str
    old_commit: str | None = None
    new_commit: str | None = None


def run_git(args: list[str], cwd: Path) -> tuple[bool, str]:
    """Run a git command and return (success, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


@router.get("", dependencies=[Depends(require_auth)])
async def check_for_updates() -> UpdateStatus:
    """Check if updates are available."""
    install_dir = settings.install_dir
    
    # Get current commit
    ok, current = run_git(["rev-parse", "HEAD"], install_dir)
    current_commit = current[:12] if ok else "unknown"
    
    # Get current branch
    ok, branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], install_dir)
    current_branch = branch if ok else "unknown"
    
    # Fetch from remote
    run_git(["fetch", "origin", current_branch], install_dir)
    
    # Get remote commit
    ok, remote = run_git(["rev-parse", f"origin/{current_branch}"], install_dir)
    remote_commit = remote[:12] if ok else None
    
    has_updates = remote_commit is not None and current_commit != remote_commit
    
    return UpdateStatus(
        current_commit=current_commit,
        current_branch=current_branch,
        has_updates=has_updates,
        remote_commit=remote_commit if has_updates else None,
    )


def do_update(install_dir: Path):
    """Perform the actual update (runs in background)."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Get current commit
    _, old_commit = run_git(["rev-parse", "HEAD"], install_dir)
    
    # Pull changes
    ok, output = run_git(["pull", "origin", "main"], install_dir)
    if not ok:
        run_git(["pull", "origin", "master"], install_dir)
    
    logger.info(f"Git pull: {output}")
    
    # Install dependencies
    venv_pip = install_dir / ".venv" / "bin" / "pip"
    if venv_pip.exists():
        subprocess.run(
            [str(venv_pip), "install", "-q", "fastapi", "uvicorn[standard]", 
             "pydantic", "pydantic-settings", "httpx", "watchdog", "python-multipart"],
            cwd=install_dir,
            capture_output=True,
        )
    
    # Restart services
    uid = os.getuid()
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.nightline.iphone-bridge"], capture_output=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.nightline.management-agent"], capture_output=True)
    
    logger.info("Update complete, services restarted")


@router.post("", dependencies=[Depends(require_auth)])
async def perform_update(background_tasks: BackgroundTasks) -> UpdateResult:
    """
    Pull latest code and restart services.
    
    Runs in background - services will restart after response.
    """
    install_dir = settings.install_dir
    
    # Get current commit before update
    _, old_commit = run_git(["rev-parse", "HEAD"], install_dir)
    
    # Schedule update in background (so we can return response before restart)
    background_tasks.add_task(do_update, install_dir)
    
    return UpdateResult(
        success=True,
        message="Update started. Services will restart shortly.",
        old_commit=old_commit[:12] if old_commit else None,
    )
