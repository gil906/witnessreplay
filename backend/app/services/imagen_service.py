import logging
import asyncio
import os
from typing import Optional
from datetime import datetime

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class ImagenService:
    """Generates AI scene images using Google Imagen 4."""

    MODELS = [
        "imagen-4-fast-generate",   # Fast, 25 RPD
        "imagen-4-generate",        # Standard, 25 RPD
        "imagen-4-ultra-generate",  # Ultra, 25 RPD
    ]

    IMAGES_DIR = "/app/data/images"

    def __init__(self):
        self.client = None
        self._daily_counts: dict[str, int] = {}
        self._last_reset = ""
        self._initialize()

    def _initialize(self):
        from app.config import settings

        if settings.google_api_key:
            self.client = genai.Client(api_key=settings.google_api_key)
            logger.info("ImagenService initialized with Google API key")
        else:
            logger.warning("ImagenService: no Google API key, Imagen generation disabled")

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    async def generate_scene(self, prompt: str, quality: str = "fast") -> Optional[bytes]:
        """Generate a scene image from a text prompt.

        Args:
            prompt: Scene description text.
            quality: 'fast', 'standard', or 'ultra' — controls model selection order.

        Returns:
            PNG image bytes, or None if all models exhausted / unavailable.
        """
        if not self.client:
            return None

        self._reset_daily_if_needed()
        model_order = self._get_model_order(quality)

        for model in model_order:
            if self._daily_counts.get(model, 0) >= 25:
                continue

            try:
                result = await asyncio.to_thread(
                    self.client.models.generate_image,
                    model=model,
                    prompt=self._build_scene_prompt(prompt),
                    config=types.GenerateImageConfig(
                        number_of_images=1,
                        aspect_ratio="16:9",
                        safety_filter_level="BLOCK_ONLY_HIGH",
                        person_generation="ALLOW_ADULT",
                    ),
                )

                self._daily_counts[model] = self._daily_counts.get(model, 0) + 1

                if result.generated_images:
                    image_bytes = result.generated_images[0].image.image_bytes
                    if image_bytes:
                        logger.info(
                            "Generated scene image with %s (%d/25 today)",
                            model,
                            self._daily_counts[model],
                        )
                        return image_bytes

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    self._daily_counts[model] = 25
                    logger.warning("Imagen model %s quota exhausted", model)
                    continue
                logger.error("Imagen error with %s: %s", model, e)
                continue

        logger.warning("All Imagen models exhausted, no image generated")
        return None

    # ------------------------------------------------------------------
    # Per-report / per-case helpers
    # ------------------------------------------------------------------

    async def generate_report_scene(
        self, report_id: str, scene_description: str, elements: list
    ) -> Optional[str]:
        """Generate a scene image for a single witness report.

        Returns:
            Relative URL path to saved image, or None.
        """
        prompt = (
            "Latest witness report reconstruction. "
            "Generate a realistic 3D scene update that reflects only the described details.\n"
            f"Report details: {scene_description}"
        )
        if elements:
            descs = ", ".join(
                e.get("description", e.get("type", "unknown")) for e in elements[:10]
            )
            prompt += f"\nVisible entities to include: {descs}"

        image_bytes = await self.generate_scene(prompt, quality="fast")
        if image_bytes:
            return self._save_image(image_bytes, f"report_{report_id}")
        return None

    async def generate_case_scene(
        self,
        case_id: str,
        case_summary: str,
        scene_description: str,
        quality: str = "standard",
    ) -> Optional[str]:
        """Generate composite scene image from all witness accounts for a case.

        Returns:
            Relative URL path to saved image, or None.
        """
        prompt = (
            "Comprehensive 3D reconstruction combining multiple witness accounts. "
            "Keep scene continuity while integrating the newest corroborated details.\n"
            f"Scene details: {scene_description}\nCase summary: {case_summary}"
        )

        image_bytes = await self.generate_scene(prompt, quality=quality)
        if image_bytes:
            return self._save_image(image_bytes, f"case_{case_id}")
        return None

    async def regenerate_scene(
        self,
        entity_type: str,
        entity_id: str,
        description: str,
        quality: str = "standard",
    ) -> Optional[str]:
        """Force-regenerate a scene image.

        Returns:
            Relative URL path to saved image, or None.
        """
        image_bytes = await self.generate_scene(description, quality=quality)
        if image_bytes:
            prefix = f"{entity_type}_{entity_id}"
            return self._save_image(image_bytes, prefix)
        return None

    # ------------------------------------------------------------------
    # Image storage & gallery
    # ------------------------------------------------------------------

    def _save_image(self, image_bytes: bytes, prefix: str) -> str:
        """Save image to disk and return its relative URL path."""
        os.makedirs(self.IMAGES_DIR, exist_ok=True)

        filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(self.IMAGES_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.info("Saved image to %s", filepath)
        return f"/data/images/{filename}"

    async def get_images_for_case(self, case_id: str) -> list[str]:
        """List all generated images for a case."""
        return self._list_images(f"case_{case_id}")

    async def get_images_for_report(self, report_id: str) -> list[str]:
        """List all generated images for a report."""
        return self._list_images(f"report_{report_id}")

    def _list_images(self, prefix: str) -> list[str]:
        if not os.path.exists(self.IMAGES_DIR):
            return []
        return sorted(
            f"/data/images/{f}"
            for f in os.listdir(self.IMAGES_DIR)
            if f.startswith(prefix)
        )

    # ------------------------------------------------------------------
    # Quota helpers
    # ------------------------------------------------------------------

    def get_quota_status(self) -> dict:
        """Return current daily usage for each Imagen model."""
        self._reset_daily_if_needed()
        return {
            model: {"used": self._daily_counts.get(model, 0), "limit": 25}
            for model in self.MODELS
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_scene_prompt(self, description: str) -> str:
        return (
            "Create a detailed, realistic 3D reconstruction of a crime/accident scene from witness testimony. "
            "Style: cinematic but factual, oblique camera angle (not top-down), natural lighting, high detail. "
            "Do NOT use template-like intersection diagrams, map symbols, color dots, labels, UI overlays, or legends. "
            "Continuously incorporate new witness details as concrete scene objects, positions, and actions. "
            "Do NOT include any graphic violence, blood, or disturbing content. "
            f"Scene description: {description} "
            "Show physically plausible placement of vehicles, people, environment, and evidence."
        )

    def _get_model_order(self, quality: str) -> list[str]:
        if quality == "ultra":
            return [
                "imagen-4-ultra-generate",
                "imagen-4-generate",
                "imagen-4-fast-generate",
            ]
        if quality == "standard":
            return [
                "imagen-4-generate",
                "imagen-4-fast-generate",
                "imagen-4-ultra-generate",
            ]
        # fast (default)
        return [
            "imagen-4-fast-generate",
            "imagen-4-generate",
            "imagen-4-ultra-generate",
        ]

    def _reset_daily_if_needed(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._last_reset != today:
            self._daily_counts = {}
            self._last_reset = today


# Global singleton
imagen_service = ImagenService()
