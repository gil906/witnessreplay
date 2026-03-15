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

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Gemini models that support image generation output
# See https://ai.google.dev/gemini-api/docs/image-generation
GEMINI_IMAGE_MODELS = [
    "gemini-2.5-flash-image",               # Nano Banana – fast, high-volume
    "gemini-3.1-flash-image-preview",        # Nano Banana 2 – best balance
    "gemini-3-pro-image-preview",            # Nano Banana Pro – professional
]

IMAGES_DIR = "/app/data/images"


class GeminiImageService:
    """Generates scene images using Gemini's native image generation."""

    def __init__(self):
        self.client = None
        self._initialize()

    def _initialize(self):
        from app.config import settings
        if settings.google_api_key:
            self.client = genai.Client(api_key=settings.google_api_key)
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
            "Do NOT include any graphic violence, blood, or disturbing content. "
            "Show physically plausible placement of vehicles, people, environment, and evidence. "
            f"\n\nScene description from witness testimony:\n{description}\n\n"
            "Generate a single high-quality image of this scene reconstruction."
        )

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

    async def generate_image(self, description: str) -> Optional[bytes]:
        """Generate an image from a description using Gemini.

        Returns PNG image bytes or None if generation fails.
        """
        if not self.client:
            logger.warning("GeminiImageService: no client available")
            return None

        prompt = self._build_scene_prompt(description)

        for model_name in GEMINI_IMAGE_MODELS:
            try:
                logger.info("Attempting image generation with %s", model_name)
                result = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                    ),
                )

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

                logger.warning(
                    "No usable image data in Gemini response from %s (has_candidates=%s, saw_inline_data=%s)",
                    model_name,
                    bool(getattr(result, "candidates", None)),
                    image_found,
                )

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    logger.warning("Gemini model %s rate limited, trying next", model_name)
                    continue
                if "not supported" in error_str.lower() or "invalid" in error_str.lower():
                    logger.warning("Gemini model %s doesn't support image gen: %s", model_name, error_str[:100])
                    continue
                logger.error("Gemini image generation error with %s: %s", model_name, e)
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
        self, report_id: str, scene_description: str, elements: list
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

        image_bytes = await self.generate_image(prompt)
        if image_bytes:
            return self._save_image(image_bytes, f"report_{report_id}")
        return None

    async def generate_case_scene(
        self, case_id: str, case_summary: str, scene_description: str
    ) -> Optional[str]:
        """Generate a composite scene image for a case. Returns URL path or None."""
        prompt = (
            f"Full scene reconstruction combining multiple witness accounts.\n"
            f"Scene details: {scene_description}\nCase summary: {case_summary}"
        )
        image_bytes = await self.generate_image(prompt)
        if image_bytes:
            return self._save_image(image_bytes, f"case_{case_id}")
        return None


# Global singleton
gemini_image_service = GeminiImageService()
