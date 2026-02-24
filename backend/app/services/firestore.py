import logging
from typing import Optional, List
from datetime import datetime
from google.cloud.firestore_v1.async_client import AsyncClient
from google.api_core import exceptions as gcp_exceptions

from app.config import settings
from app.models.schemas import ReconstructionSession, Case
from app.services.cache import cache, cached

logger = logging.getLogger(__name__)


class FirestoreService:
    """Service for managing Firestore operations with SQLite fallback."""
    
    def __init__(self):
        self.client: Optional[AsyncClient] = None
        self.collection_name = settings.firestore_collection
        self._sqlite = None  # Lazy-loaded DatabaseService
        self._case_memory_store: dict = {}
        self._memory_store: dict = {}
        self.cases_collection = "cases"
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize async Firestore client."""
        try:
            if settings.gcp_project_id:
                self.client = AsyncClient(project=settings.gcp_project_id)
                logger.info("Async Firestore client initialized successfully")
            else:
                logger.warning("GCP_PROJECT_ID not set, using SQLite session storage")
        except Exception as e:
            logger.warning(f"Firestore not available, using SQLite storage: {e}")
            self.client = None

    async def _get_sqlite(self):
        """Lazy-load the SQLite database service."""
        if self._sqlite is None:
            from app.services.database import get_database
            self._sqlite = get_database()
            if self._sqlite._db is None:
                await self._sqlite.initialize()
        return self._sqlite
    
    async def create_session(self, session: ReconstructionSession) -> bool:
        """Create a new session in Firestore or in-memory."""
        if self.client:
            try:
                session_dict = session.model_dump(mode='json')
                await self.client.collection(self.collection_name).document(session.id).set(session_dict)
                logger.info(f"Created session {session.id} in Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to create session in Firestore: {e}")
                # Fall through to in-memory
        
        # SQLite fallback
        try:
            db = await self._get_sqlite()
            session_dict = session.model_dump(mode='json')
            await db.save_session(session_dict)
            logger.info(f"Created session {session.id} in SQLite")
        except Exception as e:
            logger.warning(f"SQLite fallback failed, using memory: {e}")
            self._memory_store[session.id] = session
            logger.info(f"Created session {session.id} in memory")
        return True
    
    async def get_session(self, session_id: str) -> Optional[ReconstructionSession]:
        """Retrieve a session from cache, Firestore, or in-memory."""
        # Try cache first
        cached_session = await cache.get(f"session:{session_id}")
        if cached_session:
            logger.debug(f"Cache hit for session {session_id}")
            return cached_session
        
        session = None
        if self.client:
            try:
                doc = await self.client.collection(self.collection_name).document(session_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    session = ReconstructionSession(**data)
            except Exception as e:
                logger.error(f"Failed to get session from Firestore: {e}")
        
        # SQLite fallback
        if not session:
            try:
                db = await self._get_sqlite()
                row = await db.get_session(session_id)
                if row:
                    session = ReconstructionSession(**row)
            except Exception as e:
                logger.warning(f"SQLite get_session failed: {e}")
        
        # In-memory last resort
        if not session:
            session = self._memory_store.get(session_id)
        
        # Cache the result for 5 minutes
        if session:
            await cache.set(f"session:{session_id}", session, ttl_seconds=300)
        
        return session
    
    async def update_session(self, session: ReconstructionSession) -> bool:
        """Update an existing session in Firestore or in-memory and invalidate cache."""
        # Invalidate cache
        await cache.delete(f"session:{session.id}")
        
        if self.client:
            try:
                session.updated_at = datetime.utcnow()
                session_dict = session.model_dump(mode='json')
                await self.client.collection(self.collection_name).document(session.id).set(session_dict, merge=True)
                logger.info(f"Updated session {session.id} in Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to update session in Firestore: {e}")
        
        # SQLite fallback
        session.updated_at = datetime.utcnow()
        try:
            db = await self._get_sqlite()
            session_dict = session.model_dump(mode='json')
            await db.save_session(session_dict)
            logger.info(f"Updated session {session.id} in SQLite")
        except Exception as e:
            logger.warning(f"SQLite update_session failed: {e}")
            self._memory_store[session.id] = session
            logger.info(f"Updated session {session.id} in memory")
        return True
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from Firestore or in-memory."""
        if self.client:
            try:
                await self.client.collection(self.collection_name).document(session_id).delete()
                logger.info(f"Deleted session {session_id} from Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to delete session from Firestore: {e}")
        
        # SQLite fallback
        try:
            db = await self._get_sqlite()
            await db.delete_session(session_id)
            logger.info(f"Deleted session {session_id} from SQLite")
        except Exception as e:
            logger.warning(f"SQLite delete_session failed: {e}")
            self._memory_store.pop(session_id, None)
            logger.info(f"Deleted session {session_id} from memory")
        return True
    
    async def list_sessions(self, limit: int = 50) -> List[ReconstructionSession]:
        """List all sessions from Firestore or in-memory."""
        if self.client:
            try:
                from google.cloud.firestore_v1 import Query
                docs = (
                    self.client.collection(self.collection_name)
                    .order_by("updated_at", direction=Query.DESCENDING)
                    .limit(limit)
                    .stream()
                )
                sessions = []
                async for doc in docs:
                    try:
                        data = doc.to_dict()
                        sessions.append(ReconstructionSession(**data))
                    except Exception as e:
                        logger.error(f"Failed to parse session document: {e}")
                return sessions
            except Exception as e:
                logger.error(f"Failed to list sessions from Firestore: {e}")
        
        # SQLite fallback
        try:
            db = await self._get_sqlite()
            rows = await db.list_sessions(limit=limit)
            sessions = []
            for row in rows:
                try:
                    sessions.append(ReconstructionSession(**row))
                except Exception as e:
                    logger.error(f"Failed to parse SQLite session row: {e}")
            if sessions:
                return sessions
        except Exception as e:
            logger.warning(f"SQLite list_sessions failed: {e}")

        # In-memory last resort
        sessions = sorted(
            self._memory_store.values(),
            key=lambda s: s.updated_at,
            reverse=True
        )
        return sessions[:limit]
    
    # ── Case Methods ────────────────────────────────────

    async def create_case(self, case: Case) -> bool:
        """Create a new case in Firestore or in-memory."""
        if self.client:
            try:
                case_dict = case.model_dump(mode='json')
                await self.client.collection(self.cases_collection).document(case.id).set(case_dict)
                logger.info(f"Created case {case.id} in Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to create case in Firestore: {e}")

        # SQLite fallback
        try:
            db = await self._get_sqlite()
            case_dict = case.model_dump(mode='json')
            await db.save_case(case_dict)
            logger.info(f"Created case {case.id} in SQLite")
        except Exception as e:
            logger.warning(f"SQLite create_case failed: {e}")
            self._case_memory_store[case.id] = case
            logger.info(f"Created case {case.id} in memory")
        return True

    async def get_case(self, case_id: str) -> Optional[Case]:
        """Retrieve a case from Firestore or SQLite."""
        if self.client:
            try:
                doc = await self.client.collection(self.cases_collection).document(case_id).get()
                if doc.exists:
                    return Case(**doc.to_dict())
            except Exception as e:
                logger.error(f"Failed to get case from Firestore: {e}")

        # SQLite fallback
        try:
            db = await self._get_sqlite()
            row = await db.get_case(case_id)
            if row:
                return Case(**row)
        except Exception as e:
            logger.warning(f"SQLite get_case failed: {e}")

        return self._case_memory_store.get(case_id)

    async def list_cases(self, limit: int = 50) -> List[Case]:
        """List all cases from Firestore or SQLite."""
        if self.client:
            try:
                from google.cloud.firestore_v1 import Query
                docs = (
                    self.client.collection(self.cases_collection)
                    .order_by("updated_at", direction=Query.DESCENDING)
                    .limit(limit)
                    .stream()
                )
                cases = []
                async for doc in docs:
                    try:
                        cases.append(Case(**doc.to_dict()))
                    except Exception as e:
                        logger.error(f"Failed to parse case document: {e}")
                return cases
            except Exception as e:
                logger.error(f"Failed to list cases from Firestore: {e}")

        # SQLite fallback
        try:
            db = await self._get_sqlite()
            rows = await db.list_cases(limit=limit)
            cases = []
            for row in rows:
                try:
                    cases.append(Case(**row))
                except Exception as e:
                    logger.error(f"Failed to parse SQLite case row: {e}")
            if cases:
                return cases
        except Exception as e:
            logger.warning(f"SQLite list_cases failed: {e}")

        # In-memory last resort
        cases = sorted(
            self._case_memory_store.values(),
            key=lambda c: c.updated_at,
            reverse=True
        )
        return cases[:limit]

    async def update_case(self, case: Case) -> bool:
        """Update an existing case in Firestore or in-memory."""
        if self.client:
            try:
                case.updated_at = datetime.utcnow()
                case_dict = case.model_dump(mode='json')
                await self.client.collection(self.cases_collection).document(case.id).set(case_dict, merge=True)
                logger.info(f"Updated case {case.id} in Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to update case in Firestore: {e}")

        # SQLite fallback
        case.updated_at = datetime.utcnow()
        try:
            db = await self._get_sqlite()
            case_dict = case.model_dump(mode='json')
            await db.save_case(case_dict)
            logger.info(f"Updated case {case.id} in SQLite")
        except Exception as e:
            logger.warning(f"SQLite update_case failed: {e}")
            self._case_memory_store[case.id] = case
            logger.info(f"Updated case {case.id} in memory")
        return True

    async def get_next_case_number(self) -> str:
        """Generate next sequential case number like CASE-2026-XXXX."""
        try:
            db = await self._get_sqlite()
            count = await db.count_cases()
        except Exception:
            cases = await self.list_cases(limit=10000)
            count = len(cases)
        return f"CASE-2026-{count + 1:04d}"

    async def get_next_report_number(self) -> str:
        """Generate next sequential report number like RPT-2026-XXXX."""
        try:
            db = await self._get_sqlite()
            count = await db.count_sessions()
        except Exception:
            sessions = await self.list_sessions(limit=10000)
            count = len(sessions)
        return f"RPT-2026-{count + 1:04d}"

    async def health_check(self) -> bool:
        """Check if storage is accessible."""
        if self.client:
            try:
                # Simple async check - just verify client is initialized
                docs = self.client.collection(self.collection_name).limit(1).stream()
                async for _ in docs:
                    break
                return True
            except Exception as e:
                logger.error(f"Firestore health check failed: {e}")
                return False
        # In-memory is always healthy
        return True


# Global instance
firestore_service = FirestoreService()
