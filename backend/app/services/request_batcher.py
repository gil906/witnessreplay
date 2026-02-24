"""
Request batching service for combining multiple API requests.
Reduces RPM consumption by batching embedding and classification requests.
"""
import logging
import asyncio
import uuid
from typing import Dict, List, Optional, Any, Callable, Awaitable, TypeVar, Generic
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class BatchItem(Generic[T]):
    """Represents a single item in a batch."""
    id: str
    data: Any
    future: asyncio.Future
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BatchConfig:
    """Configuration for a batch type."""
    max_batch_size: int = 10
    max_wait_ms: int = 100  # Max time to wait for batch to fill
    enabled: bool = True


class RequestBatcher:
    """
    Batches multiple API requests to reduce RPM consumption.
    
    Features:
    - Configurable batch sizes per request type
    - Configurable wait times for batch accumulation
    - Automatic batch processing when size or time threshold is reached
    - Thread-safe operation with asyncio locks
    - Splits batch results back to individual callers
    
    Example usage:
        # For embedding requests
        embedding = await batcher.add_to_batch(
            batch_type="embedding",
            data={"text": "some text", "task_type": "SEMANTIC_SIMILARITY"},
            processor=embedding_batch_processor
        )
        
        # For classification requests  
        classification = await batcher.add_to_batch(
            batch_type="classification",
            data={"text": "classify this", "categories": ["A", "B", "C"]},
            processor=classification_batch_processor
        )
    """

    # Default configurations
    DEFAULT_CONFIGS: Dict[str, BatchConfig] = {
        "embedding": BatchConfig(max_batch_size=20, max_wait_ms=100),
        "classification": BatchConfig(max_batch_size=10, max_wait_ms=150),
        "intent": BatchConfig(max_batch_size=10, max_wait_ms=100),
        "preprocessing": BatchConfig(max_batch_size=5, max_wait_ms=200),
    }

    def __init__(self):
        self._batches: Dict[str, List[BatchItem]] = defaultdict(list)
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._timers: Dict[str, Optional[asyncio.Task]] = {}
        self._processors: Dict[str, Callable[[List[Any]], Awaitable[List[Any]]]] = {}
        self._configs: Dict[str, BatchConfig] = dict(self.DEFAULT_CONFIGS)
        self._stats = {
            "batches_processed": 0,
            "items_processed": 0,
            "items_batched": 0,  # Items that were part of multi-item batches
            "rpm_saved": 0,  # Estimated RPM savings
        }
        self._initialized = False

    async def initialize(self):
        """Initialize the batcher (load config from settings if needed)."""
        if self._initialized:
            return
        
        try:
            from app.config import settings
            
            # Allow runtime configuration override via environment
            # Format: BATCH_EMBEDDING_SIZE=20, BATCH_EMBEDDING_WAIT_MS=100
            import os
            for batch_type in self._configs:
                env_size = os.getenv(f"BATCH_{batch_type.upper()}_SIZE")
                env_wait = os.getenv(f"BATCH_{batch_type.upper()}_WAIT_MS")
                env_enabled = os.getenv(f"BATCH_{batch_type.upper()}_ENABLED")
                
                if env_size:
                    self._configs[batch_type].max_batch_size = int(env_size)
                if env_wait:
                    self._configs[batch_type].max_wait_ms = int(env_wait)
                if env_enabled is not None:
                    self._configs[batch_type].enabled = env_enabled.lower() in ("true", "1", "yes")
            
            self._initialized = True
            logger.info(f"RequestBatcher initialized with configs: {self._configs}")
        except Exception as e:
            logger.warning(f"Failed to load batch config: {e}, using defaults")
            self._initialized = True

    def configure(
        self,
        batch_type: str,
        max_batch_size: Optional[int] = None,
        max_wait_ms: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Configure batching for a specific request type."""
        if batch_type not in self._configs:
            self._configs[batch_type] = BatchConfig()
        
        config = self._configs[batch_type]
        if max_batch_size is not None:
            config.max_batch_size = max_batch_size
        if max_wait_ms is not None:
            config.max_wait_ms = max_wait_ms
        if enabled is not None:
            config.enabled = enabled
        
        logger.info(f"Updated batch config for '{batch_type}': {config}")

    def register_processor(
        self,
        batch_type: str,
        processor: Callable[[List[Any]], Awaitable[List[Any]]],
    ):
        """
        Register a batch processor function for a request type.
        
        The processor receives a list of data items and must return a list
        of results in the same order.
        
        Args:
            batch_type: Type of batch (e.g., "embedding", "classification")
            processor: Async function that processes a batch and returns results
        """
        self._processors[batch_type] = processor
        logger.info(f"Registered batch processor for '{batch_type}'")

    async def add_to_batch(
        self,
        batch_type: str,
        data: Any,
        processor: Optional[Callable[[List[Any]], Awaitable[List[Any]]]] = None,
    ) -> Any:
        """
        Add a request to a batch and wait for the result.
        
        If batching is disabled or no processor is registered, the request
        is processed immediately with the single-item processor.
        
        Args:
            batch_type: Type of batch (e.g., "embedding", "classification")
            data: The request data to batch
            processor: Optional processor to use (registered processors take priority)
            
        Returns:
            The result for this specific request
        """
        await self.initialize()
        
        config = self._configs.get(batch_type, BatchConfig())
        actual_processor = self._processors.get(batch_type, processor)
        
        # If batching is disabled or no processor, process immediately
        if not config.enabled or not actual_processor:
            if actual_processor:
                results = await actual_processor([data])
                return results[0] if results else None
            raise ValueError(f"No processor registered for batch type '{batch_type}'")
        
        # Create batch item with a future for the result
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        item = BatchItem(
            id=str(uuid.uuid4()),
            data=data,
            future=future,
        )
        
        async with self._locks[batch_type]:
            self._batches[batch_type].append(item)
            batch_size = len(self._batches[batch_type])
            
            # Check if batch is full
            if batch_size >= config.max_batch_size:
                # Process immediately
                asyncio.create_task(self._process_batch(batch_type))
            elif batch_size == 1:
                # First item in batch - start timer
                self._start_batch_timer(batch_type, config.max_wait_ms)
        
        # Wait for result
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            logger.error(f"Batch request timed out for '{batch_type}'")
            raise

    def _start_batch_timer(self, batch_type: str, wait_ms: int):
        """Start a timer to process the batch after max_wait_ms."""
        # Cancel existing timer if any
        existing_timer = self._timers.get(batch_type)
        if existing_timer and not existing_timer.done():
            existing_timer.cancel()
        
        async def timer_callback():
            await asyncio.sleep(wait_ms / 1000.0)
            await self._process_batch(batch_type)
        
        self._timers[batch_type] = asyncio.create_task(timer_callback())

    async def _process_batch(self, batch_type: str):
        """Process all items in a batch."""
        async with self._locks[batch_type]:
            # Cancel timer if running
            timer = self._timers.get(batch_type)
            if timer and not timer.done():
                timer.cancel()
            self._timers[batch_type] = None
            
            # Get items to process
            items = self._batches[batch_type]
            if not items:
                return
            
            # Clear the batch
            self._batches[batch_type] = []
        
        # Get processor
        processor = self._processors.get(batch_type)
        if not processor:
            # No processor - fail all items
            for item in items:
                if not item.future.done():
                    item.future.set_exception(
                        ValueError(f"No processor for batch type '{batch_type}'")
                    )
            return
        
        # Extract data for processing
        data_list = [item.data for item in items]
        batch_size = len(data_list)
        
        logger.debug(f"Processing batch '{batch_type}' with {batch_size} items")
        
        try:
            # Process the batch
            results = await processor(data_list)
            
            # Update stats
            self._stats["batches_processed"] += 1
            self._stats["items_processed"] += batch_size
            if batch_size > 1:
                self._stats["items_batched"] += batch_size
                # Each batch of N items saves (N-1) RPM
                self._stats["rpm_saved"] += batch_size - 1
            
            # Distribute results to individual futures
            if len(results) != len(items):
                logger.error(
                    f"Batch processor returned {len(results)} results for {len(items)} items"
                )
                # Try to match what we can
                for i, item in enumerate(items):
                    if not item.future.done():
                        if i < len(results):
                            item.future.set_result(results[i])
                        else:
                            item.future.set_exception(
                                RuntimeError("Batch result missing")
                            )
            else:
                for item, result in zip(items, results):
                    if not item.future.done():
                        item.future.set_result(result)
            
            logger.info(
                f"Batch '{batch_type}' completed: {batch_size} items, "
                f"RPM saved: {batch_size - 1 if batch_size > 1 else 0}"
            )
            
        except Exception as e:
            logger.error(f"Batch processing failed for '{batch_type}': {e}")
            # Fail all items with the same error
            for item in items:
                if not item.future.done():
                    item.future.set_exception(e)

    def get_stats(self) -> Dict[str, Any]:
        """Get batching statistics."""
        return {
            **self._stats,
            "configs": {k: {
                "max_batch_size": v.max_batch_size,
                "max_wait_ms": v.max_wait_ms,
                "enabled": v.enabled,
            } for k, v in self._configs.items()},
            "pending_batches": {k: len(v) for k, v in self._batches.items() if v},
        }

    async def flush_all(self):
        """Force process all pending batches."""
        batch_types = list(self._batches.keys())
        for batch_type in batch_types:
            await self._process_batch(batch_type)


# Global instance
request_batcher = RequestBatcher()


# =============================================================================
# Pre-built batch processors for common use cases
# =============================================================================

async def embedding_batch_processor(items: List[Dict]) -> List[Any]:
    """
    Process a batch of embedding requests.
    
    Each item should have:
        - text: str - Text to embed
        - task_type: str - Embedding task type (optional)
    
    Returns list of (embedding_vector, token_info) tuples.
    """
    from app.services.embedding_service import embedding_service
    
    if not embedding_service.client:
        return [(None, {"error": "embedding_service_unavailable"})] * len(items)
    
    # Extract texts and task types
    texts = []
    task_types = []
    for item in items:
        texts.append(item.get("text", "")[:8000])  # Limit input size
        task_types.append(item.get("task_type", "SEMANTIC_SIMILARITY"))
    
    # Check cache first
    results = []
    uncached_indices = []
    uncached_texts = []
    uncached_task_types = []
    
    for i, (text, task_type) in enumerate(zip(texts, task_types)):
        cache_key = f"{task_type}:{hash(text)}"
        if cache_key in embedding_service._cache:
            results.append((embedding_service._cache[cache_key], {"cached": True}))
        else:
            results.append(None)  # Placeholder
            uncached_indices.append(i)
            uncached_texts.append(text)
            uncached_task_types.append(task_type)
    
    if not uncached_texts:
        return results
    
    # Process uncached items - use batch embedding API
    try:
        # Gemini embedding API supports batch requests
        from google import genai
        import asyncio
        
        # Group by task_type for efficiency (API requires same task_type per batch)
        task_groups: Dict[str, List[tuple]] = defaultdict(list)
        for idx, text, task_type in zip(uncached_indices, uncached_texts, uncached_task_types):
            task_groups[task_type].append((idx, text))
        
        # Process each task type group
        for task_type, group in task_groups.items():
            indices = [g[0] for g in group]
            batch_texts = [g[1] for g in group]
            
            try:
                # Use batch embedding
                response = await asyncio.to_thread(
                    embedding_service.client.models.embed_content,
                    model=embedding_service.MODEL,
                    contents=batch_texts,
                    config={"task_type": task_type}
                )
                
                if response and response.embeddings:
                    for i, (orig_idx, text) in enumerate(group):
                        if i < len(response.embeddings):
                            embedding = response.embeddings[i].values
                            cache_key = f"{task_type}:{hash(text)}"
                            embedding_service._cache[cache_key] = embedding
                            results[orig_idx] = (embedding, {
                                "cached": False,
                                "batched": True,
                                "batch_size": len(batch_texts),
                            })
                        else:
                            results[orig_idx] = (None, {"error": "missing_embedding"})
                else:
                    for orig_idx, _ in group:
                        results[orig_idx] = (None, {"error": "empty_response"})
                        
            except Exception as e:
                logger.error(f"Batch embedding failed for task_type {task_type}: {e}")
                for orig_idx, _ in group:
                    results[orig_idx] = (None, {"error": str(e)})
        
        # Update embedding service counters (count as single request for batched)
        embedding_service._request_count += len(task_groups)
        
    except Exception as e:
        logger.error(f"Embedding batch processor error: {e}")
        # Fill remaining None slots with errors
        for i, r in enumerate(results):
            if r is None:
                results[i] = (None, {"error": str(e)})
    
    return results


async def classification_batch_processor(items: List[Dict]) -> List[Any]:
    """
    Process a batch of classification requests using a lightweight model.
    
    Each item should have:
        - text: str - Text to classify
        - categories: List[str] - Categories to classify into
        - prompt_template: str - Optional custom prompt template
    
    Returns list of classification results.
    """
    from google import genai
    from app.config import settings
    from app.services.model_selector import model_selector, call_with_retry
    import asyncio
    import json
    
    if not settings.google_api_key:
        return [{"error": "api_key_not_configured"}] * len(items)
    
    # Get a lightweight model for classification
    model = await model_selector.get_best_model_for_task("classification")
    client = genai.Client(api_key=settings.google_api_key)
    
    # Build a combined prompt for batch classification
    batch_prompt = """You are a classification assistant. Classify each of the following items into one of the provided categories.

Return your response as a JSON array with one object per item, each containing:
- "index": the item number (0-based)
- "category": the selected category
- "confidence": confidence score 0.0-1.0

Items to classify:
"""
    
    for i, item in enumerate(items):
        text = item.get("text", "")[:500]  # Limit text size
        categories = item.get("categories", [])
        batch_prompt += f"\n{i}. Text: \"{text}\"\n   Categories: {categories}\n"
    
    batch_prompt += "\nRespond with only the JSON array."
    
    try:
        response = await call_with_retry(
            asyncio.to_thread,
            client.models.generate_content,
            model=model,
            contents=batch_prompt,
            max_retries=2,
            model_name=model,
            task_type="classification",
        )
        
        if response and response.text:
            # Parse JSON response
            text = response.text.strip()
            # Handle markdown code blocks
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            
            try:
                parsed = json.loads(text)
                
                # Map results back to items
                results = [{"error": "no_result"}] * len(items)
                for result in parsed:
                    idx = result.get("index", -1)
                    if 0 <= idx < len(items):
                        results[idx] = {
                            "category": result.get("category"),
                            "confidence": result.get("confidence", 0.5),
                            "batched": True,
                            "batch_size": len(items),
                        }
                
                return results
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse classification response: {e}")
                return [{"error": "parse_error", "raw": text[:200]}] * len(items)
        else:
            return [{"error": "empty_response"}] * len(items)
            
    except Exception as e:
        logger.error(f"Classification batch processor error: {e}")
        return [{"error": str(e)}] * len(items)


# Register default processors on import
def _register_default_processors():
    """Register default batch processors."""
    request_batcher.register_processor("embedding", embedding_batch_processor)
    request_batcher.register_processor("classification", classification_batch_processor)


# Auto-register on module load
_register_default_processors()
