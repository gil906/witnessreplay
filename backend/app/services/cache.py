"""
Simple in-memory caching service for frequently accessed data.
Reduces load on storage and API calls.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, Callable
from functools import wraps

logger = logging.getLogger(__name__)


class CacheEntry:
    """Represents a single cache entry with expiration."""
    
    def __init__(self, value: Any, ttl_seconds: int = 300):
        self.value = value
        self.created_at = datetime.utcnow()
        self.ttl = timedelta(seconds=ttl_seconds)
    
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return datetime.utcnow() > (self.created_at + self.ttl)


class Cache:
    """
    Simple in-memory cache with TTL support.
    Thread-safe for async operations.
    """
    
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        logger.info("Cache service initialized")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get a value from cache.
        Returns None if not found or expired.
        """
        async with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            return entry.value
    
    async def set(self, key: str, value: Any, ttl_seconds: int = 300):
        """
        Set a value in cache with TTL.
        Default TTL is 5 minutes (300 seconds).
        """
        async with self._lock:
            self._cache[key] = CacheEntry(value, ttl_seconds)
    
    async def delete(self, key: str):
        """Delete a specific cache entry."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
            logger.info("Cache cleared")
    
    async def cleanup_expired(self):
        """Remove all expired entries from cache."""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total_requests,
            "hit_rate": round(hit_rate, 2),
        }


# Global cache instance
cache = Cache()


def cached(ttl_seconds: int = 300, key_prefix: str = ""):
    """
    Decorator for caching async function results.
    
    Args:
        ttl_seconds: Time to live in seconds (default 5 minutes)
        key_prefix: Optional prefix for cache keys
    
    Example:
        @cached(ttl_seconds=60, key_prefix="session")
        async def get_session(session_id: str):
            # expensive operation
            return session_data
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            args_str = "_".join(str(arg) for arg in args)
            kwargs_str = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = f"{key_prefix}:{func.__name__}:{args_str}:{kwargs_str}"
            
            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_value
            
            # Cache miss - execute function
            logger.debug(f"Cache miss for {cache_key}")
            result = await func(*args, **kwargs)
            
            # Store in cache
            await cache.set(cache_key, result, ttl_seconds)
            return result
        
        return wrapper
    return decorator
