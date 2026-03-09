"""Retry utility with exponential backoff for API calls."""
import asyncio
import random
import logging

logger = logging.getLogger(__name__)


async def retry_with_backoff(func, max_retries=3):
    """Retry async function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            error_str = str(e).lower()
            if attempt < max_retries - 1 and (
                "429" in error_str
                or "quota" in error_str
                or "rate" in error_str
                or "resource" in error_str
            ):
                delay = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    f"Retry {attempt+1}/{max_retries} after {delay:.1f}s: {str(e)[:100]}"
                )
                await asyncio.sleep(delay)
            else:
                raise
