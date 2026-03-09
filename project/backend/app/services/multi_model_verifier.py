"""
Multi-model verification service for cross-verifying critical extractions.

Sends the same prompt to multiple models (Gemini and Gemma) and compares
results for consistency. Flags discrepancies for high-stakes decisions.
"""
import logging
import asyncio
import json
from typing import Optional, Dict, Any, List, Tuple, Type
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.config import settings
from app.services.model_selector import (
    model_selector,
    quota_tracker,
    CHAT_MODELS,
    LIGHTWEIGHT_MODELS,
)

logger = logging.getLogger(__name__)


class VerificationResult(str, Enum):
    """Result of multi-model verification."""
    CONSISTENT = "consistent"       # Models agree
    DISCREPANCY = "discrepancy"     # Models disagree
    PARTIAL = "partial"             # Partial agreement
    SINGLE_MODEL = "single_model"   # Only one model responded (fallback)
    ERROR = "error"                 # Verification failed


@dataclass
class ModelResponse:
    """Response from a single model."""
    model_name: str
    response_text: str
    parsed_response: Optional[Any] = None
    success: bool = True
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class VerificationOutput:
    """Output of multi-model verification."""
    result: VerificationResult
    primary_response: Optional[ModelResponse] = None
    secondary_response: Optional[ModelResponse] = None
    discrepancies: List[Dict[str, Any]] = field(default_factory=list)
    confidence_score: float = 1.0  # 0.0 to 1.0
    used_verification: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result.value,
            "primary_model": self.primary_response.model_name if self.primary_response else None,
            "secondary_model": self.secondary_response.model_name if self.secondary_response else None,
            "discrepancies": self.discrepancies,
            "confidence_score": self.confidence_score,
            "used_verification": self.used_verification,
            "metadata": self.metadata,
        }


class MultiModelVerifier:
    """
    Cross-verifies critical extractions using multiple AI models.
    
    Uses Gemini (primary) and Gemma (secondary) to verify critical decisions.
    Compares structured outputs and flags any discrepancies.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.client = None
        self._initialize()
        
        # Statistics
        self._stats = {
            "total_verifications": 0,
            "consistent": 0,
            "discrepancies": 0,
            "single_model_fallback": 0,
            "errors": 0,
        }

    def _initialize(self):
        """Initialize the Gemini client."""
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                logger.info("MultiModelVerifier initialized")
        except Exception as e:
            logger.error(f"Failed to initialize MultiModelVerifier: {e}")

    def set_enabled(self, enabled: bool):
        """Toggle verification on/off."""
        self.enabled = enabled
        logger.info(f"Multi-model verification {'enabled' if enabled else 'disabled'}")

    async def verify_extraction(
        self,
        prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        primary_model: Optional[str] = None,
        secondary_model: Optional[str] = None,
        temperature: float = 0.1,
        comparison_fields: Optional[List[str]] = None,
    ) -> VerificationOutput:
        """
        Cross-verify an extraction by sending to both Gemini and Gemma.
        
        Args:
            prompt: The prompt to send to both models
            response_schema: Pydantic model for structured JSON output
            primary_model: Primary model to use (default: best chat model)
            secondary_model: Secondary model to use (default: best lightweight model)
            temperature: Model temperature
            comparison_fields: Specific fields to compare (if None, compares all)
            
        Returns:
            VerificationOutput with results, discrepancies, and confidence
        """
        self._stats["total_verifications"] += 1

        if not self.enabled or not self.client:
            # Verification disabled - just use primary model
            return await self._single_model_response(
                prompt, response_schema, primary_model, temperature
            )

        # Select models
        primary = primary_model or await model_selector.get_best_model_for_chat()
        secondary = secondary_model or await model_selector.get_best_model_for_lightweight()

        # Check if we have quota for both models
        can_primary = await quota_tracker.can_make_request(primary)
        can_secondary = await quota_tracker.can_make_request(secondary)

        if not can_primary and not can_secondary:
            self._stats["errors"] += 1
            return VerificationOutput(
                result=VerificationResult.ERROR,
                metadata={"error": "Both models quota exhausted"},
            )

        if not can_secondary:
            # Fall back to single model
            self._stats["single_model_fallback"] += 1
            return await self._single_model_response(
                prompt, response_schema, primary, temperature
            )

        # Query both models concurrently
        primary_task = self._query_model(
            primary, prompt, response_schema, temperature
        )
        secondary_task = self._query_model(
            secondary, prompt, response_schema, temperature
        )

        try:
            primary_resp, secondary_resp = await asyncio.gather(
                primary_task, secondary_task, return_exceptions=True
            )
        except Exception as e:
            logger.error(f"Verification gather failed: {e}")
            self._stats["errors"] += 1
            return await self._single_model_response(
                prompt, response_schema, primary, temperature
            )

        # Handle exceptions from gather
        if isinstance(primary_resp, Exception):
            logger.warning(f"Primary model failed: {primary_resp}")
            if isinstance(secondary_resp, Exception):
                self._stats["errors"] += 1
                return VerificationOutput(
                    result=VerificationResult.ERROR,
                    metadata={"error": "Both models failed"},
                )
            self._stats["single_model_fallback"] += 1
            return VerificationOutput(
                result=VerificationResult.SINGLE_MODEL,
                primary_response=secondary_resp,
                confidence_score=0.7,
                used_verification=False,
            )

        if isinstance(secondary_resp, Exception):
            logger.warning(f"Secondary model failed: {secondary_resp}")
            self._stats["single_model_fallback"] += 1
            return VerificationOutput(
                result=VerificationResult.SINGLE_MODEL,
                primary_response=primary_resp,
                confidence_score=0.7,
                used_verification=False,
            )

        # Compare responses
        return self._compare_responses(
            primary_resp, secondary_resp, comparison_fields
        )

    async def _query_model(
        self,
        model_name: str,
        prompt: str,
        response_schema: Optional[Type[BaseModel]],
        temperature: float,
    ) -> ModelResponse:
        """Query a single model and return the response."""
        import time
        start = time.time()

        try:
            config_kwargs: Dict[str, Any] = {"temperature": temperature}
            if response_schema:
                config_kwargs["response_mime_type"] = "application/json"
                config_kwargs["response_json_schema"] = response_schema

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )

            # Record quota usage
            await quota_tracker.record_request(model_name)

            latency_ms = (time.time() - start) * 1000
            response_text = response.text

            # Parse if schema provided
            parsed = None
            if response_schema and response_text:
                try:
                    parsed = response_schema.model_validate_json(response_text)
                except Exception as parse_err:
                    logger.warning(f"Failed to parse {model_name} response: {parse_err}")

            return ModelResponse(
                model_name=model_name,
                response_text=response_text,
                parsed_response=parsed,
                success=True,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            logger.error(f"Model {model_name} query failed: {e}")
            return ModelResponse(
                model_name=model_name,
                response_text="",
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )

    async def _single_model_response(
        self,
        prompt: str,
        response_schema: Optional[Type[BaseModel]],
        model: Optional[str],
        temperature: float,
    ) -> VerificationOutput:
        """Fall back to single model response when verification is disabled."""
        model_name = model or await model_selector.get_best_model_for_chat()
        response = await self._query_model(model_name, prompt, response_schema, temperature)

        if not response.success:
            return VerificationOutput(
                result=VerificationResult.ERROR,
                metadata={"error": response.error},
            )

        return VerificationOutput(
            result=VerificationResult.SINGLE_MODEL,
            primary_response=response,
            confidence_score=0.8,  # Lower confidence without verification
            used_verification=False,
        )

    def _compare_responses(
        self,
        primary: ModelResponse,
        secondary: ModelResponse,
        comparison_fields: Optional[List[str]] = None,
    ) -> VerificationOutput:
        """Compare two model responses and identify discrepancies."""
        discrepancies: List[Dict[str, Any]] = []

        # If both have parsed responses, compare structured data
        if primary.parsed_response and secondary.parsed_response:
            primary_dict = (
                primary.parsed_response.model_dump()
                if hasattr(primary.parsed_response, "model_dump")
                else dict(primary.parsed_response)
            )
            secondary_dict = (
                secondary.parsed_response.model_dump()
                if hasattr(secondary.parsed_response, "model_dump")
                else dict(secondary.parsed_response)
            )

            fields_to_check = comparison_fields or list(primary_dict.keys())

            for field in fields_to_check:
                p_val = primary_dict.get(field)
                s_val = secondary_dict.get(field)

                if not self._values_match(p_val, s_val):
                    discrepancies.append({
                        "field": field,
                        "primary_value": p_val,
                        "secondary_value": s_val,
                    })

        else:
            # Compare raw text similarity
            similarity = self._text_similarity(
                primary.response_text, secondary.response_text
            )
            if similarity < 0.8:
                discrepancies.append({
                    "field": "_raw_response",
                    "primary_value": primary.response_text[:200],
                    "secondary_value": secondary.response_text[:200],
                    "similarity": similarity,
                })

        # Calculate confidence and determine result
        if not discrepancies:
            self._stats["consistent"] += 1
            return VerificationOutput(
                result=VerificationResult.CONSISTENT,
                primary_response=primary,
                secondary_response=secondary,
                confidence_score=1.0,
                used_verification=True,
                metadata={
                    "primary_latency_ms": primary.latency_ms,
                    "secondary_latency_ms": secondary.latency_ms,
                },
            )

        # Has discrepancies
        self._stats["discrepancies"] += 1
        total_fields = len(comparison_fields) if comparison_fields else 5
        confidence = max(0.3, 1.0 - (len(discrepancies) / total_fields))

        result_type = (
            VerificationResult.PARTIAL
            if len(discrepancies) < total_fields / 2
            else VerificationResult.DISCREPANCY
        )

        return VerificationOutput(
            result=result_type,
            primary_response=primary,
            secondary_response=secondary,
            discrepancies=discrepancies,
            confidence_score=confidence,
            used_verification=True,
            metadata={
                "primary_latency_ms": primary.latency_ms,
                "secondary_latency_ms": secondary.latency_ms,
                "total_discrepancies": len(discrepancies),
            },
        )

    def _values_match(self, val1: Any, val2: Any) -> bool:
        """Check if two values match, with fuzzy string comparison."""
        if val1 == val2:
            return True

        # Handle None cases
        if val1 is None or val2 is None:
            return False

        # String comparison (case-insensitive, trimmed)
        if isinstance(val1, str) and isinstance(val2, str):
            return val1.strip().lower() == val2.strip().lower()

        # List comparison (order-insensitive)
        if isinstance(val1, list) and isinstance(val2, list):
            return set(str(v).lower() for v in val1) == set(str(v).lower() for v in val2)

        # Numeric comparison with tolerance
        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            return abs(val1 - val2) < 0.01 * max(abs(val1), abs(val2), 1)

        return False

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity (Jaccard-like)."""
        if not text1 or not text2:
            return 0.0

        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def get_stats(self) -> Dict[str, Any]:
        """Return verification statistics."""
        return {
            **self._stats,
            "enabled": self.enabled,
            "discrepancy_rate": (
                self._stats["discrepancies"] / max(1, self._stats["total_verifications"])
            ),
        }


# Global instance
multi_model_verifier = MultiModelVerifier(enabled=True)
