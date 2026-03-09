"""
API Key management service for WitnessReplay public API.
Uses the existing SQLite DatabaseService for persistent storage.
"""
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import bcrypt

from app.services.database import get_database

logger = logging.getLogger(__name__)

KEY_PREFIX_TAG = "wr_"
KEY_TOKEN_LENGTH = 32
KEY_DISPLAY_PREFIX_LENGTH = 8


class APIKeyService:
    """Manages API keys for the public REST API."""

    def __init__(self):
        self._db = None

    async def initialize(self):
        """Obtain a reference to the shared database."""
        self._db = get_database()
        if self._db._db is None:
            await self._db.initialize()
        logger.info("API key service initialized")

    # ── CRUD ──────────────────────────────────────────────

    async def create_key(
        self,
        name: str,
        permissions: List[str] = None,
        rate_limit_rpm: int = 30,
    ) -> Dict[str, Any]:
        """Create a new API key. Returns the full key ONCE."""
        if permissions is None:
            permissions = ["read", "write"]

        token = secrets.token_urlsafe(KEY_TOKEN_LENGTH)
        full_key = f"{KEY_PREFIX_TAG}{token}"
        prefix = full_key[:KEY_DISPLAY_PREFIX_LENGTH]

        key_hash = bcrypt.hashpw(full_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        key_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db._db.execute(
            """INSERT INTO api_keys (id, name, key_hash, key_prefix, permissions, rate_limit_rpm, created_at, is_active, usage_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)""",
            (key_id, name, key_hash, prefix, json.dumps(permissions), rate_limit_rpm, now),
        )
        await self._db._db.commit()

        logger.info(f"Created API key {prefix}... for '{name}'")
        return {
            "id": key_id,
            "name": name,
            "key": full_key,
            "prefix": prefix,
            "permissions": permissions,
            "rate_limit_rpm": rate_limit_rpm,
            "created_at": now,
        }

    async def list_keys(self) -> List[Dict[str, Any]]:
        """List all API keys (metadata only, never the full key)."""
        cursor = await self._db._db.execute(
            "SELECT id, name, key_prefix, permissions, rate_limit_rpm, created_at, last_used_at, is_active, usage_count FROM api_keys ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        keys = []
        for row in rows:
            keys.append({
                "id": row[0],
                "name": row[1],
                "prefix": row[2],
                "permissions": json.loads(row[3]) if row[3] else ["read", "write"],
                "rate_limit_rpm": row[4],
                "created_at": row[5],
                "last_used_at": row[6],
                "is_active": bool(row[7]),
                "usage_count": row[8],
            })
        return keys

    async def revoke_key(self, key_id: str) -> bool:
        """Revoke (deactivate) an API key."""
        cursor = await self._db._db.execute(
            "UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,)
        )
        await self._db._db.commit()
        revoked = cursor.rowcount > 0
        if revoked:
            logger.info(f"Revoked API key {key_id}")
        return revoked

    async def validate_key(self, raw_key: str) -> Optional[Dict[str, Any]]:
        """Validate an API key. Returns key metadata if valid, else None."""
        if not raw_key or not raw_key.startswith(KEY_PREFIX_TAG):
            return None

        cursor = await self._db._db.execute(
            "SELECT id, name, key_hash, permissions, rate_limit_rpm, is_active FROM api_keys WHERE is_active = 1"
        )
        rows = await cursor.fetchall()

        for row in rows:
            key_hash = row[2]
            if bcrypt.checkpw(raw_key.encode("utf-8"), key_hash.encode("utf-8")):
                now = datetime.now(timezone.utc).isoformat()
                await self._db._db.execute(
                    "UPDATE api_keys SET last_used_at = ?, usage_count = usage_count + 1 WHERE id = ?",
                    (now, row[0]),
                )
                await self._db._db.commit()
                return {
                    "id": row[0],
                    "name": row[1],
                    "permissions": json.loads(row[3]) if row[3] else ["read", "write"],
                    "rate_limit_rpm": row[4],
                }
        return None

    async def get_key_stats(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get usage statistics for a specific key."""
        cursor = await self._db._db.execute(
            "SELECT id, name, key_prefix, permissions, rate_limit_rpm, created_at, last_used_at, is_active, usage_count FROM api_keys WHERE id = ?",
            (key_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "prefix": row[2],
            "permissions": json.loads(row[3]) if row[3] else ["read", "write"],
            "rate_limit_rpm": row[4],
            "created_at": row[5],
            "last_used_at": row[6],
            "is_active": bool(row[7]),
            "usage_count": row[8],
        }


# Singleton
api_key_service = APIKeyService()
