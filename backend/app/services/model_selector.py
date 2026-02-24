"""
Model selector service with quota-based fallback chains.
Tracks per-model RPM/TPM/RPD quotas and provides smart routing.
"""
import logging
import random
import asyncio
from typing import List, Optional, Dict, Tuple, Any, Callable
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fallback chains with real Google API quotas
# ---------------------------------------------------------------------------

CHAT_MODELS: List[Tuple[str, Dict[str, int]]] = [
    ("gemini-3-flash", {"rpm": 5, "tpm": 250_000, "rpd": 20}),
    ("gemini-2.5-flash", {"rpm": 5, "tpm": 250_000, "rpd": 20}),
    ("gemini-2.5-flash-lite", {"rpm": 10, "tpm": 250_000, "rpd": 20}),
]

LIGHTWEIGHT_MODELS: List[Tuple[str, Dict[str, int]]] = [
    ("gemma-3-27b-it", {"rpm": 30, "tpm": 15_000, "rpd": 14_400}),
    ("gemma-3-12b-it", {"rpm": 30, "tpm": 15_000, "rpd": 14_400}),
    ("gemma-3-4b-it", {"rpm": 30, "tpm": 15_000, "rpd": 14_400}),
]

IMAGE_MODELS: List[Tuple[str, Dict[str, int]]] = [
    ("imagen-4-fast-generate", {"rpd": 25}),
    ("imagen-4-generate", {"rpd": 25}),
    ("imagen-4-ultra-generate", {"rpd": 25}),
]

EMBEDDING_MODELS: List[Tuple[str, Dict[str, int]]] = [
    ("gemini-embedding-001", {"rpm": 100, "tpm": 30_000, "rpd": 1_000}),
]

TTS_MODELS: List[Tuple[str, Dict[str, int]]] = [
    ("gemini-2.5-flash-preview-tts", {"rpm": 3, "tpm": 10_000, "rpd": 10}),
]

LIVE_MODELS: List[Tuple[str, Dict[str, int]]] = [
    ("gemini-2.5-flash-exp-native-audio-thinking", {"rpm": 0, "tpm": 1_000_000, "rpd": 0}),
]

# Convenience mapping: model name → quota dict
MODEL_QUOTAS: Dict[str, Dict[str, int]] = {}
for _chain in (CHAT_MODELS, LIGHTWEIGHT_MODELS, IMAGE_MODELS,
               EMBEDDING_MODELS, TTS_MODELS, LIVE_MODELS):
    for _name, _quota in _chain:
        MODEL_QUOTAS[_name] = _quota

# Legacy alias kept for backward-compat (scene uses same chain as chat)
SCENE_RECONSTRUCTION_MODELS = [m for m, _ in CHAT_MODELS]

# Combined chain: try Gemma first for lightweight tasks, fall back to Gemini
LIGHTWEIGHT_WITH_FALLBACK: List[Tuple[str, Dict[str, int]]] = LIGHTWEIGHT_MODELS + CHAT_MODELS

# Task-type → fallback chain mapping
TASK_CHAINS: Dict[str, List[Tuple[str, Dict[str, int]]]] = {
    "chat": CHAT_MODELS,
    "analysis": CHAT_MODELS,
    "scene": CHAT_MODELS,
    "classification": LIGHTWEIGHT_WITH_FALLBACK,
    "intent": LIGHTWEIGHT_WITH_FALLBACK,
    "preprocessing": LIGHTWEIGHT_WITH_FALLBACK,
    "lightweight": LIGHTWEIGHT_WITH_FALLBACK,
    "image": IMAGE_MODELS,
    "embedding": EMBEDDING_MODELS,
    "tts": TTS_MODELS,
    "live": LIVE_MODELS,
}


# ---------------------------------------------------------------------------
# Token estimation helper
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Estimate token count: ~4 chars per token for English text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# QuotaTracker – per-model RPM / TPM / RPD tracking
# ---------------------------------------------------------------------------

class QuotaTracker:
    """Tracks actual API usage against Google quotas per model."""

    def __init__(self):
        self._minute_counts: Dict[str, List[datetime]] = defaultdict(list)
        self._daily_counts: Dict[str, int] = defaultdict(int)
        self._daily_tokens: Dict[str, int] = defaultdict(int)
        self._last_reset_date: str = ""
        self._lock = asyncio.Lock()

    # -- internal helpers --------------------------------------------------

    def _reset_if_new_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            logger.info(f"QuotaTracker: new day {today}, resetting daily counters")
            self._daily_counts.clear()
            self._daily_tokens.clear()
            self._last_reset_date = today

    def _prune_minute_window(self, model: str):
        """Remove entries older than 60 s from the per-minute window."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        self._minute_counts[model] = [
            ts for ts in self._minute_counts[model] if ts > cutoff
        ]

    # -- public API --------------------------------------------------------

    async def record_request(self, model: str, tokens_used: int = 0):
        """Record a completed request (RPM + RPD + token count)."""
        async with self._lock:
            self._reset_if_new_day()
            now = datetime.now(timezone.utc)
            self._minute_counts[model].append(now)
            self._daily_counts[model] = self._daily_counts.get(model, 0) + 1
            self._daily_tokens[model] = self._daily_tokens.get(model, 0) + tokens_used
            self._prune_minute_window(model)

    async def can_make_request(self, model: str) -> bool:
        """Return True if the model has remaining quota for a request."""
        async with self._lock:
            self._reset_if_new_day()
            self._prune_minute_window(model)
            quota = MODEL_QUOTAS.get(model, {})

            rpm_limit = quota.get("rpm", 0)
            rpd_limit = quota.get("rpd", 0)

            # rpm=0 means unlimited
            if rpm_limit and len(self._minute_counts[model]) >= rpm_limit:
                return False
            # rpd=0 means unlimited
            if rpd_limit and self._daily_counts.get(model, 0) >= rpd_limit:
                return False
            return True

    async def rpm_usage_ratio(self, model: str) -> float:
        """Return current RPM usage as a ratio 0.0–1.0."""
        async with self._lock:
            self._prune_minute_window(model)
            quota = MODEL_QUOTAS.get(model, {})
            rpm_limit = quota.get("rpm", 0)
            if not rpm_limit:
                return 0.0
            return len(self._minute_counts[model]) / rpm_limit

    async def wait_for_quota(self, model: str, timeout: float = 60.0) -> bool:
        """Wait up to *timeout* seconds for quota to become available.
        Returns False if timed out."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self.can_make_request(model):
                return True
            await asyncio.sleep(1.0)
        return False

    async def get_quota_status(self) -> Dict[str, Any]:
        """Return real-time quota usage for every known model."""
        async with self._lock:
            self._reset_if_new_day()
            status: Dict[str, Any] = {}
            for model, quota in MODEL_QUOTAS.items():
                self._prune_minute_window(model)
                rpm_limit = quota.get("rpm", 0)
                tpm_limit = quota.get("tpm", 0)
                rpd_limit = quota.get("rpd", 0)
                rpm_used = len(self._minute_counts.get(model, []))
                rpd_used = self._daily_counts.get(model, 0)
                tpm_used = self._daily_tokens.get(model, 0)
                status[model] = {
                    "rpm": {"used": rpm_used, "limit": rpm_limit,
                            "remaining": max(0, rpm_limit - rpm_used) if rpm_limit else None},
                    "tpm": {"used": tpm_used, "limit": tpm_limit,
                            "remaining": max(0, tpm_limit - tpm_used) if tpm_limit else None},
                    "rpd": {"used": rpd_used, "limit": rpd_limit,
                            "remaining": max(0, rpd_limit - rpd_used) if rpd_limit else None},
                    "available": True,
                }
                # Mark unavailable if any hard limit is hit
                if rpm_limit and rpm_used >= rpm_limit:
                    status[model]["available"] = False
                if rpd_limit and rpd_used >= rpd_limit:
                    status[model]["available"] = False
            return status


# Module-level singleton
quota_tracker = QuotaTracker()


# ---------------------------------------------------------------------------
# ModelSelector – backward-compatible class with quota-aware routing
# ---------------------------------------------------------------------------

class ModelSelector:
    """Intelligent model selector with quota-based fallback."""

    # Keep class-level lists for backward compatibility
    SCENE_RECONSTRUCTION_MODELS = SCENE_RECONSTRUCTION_MODELS
    CHAT_MODELS_LIST = [m for m, _ in CHAT_MODELS]

    def __init__(self):
        self._rate_limited_models: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._current_scene_model: Optional[str] = None
        self._current_chat_model: Optional[str] = None
        self.quota = quota_tracker

    # -- rate-limit bookkeeping (kept for backward compat) -----------------

    def _cleanup_rate_limits(self):
        now = datetime.now(timezone.utc)
        expired = [m for m, t in self._rate_limited_models.items()
                   if now - t > timedelta(seconds=60)]
        for m in expired:
            del self._rate_limited_models[m]
            logger.info(f"Model {m} rate limit expired, now available")

    def _is_rate_limited(self, model_name: str) -> bool:
        if model_name not in self._rate_limited_models:
            return False
        limit_time = self._rate_limited_models[model_name]
        if datetime.now(timezone.utc) - limit_time > timedelta(seconds=60):
            del self._rate_limited_models[model_name]
            return False
        return True

    # -- core selection helpers --------------------------------------------

    async def _pick_from_chain(
        self, chain: List[Tuple[str, Dict[str, int]]]
    ) -> str:
        """Return the first model in *chain* that is not rate-limited and
        has remaining quota.  Falls back to first model if all exhausted."""
        self._cleanup_rate_limits()
        for model, _ in chain:
            if self._is_rate_limited(model):
                continue
            if await quota_tracker.can_make_request(model):
                return model
        # All exhausted – try waiting on the first model briefly
        first_model = chain[0][0]
        if await quota_tracker.wait_for_quota(first_model, timeout=5):
            return first_model
        logger.warning("All models in chain exhausted, returning first anyway")
        return first_model

    async def _pick_from_chain_optimized(
        self, chain: List[Tuple[str, Dict[str, int]]], task_type: str = "unknown"
    ) -> str:
        """Pick model from chain using performance metrics for optimization.
        
        Considers:
        - Quota availability (primary)
        - Rate limit status
        - Historical success rate
        - Latency performance
        """
        from app.services.model_metrics import model_metrics
        
        self._cleanup_rate_limits()
        hints = model_metrics.get_model_optimization_hints()
        
        # Build list of available models with scores
        available_models = []
        for model, _ in chain:
            if self._is_rate_limited(model):
                continue
            if not await quota_tracker.can_make_request(model):
                continue
            
            # Get optimization score (default to 0.5 if no data)
            model_hint = hints.get(model, {})
            score = model_hint.get("overall_score", 0.5)
            
            # Penalize models with high rate limit pressure
            rate_pressure = model_hint.get("rate_limit_pressure", 0)
            if rate_pressure > 0.1:
                score *= (1 - rate_pressure)
            
            available_models.append((model, score))
        
        if not available_models:
            # Fall back to standard selection
            return await self._pick_from_chain(chain)
        
        # Sort by score descending and return best
        available_models.sort(key=lambda x: x[1], reverse=True)
        best_model = available_models[0][0]
        
        logger.debug(f"Optimized model selection for {task_type}: {best_model} "
                    f"(score={available_models[0][1]:.2f})")
        return best_model

    # -- public API (backward compatible) ----------------------------------

    async def get_best_model_for_scene(self) -> str:
        async with self._lock:
            model = await self._pick_from_chain(CHAT_MODELS)
            logger.info(f"Selected model for scene reconstruction: {model}")
            self._current_scene_model = model
            return model

    async def get_best_model_for_chat(self) -> str:
        async with self._lock:
            model = await self._pick_from_chain(CHAT_MODELS)
            logger.info(f"Selected model for chat: {model}")
            self._current_chat_model = model
            return model

    async def get_best_model_for_lightweight(self) -> str:
        """Return a Gemma model (30 RPM – 6× more than Gemini).
        Use for classification, yes/no decisions, short extraction."""
        async with self._lock:
            model = await self._pick_from_chain(LIGHTWEIGHT_MODELS)
            logger.info(f"Selected lightweight model: {model}")
            return model

    async def get_best_model_for_task(
        self, task_type: str, use_optimization: bool = True
    ) -> str:
        """Smart routing: pick the cheapest sufficient model for *task_type*.

        Supported task_types:
            classification, intent, preprocessing, lightweight
                                        → Gemma chain (30 RPM), fallback to Gemini
            chat, analysis, scene       → Gemini chat chain
            image                       → Imagen chain
            embedding                   → Embedding chain
            tts                         → TTS chain
            live                        → Live/audio chain
            
        Args:
            task_type: Type of task to route
            use_optimization: If True, use performance metrics to influence selection
        """
        chain = TASK_CHAINS.get(task_type, CHAT_MODELS)
        async with self._lock:
            if use_optimization:
                try:
                    model = await self._pick_from_chain_optimized(chain, task_type)
                except Exception as e:
                    logger.debug(f"Optimized selection failed, using standard: {e}")
                    model = await self._pick_from_chain(chain)
            else:
                model = await self._pick_from_chain(chain)
            
            logger.info(f"Selected model for task '{task_type}': {model}")
            # Update current model tracking for backward compat
            if task_type in ("chat", "analysis"):
                self._current_chat_model = model
            elif task_type == "scene":
                self._current_scene_model = model
            return model

    async def mark_rate_limited(self, model_name: str):
        async with self._lock:
            self._rate_limited_models[model_name] = datetime.now(timezone.utc)
            logger.warning(f"Model {model_name} marked as rate limited")

    async def get_all_models_status(self) -> List[Dict]:
        """Return status of all known models (backward compatible)."""
        quota_status = await quota_tracker.get_quota_status()
        statuses = []
        async with self._lock:
            self._cleanup_rate_limits()
            for model in MODEL_QUOTAS:
                is_limited = self._is_rate_limited(model)
                qs = quota_status.get(model, {})
                statuses.append({
                    "model": model,
                    "available": (not is_limited) and qs.get("available", True),
                    "rate_limited": is_limited,
                    "rate_limit_expires_in": self._get_rate_limit_expiry(model) if is_limited else None,
                    "quota": qs,
                })
        return statuses

    def get_current_model(self, task_type: str = "scene") -> str:
        if task_type in ("chat", "analysis", "classification", "lightweight", "intent", "preprocessing"):
            return self._current_chat_model or CHAT_MODELS[0][0]
        elif task_type == "scene":
            return self._current_scene_model or CHAT_MODELS[0][0]
        elif task_type == "image":
            return IMAGE_MODELS[0][0]
        elif task_type == "embedding":
            return EMBEDDING_MODELS[0][0]
        elif task_type == "tts":
            return TTS_MODELS[0][0]
        else:
            return self._current_scene_model or CHAT_MODELS[0][0]

    def _get_rate_limit_expiry(self, model_name: str) -> Optional[int]:
        if model_name not in self._rate_limited_models:
            return None
        limit_time = self._rate_limited_models[model_name]
        expires_at = limit_time + timedelta(seconds=60)
        delta = expires_at - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))


# ---------------------------------------------------------------------------
# Exponential backoff with jitter for 429 retries + performance metrics
# ---------------------------------------------------------------------------

async def call_with_retry(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    model_name: Optional[str] = None,
    task_type: str = "unknown",
    **kwargs: Any,
) -> Any:
    """Call *func* with exponential backoff + jitter on 429 / RESOURCE_EXHAUSTED.
    
    Also tracks performance metrics for model selection optimization.
    """
    import time
    from app.services.model_metrics import model_metrics
    
    start_time = time.perf_counter()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = await func(*args, **kwargs)
            
            # Record success
            latency_ms = (time.perf_counter() - start_time) * 1000
            input_tokens = 0
            output_tokens = 0
            
            # Extract token usage if available
            if hasattr(result, "usage_metadata"):
                usage = result.usage_metadata
                input_tokens = getattr(usage, "prompt_token_count", 0) or 0
                output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            
            if model_name:
                model_metrics.record_request(
                    model=model_name,
                    task_type=task_type,
                    latency_ms=latency_ms,
                    success=True,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            
            return result
            
        except Exception as e:
            last_error = e
            err = str(e)
            err_lower = err.lower()
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err_lower or "rate" in err_lower:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    f"Rate limited (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait:.1f}s: {err[:120]}"
                )
                if model_name:
                    await model_selector.mark_rate_limited(model_name)
                await asyncio.sleep(wait)
            else:
                # Record failure for non-retryable errors
                latency_ms = (time.perf_counter() - start_time) * 1000
                if model_name:
                    model_metrics.record_request(
                        model=model_name,
                        task_type=task_type,
                        latency_ms=latency_ms,
                        success=False,
                        error=e,
                    )
                raise
    
    # Final attempt – record and let exception propagate
    try:
        result = await func(*args, **kwargs)
        latency_ms = (time.perf_counter() - start_time) * 1000
        
        input_tokens = 0
        output_tokens = 0
        if hasattr(result, "usage_metadata"):
            usage = result.usage_metadata
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        
        if model_name:
            model_metrics.record_request(
                model=model_name,
                task_type=task_type,
                latency_ms=latency_ms,
                success=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        return result
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        if model_name:
            model_metrics.record_request(
                model=model_name,
                task_type=task_type,
                latency_ms=latency_ms,
                success=False,
                error=e,
            )
        raise


# ---------------------------------------------------------------------------
# Global model selector instance (backward compatible)
# ---------------------------------------------------------------------------

model_selector = ModelSelector()

