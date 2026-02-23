import logging
from typing import Optional, List
from datetime import datetime
from google.cloud import firestore
from google.api_core import exceptions as gcp_exceptions

from app.config import settings
from app.models.schemas import ReconstructionSession

logger = logging.getLogger(__name__)


class FirestoreService:
    """Service for managing Firestore operations with in-memory fallback."""
    
    def __init__(self):
        self.client = None
        self.collection_name = settings.firestore_collection
        self._memory_store: dict = {}  # In-memory fallback when Firestore unavailable
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Firestore client."""
        try:
            if settings.gcp_project_id:
                self.client = firestore.Client(project=settings.gcp_project_id)
                logger.info("Firestore client initialized successfully")
            else:
                logger.warning("GCP_PROJECT_ID not set, using in-memory session storage")
        except Exception as e:
            logger.warning(f"Firestore not available, using in-memory storage: {e}")
            self.client = None
    
    async def create_session(self, session: ReconstructionSession) -> bool:
        """Create a new session in Firestore or in-memory."""
        if self.client:
            try:
                session_dict = session.model_dump(mode='json')
                self.client.collection(self.collection_name).document(session.id).set(session_dict)
                logger.info(f"Created session {session.id} in Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to create session in Firestore: {e}")
                # Fall through to in-memory
        
        # In-memory fallback
        self._memory_store[session.id] = session
        logger.info(f"Created session {session.id} in memory")
        return True
    
    async def get_session(self, session_id: str) -> Optional[ReconstructionSession]:
        """Retrieve a session from Firestore or in-memory."""
        if self.client:
            try:
                doc = self.client.collection(self.collection_name).document(session_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    return ReconstructionSession(**data)
            except Exception as e:
                logger.error(f"Failed to get session from Firestore: {e}")
        
        # In-memory fallback
        return self._memory_store.get(session_id)
    
    async def update_session(self, session: ReconstructionSession) -> bool:
        """Update an existing session in Firestore or in-memory."""
        if self.client:
            try:
                session.updated_at = datetime.utcnow()
                session_dict = session.model_dump(mode='json')
                self.client.collection(self.collection_name).document(session.id).set(session_dict, merge=True)
                logger.info(f"Updated session {session.id} in Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to update session in Firestore: {e}")
        
        # In-memory fallback
        session.updated_at = datetime.utcnow()
        self._memory_store[session.id] = session
        logger.info(f"Updated session {session.id} in memory")
        return True
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from Firestore or in-memory."""
        if self.client:
            try:
                self.client.collection(self.collection_name).document(session_id).delete()
                logger.info(f"Deleted session {session_id} from Firestore")
                return True
            except Exception as e:
                logger.error(f"Failed to delete session from Firestore: {e}")
        
        # In-memory fallback
        self._memory_store.pop(session_id, None)
        logger.info(f"Deleted session {session_id} from memory")
        return True
    
    async def list_sessions(self, limit: int = 50) -> List[ReconstructionSession]:
        """List all sessions from Firestore or in-memory."""
        if self.client:
            try:
                docs = (
                    self.client.collection(self.collection_name)
                    .order_by("updated_at", direction=firestore.Query.DESCENDING)
                    .limit(limit)
                    .stream()
                )
                sessions = []
                for doc in docs:
                    try:
                        data = doc.to_dict()
                        sessions.append(ReconstructionSession(**data))
                    except Exception as e:
                        logger.error(f"Failed to parse session document: {e}")
                return sessions
            except Exception as e:
                logger.error(f"Failed to list sessions from Firestore: {e}")
        
        # In-memory fallback
        sessions = sorted(
            self._memory_store.values(),
            key=lambda s: s.updated_at,
            reverse=True
        )
        return sessions[:limit]
    
    def health_check(self) -> bool:
        """Check if storage is accessible."""
        if self.client:
            try:
                self.client.collection(self.collection_name).limit(1).get()
                return True
            except Exception as e:
                logger.error(f"Firestore health check failed: {e}")
                return False
        # In-memory is always healthy
        return True


# Global instance
firestore_service = FirestoreService()
