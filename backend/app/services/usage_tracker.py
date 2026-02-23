"""
Usage tracking service for Gemini API quota management.
Since Gemini API doesn't provide programmatic quota endpoints,
we track usage locally with JSON file persistence.
"""
import logging
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional
from collections import defaultdict
import threading
import asyncio
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class UsageTracker:
    """Tracks Gemini API usage for quota display."""
    
    # Known rate limits (free tier as of 2024)
    # https://ai.google.dev/pricing
    RATE_LIMITS = {
        "gemini-2.5-pro": {
            "rpm": 2,  # requests per minute
            "rpd": 50,  # requests per day
            "tpd": 500000,  # tokens per day (500K)
            "tier": "free"
        },
        "gemini-2.5-flash": {
            "rpm": 15,
            "rpd": 1500,
            "tpd": 15000000,  # 15M tokens/day
            "tier": "free"
        },
        "gemini-2.5-flash-lite": {
            "rpm": 15,
            "rpd": 1500,
            "tpd": 15000000,
            "tier": "free"
        },
        "gemini-2.0-flash": {
            "rpm": 15,
            "rpd": 1500,
            "tpd": 15000000,
            "tier": "free"
        },
        "gemini-2.0-flash-lite": {
            "rpm": 15,
            "rpd": 1500,
            "tpd": 15000000,
            "tier": "free"
        },
        "gemini-2.0-flash-exp": {
            "rpm": 15,
            "rpd": 1500,
            "tpd": 15000000,
            "tier": "free"
        },
    }
    
    def __init__(self, persistence_file: Optional[str] = None):
        self._lock = threading.Lock()
        # Track requests per model
        self._requests_today: Dict[str, int] = defaultdict(int)
        self._requests_minute: Dict[str, list] = defaultdict(list)
        # Track tokens per model
        self._tokens_today: Dict[str, int] = defaultdict(int)
        # Track last reset
        self._last_reset = datetime.now(timezone.utc).date()
        
        # Persistence
        if persistence_file:
            self._persistence_file = Path(persistence_file)
        else:
            # Default to a file in /tmp or project data directory
            data_dir = Path("/tmp/witnessreplay_data")
            data_dir.mkdir(exist_ok=True)
            self._persistence_file = data_dir / "usage_tracker.json"
        
        self._load_from_disk()
    
    def _check_reset(self):
        """Reset counters if it's a new day (Pacific Time)."""
        # Gemini quotas reset at midnight Pacific Time
        try:
            pacific_tz = ZoneInfo("America/Los_Angeles")
            today = datetime.now(pacific_tz).date()
        except Exception as e:
            # Fallback to UTC if timezone not available
            logger.warning(f"Could not use Pacific timezone, falling back to UTC: {e}")
            today = datetime.now(timezone.utc).date()
        
        if today != self._last_reset:
            logger.info(f"Resetting usage counters for new day: {today}")
            self._requests_today.clear()
            self._tokens_today.clear()
            self._last_reset = today
    
    def record_request(
        self,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0
    ):
        """
        Record an API request.
        
        Args:
            model_name: Model identifier
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used
        """
        with self._lock:
            self._check_reset()
            
            # Record request count
            self._requests_today[model_name] += 1
            
            # Record for RPM tracking
            now = datetime.now(timezone.utc)
            self._requests_minute[model_name].append(now)
            
            # Clean up old minute entries (keep last 60 seconds)
            cutoff = now.timestamp() - 60
            self._requests_minute[model_name] = [
                ts for ts in self._requests_minute[model_name]
                if ts.timestamp() > cutoff
            ]
            
            # Record tokens
            total_tokens = input_tokens + output_tokens
            self._tokens_today[model_name] += total_tokens
            
            logger.debug(
                f"Recorded usage for {model_name}: "
                f"+1 req, +{total_tokens} tokens "
                f"(total today: {self._requests_today[model_name]} req, "
                f"{self._tokens_today[model_name]} tokens)"
            )
        
        # Save to disk asynchronously after recording (outside lock)
        # Use try/except to handle case when called outside async context
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_to_disk_async())
        except RuntimeError:
            # No event loop running - skip async save (will save on next async call)
            logger.debug("No event loop available for async save, skipping")
    
    def _get_usage_unlocked(self, model_name: str) -> Dict:
        """
        Get current usage stats for a model (internal, assumes lock is held).
        
        Args:
            model_name: Model identifier
        
        Returns:
            Dict with usage stats and limits
        """
        limits = self.RATE_LIMITS.get(model_name, {
            "rpm": 15,
            "rpd": 1500,
            "tpd": 15000000,
            "tier": "unknown"
        })
        
        requests_today = self._requests_today.get(model_name, 0)
        requests_minute = len(self._requests_minute.get(model_name, []))
        tokens_today = self._tokens_today.get(model_name, 0)
        
        return {
            "model": model_name,
            "tier": limits["tier"],
            "requests": {
                "minute": {
                    "used": requests_minute,
                    "limit": limits["rpm"],
                    "remaining": max(0, limits["rpm"] - requests_minute)
                },
                "day": {
                    "used": requests_today,
                    "limit": limits["rpd"],
                        "remaining": max(0, limits["rpd"] - requests_today)
                    }
                },
                "tokens": {
                    "day": {
                        "used": tokens_today,
                        "limit": limits["tpd"],
                        "remaining": max(0, limits["tpd"] - tokens_today)
                    }
                },
                "reset_time": "Midnight Pacific Time (approximate)",
                "note": "Usage tracking is approximate and based on local counting"
            }
    
    def check_rate_limit(self, model_name: str, estimated_tokens: int = 0) -> tuple[bool, str]:
        """
        Check if a request would exceed rate limits.
        
        Args:
            model_name: Model identifier
            estimated_tokens: Estimated tokens for the request
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        with self._lock:
            self._check_reset()
            
            limits = self.RATE_LIMITS.get(model_name, {
                "rpm": 15,
                "rpd": 1500,
                "tpd": 15000000,
                "tier": "unknown"
            })
            
            requests_today = self._requests_today.get(model_name, 0)
            requests_minute = len(self._requests_minute.get(model_name, []))
            tokens_today = self._tokens_today.get(model_name, 0)
            
            # Check RPM limit
            if requests_minute >= limits["rpm"]:
                return False, f"Rate limit exceeded: {requests_minute}/{limits['rpm']} requests per minute"
            
            # Check RPD limit
            if requests_today >= limits["rpd"]:
                return False, f"Daily quota exceeded: {requests_today}/{limits['rpd']} requests per day"
            
            # Check token limit
            if tokens_today + estimated_tokens > limits["tpd"]:
                return False, f"Token quota exceeded: {tokens_today + estimated_tokens}/{limits['tpd']} tokens per day"
            
            return True, "OK"
    
    def get_usage(self, model_name: str) -> Dict:
        """
        Get current usage stats for a model (public API with locking).
        
        Args:
            model_name: Model identifier
        
        Returns:
            Dict with usage stats and limits
        """
        with self._lock:
            self._check_reset()
            return self._get_usage_unlocked(model_name)
    
    def _load_from_disk(self):
        """Load usage data from disk."""
        try:
            if self._persistence_file.exists():
                with open(self._persistence_file, 'r') as f:
                    data = json.load(f)
                
                # Check if data is from today
                date_str = data.get("date", "")
                if not date_str:
                    return
                saved_date = datetime.fromisoformat(date_str).date()
                today = datetime.now(timezone.utc).date()
                
                if saved_date == today:
                    # Restore today's data
                    self._requests_today = defaultdict(int, data.get("requests_today", {}))
                    self._tokens_today = defaultdict(int, data.get("tokens_today", {}))
                    self._last_reset = saved_date
                    logger.info(f"Loaded usage data from {self._persistence_file}")
                else:
                    logger.info(f"Usage data is from {saved_date}, starting fresh for {today}")
        except Exception as e:
            logger.warning(f"Could not load usage data from disk: {e}")
    
    async def _save_to_disk_async(self):
        """Save usage data to disk asynchronously (non-blocking)."""
        try:
            # Get snapshot of data while holding lock briefly
            with self._lock:
                data = {
                    "date": self._last_reset.isoformat(),
                    "requests_today": dict(self._requests_today),
                    "tokens_today": dict(self._tokens_today),
                    "saved_at": datetime.now(timezone.utc).isoformat()
                }
            
            # Perform file I/O in thread pool (outside lock)
            def _write_file():
                # Atomic write: write to temp file, then rename
                temp_file = self._persistence_file.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump(data, f, indent=2)
                temp_file.replace(self._persistence_file)
            
            await asyncio.to_thread(_write_file)
            logger.debug(f"Saved usage data to {self._persistence_file}")
        except Exception as e:
            logger.error(f"Failed to save usage data to disk: {e}")
    
    def _save_to_disk(self):
        """Synchronous save (for use in __init__ only)."""
        try:
            data = {
                "date": self._last_reset.isoformat(),
                "requests_today": dict(self._requests_today),
                "tokens_today": dict(self._tokens_today),
                "saved_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Atomic write: write to temp file, then rename
            temp_file = self._persistence_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self._persistence_file)
            
            logger.debug(f"Saved usage data to {self._persistence_file}")
        except Exception as e:
            logger.error(f"Failed to save usage data to disk: {e}")
    
    def get_all_usage(self) -> Dict:
        """Get usage stats for all tracked models."""
        with self._lock:
            self._check_reset()
            
            result = {}
            # Get all models that have been used
            all_models = set(self._requests_today.keys()) | set(self.RATE_LIMITS.keys())
            
            for model in all_models:
                result[model] = self._get_usage_unlocked(model)
            
            return result


# Global instance
usage_tracker = UsageTracker()
