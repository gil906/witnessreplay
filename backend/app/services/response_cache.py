"""
Response caching service using embeddings for semantic similarity.
Caches AI responses and returns cached results for similar queries.
Significantly reduces redundant API calls for identical/similar queries.
"""
import logging
import asyncio
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CachedResponse:
    """A cached AI response with its query embedding."""
    query: str
    response: str
    embedding: List[float]
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 3600  # Default 1 hour
    hit_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.utcnow() > (self.created_at + timedelta(seconds=self.ttl_seconds))
    
    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {
            "query": self.query,
            "response": self.response,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "hit_count": self.hit_count,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CachedResponse":
        """Deserialize from persistence."""
        return cls(
            query=data["query"],
            response=data["response"],
            embedding=data["embedding"],
            created_at=datetime.fromisoformat(data["created_at"]),
            ttl_seconds=data.get("ttl_seconds", 3600),
            hit_count=data.get("hit_count", 0),
            metadata=data.get("metadata", {}),
        )


class ResponseCache:
    """
    Embedding-based response cache for AI calls.
    Uses cosine similarity to find cached responses for semantically similar queries.
    """
    
    DEFAULT_SIMILARITY_THRESHOLD = 0.95
    DEFAULT_TTL_SECONDS = 3600  # 1 hour
    MAX_CACHE_SIZE = 1000
    
    def __init__(
        self,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        default_ttl: int = DEFAULT_TTL_SECONDS,
    ):
        self.similarity_threshold = similarity_threshold
        self.default_ttl = default_ttl
        self._cache: Dict[str, CachedResponse] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._embedding_service = None
        logger.info(f"ResponseCache initialized (threshold={similarity_threshold}, ttl={default_ttl}s)")
    
    def _get_embedding_service(self):
        """Lazy load embedding service to avoid circular imports."""
        if self._embedding_service is None:
            from app.services.embedding_service import embedding_service
            self._embedding_service = embedding_service
        return self._embedding_service
    
    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute hash for exact match lookup."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    async def get(
        self,
        query: str,
        context_key: str = "",
        threshold: Optional[float] = None,
    ) -> Optional[Tuple[str, float]]:
        """
        Find a cached response for a similar query.
        
        Args:
            query: The query text to match
            context_key: Optional key to scope cache (e.g., session_id, task_type)
            threshold: Override similarity threshold for this lookup
            
        Returns:
            Tuple of (cached_response, similarity_score) or None if no match
        """
        threshold = threshold or self.similarity_threshold
        
        # Fast path: exact hash match
        query_hash = self._compute_hash(f"{context_key}:{query}")
        async with self._lock:
            if query_hash in self._cache:
                entry = self._cache[query_hash]
                if not entry.is_expired():
                    entry.hit_count += 1
                    self._hits += 1
                    logger.debug(f"Exact cache hit for query hash {query_hash}")
                    return entry.response, 1.0
                else:
                    del self._cache[query_hash]
        
        # Slow path: semantic similarity search
        embedding_svc = self._get_embedding_service()
        query_embedding, _ = await embedding_svc.embed_text(query, task_type="SEMANTIC_SIMILARITY")
        
        if not query_embedding:
            self._misses += 1
            return None
        
        best_match: Optional[CachedResponse] = None
        best_score = threshold
        
        async with self._lock:
            for key, entry in list(self._cache.items()):
                # Skip expired entries
                if entry.is_expired():
                    del self._cache[key]
                    continue
                
                # Skip if context doesn't match
                if context_key and entry.metadata.get("context_key") != context_key:
                    continue
                
                # Compute similarity
                score = embedding_svc.cosine_similarity(query_embedding, entry.embedding)
                if score > best_score:
                    best_score = score
                    best_match = entry
        
        if best_match:
            async with self._lock:
                best_match.hit_count += 1
            self._hits += 1
            logger.info(f"Semantic cache hit (similarity={best_score:.4f})")
            return best_match.response, best_score
        
        self._misses += 1
        return None
    
    async def set(
        self,
        query: str,
        response: str,
        context_key: str = "",
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Cache a response with its query embedding.
        
        Args:
            query: The original query
            response: The AI response to cache
            context_key: Optional key to scope cache
            ttl_seconds: Time to live (defaults to instance default)
            metadata: Additional metadata to store
            
        Returns:
            True if cached successfully
        """
        embedding_svc = self._get_embedding_service()
        embedding, _ = await embedding_svc.embed_text(query, task_type="SEMANTIC_SIMILARITY")
        
        if not embedding:
            logger.warning("Failed to generate embedding for cache entry")
            return False
        
        query_hash = self._compute_hash(f"{context_key}:{query}")
        entry_metadata = metadata or {}
        entry_metadata["context_key"] = context_key
        
        entry = CachedResponse(
            query=query,
            response=response,
            embedding=embedding,
            ttl_seconds=ttl_seconds or self.default_ttl,
            metadata=entry_metadata,
        )
        
        async with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                await self._evict_oldest()
            
            self._cache[query_hash] = entry
        
        # Persist in background
        asyncio.create_task(self._persist_entry(query_hash, entry))
        
        logger.debug(f"Cached response for query hash {query_hash}")
        return True
    
    async def _evict_oldest(self):
        """Evict oldest/least-used entries when cache is full."""
        if not self._cache:
            return
        
        # Sort by (expired first, then by hit_count ascending, then by age)
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: (
                not x[1].is_expired(),  # Expired first
                x[1].hit_count,         # Then least used
                x[1].created_at,        # Then oldest
            )
        )
        
        # Remove bottom 10%
        remove_count = max(1, len(sorted_entries) // 10)
        for key, _ in sorted_entries[:remove_count]:
            del self._cache[key]
        
        logger.info(f"Evicted {remove_count} cache entries")
    
    async def _persist_entry(self, key: str, entry: CachedResponse):
        """Persist cache entry to SQLite for survival across restarts."""
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.execute("""
                    CREATE TABLE IF NOT EXISTS response_cache (
                        key TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        created_at TEXT
                    )
                """)
                await db_svc._db.execute(
                    "INSERT OR REPLACE INTO response_cache (key, data, created_at) VALUES (?, ?, ?)",
                    (key, json.dumps(entry.to_dict()), datetime.utcnow().isoformat())
                )
                await db_svc._db.commit()
        except Exception as e:
            logger.debug(f"Failed to persist cache entry: {e}")
    
    async def load_from_db(self):
        """Load cached responses from SQLite on startup."""
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.execute("""
                    CREATE TABLE IF NOT EXISTS response_cache (
                        key TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        created_at TEXT
                    )
                """)
                async with db_svc._db.execute("SELECT key, data FROM response_cache") as cursor:
                    loaded = 0
                    async for row in cursor:
                        try:
                            entry = CachedResponse.from_dict(json.loads(row[1]))
                            if not entry.is_expired():
                                self._cache[row[0]] = entry
                                loaded += 1
                        except Exception:
                            pass
                    if loaded:
                        logger.info(f"Loaded {loaded} cached responses from SQLite")
        except Exception as e:
            logger.debug(f"Could not load cached responses: {e}")
    
    async def invalidate(self, context_key: str = ""):
        """Invalidate all cache entries matching a context key."""
        async with self._lock:
            if not context_key:
                count = len(self._cache)
                self._cache.clear()
                logger.info(f"Invalidated all {count} cache entries")
            else:
                keys_to_remove = [
                    k for k, v in self._cache.items()
                    if v.metadata.get("context_key") == context_key
                ]
                for key in keys_to_remove:
                    del self._cache[key]
                logger.info(f"Invalidated {len(keys_to_remove)} cache entries for context '{context_key}'")
    
    async def cleanup_expired(self):
        """Remove all expired entries."""
        async with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        
        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 2),
            "similarity_threshold": self.similarity_threshold,
            "default_ttl": self.default_ttl,
            "max_size": self.MAX_CACHE_SIZE,
        }


# Global instance
response_cache = ResponseCache()


async def cached_ai_call(
    query: str,
    ai_func,
    context_key: str = "",
    threshold: float = 0.95,
    ttl_seconds: int = 3600,
    **kwargs,
) -> Tuple[Any, bool]:
    """
    Wrapper for AI calls with automatic caching.
    
    Args:
        query: The query/prompt to send to the AI
        ai_func: Async function that makes the AI call (receives query as first arg)
        context_key: Optional scope for caching
        threshold: Similarity threshold for cache hits
        ttl_seconds: Time to live for cached responses
        **kwargs: Additional arguments passed to ai_func
        
    Returns:
        Tuple of (response, was_cached)
    """
    # Check cache first
    cached = await response_cache.get(query, context_key=context_key, threshold=threshold)
    if cached:
        response, similarity = cached
        logger.info(f"Using cached response (similarity={similarity:.4f})")
        return response, True
    
    # Make actual AI call
    response = await ai_func(query, **kwargs)
    
    # Cache the response
    if response:
        await response_cache.set(
            query=query,
            response=response if isinstance(response, str) else str(response),
            context_key=context_key,
            ttl_seconds=ttl_seconds,
        )
    
    return response, False
