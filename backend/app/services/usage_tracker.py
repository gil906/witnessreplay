"""
Usage tracking service for Gemini API quota management.
Since Gemini API doesn't provide programmatic quota endpoints,
we track usage locally.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from collections import defaultdict
import threading

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
    
    def __init__(self):
        self._lock = threading.Lock()
        # Track requests per model
        self._requests_today: Dict[str, int] = defaultdict(int)
        self._requests_minute: Dict[str, list] = defaultdict(list)
        # Track tokens per model
        self._tokens_today: Dict[str, int] = defaultdict(int)
        # Track last reset
        self._last_reset = datetime.now(timezone.utc).date()
    
    def _check_reset(self):
        """Reset counters if it's a new day (Pacific Time)."""
        # Gemini quotas reset at midnight Pacific Time
        # For simplicity, we reset at UTC midnight
        # TODO: Add proper Pacific Time handling
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
    
    def get_usage(self, model_name: str) -> Dict:
        """
        Get current usage stats for a model.
        
        Args:
            model_name: Model identifier
        
        Returns:
            Dict with usage stats and limits
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
    
    def get_all_usage(self) -> Dict:
        """Get usage stats for all tracked models."""
        with self._lock:
            self._check_reset()
            
            result = {}
            # Get all models that have been used
            all_models = set(self._requests_today.keys()) | set(self.RATE_LIMITS.keys())
            
            for model in all_models:
                result[model] = self.get_usage(model)
            
            return result


# Global instance
usage_tracker = UsageTracker()
