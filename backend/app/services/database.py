"""
SQLite database service for WitnessReplay.
Provides persistent local storage as fallback when Firestore is unavailable.
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton instance
_db_instance: Optional["DatabaseService"] = None


class DatabaseService:
    """Async SQLite database service."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.database_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Create database directory and tables."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        logger.info(f"SQLite database initialized at {self.db_path}")

    async def _create_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'Untitled Session',
                status TEXT DEFAULT 'active',
                source_type TEXT DEFAULT 'chat',
                report_number TEXT DEFAULT '',
                case_id TEXT,
                metadata TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS statements (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                text TEXT NOT NULL,
                audio_url TEXT,
                is_correction INTEGER DEFAULT 0,
                timestamp TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS scene_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                version INTEGER,
                description TEXT,
                image_url TEXT,
                elements TEXT DEFAULT '[]',
                timestamp TEXT,
                changes_from_previous TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                case_number TEXT UNIQUE,
                title TEXT DEFAULT 'Untitled Case',
                summary TEXT DEFAULT '',
                location TEXT DEFAULT '',
                timeframe TEXT DEFAULT '{}',
                scene_image_url TEXT,
                report_ids TEXT DEFAULT '[]',
                status TEXT DEFAULT 'open',
                metadata TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT,
                entity_id TEXT,
                action TEXT,
                details TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    # ── Session CRUD ──────────────────────────────────────

    async def save_session(self, session_dict: dict) -> bool:
        """Insert or replace a session with its statements and scene versions."""
        try:
            now = datetime.utcnow().isoformat()
            metadata = session_dict.get("metadata", {})
            if not isinstance(metadata, str):
                metadata = json.dumps(metadata)
            await self._db.execute(
                """INSERT OR REPLACE INTO sessions
                   (id, title, status, source_type, report_number, case_id, metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_dict.get("id"),
                    session_dict.get("title", "Untitled Session"),
                    session_dict.get("status", "active"),
                    session_dict.get("source_type", "chat"),
                    session_dict.get("report_number", ""),
                    session_dict.get("case_id"),
                    metadata,
                    session_dict.get("created_at", now),
                    now,
                ),
            )
            # Save statements
            sid = session_dict.get("id")
            for stmt in session_dict.get("witness_statements", []):
                await self._db.execute(
                    """INSERT OR REPLACE INTO statements
                       (id, session_id, text, audio_url, is_correction, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        stmt.get("id"),
                        sid,
                        stmt.get("text", ""),
                        stmt.get("audio_url"),
                        1 if stmt.get("is_correction") else 0,
                        stmt.get("timestamp", now),
                    ),
                )
            # Save scene versions
            for sv in session_dict.get("scene_versions", []):
                elements = sv.get("elements", [])
                if not isinstance(elements, str):
                    elements = json.dumps(elements)
                await self._db.execute(
                    """INSERT OR REPLACE INTO scene_versions
                       (session_id, version, description, image_url, elements, timestamp, changes_from_previous)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        sv.get("version"),
                        sv.get("description"),
                        sv.get("image_url"),
                        elements,
                        sv.get("timestamp", now),
                        sv.get("changes_from_previous"),
                    ),
                )
            await self._db.commit()
            await self._audit("session", sid, "save")
            return True
        except Exception as e:
            logger.error(f"SQLite save_session error: {e}")
            return False

    async def get_session(self, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
        # Load statements
        stmts = []
        async with self._db.execute(
            "SELECT * FROM statements WHERE session_id = ? ORDER BY timestamp", (session_id,)
        ) as cursor:
            async for row in cursor:
                s = self._row_to_dict(row)
                s["is_correction"] = bool(s.get("is_correction"))
                stmts.append(s)
        d["witness_statements"] = stmts
        # Load scene versions
        svs = []
        async with self._db.execute(
            "SELECT * FROM scene_versions WHERE session_id = ? ORDER BY version", (session_id,)
        ) as cursor:
            async for row in cursor:
                svs.append(self._row_to_dict(row))
        d["scene_versions"] = svs
        return d

    async def delete_session(self, session_id: str) -> bool:
        try:
            await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await self._db.execute("DELETE FROM statements WHERE session_id = ?", (session_id,))
            await self._db.execute("DELETE FROM scene_versions WHERE session_id = ?", (session_id,))
            await self._db.commit()
            await self._audit("session", session_id, "delete")
            return True
        except Exception as e:
            logger.error(f"SQLite delete_session error: {e}")
            return False

    async def list_sessions(self, limit: int = 50) -> List[dict]:
        rows = []
        async with self._db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    # ── Case CRUD ─────────────────────────────────────────

    async def save_case(self, case_dict: dict) -> bool:
        try:
            now = datetime.utcnow().isoformat()
            timeframe = case_dict.get("timeframe", {})
            if not isinstance(timeframe, str):
                timeframe = json.dumps(timeframe)
            report_ids = case_dict.get("report_ids", [])
            if not isinstance(report_ids, str):
                report_ids = json.dumps(report_ids)
            metadata = case_dict.get("metadata", {})
            if not isinstance(metadata, str):
                metadata = json.dumps(metadata)
            await self._db.execute(
                """INSERT OR REPLACE INTO cases
                   (id, case_number, title, summary, location, timeframe,
                    scene_image_url, report_ids, status, metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    case_dict.get("id"),
                    case_dict.get("case_number"),
                    case_dict.get("title", "Untitled Case"),
                    case_dict.get("summary", ""),
                    case_dict.get("location", ""),
                    timeframe,
                    case_dict.get("scene_image_url"),
                    report_ids,
                    case_dict.get("status", "open"),
                    metadata,
                    case_dict.get("created_at", now),
                    now,
                ),
            )
            await self._db.commit()
            await self._audit("case", case_dict.get("id"), "save")
            return True
        except Exception as e:
            logger.error(f"SQLite save_case error: {e}")
            return False

    async def get_case(self, case_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    async def list_cases(self, limit: int = 50) -> List[dict]:
        rows = []
        async with self._db.execute(
            "SELECT * FROM cases ORDER BY updated_at DESC LIMIT ?", (limit,)
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def count_cases(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM cases") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_sessions(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM sessions") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ── Helpers ───────────────────────────────────────────

    async def _audit(self, entity_type: str, entity_id: str, action: str, details: str = ""):
        try:
            await self._db.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, details) VALUES (?, ?, ?, ?)",
                (entity_type, entity_id, action, details),
            )
            await self._db.commit()
        except Exception as e:
            logger.warning(f"Audit log write failed: {e}")

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        # Deserialize JSON string fields
        for key in ('metadata', 'timeframe', 'report_ids', 'elements'):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    async def health_check(self) -> bool:
        try:
            async with self._db.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except Exception:
            return False


def get_database() -> DatabaseService:
    """Get or create the singleton DatabaseService."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseService()
    return _db_instance
