"""
AI Model Performance Metrics Service.

Tracks per-model:
- Latency (average, p50, p95)
- Success/failure rate
- Token usage
- Error types

Stores metrics in database and provides dashboard endpoint data.
"""
import logging
import threading
import asyncio
import json
import statistics
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Categorized error types for AI model calls."""
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    QUOTA_EXCEEDED = "quota_exceeded"
    AUTHENTICATION = "authentication"
    NETWORK = "network"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


@dataclass
class ModelMetricRecord:
    """Single metric record for a model call."""
    model: str
    task_type: str
    latency_ms: float
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "task_type": self.task_type,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ModelPerformanceSummary:
    """Aggregated performance summary for a model."""
    model: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    success_rate: float = 0.0
    
    # Latency metrics (milliseconds)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    
    # Token usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    avg_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    
    # Error breakdown
    error_counts: Dict[str, int] = field(default_factory=dict)
    
    # Time range
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 4),
            "latency": {
                "avg_ms": round(self.avg_latency_ms, 2),
                "p50_ms": round(self.p50_latency_ms, 2),
                "p95_ms": round(self.p95_latency_ms, 2),
                "min_ms": round(self.min_latency_ms, 2),
                "max_ms": round(self.max_latency_ms, 2),
            },
            "tokens": {
                "total_input": self.total_input_tokens,
                "total_output": self.total_output_tokens,
                "avg_input": round(self.avg_input_tokens, 1),
                "avg_output": round(self.avg_output_tokens, 1),
                "total": self.total_input_tokens + self.total_output_tokens,
            },
            "errors": self.error_counts,
            "period": {
                "start": self.period_start.isoformat() if self.period_start else None,
                "end": self.period_end.isoformat() if self.period_end else None,
            }
        }


def classify_error(error: Exception) -> Tuple[ErrorType, str]:
    """Classify an exception into error type and message."""
    err_str = str(error).lower()
    
    if "429" in err_str or "rate" in err_str and "limit" in err_str:
        return ErrorType.RATE_LIMIT, "Rate limit exceeded"
    elif "resource_exhausted" in err_str or "quota" in err_str:
        return ErrorType.QUOTA_EXCEEDED, "Quota exhausted"
    elif "timeout" in err_str or "timed out" in err_str:
        return ErrorType.TIMEOUT, "Request timed out"
    elif "invalid" in err_str and ("response" in err_str or "json" in err_str):
        return ErrorType.INVALID_RESPONSE, "Invalid response format"
    elif "auth" in err_str or "api_key" in err_str or "credential" in err_str:
        return ErrorType.AUTHENTICATION, "Authentication error"
    elif "network" in err_str or "connection" in err_str or "connect" in err_str:
        return ErrorType.NETWORK, "Network error"
    elif "safety" in err_str or "blocked" in err_str or "filter" in err_str:
        return ErrorType.CONTENT_FILTER, "Content filtered"
    else:
        return ErrorType.UNKNOWN, str(error)[:200]


class ModelMetricsCollector:
    """
    Collects and aggregates AI model performance metrics.
    
    Thread-safe for concurrent request tracking.
    Supports:
    - Real-time metrics collection
    - Historical aggregation
    - Database persistence
    - Model selection optimization hints
    """
    
    def __init__(self, max_recent_records: int = 5000):
        self._lock = threading.Lock()
        self.max_recent_records = max_recent_records
        
        # Recent records per model (for percentile calculations)
        self._recent_records: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_recent_records)
        )
        
        # Aggregated counters (reset daily)
        self._daily_counters: Dict[str, Dict] = defaultdict(lambda: {
            "total": 0,
            "success": 0,
            "failed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latencies": [],
            "errors": defaultdict(int),
        })
        
        # Per-task-type metrics
        self._task_metrics: Dict[str, Dict[str, Dict]] = defaultdict(
            lambda: defaultdict(lambda: {"count": 0, "success": 0, "latencies": []})
        )
        
        # Current day tracking
        self._current_date = datetime.now(timezone.utc).date()
        
        # Historical daily summaries (last 30 days)
        self._daily_summaries: deque = deque(maxlen=30)
        
        # Database reference (lazy loaded)
        self._db = None
        
    async def _get_db(self):
        """Lazy load database connection."""
        if self._db is None:
            from app.services.database import get_database
            self._db = get_database()
        return self._db
    
    def _check_day_rollover(self):
        """Check if we need to roll over to a new day."""
        today = datetime.now(timezone.utc).date()
        if today != self._current_date:
            # Save previous day summary
            for model, counters in self._daily_counters.items():
                if counters["total"] > 0:
                    summary = self._compute_summary(model, counters)
                    self._daily_summaries.append({
                        "date": self._current_date.isoformat(),
                        **summary.to_dict()
                    })
            
            # Reset for new day
            self._daily_counters.clear()
            self._task_metrics.clear()
            self._current_date = today
            logger.info(f"Model metrics rolled over to new day: {today}")
    
    def record_request(
        self,
        model: str,
        task_type: str,
        latency_ms: float,
        success: bool,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: Optional[Exception] = None,
    ):
        """
        Record a completed model request.
        
        Args:
            model: Model name
            task_type: Type of task (chat, scene, classification, etc.)
            latency_ms: Request latency in milliseconds
            success: Whether the request succeeded
            input_tokens: Input token count
            output_tokens: Output token count  
            error: Exception if request failed
        """
        error_type = None
        error_message = None
        
        if error:
            err_type, err_msg = classify_error(error)
            error_type = err_type.value
            error_message = err_msg
        
        record = ModelMetricRecord(
            model=model,
            task_type=task_type,
            latency_ms=latency_ms,
            success=success,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_type=error_type,
            error_message=error_message,
        )
        
        with self._lock:
            self._check_day_rollover()
            
            # Add to recent records
            self._recent_records[model].append(record)
            
            # Update daily counters
            counters = self._daily_counters[model]
            counters["total"] += 1
            if success:
                counters["success"] += 1
            else:
                counters["failed"] += 1
                if error_type:
                    counters["errors"][error_type] += 1
            
            counters["input_tokens"] += input_tokens
            counters["output_tokens"] += output_tokens
            counters["latencies"].append(latency_ms)
            
            # Update task metrics
            task_metrics = self._task_metrics[task_type][model]
            task_metrics["count"] += 1
            if success:
                task_metrics["success"] += 1
            task_metrics["latencies"].append(latency_ms)
        
        # Async persist to database
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_record(record))
        except RuntimeError:
            pass  # No event loop
        
        logger.debug(
            f"Recorded metric: {model}/{task_type} "
            f"latency={latency_ms:.0f}ms success={success} "
            f"tokens={input_tokens}+{output_tokens}"
        )
    
    async def _persist_record(self, record: ModelMetricRecord):
        """Persist a record to the database."""
        try:
            db = await self._get_db()
            if db and db._db:
                await db._db.execute(
                    """INSERT INTO model_metrics 
                       (model, task_type, latency_ms, success, input_tokens, 
                        output_tokens, error_type, error_message, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.model,
                        record.task_type,
                        record.latency_ms,
                        1 if record.success else 0,
                        record.input_tokens,
                        record.output_tokens,
                        record.error_type,
                        record.error_message,
                        record.timestamp.isoformat(),
                    )
                )
                await db._db.commit()
        except Exception as e:
            logger.debug(f"Failed to persist model metric: {e}")
    
    def _compute_summary(
        self, 
        model: str, 
        counters: Dict,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> ModelPerformanceSummary:
        """Compute performance summary from counters."""
        total = counters["total"]
        latencies = counters.get("latencies", [])
        
        if not latencies:
            latencies = [0]
        
        sorted_latencies = sorted(latencies)
        p50_idx = int(len(sorted_latencies) * 0.5)
        p95_idx = int(len(sorted_latencies) * 0.95)
        
        return ModelPerformanceSummary(
            model=model,
            total_requests=total,
            successful_requests=counters["success"],
            failed_requests=counters["failed"],
            success_rate=counters["success"] / total if total > 0 else 0.0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            p50_latency_ms=sorted_latencies[p50_idx] if sorted_latencies else 0,
            p95_latency_ms=sorted_latencies[p95_idx] if sorted_latencies else 0,
            min_latency_ms=min(latencies) if latencies else 0,
            max_latency_ms=max(latencies) if latencies else 0,
            total_input_tokens=counters["input_tokens"],
            total_output_tokens=counters["output_tokens"],
            avg_input_tokens=counters["input_tokens"] / total if total > 0 else 0,
            avg_output_tokens=counters["output_tokens"] / total if total > 0 else 0,
            error_counts=dict(counters.get("errors", {})),
            period_start=period_start,
            period_end=period_end,
        )
    
    def get_model_summary(self, model: str) -> ModelPerformanceSummary:
        """Get performance summary for a specific model (current day)."""
        with self._lock:
            self._check_day_rollover()
            counters = self._daily_counters.get(model, {
                "total": 0, "success": 0, "failed": 0,
                "input_tokens": 0, "output_tokens": 0,
                "latencies": [], "errors": {}
            })
            return self._compute_summary(
                model, counters,
                datetime.combine(self._current_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                datetime.now(timezone.utc)
            )
    
    def get_all_models_summary(self) -> Dict[str, Dict]:
        """Get performance summary for all tracked models."""
        with self._lock:
            self._check_day_rollover()
            return {
                model: self._compute_summary(model, counters).to_dict()
                for model, counters in self._daily_counters.items()
            }
    
    def get_task_metrics(self) -> Dict[str, Dict[str, Dict]]:
        """Get metrics broken down by task type."""
        with self._lock:
            result = {}
            for task_type, models in self._task_metrics.items():
                result[task_type] = {}
                for model, metrics in models.items():
                    latencies = metrics.get("latencies", [])
                    count = metrics["count"]
                    result[task_type][model] = {
                        "count": count,
                        "success": metrics["success"],
                        "success_rate": metrics["success"] / count if count > 0 else 0,
                        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
                    }
            return result
    
    def get_model_optimization_hints(self) -> Dict[str, Dict]:
        """
        Generate model selection optimization hints based on metrics.
        
        Returns recommendations for model selection based on:
        - Success rate
        - Latency
        - Error patterns
        """
        hints = {}
        
        with self._lock:
            for model, counters in self._daily_counters.items():
                total = counters["total"]
                if total < 5:
                    continue  # Not enough data
                
                success_rate = counters["success"] / total if total > 0 else 0
                latencies = counters.get("latencies", [])
                avg_latency = sum(latencies) / len(latencies) if latencies else 0
                
                error_counts = counters.get("errors", {})
                rate_limit_errors = error_counts.get(ErrorType.RATE_LIMIT.value, 0)
                
                # Generate hints
                model_hints = {
                    "reliability_score": success_rate,
                    "avg_latency_ms": avg_latency,
                    "rate_limit_pressure": rate_limit_errors / total if total > 0 else 0,
                    "recommendations": [],
                }
                
                if success_rate < 0.9:
                    model_hints["recommendations"].append(
                        f"Low success rate ({success_rate:.1%}). Consider fallback model."
                    )
                
                if rate_limit_errors > total * 0.1:
                    model_hints["recommendations"].append(
                        "High rate limit errors. Reduce request frequency or switch models."
                    )
                
                if avg_latency > 5000:
                    model_hints["recommendations"].append(
                        f"High latency ({avg_latency:.0f}ms). Consider faster model for latency-sensitive tasks."
                    )
                
                # Compute overall score (0-1, higher is better)
                latency_score = max(0, 1 - (avg_latency / 10000))  # 10s max
                model_hints["overall_score"] = (
                    success_rate * 0.5 + 
                    latency_score * 0.3 + 
                    (1 - model_hints["rate_limit_pressure"]) * 0.2
                )
                
                hints[model] = model_hints
        
        return hints
    
    def get_dashboard_data(self) -> Dict:
        """Get comprehensive dashboard data for model metrics."""
        with self._lock:
            self._check_day_rollover()
            
            # Current day summaries
            models_summary = self.get_all_models_summary()
            
            # Task breakdown
            task_metrics = self.get_task_metrics()
            
            # Optimization hints
            hints = self.get_model_optimization_hints()
            
            # Totals
            total_requests = sum(
                counters["total"] for counters in self._daily_counters.values()
            )
            total_success = sum(
                counters["success"] for counters in self._daily_counters.values()
            )
            total_tokens = sum(
                counters["input_tokens"] + counters["output_tokens"]
                for counters in self._daily_counters.values()
            )
            
            # Best performing model (by score)
            best_model = None
            best_score = 0
            for model, hint in hints.items():
                if hint.get("overall_score", 0) > best_score:
                    best_score = hint["overall_score"]
                    best_model = model
            
            return {
                "summary": {
                    "total_requests_today": total_requests,
                    "success_rate": total_success / total_requests if total_requests > 0 else 0,
                    "total_tokens_today": total_tokens,
                    "models_tracked": len(self._daily_counters),
                    "best_performing_model": best_model,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                "models": models_summary,
                "by_task": task_metrics,
                "optimization_hints": hints,
                "historical": list(self._daily_summaries)[-7:],  # Last 7 days
            }
    
    async def get_historical_metrics(
        self, 
        model: Optional[str] = None,
        days: int = 7
    ) -> List[Dict]:
        """Fetch historical metrics from database."""
        try:
            db = await self._get_db()
            if not db or not db._db:
                return []
            
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            
            if model:
                query = """
                    SELECT 
                        DATE(timestamp) as date,
                        model,
                        COUNT(*) as total,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
                        AVG(latency_ms) as avg_latency,
                        SUM(input_tokens) as input_tokens,
                        SUM(output_tokens) as output_tokens
                    FROM model_metrics
                    WHERE timestamp >= ? AND model = ?
                    GROUP BY DATE(timestamp), model
                    ORDER BY date DESC
                """
                cursor = await db._db.execute(query, (cutoff, model))
            else:
                query = """
                    SELECT 
                        DATE(timestamp) as date,
                        model,
                        COUNT(*) as total,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
                        AVG(latency_ms) as avg_latency,
                        SUM(input_tokens) as input_tokens,
                        SUM(output_tokens) as output_tokens
                    FROM model_metrics
                    WHERE timestamp >= ?
                    GROUP BY DATE(timestamp), model
                    ORDER BY date DESC
                """
                cursor = await db._db.execute(query, (cutoff,))
            
            rows = await cursor.fetchall()
            return [
                {
                    "date": row[0],
                    "model": row[1],
                    "total": row[2],
                    "success": row[3],
                    "success_rate": row[3] / row[2] if row[2] > 0 else 0,
                    "avg_latency_ms": row[4],
                    "total_tokens": (row[5] or 0) + (row[6] or 0),
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching historical metrics: {e}")
            return []


# Global singleton
model_metrics = ModelMetricsCollector()


# ─────────────────────────────────────────────────────────────────────────────
# Instrumented wrapper for model calls
# ─────────────────────────────────────────────────────────────────────────────

import time
from functools import wraps


def track_model_call(task_type: str = "unknown"):
    """
    Decorator to track model call performance.
    
    Usage:
        @track_model_call(task_type="chat")
        async def my_model_call(model_name: str, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            model = kwargs.get("model") or kwargs.get("model_name") or "unknown"
            if isinstance(model, str) and "/" in model:
                model = model.split("/")[-1]
            
            start_time = time.perf_counter()
            success = True
            error = None
            input_tokens = 0
            output_tokens = 0
            
            try:
                result = await func(*args, **kwargs)
                
                # Try to extract token usage from response
                if hasattr(result, "usage_metadata"):
                    usage = result.usage_metadata
                    input_tokens = getattr(usage, "prompt_token_count", 0)
                    output_tokens = getattr(usage, "candidates_token_count", 0)
                
                return result
            except Exception as e:
                success = False
                error = e
                raise
            finally:
                latency_ms = (time.perf_counter() - start_time) * 1000
                model_metrics.record_request(
                    model=model,
                    task_type=task_type,
                    latency_ms=latency_ms,
                    success=success,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error=error,
                )
        
        return wrapper
    return decorator


async def record_model_call(
    model: str,
    task_type: str,
    latency_ms: float,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: Optional[Exception] = None,
):
    """Direct function to record a model call (for use without decorator)."""
    model_metrics.record_request(
        model=model,
        task_type=task_type,
        latency_ms=latency_ms,
        success=success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error=error,
    )
