"""
Conversation memory service for persistent witness memory across sessions.

Uses embeddings for semantic retrieval of relevant memories.
"""
import logging
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from app.services.embedding_service import embedding_service
from app.config import settings

logger = logging.getLogger(__name__)


class WitnessMemory:
    """Represents a stored memory about a witness."""
    
    def __init__(
        self,
        id: str,
        witness_id: str,
        memory_type: str,  # "fact", "testimony", "behavior", "relationship"
        content: str,
        session_id: Optional[str] = None,
        case_id: Optional[str] = None,
        confidence: float = 0.5,
        embedding: Optional[List[float]] = None,
        created_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.witness_id = witness_id
        self.memory_type = memory_type
        self.content = content
        self.session_id = session_id
        self.case_id = case_id
        self.confidence = confidence
        self.embedding = embedding
        self.created_at = created_at or datetime.utcnow().isoformat()
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "witness_id": self.witness_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "session_id": self.session_id,
            "case_id": self.case_id,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WitnessMemory":
        return cls(
            id=data["id"],
            witness_id=data["witness_id"],
            memory_type=data["memory_type"],
            content=data["content"],
            session_id=data.get("session_id"),
            case_id=data.get("case_id"),
            confidence=data.get("confidence", 0.5),
            embedding=data.get("embedding"),
            created_at=data.get("created_at"),
            metadata=data.get("metadata", {}),
        )


class MemoryService:
    """
    Service for managing persistent witness memories across sessions.
    
    Uses semantic embeddings for relevant memory retrieval.
    """
    
    def __init__(self):
        self._memories: Dict[str, WitnessMemory] = {}  # In-memory cache
        self._db_initialized = False
    
    async def _ensure_db(self):
        """Ensure memory tables exist in SQLite."""
        if self._db_initialized:
            return
        
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.executescript("""
                    CREATE TABLE IF NOT EXISTS witness_memories (
                        id TEXT PRIMARY KEY,
                        witness_id TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        session_id TEXT,
                        case_id TEXT,
                        confidence REAL DEFAULT 0.5,
                        embedding TEXT,
                        created_at TEXT,
                        metadata TEXT DEFAULT '{}'
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_witness_memories_witness 
                        ON witness_memories(witness_id);
                    CREATE INDEX IF NOT EXISTS idx_witness_memories_case 
                        ON witness_memories(case_id);
                    CREATE INDEX IF NOT EXISTS idx_witness_memories_type 
                        ON witness_memories(memory_type);
                """)
                await db_svc._db.commit()
                self._db_initialized = True
                logger.info("Memory tables initialized")
        except Exception as e:
            logger.error(f"Failed to initialize memory tables: {e}")
    
    async def store_memory(
        self,
        witness_id: str,
        memory_type: str,
        content: str,
        session_id: Optional[str] = None,
        case_id: Optional[str] = None,
        confidence: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[WitnessMemory]:
        """
        Store a new memory about a witness.
        
        Args:
            witness_id: ID of the witness
            memory_type: Type of memory (fact, testimony, behavior, relationship)
            content: The memory content
            session_id: Optional session where this was recorded
            case_id: Optional case this relates to
            confidence: Confidence score (0-1)
            metadata: Additional metadata
            
        Returns:
            The stored memory, or None on failure
        """
        await self._ensure_db()
        
        memory_id = str(uuid.uuid4())
        
        # Generate embedding for semantic search
        embedding, token_info = await embedding_service.embed_text(
            content, 
            task_type="RETRIEVAL_DOCUMENT"
        )
        
        memory = WitnessMemory(
            id=memory_id,
            witness_id=witness_id,
            memory_type=memory_type,
            content=content,
            session_id=session_id,
            case_id=case_id,
            confidence=confidence,
            embedding=embedding,
            metadata=metadata,
        )
        
        # Cache in memory
        self._memories[memory_id] = memory
        
        # Persist to SQLite
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.execute(
                    """INSERT INTO witness_memories 
                       (id, witness_id, memory_type, content, session_id, case_id, 
                        confidence, embedding, created_at, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        memory.id,
                        memory.witness_id,
                        memory.memory_type,
                        memory.content,
                        memory.session_id,
                        memory.case_id,
                        memory.confidence,
                        json.dumps(embedding) if embedding else None,
                        memory.created_at,
                        json.dumps(memory.metadata),
                    ),
                )
                await db_svc._db.commit()
                logger.info(f"Stored memory {memory_id} for witness {witness_id}")
        except Exception as e:
            logger.error(f"Failed to persist memory: {e}")
        
        return memory
    
    async def retrieve_relevant_memories(
        self,
        witness_id: str,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
        memory_types: Optional[List[str]] = None,
    ) -> List[Tuple[WitnessMemory, float]]:
        """
        Retrieve relevant memories for a witness based on semantic similarity.
        
        Args:
            witness_id: ID of the witness
            query: The query text to match against
            top_k: Maximum number of memories to return
            threshold: Minimum similarity score
            memory_types: Optional filter by memory types
            
        Returns:
            List of (memory, similarity_score) tuples sorted by relevance
        """
        await self._ensure_db()
        
        # Get query embedding
        query_embedding, _ = await embedding_service.embed_text(
            query, 
            task_type="RETRIEVAL_QUERY"
        )
        
        if not query_embedding:
            logger.warning("Could not generate query embedding")
            return []
        
        # Get all memories for this witness
        memories = await self.get_witness_memories(witness_id, memory_types)
        
        # Score each memory by similarity
        scored_memories: List[Tuple[WitnessMemory, float]] = []
        
        for memory in memories:
            if memory.embedding:
                similarity = embedding_service.cosine_similarity(
                    query_embedding, 
                    memory.embedding
                )
                if similarity >= threshold:
                    scored_memories.append((memory, similarity))
            else:
                # Re-generate embedding if missing
                embedding, _ = await embedding_service.embed_text(
                    memory.content,
                    task_type="RETRIEVAL_DOCUMENT"
                )
                if embedding:
                    memory.embedding = embedding
                    similarity = embedding_service.cosine_similarity(
                        query_embedding, 
                        embedding
                    )
                    if similarity >= threshold:
                        scored_memories.append((memory, similarity))
        
        # Sort by similarity and return top_k
        scored_memories.sort(key=lambda x: x[1], reverse=True)
        return scored_memories[:top_k]
    
    async def get_witness_memories(
        self,
        witness_id: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[WitnessMemory]:
        """
        Get all memories for a witness.
        
        Args:
            witness_id: ID of the witness
            memory_types: Optional filter by memory types
            limit: Maximum number to return
            
        Returns:
            List of memories
        """
        await self._ensure_db()
        
        memories = []
        
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                if memory_types:
                    placeholders = ",".join("?" * len(memory_types))
                    query = f"""SELECT * FROM witness_memories 
                               WHERE witness_id = ? AND memory_type IN ({placeholders})
                               ORDER BY created_at DESC LIMIT ?"""
                    params = [witness_id] + memory_types + [limit]
                else:
                    query = """SELECT * FROM witness_memories 
                              WHERE witness_id = ?
                              ORDER BY created_at DESC LIMIT ?"""
                    params = [witness_id, limit]
                
                async with db_svc._db.execute(query, params) as cursor:
                    async for row in cursor:
                        row_dict = dict(row)
                        # Parse JSON fields
                        if row_dict.get("embedding"):
                            row_dict["embedding"] = json.loads(row_dict["embedding"])
                        if row_dict.get("metadata"):
                            row_dict["metadata"] = json.loads(row_dict["metadata"])
                        memories.append(WitnessMemory.from_dict(row_dict))
        except Exception as e:
            logger.error(f"Failed to get witness memories: {e}")
        
        return memories
    
    async def get_memory(self, memory_id: str) -> Optional[WitnessMemory]:
        """Get a specific memory by ID."""
        # Check cache first
        if memory_id in self._memories:
            return self._memories[memory_id]
        
        await self._ensure_db()
        
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                async with db_svc._db.execute(
                    "SELECT * FROM witness_memories WHERE id = ?", (memory_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        row_dict = dict(row)
                        if row_dict.get("embedding"):
                            row_dict["embedding"] = json.loads(row_dict["embedding"])
                        if row_dict.get("metadata"):
                            row_dict["metadata"] = json.loads(row_dict["metadata"])
                        return WitnessMemory.from_dict(row_dict)
        except Exception as e:
            logger.error(f"Failed to get memory: {e}")
        
        return None
    
    async def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[WitnessMemory]:
        """Update an existing memory."""
        memory = await self.get_memory(memory_id)
        if not memory:
            return None
        
        if content is not None:
            memory.content = content
            # Re-generate embedding for new content
            embedding, _ = await embedding_service.embed_text(
                content,
                task_type="RETRIEVAL_DOCUMENT"
            )
            memory.embedding = embedding
        
        if confidence is not None:
            memory.confidence = confidence
        
        if metadata is not None:
            memory.metadata.update(metadata)
        
        # Update in database
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.execute(
                    """UPDATE witness_memories 
                       SET content = ?, confidence = ?, embedding = ?, metadata = ?
                       WHERE id = ?""",
                    (
                        memory.content,
                        memory.confidence,
                        json.dumps(memory.embedding) if memory.embedding else None,
                        json.dumps(memory.metadata),
                        memory_id,
                    ),
                )
                await db_svc._db.commit()
        except Exception as e:
            logger.error(f"Failed to update memory: {e}")
            return None
        
        # Update cache
        self._memories[memory_id] = memory
        return memory
    
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory."""
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.execute(
                    "DELETE FROM witness_memories WHERE id = ?", (memory_id,)
                )
                await db_svc._db.commit()
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False
        
        # Remove from cache
        if memory_id in self._memories:
            del self._memories[memory_id]
        
        return True
    
    async def extract_memories_from_session(
        self,
        session_id: str,
        witness_id: str,
        statements: List[Dict[str, Any]],
        case_id: Optional[str] = None,
    ) -> List[WitnessMemory]:
        """
        Extract and store memories from a completed interview session.
        
        Args:
            session_id: The session ID
            witness_id: The witness ID
            statements: List of witness statements from the session
            case_id: Optional case ID
            
        Returns:
            List of extracted memories
        """
        extracted_memories = []
        
        # Combine statements for fact extraction
        all_text = " ".join([s.get("text", "") for s in statements])
        
        if not all_text.strip():
            return []
        
        # Use AI to extract key facts (could use structured output)
        try:
            from google import genai
            from app.services.model_selector import model_selector, call_with_retry
            import asyncio
            
            if settings.google_api_key:
                client = genai.Client(api_key=settings.google_api_key)
                
                extraction_prompt = f"""Extract key facts from this witness testimony that should be remembered for future interviews.

Testimony:
{all_text}

Return a JSON array of facts to remember. Each fact should have:
- "type": one of "fact", "testimony", "behavior", "relationship"
- "content": the fact to remember (1-2 sentences max)
- "confidence": how certain this fact is (0.0-1.0)

Focus on:
- Physical descriptions of people, vehicles, objects
- Locations and landmarks mentioned
- Timeline details and sequences of events
- Relationships between people mentioned
- The witness's vantage point and involvement

Return ONLY the JSON array, no other text."""

                lightweight_model = await model_selector.get_best_model_for_task("lightweight")
                
                response = await call_with_retry(
                    asyncio.to_thread,
                    client.models.generate_content,
                    model=lightweight_model,
                    contents=extraction_prompt,
                    config={"temperature": 0.2},
                    model_name=lightweight_model,
                )
                
                # Parse response
                response_text = response.text.strip()
                # Handle markdown code blocks
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                
                facts = json.loads(response_text)
                
                for fact in facts:
                    memory = await self.store_memory(
                        witness_id=witness_id,
                        memory_type=fact.get("type", "fact"),
                        content=fact.get("content", ""),
                        session_id=session_id,
                        case_id=case_id,
                        confidence=fact.get("confidence", 0.5),
                        metadata={"source": "auto_extraction"}
                    )
                    if memory:
                        extracted_memories.append(memory)
                
                logger.info(f"Extracted {len(extracted_memories)} memories from session {session_id}")
                
        except Exception as e:
            logger.error(f"Failed to extract memories from session: {e}")
        
        return extracted_memories
    
    async def build_memory_context(
        self,
        witness_id: str,
        current_statement: str,
        max_memories: int = 5,
    ) -> str:
        """
        Build a context string with relevant memories for the AI.
        
        Args:
            witness_id: The witness ID
            current_statement: The current conversation context
            max_memories: Maximum memories to include
            
        Returns:
            Formatted context string for AI prompt
        """
        relevant = await self.retrieve_relevant_memories(
            witness_id=witness_id,
            query=current_statement,
            top_k=max_memories,
            threshold=0.5,
        )
        
        if not relevant:
            return ""
        
        context_parts = [
            "\n[PRIOR KNOWLEDGE ABOUT THIS WITNESS]",
            "The following facts are known from previous interactions:"
        ]
        
        for memory, score in relevant:
            confidence_label = "high" if memory.confidence > 0.7 else "medium" if memory.confidence > 0.4 else "low"
            context_parts.append(
                f"- ({memory.memory_type}, {confidence_label} confidence): {memory.content}"
            )
        
        context_parts.append("[END PRIOR KNOWLEDGE]\n")
        
        return "\n".join(context_parts)
    
    async def get_memory_stats(self, witness_id: Optional[str] = None) -> Dict[str, Any]:
        """Get memory statistics."""
        await self._ensure_db()
        
        stats = {
            "total_memories": 0,
            "by_type": {},
            "by_witness": {},
        }
        
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                if witness_id:
                    async with db_svc._db.execute(
                        "SELECT COUNT(*) FROM witness_memories WHERE witness_id = ?",
                        (witness_id,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        stats["total_memories"] = row[0] if row else 0
                    
                    async with db_svc._db.execute(
                        """SELECT memory_type, COUNT(*) as count 
                           FROM witness_memories WHERE witness_id = ?
                           GROUP BY memory_type""",
                        (witness_id,)
                    ) as cursor:
                        async for row in cursor:
                            stats["by_type"][row[0]] = row[1]
                else:
                    async with db_svc._db.execute(
                        "SELECT COUNT(*) FROM witness_memories"
                    ) as cursor:
                        row = await cursor.fetchone()
                        stats["total_memories"] = row[0] if row else 0
                    
                    async with db_svc._db.execute(
                        """SELECT memory_type, COUNT(*) as count 
                           FROM witness_memories GROUP BY memory_type"""
                    ) as cursor:
                        async for row in cursor:
                            stats["by_type"][row[0]] = row[1]
                    
                    async with db_svc._db.execute(
                        """SELECT witness_id, COUNT(*) as count 
                           FROM witness_memories GROUP BY witness_id"""
                    ) as cursor:
                        async for row in cursor:
                            stats["by_witness"][row[0]] = row[1]
        except Exception as e:
            logger.error(f"Failed to get memory stats: {e}")
        
        return stats


# Global instance
memory_service = MemoryService()
