"""
Usage tracking service for Gemini API quota management.
Since Gemini API doesn't provide programmatic quota endpoints,
we track usage locally with JSON file persistence.

Updated for actual Google API quotas (per-model RPM/TPM/RPD).
"""
import logging
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple
from collections import defaultdict
import threading
import asyncio
from zoneinfo import ZoneInfo

from app.services.model_selector import MODEL_QUOTAS
from app.services.token_estimator import (
    token_estimator,
    estimate_tokens,
    TokenEstimate,
    QuotaCheckResult,
)

logger = logging.getLogger(__name__)


class UsageTracker:
    """Tracks Gemini API usage for quota display."""
    
    # Actual rate limits from Google API quota table
    RATE_LIMITS: Dict[str, Dict] = {
        "gemini-3-flash": {
            "rpm": 5, "rpd": 20, "tpm": 250_000, "tier": "free"
        },
        "gemini-2.5-flash": {
            "rpm": 5, "rpd": 20, "tpm": 250_000, "tier": "free"
        },
        "gemini-2.5-flash-lite": {
            "rpm": 10, "rpd": 20, "tpm": 250_000, "tier": "free"
        },
        "gemma-3-27b-it": {
            "rpm": 30, "rpd": 14_400, "tpm": 15_000, "tier": "free"
        },
        "gemma-3-12b-it": {
            "rpm": 30, "rpd": 14_400, "tpm": 15_000, "tier": "free"
        },
        "gemma-3-4b-it": {
            "rpm": 30, "rpd": 14_400, "tpm": 15_000, "tier": "free"
        },
        "imagen-4-fast-generate": {
            "rpm": 0, "rpd": 25, "tpm": 0, "tier": "free"
        },
        "imagen-4-generate": {
            "rpm": 0, "rpd": 25, "tpm": 0, "tier": "free"
        },
        "imagen-4-ultra-generate": {
            "rpm": 0, "rpd": 25, "tpm": 0, "tier": "free"
        },
        "gemini-embedding-001": {
            "rpm": 100, "rpd": 1_000, "tpm": 30_000, "tier": "free"
        },
        "gemini-2.5-flash-exp-native-audio-thinking": {
            "rpm": 0, "rpd": 0, "tpm": 1_000_000, "tier": "free"
        },
        "gemini-2.5-flash-preview-tts": {
            "rpm": 3, "rpd": 10, "tpm": 10_000, "tier": "free"
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
        """Reset counters if it's a new day (UTC midnight)."""
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
        """Record an API request with token counts."""
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
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_to_disk_async())
        except RuntimeError:
            logger.debug("No event loop available for async save, skipping")
    
    def _get_limits(self, model_name: str) -> Dict:
        """Get rate limits for a model, falling back to conservative defaults."""
        return self.RATE_LIMITS.get(model_name, {
            "rpm": 5, "rpd": 20, "tpm": 250_000, "tier": "unknown"
        })

    def _get_usage_unlocked(self, model_name: str) -> Dict:
        """Get current usage stats for a model (internal, assumes lock is held)."""
        limits = self._get_limits(model_name)
        
        requests_today = self._requests_today.get(model_name, 0)
        requests_minute = len(self._requests_minute.get(model_name, []))
        tokens_today = self._tokens_today.get(model_name, 0)
        
        rpm_limit = limits.get("rpm", 0)
        rpd_limit = limits.get("rpd", 0)
        tpm_limit = limits.get("tpm", 0)

        # Calculate next reset timestamp (midnight UTC)
        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        next_reset_timestamp = tomorrow.timestamp()
        
        return {
            "model": model_name,
            "tier": limits.get("tier", "unknown"),
            "limits": {
                "requests_per_minute": rpm_limit,
                "requests_per_day": rpd_limit,
                "tokens_per_minute": tpm_limit,
            },
            "remaining": {
                "requests_per_minute": max(0, rpm_limit - requests_minute) if rpm_limit else None,
                "requests_per_day": max(0, rpd_limit - requests_today) if rpd_limit else None,
                "tokens_per_minute": max(0, tpm_limit - tokens_today) if tpm_limit else None,
            },
            "requests": {
                "minute": {
                    "used": requests_minute,
                    "limit": rpm_limit,
                    "remaining": max(0, rpm_limit - requests_minute) if rpm_limit else None,
                },
                "day": {
                    "used": requests_today,
                    "limit": rpd_limit,
                    "remaining": max(0, rpd_limit - requests_today) if rpd_limit else None,
                },
            },
            "tokens": {
                "day": {
                    "used": tokens_today,
                    "limit": tpm_limit,
                    "remaining": max(0, tpm_limit - tokens_today) if tpm_limit else None,
                },
            },
            "next_reset_timestamp": next_reset_timestamp,
            "reset_time": "Midnight UTC",
            "note": "Usage tracking is approximate and based on local counting",
        }
    
    def check_rate_limit(self, model_name: str, estimated_tokens: int = 0) -> Tuple[bool, str]:
        """Check if a request would exceed rate limits.
        
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        with self._lock:
            self._check_reset()
            
            limits = self._get_limits(model_name)
            
            requests_today = self._requests_today.get(model_name, 0)
            requests_minute = len(self._requests_minute.get(model_name, []))
            tokens_today = self._tokens_today.get(model_name, 0)
            
            rpm_limit = limits.get("rpm", 0)
            rpd_limit = limits.get("rpd", 0)
            tpm_limit = limits.get("tpm", 0)
            
            # Check RPM limit (0 = unlimited)
            if rpm_limit and requests_minute >= rpm_limit:
                return False, f"Rate limit exceeded: {requests_minute}/{rpm_limit} requests per minute"
            
            # Check RPD limit (0 = unlimited)
            if rpd_limit and requests_today >= rpd_limit:
                return False, f"Daily quota exceeded: {requests_today}/{rpd_limit} requests per day"
            
            # Check TPM limit (0 = unlimited)
            if tpm_limit and tokens_today + estimated_tokens > tpm_limit:
                return False, f"Token quota exceeded: {tokens_today + estimated_tokens}/{tpm_limit} tokens per day"
            
            return True, "OK"
    
    def precheck_request(
        self,
        model_name: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[list] = None,
        task_type: str = "chat",
        enforce: bool = True,
    ) -> Tuple[QuotaCheckResult, TokenEstimate]:
        """
        Pre-check a request before sending to the API.
        
        Estimates tokens and checks against current quota usage.
        
        Args:
            model_name: Target model
            prompt: User prompt
            system_prompt: System instructions
            history: Conversation history
            task_type: Type of task
            enforce: If True, reject requests that exceed limits
            
        Returns:
            Tuple of (QuotaCheckResult, TokenEstimate)
        """
        # Estimate tokens for the request
        estimate = token_estimator.estimate_request(
            prompt=prompt,
            system_prompt=system_prompt,
            history=history,
            task_type=task_type,
        )
        
        # Get current usage
        with self._lock:
            self._check_reset()
            current_tokens = self._tokens_today.get(model_name, 0)
        
        # Check against quota
        check_result = token_estimator.check_quota(
            model_name=model_name,
            estimated_tokens=estimate.total_tokens,
            current_usage=current_tokens,
            enforce=enforce,
        )
        
        if check_result.warning:
            logger.warning(f"Token quota warning for {model_name}: {check_result.warning}")
        
        if not check_result.allowed:
            logger.warning(f"Token quota exceeded for {model_name}: {check_result.rejection_reason}")
        
        return check_result, estimate
    
    def get_usage(self, model_name: str) -> Dict:
        """Get current usage stats for a model (public API with locking)."""
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
            with self._lock:
                data = {
                    "date": self._last_reset.isoformat(),
                    "requests_today": dict(self._requests_today),
                    "tokens_today": dict(self._tokens_today),
                    "saved_at": datetime.now(timezone.utc).isoformat()
                }
            
            def _write_file():
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
            all_models = set(self._requests_today.keys()) | set(self.RATE_LIMITS.keys())
            
            for model in all_models:
                result[model] = self._get_usage_unlocked(model)
            
            return result


# Global instance
usage_tracker = UsageTracker()
