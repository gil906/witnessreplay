import logging
import asyncio
import os
import re
from typing import Optional, Any, Dict, List, Tuple
from datetime import datetime

from google.genai import types
from app.services.api_key_manager import get_genai_client

logger = logging.getLogger(__name__)

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

SCENE_FILLER_PATTERN = re.compile(
    r"\b("
    r"that will be all|that's all|thats all|that's perfect|thats perfect|"
    r"thank you|thanks|goodbye|bye|repeat that slowly|start from the beginning"
    r")\b",
    re.IGNORECASE,
)


class ImagenService:
    """Generates AI scene images using Google Imagen 4."""

    MODELS = [
        "imagen-4.0-fast-generate-001",   # Fast, 25 RPD
        "imagen-4.0-generate-001",        # Standard, 25 RPD
        "imagen-4.0-ultra-generate-001",  # Ultra, 25 RPD
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
            self.client = get_genai_client()
            logger.info("ImagenService initialized with Google API key")
        else:
            logger.warning("ImagenService: no Google API key, Imagen generation disabled")

    def normalize_quality(self, quality: str) -> str:
        """Normalize caller-facing quality names to Imagen/Gemini tiers."""
        return QUALITY_ALIASES.get((quality or "").strip().lower(), "standard")

    def _normalize_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _is_low_information_text(self, value: Any) -> bool:
        text = self._normalize_text(value)
        if not text:
            return True

        from app.services.image_gen import image_service

        detail = image_service.assess_scene_detail(text, [])
        if detail["reason"] in {"placeholder_text", "filler_phrase"}:
            return True
        if SCENE_FILLER_PATTERN.search(text) and detail["concrete_term_count"] < 2:
            return True
        if detail["concrete_term_count"] == 0 and detail["word_count"] < 8:
            return True
        return False

    def _dedupe_fragments(self, values: List[str], limit: int) -> List[str]:
        results: List[str] = []
        seen: set[str] = set()
        for raw in values:
            text = self._normalize_text(raw)
            if not text:
                continue
            normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            results.append(text)
            if len(results) >= limit:
                break
        return results

    def _normalize_elements(self, elements: List[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for element in elements or []:
            if isinstance(element, dict):
                normalized.append(element)
                continue
            normalized.append({
                "type": getattr(element, "type", None),
                "description": getattr(element, "description", None),
                "position": getattr(element, "position", None),
                "color": getattr(element, "color", None),
                "size": getattr(element, "size", None),
            })
        return normalized

    def _build_element_fragments(self, elements: List[Any], limit: int = 10) -> List[str]:
        fragments: List[str] = []
        for element in self._normalize_elements(elements)[:limit]:
            parts = [self._normalize_text(element.get("type"))]
            description = self._normalize_text(element.get("description"))
            color = self._normalize_text(element.get("color"))
            position = element.get("position")
            size = self._normalize_text(element.get("size"))
            if description and description.lower() not in {"car", "vehicle", "person", "object"}:
                parts.append(description)
            if color:
                parts.append(f"color {color}")
            if position:
                parts.append(f"position {position}")
            if size:
                parts.append(f"size {size}")
            fragment = ", ".join(part for part in parts if part)
            if fragment:
                fragments.append(fragment)
        return self._dedupe_fragments(fragments, limit=limit)

    def build_report_scene_description(
        self,
        *,
        primary_description: str = "",
        statements: Optional[List[str]] = None,
        elements: Optional[List[Any]] = None,
        title: str = "",
        ai_summary: str = "",
        latest_scene_description: str = "",
    ) -> str:
        """Compose a report-scene description from the richest available witness details."""
        fragments: List[str] = []

        for candidate in (primary_description, latest_scene_description, ai_summary):
            if candidate and not self._is_low_information_text(candidate):
                fragments.append(candidate)

        for statement in statements or []:
            if not self._is_low_information_text(statement):
                fragments.append(statement)

        if title and not self._is_low_information_text(title):
            fragments.append(title)

        witness_lines = self._dedupe_fragments(fragments, limit=8)
        element_lines = self._build_element_fragments(elements or [], limit=8)

        sections: List[str] = []
        if witness_lines:
            sections.append("Witness-reported details:\n- " + "\n- ".join(witness_lines))
        if element_lines:
            sections.append("Structured scene elements:\n- " + "\n- ".join(element_lines))

        return "\n\n".join(sections)[:1600]

    def build_case_scene_description(
        self,
        *,
        case_summary: str = "",
        scene_description: str = "",
        report_fragments: Optional[List[str]] = None,
        title: str = "",
    ) -> str:
        """Compose a case-level scene description from case and report context."""
        summary_lines: List[str] = []
        for candidate in (scene_description, case_summary, title):
            if candidate and not self._is_low_information_text(candidate):
                summary_lines.append(candidate)

        report_lines = self._dedupe_fragments(
            [fragment for fragment in (report_fragments or []) if not self._is_low_information_text(fragment)],
            limit=10,
        )

        sections: List[str] = []
        if summary_lines:
            sections.append(
                "Corroborated case summary:\n- "
                + "\n- ".join(self._dedupe_fragments(summary_lines, limit=4))
            )
        if report_lines:
            sections.append("Supporting witness details:\n- " + "\n- ".join(report_lines))

        return "\n\n".join(sections)[:1800]

    def _report_prompt(self, scene_description: str, elements: List[Any]) -> str:
        element_lines = self._build_element_fragments(elements, limit=10)
        details_block = "\n".join(f"- {line}" for line in element_lines) if element_lines else "- No extra structured elements supplied."
        return (
            "Latest witness report reconstruction. "
            "Generate a realistic, factual scene update using only the described details. "
            "Do not add generic intersections, placeholder storefronts, extra vehicles, or empty template scenery. "
            "If testimony is incomplete, keep unknown background areas neutral rather than inventing specifics.\n\n"
            f"Report details:\n{scene_description}\n\n"
            f"Visible entities to include:\n{details_block}"
        )

    def _case_prompt(
        self,
        case_summary: str,
        scene_description: str,
        elements: Optional[List[Any]] = None,
    ) -> str:
        element_lines = self._build_element_fragments(elements or [], limit=12)
        corroborated_entities = (
            "\n".join(f"- {line}" for line in element_lines)
            if element_lines
            else "- Use only the corroborated witness details summarized above."
        )
        return (
            "Comprehensive 3D reconstruction combining multiple witness accounts. "
            "Preserve only the corroborated details and do not invent template roads, plazas, or buildings. "
            "If exact background context is missing, keep the unseen surroundings understated. "
            "Prioritize the corroborated people, vehicles, objects, positions, and lighting described by witnesses.\n\n"
            f"Case summary:\n{case_summary}\n\n"
            f"Scene details:\n{scene_description}\n\n"
            f"Corroborated entities to include:\n{corroborated_entities}"
        )

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    async def generate_scene_with_source(
        self,
        prompt: str,
        quality: str = "standard",
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """Generate scene bytes and return the originating model/source."""
        normalized_quality = self.normalize_quality(quality)

        # --- Try Gemini image generation first (higher quotas) ---
        try:
            from app.services.gemini_image_service import gemini_image_service

            gemini_bytes = await gemini_image_service.generate_image(prompt, quality=normalized_quality)
            if gemini_bytes:
                logger.info("Generated scene image via Gemini native image generation")
                return gemini_bytes, "gemini"
        except Exception as e:
            logger.warning("Gemini image generation unavailable, falling back to Imagen: %s", e)

        # --- Fallback to Imagen 4 ---
        if not self.client:
            return None, None

        self._reset_daily_if_needed()
        model_order = self._get_model_order(normalized_quality)

        for model in model_order:
            if self._daily_counts.get(model, 0) >= 25:
                continue

            try:
                result = await asyncio.to_thread(
                    self.client.models.generate_images,
                    model=model,
                    prompt=self._build_scene_prompt(prompt),
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="16:9",
                        safety_filter_level="BLOCK_LOW_AND_ABOVE",
                        person_generation="ALLOW_ADULT",
                    ),
                )

                self._daily_counts[model] = self._daily_counts.get(model, 0) + 1

                if result.generated_images:
                    image_bytes = result.generated_images[0].image.image_bytes
                    if image_bytes:
                        logger.info(
                            "Generated scene image with %s (%d/25 today, requested_quality=%s)",
                            model,
                            self._daily_counts[model],
                            normalized_quality,
                        )
                        return image_bytes, model

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    self._daily_counts[model] = 25
                    logger.warning("Imagen model %s quota exhausted", model)
                    continue
                logger.error("Imagen error with %s: %s", model, e)
                continue

        logger.warning("All Imagen models exhausted, no image generated")
        return None, None

    async def generate_scene(self, prompt: str, quality: str = "standard") -> Optional[bytes]:
        """Generate a scene image from a text prompt."""
        image_bytes, _ = await self.generate_scene_with_source(prompt, quality=quality)
        return image_bytes

    async def generate_scene_with_fallback(
        self,
        *,
        prompt: str,
        scene_description: str,
        elements: Optional[List[Any]] = None,
        quality: str = "standard",
        prefix: str,
    ) -> Dict[str, Any]:
        """Generate an AI scene image, then fall back to PIL only when detail is sufficient."""
        normalized_quality = self.normalize_quality(quality)
        normalized_elements = self._normalize_elements(elements or [])

        from app.services.image_gen import image_service

        detail = image_service.assess_scene_detail(scene_description, normalized_elements)
        base_result: Dict[str, Any] = {
            "path": None,
            "model_used": None,
            "prompt": prompt[:500],
            "quality": normalized_quality,
            "status": "failed",
            "reason": "all_models_failed",
            "detail_reason": detail.get("reason"),
            "word_count": detail.get("word_count"),
            "concrete_term_count": detail.get("concrete_term_count"),
            "rich_element_count": detail.get("rich_element_count"),
        }
        if not detail["is_sufficient"]:
            logger.info(
                "Skipping scene generation for %s; insufficient detail (%s, words=%s, concrete_terms=%s, rich_elements=%s)",
                prefix,
                detail["reason"],
                detail["word_count"],
                detail["concrete_term_count"],
                detail["rich_element_count"],
            )
            base_result.update({
                "status": "skipped",
                "reason": "insufficient_detail",
            })
            return base_result

        image_bytes, source = await self.generate_scene_with_source(prompt, quality=normalized_quality)
        if image_bytes:
            base_result.update({
                "path": self._save_image(image_bytes, prefix),
                "model_used": source or "ai_generated",
                "status": "generated",
                "reason": "generated",
            })
            return base_result

        from app.models.schemas import SceneElement

        fallback_elements = []
        for element in normalized_elements:
            try:
                fallback_elements.append(SceneElement(**element))
            except Exception:
                continue

        fallback_bytes = image_service.generate_pil_scene_fallback(
            scene_description=scene_description,
            elements=fallback_elements,
        )
        if fallback_bytes:
            base_result.update({
                "path": self._save_image(fallback_bytes, prefix),
                "model_used": "pil_fallback",
                "status": "generated",
                "reason": "generated",
            })
            return base_result

        return base_result

    # ------------------------------------------------------------------
    # Per-report / per-case helpers
    # ------------------------------------------------------------------

    async def generate_report_scene(
        self,
        report_id: str,
        scene_description: str,
        elements: list,
        quality: str = "standard",
    ) -> Optional[str]:
        """Generate a scene image for a single witness report."""
        result = await self.generate_report_scene_with_fallback(
            report_id,
            scene_description,
            elements,
            quality=quality,
        )
        return result.get("path")

    async def generate_report_scene_with_fallback(
        self,
        report_id: str,
        scene_description: str,
        elements: list,
        quality: str = "standard",
    ) -> Dict[str, Any]:
        prompt = self._report_prompt(scene_description, elements)
        return await self.generate_scene_with_fallback(
            prompt=prompt,
            scene_description=scene_description,
            elements=elements,
            quality=quality,
            prefix=f"report_{report_id}",
        )

    async def generate_case_scene(
        self,
        case_id: str,
        case_summary: str,
        scene_description: str,
        elements: Optional[List[Any]] = None,
        quality: str = "standard",
    ) -> Optional[str]:
        """Generate composite scene image from all witness accounts for a case."""
        result = await self.generate_case_scene_with_fallback(
            case_id,
            case_summary,
            scene_description,
            elements=elements,
            quality=quality,
        )
        return result.get("path")

    async def generate_case_scene_with_fallback(
        self,
        case_id: str,
        case_summary: str,
        scene_description: str,
        elements: Optional[List[Any]] = None,
        quality: str = "standard",
    ) -> Dict[str, Any]:
        prompt = self._case_prompt(case_summary, scene_description, elements=elements)
        return await self.generate_scene_with_fallback(
            prompt=prompt,
            scene_description=scene_description,
            elements=elements or [],
            quality=quality,
            prefix=f"case_{case_id}",
        )

    async def regenerate_scene(
        self,
        entity_type: str,
        entity_id: str,
        description: str,
        quality: str = "standard",
    ) -> Optional[str]:
        """Force-regenerate a scene image."""
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
            "Do NOT invent generic roads, parking lots, storefronts, or extra vehicles that were not described. "
            "If some background context is unknown, keep the unseen surroundings understated instead of filling them with placeholder scenery. "
            "Continuously incorporate new witness details as concrete scene objects, positions, and actions. "
            "Do NOT include any graphic violence, blood, or disturbing content. "
            f"Scene description: {description} "
            "Show physically plausible placement of vehicles, people, environment, and evidence."
        )

    def _get_model_order(self, quality: str) -> list[str]:
        normalized_quality = self.normalize_quality(quality)
        if normalized_quality == "ultra":
            return [
                "imagen-4.0-ultra-generate-001",
                "imagen-4.0-generate-001",
                "imagen-4.0-fast-generate-001",
            ]
        if normalized_quality == "standard":
            return [
                "imagen-4.0-generate-001",
                "imagen-4.0-fast-generate-001",
                "imagen-4.0-ultra-generate-001",
            ]
        return [
            "imagen-4.0-fast-generate-001",
            "imagen-4.0-generate-001",
            "imagen-4.0-ultra-generate-001",
        ]

    def _reset_daily_if_needed(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._last_reset != today:
            self._daily_counts = {}
            self._last_reset = today


# Global singleton
imagen_service = ImagenService()
