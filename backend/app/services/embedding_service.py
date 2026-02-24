"""
Embedding service using Gemini Embedding 1 for semantic case matching.
100 RPM / 30K TPM / 1K RPD - very generous quota!
"""
import logging
import asyncio
import json
import math
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from google import genai

from app.services.token_estimator import token_estimator

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generates and manages text embeddings for semantic search and case matching."""

    MODEL = "gemini-embedding-001"
    EMBEDDING_DIM = 768  # Default dimension

    def __init__(self):
        self.client = None
        self._cache: Dict[str, List[float]] = {}  # key -> embedding
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

        # Check cache first
        cache_key = f"{task_type}:{hash(text)}"
        if cache_key in self._cache:
            return self._cache[cache_key], {"cached": True, "estimated_tokens": 0}

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
                self._cache[cache_key] = embedding
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
        task_type: str = "SEMANTIC_SIMILARITY"
    ) -> List[Tuple[Optional[List[float]], Optional[Dict]]]:
        """Embed multiple texts. More efficient than individual calls."""
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
                    (key, json.dumps(embedding), datetime.utcnow().isoformat())
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
                async with db_svc._db.execute("SELECT key, vector FROM embeddings") as cursor:
                    async for row in cursor:
                        self._cache[row[0]] = json.loads(row[1])
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

    def get_quota_status(self) -> dict:
        self._reset_daily_if_needed()
        return {
            "model": self.MODEL,
            "requests_today": self._request_count,
            "daily_limit": 1000,
            "tokens_today": self._token_usage,
            "token_limit": 30_000,  # TPM limit for embeddings
            "cache_size": len(self._cache),
        }


# Global instance
embedding_service = EmbeddingService()
