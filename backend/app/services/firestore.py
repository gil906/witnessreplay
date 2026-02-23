import logging
from typing import Optional, List
from datetime import datetime
from google.cloud import firestore
from google.api_core import exceptions as gcp_exceptions

from app.config import settings
from app.models.schemas import ReconstructionSession

logger = logging.getLogger(__name__)


class FirestoreService:
    """Service for managing Firestore operations."""
    
    def __init__(self):
        self.client = None
        self.collection_name = settings.firestore_collection
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Firestore client."""
        try:
            if settings.gcp_project_id:
                self.client = firestore.Client(project=settings.gcp_project_id)
                logger.info("Firestore client initialized successfully")
            else:
                logger.warning("GCP_PROJECT_ID not set, Firestore client not initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Firestore client: {e}")
            self.client = None
    
    async def create_session(self, session: ReconstructionSession) -> bool:
        """Create a new session in Firestore."""
        if not self.client:
            logger.warning("Firestore client not available")
            return False
        
        try:
            session_dict = session.model_dump(mode='json')
            self.client.collection(self.collection_name).document(session.id).set(session_dict)
            logger.info(f"Created session {session.id} in Firestore")
            return True
        except Exception as e:
            logger.error(f"Failed to create session in Firestore: {e}")
            return False
    
    async def get_session(self, session_id: str) -> Optional[ReconstructionSession]:
        """Retrieve a session from Firestore."""
        if not self.client:
            logger.warning("Firestore client not available")
            return None
        
        try:
            doc = self.client.collection(self.collection_name).document(session_id).get()
            if doc.exists:
                data = doc.to_dict()
                return ReconstructionSession(**data)
            return None
        except Exception as e:
            logger.error(f"Failed to get session from Firestore: {e}")
            return None
    
    async def update_session(self, session: ReconstructionSession) -> bool:
        """Update an existing session in Firestore."""
        if not self.client:
            logger.warning("Firestore client not available")
            return False
        
        try:
            session.updated_at = datetime.utcnow()
            session_dict = session.model_dump(mode='json')
            self.client.collection(self.collection_name).document(session.id).set(session_dict, merge=True)
            logger.info(f"Updated session {session.id} in Firestore")
            return True
        except Exception as e:
            logger.error(f"Failed to update session in Firestore: {e}")
            return False
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from Firestore."""
        if not self.client:
            logger.warning("Firestore client not available")
            return False
        
        try:
            self.client.collection(self.collection_name).document(session_id).delete()
            logger.info(f"Deleted session {session_id} from Firestore")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session from Firestore: {e}")
            return False
    
    async def list_sessions(self, limit: int = 50) -> List[ReconstructionSession]:
        """List all sessions from Firestore."""
        if not self.client:
            logger.warning("Firestore client not available")
            return []
        
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
            return []
    
    def health_check(self) -> bool:
        """Check if Firestore is accessible."""
        if not self.client:
            return False
        try:
            # Try to access a collection (doesn't actually fetch data)
            self.client.collection(self.collection_name).limit(1).get()
            return True
        except Exception as e:
            logger.error(f"Firestore health check failed: {e}")
            return False


# Global instance
firestore_service = FirestoreService()
