"""
Evidence Chain of Custody Service.
Tracks who accessed/modified evidence, when, and what changes were made.
Provides full audit trail for legal compliance and evidence integrity.
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any

from app.models.schemas import CustodyEvent, CustodyEventResponse, CustodyChainResponse

logger = logging.getLogger(__name__)


class CustodyChainService:
    """Service for tracking evidence chain of custody."""

    def __init__(self):
        self._db = None

    async def _get_db(self):
        """Lazy-load database service."""
        if self._db is None:
            from app.services.database import get_database
            self._db = get_database()
            if self._db._db is None:
                await self._db.initialize()
        return self._db

    def _compute_hash(self, data: Any) -> str:
        """Compute SHA-256 hash of data for integrity verification."""
        if data is None:
            return ""
        try:
            if hasattr(data, 'model_dump'):
                data_str = json.dumps(data.model_dump(), sort_keys=True, default=str)
            elif isinstance(data, dict):
                data_str = json.dumps(data, sort_keys=True, default=str)
            else:
                data_str = str(data)
            return hashlib.sha256(data_str.encode()).hexdigest()[:16]
        except Exception as e:
            logger.warning(f"Failed to compute hash: {e}")
            return ""

    async def record_event(
        self,
        evidence_type: str,
        evidence_id: str,
        action: str,
        actor: str,
        actor_role: Optional[str] = None,
        details: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        data_before: Any = None,
        data_after: Any = None,
    ) -> CustodyEvent:
        """
        Record a custody event for evidence tracking.

        Args:
            evidence_type: Type of evidence (session, case, evidence_marker, etc.)
            evidence_id: ID of the evidence item
            action: Action performed (created, viewed, modified, exported, etc.)
            actor: User or system performing the action
            actor_role: Role of the actor (investigator, admin, system)
            details: Description of what changed
            metadata: Additional context (IP address, session info, etc.)
            data_before: State of evidence before change (for hash)
            data_after: State of evidence after change (for hash)

        Returns:
            The created CustodyEvent
        """
        event = CustodyEvent(
            id=str(uuid.uuid4()),
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            action=action,
            actor=actor,
            actor_role=actor_role,
            details=details,
            metadata=metadata or {},
            timestamp=datetime.utcnow(),
            hash_before=self._compute_hash(data_before) if data_before else None,
            hash_after=self._compute_hash(data_after) if data_after else None,
        )

        try:
            db = await self._get_db()
            await db.save_custody_event(event.model_dump(mode='json'))
            logger.info(f"Recorded custody event: {action} on {evidence_type}/{evidence_id} by {actor}")
        except Exception as e:
            logger.error(f"Failed to save custody event: {e}")

        return event

    async def get_custody_chain(
        self,
        evidence_type: str,
        evidence_id: str,
        limit: int = 100,
    ) -> CustodyChainResponse:
        """
        Get the full chain of custody for an evidence item.

        Args:
            evidence_type: Type of evidence
            evidence_id: ID of the evidence item
            limit: Maximum number of events to return

        Returns:
            CustodyChainResponse with all custody events
        """
        try:
            db = await self._get_db()
            events_data = await db.get_custody_events(evidence_type, evidence_id, limit)
            
            events = []
            unique_actors = set()
            first_access = None
            last_access = None

            for event_dict in events_data:
                event = CustodyEventResponse(
                    id=event_dict.get('id', ''),
                    evidence_type=event_dict.get('evidence_type', evidence_type),
                    evidence_id=event_dict.get('evidence_id', evidence_id),
                    action=event_dict.get('action', ''),
                    actor=event_dict.get('actor', ''),
                    actor_role=event_dict.get('actor_role'),
                    details=event_dict.get('details'),
                    timestamp=datetime.fromisoformat(event_dict['timestamp']) if isinstance(event_dict.get('timestamp'), str) else event_dict.get('timestamp', datetime.utcnow()),
                    hash_before=event_dict.get('hash_before'),
                    hash_after=event_dict.get('hash_after'),
                )
                events.append(event)
                unique_actors.add(event.actor)
                
                if first_access is None or event.timestamp < first_access:
                    first_access = event.timestamp
                if last_access is None or event.timestamp > last_access:
                    last_access = event.timestamp

            return CustodyChainResponse(
                evidence_type=evidence_type,
                evidence_id=evidence_id,
                total_events=len(events),
                events=events,
                first_access=first_access,
                last_access=last_access,
                unique_actors=list(unique_actors),
            )
        except Exception as e:
            logger.error(f"Failed to get custody chain: {e}")
            return CustodyChainResponse(
                evidence_type=evidence_type,
                evidence_id=evidence_id,
                total_events=0,
                events=[],
                first_access=None,
                last_access=None,
                unique_actors=[],
            )

    async def get_all_custody_for_session(
        self,
        session_id: str,
        limit: int = 500,
    ) -> List[CustodyEventResponse]:
        """
        Get all custody events related to a session and its evidence.

        Args:
            session_id: Session ID
            limit: Maximum events to return

        Returns:
            List of all custody events for the session
        """
        try:
            db = await self._get_db()
            events_data = await db.get_all_custody_for_session(session_id, limit)
            
            events = []
            for event_dict in events_data:
                event = CustodyEventResponse(
                    id=event_dict.get('id', ''),
                    evidence_type=event_dict.get('evidence_type', ''),
                    evidence_id=event_dict.get('evidence_id', ''),
                    action=event_dict.get('action', ''),
                    actor=event_dict.get('actor', ''),
                    actor_role=event_dict.get('actor_role'),
                    details=event_dict.get('details'),
                    timestamp=datetime.fromisoformat(event_dict['timestamp']) if isinstance(event_dict.get('timestamp'), str) else event_dict.get('timestamp', datetime.utcnow()),
                    hash_before=event_dict.get('hash_before'),
                    hash_after=event_dict.get('hash_after'),
                )
                events.append(event)

            return events
        except Exception as e:
            logger.error(f"Failed to get custody events for session: {e}")
            return []

    async def record_session_created(self, session_id: str, actor: str = "system", metadata: Dict = None):
        """Helper to record session creation."""
        return await self.record_event(
            evidence_type="session",
            evidence_id=session_id,
            action="created",
            actor=actor,
            details="Session created",
            metadata=metadata,
        )

    async def record_session_viewed(self, session_id: str, actor: str, metadata: Dict = None):
        """Helper to record session view."""
        return await self.record_event(
            evidence_type="session",
            evidence_id=session_id,
            action="viewed",
            actor=actor,
            details="Session accessed",
            metadata=metadata,
        )

    async def record_session_modified(self, session_id: str, actor: str, details: str, data_before=None, data_after=None, metadata: Dict = None):
        """Helper to record session modification."""
        return await self.record_event(
            evidence_type="session",
            evidence_id=session_id,
            action="modified",
            actor=actor,
            details=details,
            data_before=data_before,
            data_after=data_after,
            metadata=metadata,
        )

    async def record_evidence_exported(self, evidence_type: str, evidence_id: str, actor: str, export_format: str, metadata: Dict = None):
        """Helper to record evidence export."""
        return await self.record_event(
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            action="exported",
            actor=actor,
            details=f"Exported as {export_format}",
            metadata=metadata,
        )

    async def record_statement_added(self, session_id: str, statement_id: str, actor: str = "system", metadata: Dict = None):
        """Helper to record statement added to session."""
        return await self.record_event(
            evidence_type="statement",
            evidence_id=statement_id,
            action="created",
            actor=actor,
            details=f"Statement added to session {session_id}",
            metadata={"session_id": session_id, **(metadata or {})},
        )

    async def record_marker_added(self, session_id: str, marker_id: str, actor: str, metadata: Dict = None):
        """Helper to record evidence marker added."""
        return await self.record_event(
            evidence_type="evidence_marker",
            evidence_id=marker_id,
            action="created",
            actor=actor,
            details=f"Evidence marker added to session {session_id}",
            metadata={"session_id": session_id, **(metadata or {})},
        )

    async def record_scene_generated(self, session_id: str, version: int, actor: str = "system", metadata: Dict = None):
        """Helper to record scene version generated."""
        return await self.record_event(
            evidence_type="scene_version",
            evidence_id=f"{session_id}_v{version}",
            action="created",
            actor=actor,
            details=f"Scene version {version} generated",
            metadata={"session_id": session_id, "version": version, **(metadata or {})},
        )


# Global singleton instance
custody_chain_service = CustodyChainService()
