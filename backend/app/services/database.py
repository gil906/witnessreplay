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
                environmental_conditions TEXT DEFAULT '{"weather":"clear","lighting":"daylight","visibility":"good"}',
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

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS embeddings (
                key TEXT PRIMARY KEY,
                vector TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS generated_images (
                id TEXT PRIMARY KEY,
                entity_type TEXT,
                entity_id TEXT,
                image_path TEXT,
                model_used TEXT,
                prompt TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS background_tasks (
                id TEXT PRIMARY KEY,
                task_type TEXT,
                status TEXT DEFAULT 'pending',
                result TEXT,
                error TEXT,
                created_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS case_relationships (
                id TEXT PRIMARY KEY,
                case_a_id TEXT NOT NULL,
                case_b_id TEXT NOT NULL,
                relationship_type TEXT DEFAULT 'related',
                link_reason TEXT DEFAULT 'manual',
                confidence REAL DEFAULT 0.5,
                notes TEXT,
                created_by TEXT DEFAULT 'system',
                created_at TEXT,
                UNIQUE(case_a_id, case_b_id)
            );

            CREATE INDEX IF NOT EXISTS idx_case_rel_a ON case_relationships(case_a_id);
            CREATE INDEX IF NOT EXISTS idx_case_rel_b ON case_relationships(case_b_id);

            CREATE TABLE IF NOT EXISTS custody_events (
                id TEXT PRIMARY KEY,
                evidence_type TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_role TEXT,
                details TEXT,
                metadata TEXT DEFAULT '{}',
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                hash_before TEXT,
                hash_after TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_custody_evidence ON custody_events(evidence_type, evidence_id);
            CREATE INDEX IF NOT EXISTS idx_custody_timestamp ON custody_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_custody_actor ON custody_events(actor);

            CREATE TABLE IF NOT EXISTS model_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                task_type TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                success INTEGER NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                error_type TEXT,
                error_message TEXT,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_model_metrics_model ON model_metrics(model);
            CREATE INDEX IF NOT EXISTS idx_model_metrics_timestamp ON model_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_model_metrics_task ON model_metrics(task_type);

            CREATE TABLE IF NOT EXISTS investigators (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                badge_number TEXT,
                email TEXT,
                department TEXT,
                active INTEGER DEFAULT 1,
                max_cases INTEGER DEFAULT 10,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_investigators_active ON investigators(active);
            CREATE INDEX IF NOT EXISTS idx_investigators_department ON investigators(department);

            CREATE TABLE IF NOT EXISTS case_assignments (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                investigator_id TEXT NOT NULL,
                investigator_name TEXT NOT NULL,
                assigned_by TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                unassigned_at TEXT,
                notes TEXT,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (case_id) REFERENCES cases(id),
                FOREIGN KEY (investigator_id) REFERENCES investigators(id)
            );

            CREATE INDEX IF NOT EXISTS idx_assignments_case ON case_assignments(case_id);
            CREATE INDEX IF NOT EXISTS idx_assignments_investigator ON case_assignments(investigator_id);
            CREATE INDEX IF NOT EXISTS idx_assignments_active ON case_assignments(is_active);

            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                permissions TEXT DEFAULT '["read","write"]',
                rate_limit_rpm INTEGER DEFAULT 30,
                created_at TEXT,
                last_used_at TEXT,
                is_active INTEGER DEFAULT 1,
                usage_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT,
                full_name TEXT DEFAULT '',
                role TEXT DEFAULT 'officer',
                auth_provider TEXT DEFAULT 'local',
                provider_id TEXT,
                avatar_url TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                last_login_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_provider ON users(auth_provider, provider_id);

            CREATE TABLE IF NOT EXISTS interview_scripts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                incident_type TEXT,
                questions TEXT DEFAULT '[]',
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS case_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                color TEXT DEFAULT '#60a5fa',
                created_at TEXT,
                UNIQUE(case_id, tag)
            );
            CREATE INDEX IF NOT EXISTS idx_case_tags_case ON case_tags(case_id);

            CREATE TABLE IF NOT EXISTS case_notes (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                author_id TEXT,
                author_name TEXT,
                content TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );
            CREATE INDEX IF NOT EXISTS idx_case_notes_case ON case_notes(case_id);

            CREATE TABLE IF NOT EXISTS case_deadlines (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                deadline_type TEXT NOT NULL,
                due_date TEXT NOT NULL,
                description TEXT DEFAULT '',
                is_completed INTEGER DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );
            CREATE INDEX IF NOT EXISTS idx_deadlines_case ON case_deadlines(case_id);
            CREATE INDEX IF NOT EXISTS idx_deadlines_due ON case_deadlines(due_date);

            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT, max_users INTEGER DEFAULT 50, plan TEXT DEFAULT 'free', created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS org_members (
                org_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT DEFAULT 'member', joined_at TEXT,
                PRIMARY KEY (org_id, user_id),
                FOREIGN KEY (org_id) REFERENCES organizations(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS user_2fa (
                user_id TEXT PRIMARY KEY, secret TEXT NOT NULL, is_enabled INTEGER DEFAULT 0, backup_codes TEXT, created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS witness_feedback (
                id TEXT PRIMARY KEY, session_id TEXT, rating INTEGER, ease_of_use INTEGER, felt_heard INTEGER, comments TEXT, created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS webhooks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                events TEXT DEFAULT '["case.created"]',
                secret TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
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
                env_conditions = sv.get("environmental_conditions", {"weather": "clear", "lighting": "daylight", "visibility": "good"})
                if not isinstance(env_conditions, str):
                    env_conditions = json.dumps(env_conditions)
                await self._db.execute(
                    """INSERT OR REPLACE INTO scene_versions
                       (session_id, version, description, image_url, elements, timestamp, changes_from_previous, environmental_conditions)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        sv.get("version"),
                        sv.get("description"),
                        sv.get("image_url"),
                        elements,
                        sv.get("timestamp", now),
                        sv.get("changes_from_previous"),
                        env_conditions,
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
        for key in ('metadata', 'timeframe', 'report_ids', 'elements', 'environmental_conditions'):
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

    # ── Background Tasks ─────────────────────────────────

    async def save_background_task(self, task_dict: dict) -> bool:
        try:
            now = datetime.utcnow().isoformat()
            await self._db.execute(
                """INSERT OR REPLACE INTO background_tasks
                   (id, task_type, status, result, error, created_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_dict.get("id"),
                    task_dict.get("task_type"),
                    task_dict.get("status", "pending"),
                    task_dict.get("result"),
                    task_dict.get("error"),
                    task_dict.get("created_at", now),
                    task_dict.get("completed_at"),
                ),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite save_background_task error: {e}")
            return False

    async def get_background_task(self, task_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM background_tasks WHERE id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    # ── Generated Images ─────────────────────────────────

    async def save_generated_image(self, image_dict: dict) -> bool:
        try:
            now = datetime.utcnow().isoformat()
            await self._db.execute(
                """INSERT OR REPLACE INTO generated_images
                   (id, entity_type, entity_id, image_path, model_used, prompt, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    image_dict.get("id"),
                    image_dict.get("entity_type"),
                    image_dict.get("entity_id"),
                    image_dict.get("image_path"),
                    image_dict.get("model_used"),
                    image_dict.get("prompt"),
                    image_dict.get("created_at", now),
                ),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite save_generated_image error: {e}")
            return False

    async def list_images_for_entity(self, entity_type: str, entity_id: str) -> List[dict]:
        rows = []
        async with self._db.execute(
            "SELECT * FROM generated_images WHERE entity_type = ? AND entity_id = ? ORDER BY created_at DESC",
            (entity_type, entity_id),
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    # ── Case Relationships ───────────────────────────────────

    async def save_case_relationship(self, rel_dict: dict) -> bool:
        """Insert or replace a case relationship."""
        try:
            now = datetime.utcnow().isoformat()
            await self._db.execute(
                """INSERT OR REPLACE INTO case_relationships
                   (id, case_a_id, case_b_id, relationship_type, link_reason, confidence, notes, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rel_dict.get("id"),
                    rel_dict.get("case_a_id"),
                    rel_dict.get("case_b_id"),
                    rel_dict.get("relationship_type", "related"),
                    rel_dict.get("link_reason", "manual"),
                    rel_dict.get("confidence", 0.5),
                    rel_dict.get("notes"),
                    rel_dict.get("created_by", "system"),
                    rel_dict.get("created_at", now),
                ),
            )
            await self._db.commit()
            await self._audit("case_relationship", rel_dict.get("id"), "save")
            return True
        except Exception as e:
            logger.error(f"SQLite save_case_relationship error: {e}")
            return False

    async def get_case_relationships(self, case_id: str) -> List[dict]:
        """Get all relationships for a case (either as case_a or case_b)."""
        rows = []
        async with self._db.execute(
            """SELECT * FROM case_relationships 
               WHERE case_a_id = ? OR case_b_id = ? 
               ORDER BY created_at DESC""",
            (case_id, case_id),
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def get_case_relationship(self, rel_id: str) -> Optional[dict]:
        """Get a specific case relationship by ID."""
        async with self._db.execute(
            "SELECT * FROM case_relationships WHERE id = ?", (rel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    async def delete_case_relationship(self, rel_id: str) -> bool:
        """Delete a case relationship."""
        try:
            await self._db.execute(
                "DELETE FROM case_relationships WHERE id = ?", (rel_id,)
            )
            await self._db.commit()
            await self._audit("case_relationship", rel_id, "delete")
            return True
        except Exception as e:
            logger.error(f"SQLite delete_case_relationship error: {e}")
            return False

    async def check_relationship_exists(self, case_a_id: str, case_b_id: str) -> Optional[dict]:
        """Check if a relationship exists between two cases (in either direction)."""
        async with self._db.execute(
            """SELECT * FROM case_relationships 
               WHERE (case_a_id = ? AND case_b_id = ?) OR (case_a_id = ? AND case_b_id = ?)""",
            (case_a_id, case_b_id, case_b_id, case_a_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    # ── Chain of Custody ─────────────────────────────────────

    async def save_custody_event(self, event_dict: dict) -> bool:
        """Save a custody event to the database."""
        try:
            metadata = event_dict.get("metadata", {})
            if not isinstance(metadata, str):
                metadata = json.dumps(metadata)
            await self._db.execute(
                """INSERT INTO custody_events
                   (id, evidence_type, evidence_id, action, actor, actor_role, details, metadata, timestamp, hash_before, hash_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_dict.get("id"),
                    event_dict.get("evidence_type"),
                    event_dict.get("evidence_id"),
                    event_dict.get("action"),
                    event_dict.get("actor"),
                    event_dict.get("actor_role"),
                    event_dict.get("details"),
                    metadata,
                    event_dict.get("timestamp", datetime.utcnow().isoformat()),
                    event_dict.get("hash_before"),
                    event_dict.get("hash_after"),
                ),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite save_custody_event error: {e}")
            return False

    async def get_custody_events(self, evidence_type: str, evidence_id: str, limit: int = 100) -> List[dict]:
        """Get custody events for a specific evidence item."""
        rows = []
        async with self._db.execute(
            """SELECT * FROM custody_events 
               WHERE evidence_type = ? AND evidence_id = ? 
               ORDER BY timestamp DESC LIMIT ?""",
            (evidence_type, evidence_id, limit),
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def get_all_custody_for_session(self, session_id: str, limit: int = 500) -> List[dict]:
        """Get all custody events related to a session (direct and via metadata)."""
        rows = []
        async with self._db.execute(
            """SELECT * FROM custody_events 
               WHERE (evidence_type = 'session' AND evidence_id = ?)
                  OR metadata LIKE ?
               ORDER BY timestamp DESC LIMIT ?""",
            (session_id, f'%"session_id": "{session_id}"%', limit),
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def get_custody_by_actor(self, actor: str, limit: int = 100) -> List[dict]:
        """Get custody events by a specific actor."""
        rows = []
        async with self._db.execute(
            """SELECT * FROM custody_events 
               WHERE actor = ? 
               ORDER BY timestamp DESC LIMIT ?""",
            (actor, limit),
        ) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def get_custody_exports(self, evidence_type: Optional[str] = None, limit: int = 100) -> List[dict]:
        """Get all export custody events for audit trail."""
        rows = []
        if evidence_type:
            async with self._db.execute(
                """SELECT * FROM custody_events 
                   WHERE action = 'exported' AND evidence_type = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (evidence_type, limit),
            ) as cursor:
                async for row in cursor:
                    rows.append(self._row_to_dict(row))
        else:
            async with self._db.execute(
                """SELECT * FROM custody_events 
                   WHERE action = 'exported'
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ) as cursor:
                async for row in cursor:
                    rows.append(self._row_to_dict(row))
        return rows

    # ── Investigator CRUD ──────────────────────────────────────

    async def save_investigator(self, investigator_dict: dict) -> bool:
        """Insert or replace an investigator."""
        try:
            now = datetime.utcnow().isoformat()
            await self._db.execute(
                """INSERT OR REPLACE INTO investigators
                   (id, name, badge_number, email, department, active, max_cases, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    investigator_dict.get("id"),
                    investigator_dict.get("name"),
                    investigator_dict.get("badge_number"),
                    investigator_dict.get("email"),
                    investigator_dict.get("department"),
                    1 if investigator_dict.get("active", True) else 0,
                    investigator_dict.get("max_cases", 10),
                    investigator_dict.get("created_at", now),
                    now,
                ),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite save_investigator error: {e}")
            return False

    async def get_investigator(self, investigator_id: str) -> Optional[dict]:
        """Get an investigator by ID."""
        async with self._db.execute(
            "SELECT * FROM investigators WHERE id = ?", (investigator_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = self._row_to_dict(row)
                result["active"] = bool(result.get("active", 1))
                return result
        return None

    async def list_investigators(self, active_only: bool = False, limit: int = 100) -> List[dict]:
        """List all investigators."""
        rows = []
        query = "SELECT * FROM investigators"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY name ASC LIMIT ?"
        async with self._db.execute(query, (limit,)) as cursor:
            async for row in cursor:
                result = self._row_to_dict(row)
                result["active"] = bool(result.get("active", 1))
                rows.append(result)
        return rows

    async def delete_investigator(self, investigator_id: str) -> bool:
        """Delete an investigator (soft delete by setting active=0)."""
        try:
            await self._db.execute(
                "UPDATE investigators SET active = 0, updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), investigator_id),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite delete_investigator error: {e}")
            return False

    # ── Case Assignment CRUD ──────────────────────────────────────

    async def save_case_assignment(self, assignment_dict: dict) -> bool:
        """Insert or replace a case assignment."""
        try:
            await self._db.execute(
                """INSERT OR REPLACE INTO case_assignments
                   (id, case_id, investigator_id, investigator_name, assigned_by, assigned_at, unassigned_at, notes, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assignment_dict.get("id"),
                    assignment_dict.get("case_id"),
                    assignment_dict.get("investigator_id"),
                    assignment_dict.get("investigator_name"),
                    assignment_dict.get("assigned_by"),
                    assignment_dict.get("assigned_at", datetime.utcnow().isoformat()),
                    assignment_dict.get("unassigned_at"),
                    assignment_dict.get("notes"),
                    1 if assignment_dict.get("is_active", True) else 0,
                ),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite save_case_assignment error: {e}")
            return False

    async def get_case_assignments(self, case_id: str, active_only: bool = False) -> List[dict]:
        """Get all assignments for a case."""
        rows = []
        query = "SELECT * FROM case_assignments WHERE case_id = ?"
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY assigned_at DESC"
        async with self._db.execute(query, (case_id,)) as cursor:
            async for row in cursor:
                result = self._row_to_dict(row)
                result["is_active"] = bool(result.get("is_active", 1))
                rows.append(result)
        return rows

    async def get_active_assignment_for_case(self, case_id: str) -> Optional[dict]:
        """Get the active assignment for a case."""
        async with self._db.execute(
            "SELECT * FROM case_assignments WHERE case_id = ? AND is_active = 1 LIMIT 1",
            (case_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = self._row_to_dict(row)
                result["is_active"] = bool(result.get("is_active", 1))
                return result
        return None

    async def get_investigator_assignments(self, investigator_id: str, active_only: bool = False) -> List[dict]:
        """Get all assignments for an investigator."""
        rows = []
        query = "SELECT * FROM case_assignments WHERE investigator_id = ?"
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY assigned_at DESC"
        async with self._db.execute(query, (investigator_id,)) as cursor:
            async for row in cursor:
                result = self._row_to_dict(row)
                result["is_active"] = bool(result.get("is_active", 1))
                rows.append(result)
        return rows

    async def deactivate_case_assignments(self, case_id: str) -> bool:
        """Deactivate all active assignments for a case (for reassignment)."""
        try:
            now = datetime.utcnow().isoformat()
            await self._db.execute(
                "UPDATE case_assignments SET is_active = 0, unassigned_at = ? WHERE case_id = ? AND is_active = 1",
                (now, case_id),
            )
            await self._db.commit()
            return True
        except Exception as e:
            logger.error(f"SQLite deactivate_case_assignments error: {e}")
            return False

    async def get_workload_stats(self) -> List[dict]:
        """Get workload statistics for all active investigators."""
        rows = []
        query = """
            SELECT 
                i.id as investigator_id,
                i.name as investigator_name,
                i.badge_number,
                i.department,
                i.max_cases,
                i.active,
                COUNT(CASE WHEN ca.is_active = 1 THEN 1 END) as active_cases,
                COUNT(ca.id) as total_assignments
            FROM investigators i
            LEFT JOIN case_assignments ca ON i.id = ca.investigator_id
            WHERE i.active = 1
            GROUP BY i.id
            ORDER BY i.name
        """
        async with self._db.execute(query) as cursor:
            async for row in cursor:
                result = self._row_to_dict(row)
                result["active"] = bool(result.get("active", 1))
                rows.append(result)
        return rows

    async def count_unassigned_cases(self) -> int:
        """Count cases without active assignments."""
        async with self._db.execute(
            """SELECT COUNT(*) FROM cases c 
               WHERE c.status != 'closed' 
               AND NOT EXISTS (
                   SELECT 1 FROM case_assignments ca 
                   WHERE ca.case_id = c.id AND ca.is_active = 1
               )"""
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


def get_database() -> DatabaseService:
    """Get or create the singleton DatabaseService."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseService()
    return _db_instance
