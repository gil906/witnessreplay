"""
User account management service.
Handles registration, authentication, and user profile management.
"""
import json
import logging
import uuid
import bcrypt
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from app.services.database import get_database

logger = logging.getLogger(__name__)


class UserService:
    """Manages user accounts for WitnessReplay."""

    def __init__(self):
        self._db = None

    async def initialize(self):
        """Get reference to the shared database."""
        self._db = get_database()
        logger.info("UserService initialized")

    async def create_user(
        self,
        username: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        full_name: str = "",
        role: str = "officer",
        auth_provider: str = "local",
        provider_id: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new user account. Returns user dict (without password_hash)."""
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        # Hash password if provided (local auth)
        password_hash = None
        if password:
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        try:
            db = self._db
            await db._db.execute(
                """INSERT INTO users (id, username, email, password_hash, full_name, role, auth_provider, provider_id, avatar_url, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (user_id, username.lower().strip(), email.lower().strip() if email else None, password_hash, full_name, role, auth_provider, provider_id, avatar_url, now)
            )
            await db._db.commit()
            
            logger.info(f"Created user: {username} (id={user_id[:8]}, provider={auth_provider})")
            return {
                "id": user_id,
                "username": username.lower().strip(),
                "email": email.lower().strip() if email else None,
                "full_name": full_name,
                "role": role,
                "auth_provider": auth_provider,
                "avatar_url": avatar_url,
                "is_active": True,
                "created_at": now,
            }
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                if "username" in str(e):
                    raise ValueError("Username already taken")
                if "email" in str(e):
                    raise ValueError("Email already registered")
            raise

    async def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate with username + password. Returns user dict or None."""
        db = self._db
        cursor = await db._db.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username.lower().strip(),)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        
        user = dict(row)
        if not user.get("password_hash"):
            return None  # OAuth-only user, can't login with password
        
        if bcrypt.checkpw(password.encode('utf-8'), user["password_hash"].encode('utf-8')):
            # Update last login
            await db._db.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), user["id"])
            )
            await db._db.commit()
            return self._sanitize_user(user)
        return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        db = self._db
        cursor = await db._db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return self._sanitize_user(dict(row)) if row else None

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        db = self._db
        cursor = await db._db.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (email.lower().strip(),))
        row = await cursor.fetchone()
        return self._sanitize_user(dict(row)) if row else None

    async def get_user_by_provider(self, provider: str, provider_id: str) -> Optional[Dict[str, Any]]:
        db = self._db
        cursor = await db._db.execute(
            "SELECT * FROM users WHERE auth_provider = ? AND provider_id = ? AND is_active = 1",
            (provider, provider_id)
        )
        row = await cursor.fetchone()
        return self._sanitize_user(dict(row)) if row else None

    async def find_or_create_oauth_user(
        self, provider: str, provider_id: str, email: str, full_name: str, avatar_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Find existing OAuth user or create a new one."""
        # Try by provider+id first
        user = await self.get_user_by_provider(provider, provider_id)
        if user:
            return user
        
        # Try by email (link accounts)
        user = await self.get_user_by_email(email)
        if user:
            # Update provider info
            db = self._db
            await db._db.execute(
                "UPDATE users SET auth_provider = ?, provider_id = ?, avatar_url = COALESCE(?, avatar_url) WHERE id = ?",
                (provider, provider_id, avatar_url, user["id"])
            )
            await db._db.commit()
            user["auth_provider"] = provider
            return user
        
        # Create new user
        # Generate username from email
        username = email.split("@")[0].lower()
        # Ensure unique
        base_username = username
        counter = 1
        while True:
            try:
                return await self.create_user(
                    username=username,
                    email=email,
                    full_name=full_name,
                    role="officer",
                    auth_provider=provider,
                    provider_id=provider_id,
                    avatar_url=avatar_url,
                )
            except ValueError as e:
                if "Username already taken" in str(e):
                    username = f"{base_username}{counter}"
                    counter += 1
                else:
                    raise

    async def update_last_login(self, user_id: str):
        db = self._db
        await db._db.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), user_id)
        )
        await db._db.commit()

    async def list_users(self, limit: int = 50) -> List[Dict[str, Any]]:
        db = self._db
        cursor = await db._db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [self._sanitize_user(dict(r)) for r in rows]

    async def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update user fields. Allowed: full_name, email, role, is_active, avatar_url."""
        allowed = {"full_name", "email", "role", "is_active", "avatar_url"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return await self.get_user_by_id(user_id)
        
        sets = ", ".join(f"{k} = ?" for k in filtered)
        vals = list(filtered.values()) + [user_id]
        db = self._db
        await db._db.execute(f"UPDATE users SET {sets} WHERE id = ?", vals)
        await db._db.commit()
        return await self.get_user_by_id(user_id)

    async def change_password(self, user_id: str, new_password: str) -> bool:
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db = self._db
        await db._db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        await db._db.commit()
        return True

    async def user_count(self) -> int:
        db = self._db
        cursor = await db._db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0

    def _sanitize_user(self, user: Dict) -> Dict:
        """Remove password_hash from user dict."""
        user.pop("password_hash", None)
        user["is_active"] = bool(user.get("is_active", 1))
        return user


user_service = UserService()
