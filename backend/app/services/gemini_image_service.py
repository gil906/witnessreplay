"""Gemini-based image generation service.

Uses Gemini's native image generation capabilities via generate_content
with response_modalities=["IMAGE", "TEXT"]. This has much higher quotas
than Imagen 4 (25 RPD per model) and produces good quality scene images.
"""

import logging
import asyncio
import os
import base64
from typing import Optional
from datetime import datetime

from google.genai import types
from app.services.api_key_manager import get_genai_client

logger = logging.getLogger(__name__)

# Gemini models that support image generation output
# See https://ai.google.dev/gemini-api/docs/image-generation
GEMINI_IMAGE_MODELS = [
    "gemini-2.5-flash-image",               # Nano Banana – fast, high-volume
    "gemini-3.1-flash-image-preview",        # Nano Banana 2 – best balance
    "gemini-3-pro-image-preview",            # Nano Banana Pro – professional
]

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

QUALITY_MODEL_ORDER = {
    "fast": [
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-3-pro-image-preview",
    ],
    "standard": [
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
        "gemini-3-pro-image-preview",
    ],
    "ultra": [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ],
}

IMAGES_DIR = "/app/data/images"


class GeminiImageService:
    """Generates scene images using Gemini's native image generation."""

    def __init__(self):
        self.client = None
        self._initialize()

    def _initialize(self):
        from app.config import settings
        if settings.google_api_key:
            self.client = get_genai_client()
            logger.info("GeminiImageService initialized with Google API key")
        else:
            logger.warning("GeminiImageService: no Google API key")

    def _build_scene_prompt(self, description: str) -> str:
        """Build a detailed prompt for scene image generation."""
        return (
            "Generate a detailed, realistic image reconstructing a crime or accident scene "
            "based on the following witness testimony. "
            "Style: cinematic, realistic, oblique camera angle showing the full scene, "
            "natural lighting, high detail, photorealistic. "
            "Do NOT include any text, labels, UI overlays, legends, or map symbols. "
            "Do NOT add generic intersections, roads, parking lots, storefronts, or placeholder scenery unless the testimony explicitly supports them. "
            "If some context is unknown, keep the unseen background subdued and non-specific instead of inventing extra detail. "
            "Do NOT include any graphic violence, blood, or disturbing content. "
            "Show physically plausible placement of vehicles, people, environment, and evidence. "
            f"\n\nScene description from witness testimony:\n{description}\n\n"
            "Generate a single high-quality image of this scene reconstruction."
        )

    def _normalize_quality(self, quality: str) -> str:
        return QUALITY_ALIASES.get((quality or "").strip().lower(), "standard")

    def _get_model_order(self, quality: str) -> list[str]:
        return QUALITY_MODEL_ORDER[self._normalize_quality(quality)]

    async def _generate_with_model(self, model_name: str, prompt: str):
        configs = [
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="16:9"),
            ),
            types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
                image_config=types.ImageConfig(aspect_ratio="16:9"),
            ),
            None,
        ]

        last_error = None
        for config in configs:
            try:
                if config is None:
                    return await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=model_name,
                        contents=[prompt],
                    )
                return await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model_name,
                    contents=[prompt],
                    config=config,
                )
            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                unsupported_config = any(
                    token in error_str
                    for token in (
                        "response_modalities",
                        "response modalities",
                        "image_config",
                        "unknown field",
                        "unexpected keyword",
                        "invalid argument",
                    )
                )
                if config is not None and unsupported_config:
                    logger.debug(
                        "Gemini image generation retrying %s without current config after: %s",
                        model_name,
                        str(e)[:180],
                    )
                    continue
                raise

        if last_error:
            raise last_error
        return None

    @staticmethod
    def _iter_response_parts(result):
        """Yield response parts across SDK response shapes."""
        direct_parts = getattr(result, "parts", None) or []
        for part in direct_parts:
            yield part

        for candidate in getattr(result, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                yield part

    async def generate_image(self, description: str, quality: str = "standard") -> Optional[bytes]:
        """Generate an image from a description using Gemini.

        Returns PNG image bytes or None if generation fails.
        """
        if not self.client:
            logger.warning("GeminiImageService: no client available")
            return None

        prompt = self._build_scene_prompt(description)
        normalized_quality = self._normalize_quality(quality)

        for model_name in self._get_model_order(normalized_quality):
            try:
                logger.info(
                    "Attempting Gemini image generation with %s (quality=%s)",
                    model_name,
                    normalized_quality,
                )
                result = await self._generate_with_model(model_name, prompt)

                # Extract image from response parts using the SDK helpers
                image_found = False
                for part in self._iter_response_parts(result):
                    # Try SDK as_image() helper first (returns PIL Image)
                    try:
                        pil_image = part.as_image()
                        if pil_image:
                            import io
                            buf = io.BytesIO()
                            pil_image.save(buf, format="PNG")
                            image_bytes = buf.getvalue()
                            if image_bytes:
                                logger.info("Generated image with Gemini model %s (as_image)", model_name)
                                return image_bytes
                    except Exception:
                        pass

                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        mime_type = str(getattr(inline_data, "mime_type", "") or "")
                        if "image" in mime_type:
                            image_bytes = inline_data.data
                            if isinstance(image_bytes, str):
                                image_bytes = base64.b64decode(image_bytes)
                            if image_bytes:
                                logger.info("Generated image with Gemini model %s (inline_data)", model_name)
                                return image_bytes
                        image_found = True

                response_text = str(getattr(result, "text", "") or "")[:160]
                logger.warning(
                    "No usable image data in Gemini response from %s (quality=%s, has_candidates=%s, saw_inline_data=%s, text_preview=%r)",
                    model_name,
                    normalized_quality,
                    bool(getattr(result, "candidates", None)),
                    image_found,
                    response_text,
                )

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    logger.warning("Gemini model %s rate limited, trying next", model_name)
                    continue
                if "not supported" in error_str.lower() or "invalid" in error_str.lower():
                    logger.warning("Gemini model %s doesn't support image gen: %s", model_name, error_str[:100])
                    continue
                logger.error(
                    "Gemini image generation error with %s (quality=%s): %s",
                    model_name,
                    normalized_quality,
                    e,
                )
                continue

        logger.warning("All Gemini image models failed")
        return None

    def _save_image(self, image_bytes: bytes, prefix: str) -> str:
        """Save image to disk and return its relative URL path."""
        os.makedirs(IMAGES_DIR, exist_ok=True)
        filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        logger.info("Saved Gemini image to %s", filepath)
        return f"/data/images/{filename}"

    async def generate_report_scene(
        self, report_id: str, scene_description: str, elements: list, quality: str = "standard"
    ) -> Optional[str]:
        """Generate a scene image for a report. Returns URL path or None."""
        prompt = scene_description
        if elements:
            descs = ", ".join(
                e.get("description", e.get("type", "unknown"))
                for e in elements[:10]
                if isinstance(e, dict)
            )
            if descs:
                prompt += f"\nVisible entities: {descs}"

        image_bytes = await self.generate_image(prompt, quality=quality)
        if image_bytes:
            return self._save_image(image_bytes, f"report_{report_id}")
        return None

    async def generate_case_scene(
        self, case_id: str, case_summary: str, scene_description: str, quality: str = "standard"
    ) -> Optional[str]:
        """Generate a composite scene image for a case. Returns URL path or None."""
        prompt = (
            f"Full scene reconstruction combining multiple witness accounts.\n"
            f"Scene details: {scene_description}\nCase summary: {case_summary}"
        )
        image_bytes = await self.generate_image(prompt, quality=quality)
        if image_bytes:
            return self._save_image(image_bytes, f"case_{case_id}")
        return None


# Global singleton
gemini_image_service = GeminiImageService()
