import asyncio
import json
import logging
from typing import Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

QUALITY_MODEL_ORDER = {
    "fast": [
        "black-forest-labs/FLUX.1-schnell",
        "stabilityai/stable-diffusion-xl-base-1.0",
        "stabilityai/stable-diffusion-3-medium-diffusers",
    ],
    "standard": [
        "stabilityai/stable-diffusion-xl-base-1.0",
        "black-forest-labs/FLUX.1-schnell",
        "stabilityai/stable-diffusion-3-medium-diffusers",
    ],
    "ultra": [
        "stabilityai/stable-diffusion-xl-base-1.0",
        "stabilityai/stable-diffusion-3-medium-diffusers",
        "black-forest-labs/FLUX.1-schnell",
    ],
}

QUALITY_ALIASES = {
    "fast": "fast",
    "standard": "standard",
    "generate": "standard",
    "balanced": "standard",
    "default": "standard",
    "ultra": "ultra",
    "hd": "ultra",
    "high": "ultra",
}


class HuggingFaceImageService:
    API_BASE = "https://router.huggingface.co/hf-inference/models"

    def __init__(self) -> None:
        self._token = (settings.huggingface_api_token or "").strip()
        self._timeout = httpx.Timeout(180.0, connect=20.0)
        if self._token:
            logger.info("HuggingFaceImageService initialized")
        else:
            logger.info("HuggingFaceImageService disabled; no token configured")

    def is_configured(self) -> bool:
        return bool(self._token)

    def _normalize_quality(self, quality: str) -> str:
        return QUALITY_ALIASES.get((quality or "").strip().lower(), "standard")

    def _get_model_order(self, quality: str) -> list[str]:
        return QUALITY_MODEL_ORDER[self._normalize_quality(quality)]

    @staticmethod
    def _looks_like_image(content_type: str, payload: bytes) -> bool:
        lowered = (content_type or "").strip().lower()
        if lowered.startswith("image/"):
            return True
        return payload.startswith(b"\x89PNG\r\n\x1a\n") or payload.startswith(b"\xff\xd8\xff")

    @staticmethod
    def _extract_error(body: bytes, fallback: str) -> Tuple[str, Optional[float]]:
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                message = str(payload.get("error") or payload.get("message") or fallback)
                estimated_time = payload.get("estimated_time")
                try:
                    estimated_seconds = float(estimated_time) if estimated_time is not None else None
                except (TypeError, ValueError):
                    estimated_seconds = None
                return message, estimated_seconds
        except Exception:
            pass
        return fallback, None

    async def _request_model(self, client: httpx.AsyncClient, model: str, prompt: str) -> Optional[bytes]:
        url = f"{self.API_BASE}/{model}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "image/png",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": prompt,
            "options": {
                "wait_for_model": True,
                "use_cache": False,
            },
        }

        for attempt in range(2):
            response = await client.post(url, headers=headers, json=payload)
            if self._looks_like_image(response.headers.get("content-type", ""), response.content):
                return response.content

            error_message, estimated_seconds = self._extract_error(
                response.content,
                f"HTTP {response.status_code}",
            )
            if response.status_code == 503 and estimated_seconds and attempt == 0:
                wait_seconds = max(3.0, min(float(estimated_seconds) + 1.0, 35.0))
                logger.info(
                    "Hugging Face model %s is loading; retrying in %.1fs",
                    model,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
                continue

            logger.warning(
                "Hugging Face image model %s failed with %s: %s",
                model,
                response.status_code,
                error_message[:220],
            )
            return None

        return None

    async def generate_image(
        self,
        prompt: str,
        quality: str = "standard",
    ) -> Tuple[Optional[bytes], Optional[str]]:
        if not self._token:
            return None, None

        model_order = self._get_model_order(quality)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            for model in model_order:
                try:
                    logger.info(
                        "Attempting Hugging Face image generation with %s (quality=%s)",
                        model,
                        quality,
                    )
                    image_bytes = await self._request_model(client, model, prompt)
                    if image_bytes:
                        logger.info("Generated scene image via Hugging Face model %s", model)
                        return image_bytes, model
                except Exception as exc:
                    logger.warning("Hugging Face model %s unavailable: %s", model, str(exc)[:220])

        logger.warning("All Hugging Face image models failed")
        return None, None


huggingface_image_service = HuggingFaceImageService()
