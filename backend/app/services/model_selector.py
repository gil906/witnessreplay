"""
Model selector service for automatic fallback when rate limited.
Implements Idea #2: Automatic model switching when rate limited.
"""
import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import asyncio
from google import genai

from app.config import settings

logger = logging.getLogger(__name__)


class ModelSelector:
    """
    Intelligent model selector that tracks rate limits and automatically
    falls back to alternative models when rate limited.
    """
    
    # Model tiers: best to fallback (for scene reconstruction)
    SCENE_RECONSTRUCTION_MODELS = [
        "gemini-2.0-flash-exp",  # Best quality, but may be rate limited
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ]
    
    # Models for chat/conversation (can use lighter models)
    CHAT_MODELS = [
        "gemini-1.5-flash-8b",  # Fastest for chat
        "gemini-1.5-flash",
        "gemini-2.0-flash-exp",
    ]
    
    def __init__(self):
        self._rate_limited_models: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        
    async def get_best_model_for_scene(self) -> str:
        """
        Get the best available model for scene reconstruction.
        Returns the highest quality model that isn't rate limited.
        
        Implements Idea #3: Use best models for scene reconstruction.
        """
        async with self._lock:
            # Clean up expired rate limits (reset after 1 minute)
            self._cleanup_rate_limits()
            
            # Try each model in order of quality
            for model in self.SCENE_RECONSTRUCTION_MODELS:
                if not self._is_rate_limited(model):
                    logger.info(f"Selected model for scene reconstruction: {model}")
                    return model
            
            # If all are rate limited, use the first one and hope it's recovered
            logger.warning("All scene models rate limited, using first option anyway")
            return self.SCENE_RECONSTRUCTION_MODELS[0]
    
    async def get_best_model_for_chat(self) -> str:
        """
        Get the best available model for chat/conversation.
        Returns a fast model that isn't rate limited.
        """
        async with self._lock:
            self._cleanup_rate_limits()
            
            for model in self.CHAT_MODELS:
                if not self._is_rate_limited(model):
                    logger.info(f"Selected model for chat: {model}")
                    return model
            
            logger.warning("All chat models rate limited, using first option anyway")
            return self.CHAT_MODELS[0]
    
    async def mark_rate_limited(self, model_name: str):
        """
        Mark a model as rate limited. It will be avoided for 60 seconds.
        """
        async with self._lock:
            self._rate_limited_models[model_name] = datetime.utcnow()
            logger.warning(f"Model {model_name} marked as rate limited")
    
    def _is_rate_limited(self, model_name: str) -> bool:
        """Check if a model is currently rate limited."""
        if model_name not in self._rate_limited_models:
            return False
        
        # Rate limits typically reset after 1 minute
        limit_time = self._rate_limited_models[model_name]
        expired = datetime.utcnow() - limit_time > timedelta(seconds=60)
        
        if expired:
            del self._rate_limited_models[model_name]
            return False
        
        return True
    
    def _cleanup_rate_limits(self):
        """Remove expired rate limits."""
        now = datetime.utcnow()
        expired_models = [
            model for model, limit_time in self._rate_limited_models.items()
            if now - limit_time > timedelta(seconds=60)
        ]
        for model in expired_models:
            del self._rate_limited_models[model]
            logger.info(f"Model {model} rate limit expired, now available")
    
    async def check_model_availability(self, model_name: str) -> bool:
        """
        Check if a model is available without spending tokens.
        This is a lightweight check - just verifies the model exists.
        
        Implements Idea #2: Check what models are rate limited without spending tokens.
        """
        try:
            # Use cached client if available
            client = genai.Client(api_key=settings.google_api_key)
            
            # Run in thread to avoid blocking
            def check():
                try:
                    # List models and check if our model exists
                    for model in client.models.list():
                        if model_name in model.name:
                            return True
                    return False
                except Exception as e:
                    # If we get 429, mark as rate limited
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        return False
                    raise
            
            available = await asyncio.to_thread(check)
            
            if not available:
                await self.mark_rate_limited(model_name)
            
            return available
            
        except Exception as e:
            logger.warning(f"Error checking model availability for {model_name}: {e}")
            return False
    
    async def get_all_models_status(self) -> List[Dict]:
        """
        Get status of all known models.
        Returns list of dicts with model name and availability status.
        """
        all_models = list(set(self.SCENE_RECONSTRUCTION_MODELS + self.CHAT_MODELS))
        
        statuses = []
        for model in all_models:
            async with self._lock:
                is_limited = self._is_rate_limited(model)
            
            statuses.append({
                "model": model,
                "available": not is_limited,
                "rate_limited": is_limited,
                "rate_limit_expires_in": self._get_rate_limit_expiry(model) if is_limited else None
            })
        
        return statuses
    
    def _get_rate_limit_expiry(self, model_name: str) -> Optional[int]:
        """Get seconds until rate limit expires for a model."""
        if model_name not in self._rate_limited_models:
            return None
        
        limit_time = self._rate_limited_models[model_name]
        expires_at = limit_time + timedelta(seconds=60)
        delta = expires_at - datetime.utcnow()
        
        return max(0, int(delta.total_seconds()))


# Global model selector instance
model_selector = ModelSelector()
