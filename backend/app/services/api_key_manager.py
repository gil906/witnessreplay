"""
API Key Manager - handles rotation and fallback for Google API keys.
Provides resilience against rate limits and key revocation.
Updated for multi-model support with per-model cooldown tracking.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)


class APIKeyManager:
    """
    Manages multiple API keys with automatic rotation and fallback.
    
    Features:
    - Automatic rotation when rate limited (429)
    - Fallback when key fails (401, 403)
    - Track key usage and health
    - Cooldown period for rate-limited keys
    - Per-model cooldown tracking for multi-model support
    """
    
    def __init__(self, api_keys: List[str]):
        self.api_keys = [key.strip() for key in api_keys if key.strip()]
        self.current_index = 0
        self.key_status: Dict[str, Dict] = {
            key: {"healthy": True, "cooldown_until": None, "error_count": 0}
            for key in self.api_keys
        }
        # Per-model per-key cooldown: {(key, model): cooldown_until}
        self._model_cooldowns: Dict[tuple, datetime] = {}
        self._lock = asyncio.Lock()
        
        if not self.api_keys:
            logger.warning("APIKeyManager initialized with no keys!")
        else:
            logger.info(f"APIKeyManager initialized with {len(self.api_keys)} keys")
    
    async def get_key(self, model_name: Optional[str] = None) -> Optional[str]:
        """
        Get the current active API key.
        
        Args:
            model_name: Optional model name to check per-model cooldowns.
        
        Returns:
            API key string, or None if no healthy keys available
        """
        async with self._lock:
            if not self.api_keys:
                logger.error("No API keys configured!")
                return None
            
            now = datetime.now()
            available_keys = []
            
            for key in self.api_keys:
                status = self.key_status[key]
                
                # Check if global cooldown expired
                if status["cooldown_until"] and now >= status["cooldown_until"]:
                    status["cooldown_until"] = None
                    status["healthy"] = True
                    status["error_count"] = 0
                    logger.info(f"API key cooldown expired, marking as healthy: {key[:8]}...")
                
                # Check per-model cooldown
                if model_name:
                    model_cd = self._model_cooldowns.get((key, model_name))
                    if model_cd and now < model_cd:
                        continue  # Skip this key for this model
                    elif model_cd and now >= model_cd:
                        del self._model_cooldowns[(key, model_name)]
                
                if status["healthy"] and not status["cooldown_until"]:
                    available_keys.append(key)
            
            if not available_keys:
                logger.error("No healthy API keys available! All in cooldown or failed.")
                return self.api_keys[0]
            
            self.current_index = (self.current_index + 1) % len(available_keys)
            return available_keys[self.current_index]
    
    async def mark_rate_limited(self, api_key: str, cooldown_minutes: int = 5,
                                model_name: Optional[str] = None):
        """
        Mark an API key as rate limited and put it in cooldown.
        
        Args:
            api_key: The API key that hit rate limit
            cooldown_minutes: How long to wait before retrying (default 5 minutes)
            model_name: If set, only cool down this key for this specific model
        """
        async with self._lock:
            if model_name:
                cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
                self._model_cooldowns[(api_key, model_name)] = cooldown_until
                logger.warning(
                    f"API key rate limited for model {model_name}, "
                    f"cooldown until {cooldown_until.isoformat()}: {api_key[:8]}..."
                )
            elif api_key in self.key_status:
                cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
                self.key_status[api_key]["cooldown_until"] = cooldown_until
                self.key_status[api_key]["healthy"] = False
                self.key_status[api_key]["error_count"] += 1
                
                logger.warning(
                    f"API key rate limited, cooldown until {cooldown_until.isoformat()}: "
                    f"{api_key[:8]}... (error count: {self.key_status[api_key]['error_count']})"
                )
    
    async def mark_failed(self, api_key: str, error_code: int):
        """Mark an API key as failed (authentication error, revoked, etc)."""
        async with self._lock:
            if api_key in self.key_status:
                self.key_status[api_key]["healthy"] = False
                self.key_status[api_key]["error_count"] += 1
                
                logger.error(
                    f"API key failed with error {error_code}: {api_key[:8]}... "
                    f"(error count: {self.key_status[api_key]['error_count']})"
                )
    
    async def mark_success(self, api_key: str, model_name: Optional[str] = None):
        """Mark an API key as successfully used (reset error count)."""
        async with self._lock:
            if api_key in self.key_status:
                self.key_status[api_key]["error_count"] = 0
                self.key_status[api_key]["healthy"] = True
            # Clear any per-model cooldown on success
            if model_name and (api_key, model_name) in self._model_cooldowns:
                del self._model_cooldowns[(api_key, model_name)]
    
    def get_status(self) -> dict:
        """Get the status of all API keys."""
        now = datetime.now()
        status = {
            "total_keys": len(self.api_keys),
            "healthy_keys": 0,
            "rate_limited_keys": 0,
            "failed_keys": 0,
            "model_cooldowns": len(self._model_cooldowns),
            "keys": []
        }
        
        for i, key in enumerate(self.api_keys):
            key_status = self.key_status[key]
            masked_key = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
            
            # Count per-model cooldowns for this key
            active_model_cds = sum(
                1 for (k, _m), cd in self._model_cooldowns.items()
                if k == key and now < cd
            )
            
            key_info = {
                "index": i,
                "masked_key": masked_key,
                "healthy": key_status["healthy"],
                "error_count": key_status["error_count"],
                "in_cooldown": bool(key_status["cooldown_until"] and now < key_status["cooldown_until"]),
                "cooldown_expires": key_status["cooldown_until"].isoformat() if key_status["cooldown_until"] else None,
                "model_cooldowns_active": active_model_cds,
            }
            
            if key_info["in_cooldown"]:
                status["rate_limited_keys"] += 1
            elif key_status["healthy"]:
                status["healthy_keys"] += 1
            else:
                status["failed_keys"] += 1
            
            status["keys"].append(key_info)
        
        return status


# Global key manager instance
_key_manager: Optional[APIKeyManager] = None


def initialize_key_manager(api_keys: List[str]):
    """Initialize the global API key manager."""
    global _key_manager
    _key_manager = APIKeyManager(api_keys)


def get_key_manager() -> Optional[APIKeyManager]:
    """Get the global API key manager instance."""
    return _key_manager
