"""
Admin authentication module
Simple password-based authentication for admin portal
"""
import os
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import HTTPException, Header
import logging

logger = logging.getLogger(__name__)

# Simple in-memory session store (for demo purposes)
# In production, use Redis or database
active_sessions: Dict[str, datetime] = {}

# Admin credentials (in production, use proper password hashing and DB)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "DetectiveRay2026")
SESSION_EXPIRY_HOURS = 24


def create_session() -> str:
    """Create a new admin session token."""
    token = secrets.token_urlsafe(32)
    active_sessions[token] = datetime.utcnow()
    logger.info(f"Created admin session: {token[:8]}...")
    return token


def validate_session(token: str) -> bool:
    """Validate an admin session token."""
    if token not in active_sessions:
        return False
    
    # Check if session has expired
    session_time = active_sessions[token]
    if datetime.utcnow() - session_time > timedelta(hours=SESSION_EXPIRY_HOURS):
        # Session expired, remove it
        del active_sessions[token]
        logger.info(f"Session expired: {token[:8]}...")
        return False
    
    # Update session time (keep-alive)
    active_sessions[token] = datetime.utcnow()
    return True


def revoke_session(token: str) -> bool:
    """Revoke an admin session."""
    if token in active_sessions:
        del active_sessions[token]
        logger.info(f"Revoked session: {token[:8]}...")
        return True
    return False


def authenticate(password: str) -> Optional[str]:
    """Authenticate with password and return session token if successful."""
    if password == ADMIN_PASSWORD:
        return create_session()
    return None


def require_admin_auth(authorization: Optional[str] = Header(None)) -> None:
    """Dependency to require admin authentication."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization header"
        )
    
    # Expected format: "Bearer <token>"
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization format"
        )
    
    token = authorization[7:]  # Remove "Bearer " prefix
    
    if not validate_session(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )
