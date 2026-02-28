"""
Translation Service using Gemini for real-time interview translation.
Detects witness language and translates between languages.
"""

import logging
import asyncio
from typing import Optional, Tuple, Dict, Any
from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

# Supported languages with their codes
SUPPORTED_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "vi": "Vietnamese",
    "ko": "Korean",
    "tl": "Tagalog",
    "ar": "Arabic",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "hi": "Hindi",
    "it": "Italian",
    "pl": "Polish",
    "uk": "Ukrainian",
    "fa": "Persian",
    "th": "Thai",
    "he": "Hebrew",
}


class TranslationService:
    """
    Translation service using Gemini for detecting and translating languages.
    """

    def __init__(self):
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialize the Gemini client."""
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                logger.info("Translation service initialized")
            else:
                logger.warning("GOOGLE_API_KEY not set, translation service not initialized")
        except Exception as e:
            logger.error(f"Failed to initialize translation service: {e}")
            self.client = None

    async def detect_language(self, text: str) -> Tuple[str, float]:
        """
        Detect the language of the given text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Tuple of (language_code, confidence)
        """
        if not self.client or not text.strip():
            return ("en", 1.0)

        try:
            prompt = f"""Detect the language of this text and respond with ONLY a JSON object.
Do not include any other text or explanation.

Text: "{text}"

Response format:
{{"language_code": "xx", "language_name": "Language Name", "confidence": 0.95}}

Use ISO 639-1 language codes (en, es, zh, vi, ko, etc.)."""

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=settings.gemini_lite_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=100,
                )
            )

            import json
            result_text = response.text.strip()
            # Handle markdown code blocks
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()
            
            result = json.loads(result_text)
            lang_code = result.get("language_code", "en")
            confidence = result.get("confidence", 0.5)
            
            logger.debug(f"Detected language: {lang_code} (confidence: {confidence})")
            return (lang_code, confidence)

        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
            return ("en", 0.5)

    async def translate(
        self,
        text: str,
        target_language: str,
        source_language: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Translate text to target language.
        
        Args:
            text: Text to translate
            target_language: Target language code (e.g., 'es' for Spanish)
            source_language: Source language code (auto-detected if not provided)
            
        Returns:
            Tuple of (translated_text, detected_source_language)
        """
        if not self.client:
            return (text, source_language or "en")

        if not text.strip():
            return (text, source_language or "en")

        # Detect source language if not provided
        if not source_language:
            source_language, _ = await self.detect_language(text)

        # Don't translate if source and target are the same
        if source_language == target_language:
            return (text, source_language)

        try:
            target_name = SUPPORTED_LANGUAGES.get(target_language, target_language)
            source_name = SUPPORTED_LANGUAGES.get(source_language, source_language)

            prompt = f"""Translate the following text from {source_name} to {target_name}.
Preserve the meaning, tone, and any specific terminology.
Return ONLY the translated text, nothing else.

Text to translate:
{text}"""

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=settings.gemini_lite_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                )
            )

            translated = response.text.strip()
            logger.debug(f"Translated from {source_language} to {target_language}: {text[:50]}... -> {translated[:50]}...")
            return (translated, source_language)

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return (text, source_language)

    async def translate_for_witness(
        self,
        agent_response: str,
        witness_language: str,
    ) -> Dict[str, Any]:
        """
        Translate an AI agent response for a witness in their language.
        
        Args:
            agent_response: The AI's response in English
            witness_language: The witness's preferred language code
            
        Returns:
            Dict with original and translated text
        """
        if witness_language == "en" or not witness_language:
            return {
                "original": agent_response,
                "translated": agent_response,
                "source_language": "en",
                "target_language": "en",
            }

        translated, source_lang = await self.translate(
            text=agent_response,
            target_language=witness_language,
            source_language="en",
        )

        return {
            "original": agent_response,
            "translated": translated,
            "source_language": source_lang,
            "target_language": witness_language,
        }

    async def process_witness_input(
        self,
        witness_text: str,
        expected_language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process witness input: detect language, translate to English if needed.
        
        Args:
            witness_text: The witness's statement
            expected_language: Expected language (if known)
            
        Returns:
            Dict with original text, translated text (to English), and detected language
        """
        # Detect language
        detected_lang, confidence = await self.detect_language(witness_text)
        
        # Use expected language if confidence is low
        if confidence < 0.7 and expected_language:
            detected_lang = expected_language

        # Translate to English for processing
        if detected_lang != "en":
            english_text, _ = await self.translate(
                text=witness_text,
                target_language="en",
                source_language=detected_lang,
            )
        else:
            english_text = witness_text

        return {
            "original_text": witness_text,
            "english_text": english_text,
            "detected_language": detected_lang,
            "language_confidence": confidence,
        }

    def get_supported_languages(self) -> Dict[str, str]:
        """Get dictionary of supported language codes and names."""
        return SUPPORTED_LANGUAGES.copy()


# Global singleton instance
translation_service = TranslationService()
