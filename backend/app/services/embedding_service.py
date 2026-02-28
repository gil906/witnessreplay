"""
Embedding service using Gemini Embedding 1 for semantic case matching.
100 RPM / 30K TPM / 1K RPD - very generous quota!

Now supports request batching to reduce RPM consumption.
"""
import logging
import asyncio
import json
import math
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, timezone
from google import genai

from app.services.token_estimator import token_estimator

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generates and manages text embeddings for semantic search and case matching."""

    MODEL = "gemini-embedding-001"
    EMBEDDING_DIM = 768  # Default dimension
    CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h default cache TTL

    def __init__(self):
        self.client = None
        self._cache: Dict[str, Dict[str, Any]] = {}  # key -> {"embedding": [...], "cached_at": iso}
        self._cache_ttl_seconds = self.CACHE_TTL_SECONDS
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_expired_purged = 0
        self._last_cache_cleanup: str = ""
        self._request_count = 0
        self._token_usage = 0  # Track token usage for TPM limit
        self._last_reset = ""
        self._initialize()

    def _initialize(self):
        from app.config import settings
        if settings.google_api_key:
            self.client = genai.Client(api_key=settings.google_api_key)
            logger.info("EmbeddingService initialized")

    def _get_token_usage(self) -> int:
        """Get current token usage for the day."""
        self._reset_daily_if_needed()
        return self._token_usage

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.utcnow().isoformat()

    def _create_cache_entry(self, embedding: List[float], cached_at: Optional[str] = None) -> Dict[str, Any]:
        return {
            "embedding": embedding,
            "cached_at": cached_at or self._utcnow_iso(),
        }

    def _is_cache_entry_expired(self, entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False  # legacy in-memory entry without metadata

        cached_at = entry.get("cached_at")
        if not cached_at:
            return False

        try:
            ts = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00"))
            if ts.tzinfo is not None:
                ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
            age_seconds = (datetime.utcnow() - ts).total_seconds()
            return age_seconds > self._cache_ttl_seconds
        except Exception:
            return False

    def cleanup_expired_cache(self) -> int:
        """Lazily purge expired in-memory cache entries."""
        expired_keys = [
            key for key, entry in self._cache.items()
            if self._is_cache_entry_expired(entry)
        ]
        for key in expired_keys:
            self._cache.pop(key, None)

        purged = len(expired_keys)
        if purged:
            self._cache_expired_purged += purged
            logger.debug(f"Purged {purged} expired embedding cache entries")
        self._last_cache_cleanup = self._utcnow_iso()
        return purged

    @staticmethod
    def _extract_embedding(entry: Any) -> Optional[List[float]]:
        if isinstance(entry, dict):
            embedding = entry.get("embedding")
            if isinstance(embedding, list):
                return embedding
            return None
        if isinstance(entry, list):
            return entry
        return None

    async def embed_text(
        self, 
        text: str, 
        task_type: str = "SEMANTIC_SIMILARITY",
        precheck: bool = True
    ) -> Tuple[Optional[List[float]], Optional[Dict]]:
        """
        Generate embedding for text. Returns (vector, token_info) or (None, None).
        
        Args:
            text: Text to embed
            task_type: Embedding task type
            precheck: Whether to pre-check token quota
            
        Returns:
            Tuple of (embedding vector, token_info dict)
        """
        if not self.client:
            return None, None

        self.cleanup_expired_cache()

        # Check cache first
        cache_key = f"{task_type}:{hash(text)}"
        cached_embedding = self._extract_embedding(self._cache.get(cache_key))
        if cached_embedding:
            self._cache_hits += 1
            return cached_embedding, {"cached": True, "estimated_tokens": 0}
        self._cache_misses += 1

        self._reset_daily_if_needed()
        if self._request_count >= 1000:
            logger.warning("Embedding daily quota exhausted")
            return None, {"error": "daily_quota_exhausted", "limit": 1000}

        # Pre-check token quota
        estimated_tokens = token_estimator.estimate_tokens(text[:8000])
        token_info = {
            "estimated_tokens": estimated_tokens,
            "model": self.MODEL,
        }
        
        if precheck:
            quota_check = token_estimator.check_quota(
                model_name=self.MODEL,
                estimated_tokens=estimated_tokens,
                current_usage=self._get_token_usage(),
                enforce=False,  # Warn but don't reject for embeddings
            )
            token_info["quota_check"] = quota_check.to_dict()
            if quota_check.warning:
                logger.warning(f"Embedding quota warning: {quota_check.warning}")

        try:
            result = await asyncio.to_thread(
                self.client.models.embed_content,
                model=self.MODEL,
                contents=text[:8000],  # Limit input size
                config={"task_type": task_type}
            )

            self._request_count += 1
            self._token_usage += estimated_tokens

            if result and result.embeddings:
                embedding = result.embeddings[0].values
                self._cache[cache_key] = self._create_cache_entry(embedding)
                # Persist to SQLite in background
                asyncio.create_task(self._save_embedding_to_db(cache_key, embedding))
                return embedding, token_info
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                logger.warning("Embedding API rate limited")
                token_info["error"] = "rate_limited"
            else:
                logger.error(f"Embedding error: {e}")
                token_info["error"] = str(e)

        return None, token_info

    async def embed_batch(
        self, 
        texts: List[str], 
        task_type: str = "SEMANTIC_SIMILARITY",
        use_batcher: bool = True
    ) -> List[Tuple[Optional[List[float]], Optional[Dict]]]:
        """Embed multiple texts efficiently using the request batcher.
        
        Args:
            texts: List of texts to embed
            task_type: Embedding task type
            use_batcher: If True, use request batcher for RPM efficiency
            
        Returns:
            List of (embedding vector, token_info) tuples
        """
        if not use_batcher:
            # Fall back to sequential processing
            results = []
            for text in texts:
                embedding, token_info = await self.embed_text(text, task_type)
                results.append((embedding, token_info))
            return results
        
        # Use the request batcher for efficient batching
        try:
            from app.services.request_batcher import request_batcher
            
            # Create batch items
            batch_items = [
                {"text": text, "task_type": task_type}
                for text in texts
            ]
            
            # Submit all items to the batcher concurrently
            tasks = [
                request_batcher.add_to_batch("embedding", item)
                for item in batch_items
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Convert exceptions to error tuples
            processed_results = []
            for r in results:
                if isinstance(r, Exception):
                    processed_results.append((None, {"error": str(r)}))
                else:
                    processed_results.append(r)
            
            return processed_results
            
        except Exception as e:
            logger.warning(f"Batcher failed, falling back to sequential: {e}")
            # Fall back to sequential processing
            results = []
            for text in texts:
                embedding, token_info = await self.embed_text(text, task_type)
                results.append((embedding, token_info))
            return results

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        magnitude_a = math.sqrt(sum(a * a for a in vec_a))
        magnitude_b = math.sqrt(sum(b * b for b in vec_b))

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)

    async def find_most_similar(self, query_text: str, candidates: List[Tuple[str, str]], threshold: float = 0.75) -> Optional[str]:
        """Find the most similar candidate to query text.

        Args:
            query_text: The text to match against
            candidates: List of (id, text) tuples
            threshold: Minimum similarity score (0-1)

        Returns:
            ID of best match, or None if below threshold
        """
        query_embedding, _ = await self.embed_text(query_text)
        if not query_embedding:
            return None

        best_id = None
        best_score = threshold

        for candidate_id, candidate_text in candidates:
            candidate_embedding, _ = await self.embed_text(candidate_text)
            if candidate_embedding:
                score = self.cosine_similarity(query_embedding, candidate_embedding)
                if score > best_score:
                    best_score = score
                    best_id = candidate_id

        if best_id:
            logger.info(f"Found match with similarity {best_score:.3f}")

        return best_id

    async def semantic_search(self, query: str, documents: List[Tuple[str, str]], top_k: int = 5) -> List[Tuple[str, float]]:
        """Search documents by semantic similarity.

        Args:
            query: Search query
            documents: List of (id, text) tuples
            top_k: Number of top results

        Returns:
            List of (id, score) tuples sorted by relevance
        """
        query_embedding, _ = await self.embed_text(query, task_type="RETRIEVAL_QUERY")
        if not query_embedding:
            return []

        scores = []
        for doc_id, doc_text in documents:
            doc_embedding, _ = await self.embed_text(doc_text, task_type="RETRIEVAL_DOCUMENT")
            if doc_embedding:
                score = self.cosine_similarity(query_embedding, doc_embedding)
                scores.append((doc_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    # ── SQLite Persistence ────────────────────────────────
    # NOTE: The embeddings table must be created by the database service:
    #   CREATE TABLE IF NOT EXISTS embeddings (
    #       key TEXT PRIMARY KEY,
    #       vector TEXT NOT NULL,
    #       created_at TEXT
    #   );

    async def _save_embedding_to_db(self, key: str, embedding: List[float]):
        """Persist embedding to SQLite for reuse across restarts."""
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                await db_svc._db.execute(
                    "CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL, created_at TEXT)"
                )
                await db_svc._db.execute(
                    "INSERT OR REPLACE INTO embeddings (key, vector, created_at) VALUES (?, ?, ?)",
                    (key, json.dumps(embedding), self._utcnow_iso())
                )
                await db_svc._db.commit()
        except Exception as e:
            logger.debug(f"Failed to persist embedding: {e}")

    async def _load_embeddings_from_db(self):
        """Load cached embeddings from SQLite on startup."""
        try:
            from app.services.database import get_database
            db_svc = get_database()
            if db_svc and db_svc._db:
                # Ensure table exists before querying
                await db_svc._db.execute(
                    "CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL, created_at TEXT)"
                )
                async with db_svc._db.execute("SELECT key, vector, created_at FROM embeddings") as cursor:
                    async for row in cursor:
                        self._cache[row[0]] = self._create_cache_entry(
                            json.loads(row[1]),
                            row[2],
                        )
                self.cleanup_expired_cache()
                if self._cache:
                    logger.info(f"Loaded {len(self._cache)} cached embeddings from SQLite")
        except Exception as e:
            logger.debug(f"Could not load cached embeddings: {e}")

    def _reset_daily_if_needed(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._last_reset != today:
            self._request_count = 0
            self._token_usage = 0
            self._last_reset = today

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache and TTL metrics."""
        purged_now = self.cleanup_expired_cache()
        return {
            "entries": len(self._cache),
            "ttl_seconds": self._cache_ttl_seconds,
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "expired_purged_total": self._cache_expired_purged,
            "expired_purged_last_cleanup": purged_now,
            "last_cleanup_at": self._last_cache_cleanup,
        }

    def get_quota_status(self) -> dict:
        self._reset_daily_if_needed()
        cache_stats = self.get_cache_stats()
        return {
            "model": self.MODEL,
            "requests_today": self._request_count,
            "daily_limit": 1000,
            "tokens_today": self._token_usage,
            "token_limit": 30_000,  # TPM limit for embeddings
            "cache_size": cache_stats["entries"],  # backward compatible
            "cache": cache_stats,
        }


# Global instance
embedding_service = EmbeddingService()
