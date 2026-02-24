"""
Admin authentication module
Simple password-based authentication for admin portal
"""
import os
import secrets
import time
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from fastapi import HTTPException, Header
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Simple in-memory session store (for demo purposes)
# In production, use Redis or database
active_sessions: Dict[str, datetime] = {}

# Session expiry
SESSION_EXPIRY_HOURS = 24

# Bcrypt hashed password (hashed on first use from settings)
_hashed_password = None

def _get_hashed_password():
    global _hashed_password
    if _hashed_password is None:
        _hashed_password = bcrypt.hashpw(
            settings.admin_password.encode('utf-8'),
            bcrypt.gensalt()
        )
    return _hashed_password

# Login rate limiting
_login_attempts = {}  # IP -> (count, first_attempt_time)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = 900  # 15 minutes

def check_rate_limit(client_ip: str) -> bool:
    """Check if login attempts from this IP are within limits."""
    now = time.time()
    if client_ip in _login_attempts:
        count, first_time = _login_attempts[client_ip]
        if now - first_time > LOGIN_WINDOW:
            _login_attempts[client_ip] = (1, now)
            return True
        if count >= MAX_LOGIN_ATTEMPTS:
            return False
        _login_attempts[client_ip] = (count + 1, first_time)
    else:
        _login_attempts[client_ip] = (1, now)
    return True


def create_session() -> str:
    """Create a new admin session token."""
    token = secrets.token_urlsafe(32)
    active_sessions[token] = datetime.now(timezone.utc)
    logger.info(f"Created admin session: {token[:8]}...")
    return token


def validate_session(token: str) -> bool:
    """Validate an admin session token."""
    if token not in active_sessions:
        return False
    
    # Check if session has expired
    session_time = active_sessions[token]
    if datetime.now(timezone.utc) - session_time > timedelta(hours=SESSION_EXPIRY_HOURS):
        # Session expired, remove it
        del active_sessions[token]
        logger.info(f"Session expired: {token[:8]}...")
        return False
    
    # Update session time (keep-alive)
    active_sessions[token] = datetime.now(timezone.utc)
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
    if bcrypt.checkpw(password.encode('utf-8'), _get_hashed_password()):
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


# ─── Per-API-key rate limiter ─────────────────────────────
_api_key_requests: Dict[str, list] = {}  # key_id -> [timestamps]


async def require_api_key(x_api_key: Optional[str] = Header(None)) -> Dict:
    """Dependency that validates an X-API-Key header and enforces per-key rate limits."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    from app.services.api_key_service import api_key_service

    key_meta = await api_key_service.validate_key(x_api_key)
    if key_meta is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Per-key rate limiting
    key_id = key_meta["id"]
    rpm = key_meta.get("rate_limit_rpm", 30)
    now = time.time()
    window = _api_key_requests.setdefault(key_id, [])
    cutoff = now - 60
    _api_key_requests[key_id] = [t for t in window if t > cutoff]
    if len(_api_key_requests[key_id]) >= rpm:
        raise HTTPException(
            status_code=429,
            detail="API key rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    _api_key_requests[key_id].append(now)

    return key_meta
