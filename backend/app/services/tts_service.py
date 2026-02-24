"""
Text-to-Speech service using Google Gemini 2.5 Flash Preview TTS.
Provides audio output for AI responses to improve accessibility.

Rate limits: 3 RPM, 10K TPM, 10 RPD
"""
import logging
import asyncio
import base64
from typing import Optional, List
from datetime import datetime, timezone

from google import genai
from google.genai import types

from app.config import settings
from app.services.model_selector import model_selector, quota_tracker

logger = logging.getLogger(__name__)


# Available voice presets for Gemini TTS
# These are the voice options available in the Gemini 2.5 Flash TTS model
AVAILABLE_VOICES = [
    {"id": "Puck", "name": "Puck", "description": "Warm and friendly voice"},
    {"id": "Charon", "name": "Charon", "description": "Deep and authoritative voice"},
    {"id": "Kore", "name": "Kore", "description": "Clear and professional voice"},
    {"id": "Fenrir", "name": "Fenrir", "description": "Strong and confident voice"},
    {"id": "Aoede", "name": "Aoede", "description": "Melodic and pleasant voice"},
    {"id": "Leda", "name": "Leda", "description": "Gentle and soothing voice"},
    {"id": "Orus", "name": "Orus", "description": "Natural and conversational voice"},
    {"id": "Zephyr", "name": "Zephyr", "description": "Light and airy voice"},
]

DEFAULT_VOICE = "Puck"


class TTSService:
    """Service for generating text-to-speech audio using Gemini TTS."""

    MODEL = "gemini-2.5-flash-preview-tts"

    def __init__(self):
        self.client = None
        self._daily_count = 0
        self._minute_requests: List[datetime] = []
        self._last_reset_date = ""
        self._initialize()

    def _initialize(self):
        if settings.google_api_key:
            self.client = genai.Client(api_key=settings.google_api_key)
            logger.info("TTSService initialized with Google API key")
        else:
            logger.warning("TTSService: no Google API key, TTS disabled")

    def _reset_if_new_day(self):
        """Reset daily counter at midnight UTC."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._daily_count = 0
            self._last_reset_date = today
            logger.info("TTS daily counter reset for %s", today)

    def _prune_minute_window(self):
        """Remove requests older than 60 seconds from minute tracking."""
        cutoff = datetime.now(timezone.utc).timestamp() - 60
        self._minute_requests = [
            ts for ts in self._minute_requests
            if ts.timestamp() > cutoff
        ]

    def _can_make_request(self) -> tuple[bool, str]:
        """Check if we can make a TTS request within rate limits.
        
        Returns:
            Tuple of (allowed, reason)
        """
        self._reset_if_new_day()
        self._prune_minute_window()

        # Check RPD (10 requests per day)
        if self._daily_count >= 10:
            return False, "Daily TTS quota exhausted (10/day)"

        # Check RPM (3 requests per minute)
        if len(self._minute_requests) >= 3:
            return False, "TTS rate limit reached (3/minute), please wait"

        return True, "OK"

    def _record_request(self):
        """Record a successful TTS request for rate limiting."""
        self._daily_count += 1
        self._minute_requests.append(datetime.now(timezone.utc))

    async def generate_speech(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
    ) -> Optional[bytes]:
        """Generate speech audio from text.

        Args:
            text: The text to convert to speech.
            voice: Voice preset to use (default: Puck).

        Returns:
            WAV audio bytes, or None if generation failed.
        """
        if not self.client:
            logger.warning("TTS client not initialized")
            return None

        if not text or not text.strip():
            logger.warning("Empty text provided for TTS")
            return None

        # Truncate very long text to stay within token limits
        # Estimate ~4 chars per token, 10K TPM limit
        max_chars = 8000  # Leave buffer for response tokens
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.info("TTS text truncated to %d characters", max_chars)

        # Check rate limits
        allowed, reason = self._can_make_request()
        if not allowed:
            logger.warning("TTS request blocked: %s", reason)
            return None

        # Validate voice
        valid_voices = [v["id"] for v in AVAILABLE_VOICES]
        if voice not in valid_voices:
            voice = DEFAULT_VOICE

        try:
            # Generate speech using Gemini TTS
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice,
                            )
                        )
                    ),
                ),
            )

            self._record_request()

            # Extract audio data from response
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                        audio_data = part.inline_data.data
                        logger.info(
                            "Generated TTS audio (%d bytes) with voice '%s' (%d/10 daily)",
                            len(audio_data) if audio_data else 0,
                            voice,
                            self._daily_count,
                        )
                        return audio_data

            logger.warning("TTS response contained no audio data")
            return None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                logger.warning("TTS rate limited by API: %s", error_str[:200])
                # Mark as exhausted
                self._daily_count = 10
            else:
                logger.error("TTS generation error: %s", e)
            return None

    async def generate_speech_base64(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
    ) -> Optional[str]:
        """Generate speech and return as base64-encoded string.

        Args:
            text: The text to convert to speech.
            voice: Voice preset to use.

        Returns:
            Base64-encoded audio string, or None if generation failed.
        """
        audio_bytes = await self.generate_speech(text, voice)
        if audio_bytes:
            return base64.b64encode(audio_bytes).decode("utf-8")
        return None

    def get_available_voices(self) -> List[dict]:
        """Return list of available voice options."""
        return AVAILABLE_VOICES

    def get_quota_status(self) -> dict:
        """Return current TTS quota status."""
        self._reset_if_new_day()
        self._prune_minute_window()

        return {
            "model": self.MODEL,
            "rpm": {
                "used": len(self._minute_requests),
                "limit": 3,
                "remaining": max(0, 3 - len(self._minute_requests)),
            },
            "rpd": {
                "used": self._daily_count,
                "limit": 10,
                "remaining": max(0, 10 - self._daily_count),
            },
            "available": self.client is not None and self._daily_count < 10,
        }

    def health_check(self) -> bool:
        """Check if TTS service is available."""
        return self.client is not None


# Global singleton
tts_service = TTSService()
