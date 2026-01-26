"""Authentication for Management Agent."""

import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Cookie, Header, HTTPException, status

from management.config import settings


def verify_token(token: str) -> bool:
    """Securely compare token against configured management token."""
    if not settings.management_token:
        return False
    return hmac.compare_digest(token, settings.management_token)


async def require_auth(
    authorization: Optional[str] = Header(None),
    mgmt_session: Optional[str] = Cookie(None),
) -> str:
    """
    Dependency that requires valid authentication.
    
    Accepts either:
    - Authorization: Bearer <token> header
    - mgmt_session cookie
    
    Returns the validated token.
    """
    token = None

    # Check header first
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization

    # Fall back to cookie
    if not token and mgmt_session:
        token = mgmt_session

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_hex(32)
