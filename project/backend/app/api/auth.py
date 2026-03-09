"""
Admin authentication module
Simple password-based authentication for admin portal
"""
import asyncio
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

# Session store: token → {user_id, username, role, created_at}
active_sessions: Dict[str, Dict] = {}
_session_lock = asyncio.Lock()

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


async def create_session(user_id: str = "superadmin", username: str = "admin", role: str = "admin") -> str:
    """Create a new session token with user info."""
    token = secrets.token_urlsafe(32)
    async with _session_lock:
        active_sessions[token] = {
            "user_id": user_id,
            "username": username,
            "role": role,
            "created_at": datetime.now(timezone.utc),
        }
    logger.info(f"Created session for {username}: {token[:8]}...")
    return token


async def validate_session(token: str) -> Optional[Dict]:
    """Validate session. Returns session dict with user info, or None."""
    async with _session_lock:
        if token not in active_sessions:
            return None
        session = active_sessions[token]
        if datetime.now(timezone.utc) - session["created_at"] > timedelta(hours=SESSION_EXPIRY_HOURS):
            del active_sessions[token]
            logger.info(f"Session expired: {token[:8]}...")
            return None
        # Keep-alive
        session["created_at"] = datetime.now(timezone.utc)
        return session


async def _revoke_session_locked(token: str) -> bool:
    async with _session_lock:
        if token in active_sessions:
            del active_sessions[token]
            logger.info(f"Revoked session: {token[:8]}...")
            return True
    return False


def revoke_session(token: str) -> bool:
    """Revoke an admin session."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_revoke_session_locked(token))
    existed = token in active_sessions
    loop.create_task(_revoke_session_locked(token))
    return existed


async def authenticate(password: str) -> Optional[str]:
    """Legacy: authenticate with just admin password (superadmin fallback)."""
    if bcrypt.checkpw(password.encode('utf-8'), _get_hashed_password()):
        return await create_session(user_id="superadmin", username="admin", role="admin")
    return None


async def authenticate_user_credentials(username: str, password: str) -> Optional[tuple]:
    """Authenticate with username+password. Returns (token, user_dict) or None."""
    from app.services.user_service import user_service
    user = await user_service.authenticate_user(username, password)
    if user:
        token = await create_session(user_id=user["id"], username=user["username"], role=user["role"])
        return token, user
    return None


async def cleanup_expired_sessions():
    """Remove expired sessions from memory."""
    now = datetime.now(timezone.utc)
    async with _session_lock:
        expired = [token for token, session in active_sessions.items()
                   if (now - session.get("created_at", now)).total_seconds() > SESSION_EXPIRY_HOURS * 3600]
        for token in expired:
            del active_sessions[token]
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired sessions")


async def require_admin_auth(authorization: Optional[str] = Header(None)) -> Dict:
    """Dependency to require admin authentication. Returns session info."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    token = authorization[7:]
    session = await validate_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session"
        )
    return session


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
