"""Text-to-Speech service with Native Audio Live API primary and TTS fallback."""
import logging
import asyncio
import base64
import io
import re
import wave
from typing import Optional, List
from datetime import datetime, timezone

from google import genai
from google.genai import types

from app.config import settings
from app.services.model_selector import MODEL_QUOTAS, is_retryable_model_error

logger = logging.getLogger(__name__)


# Available voice presets for Gemini TTS
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
    """Service for generating text-to-speech audio using Gemini models."""

    PRIMARY_MODEL = "gemini-2.5-flash-native-audio-latest"
    NATIVE_FALLBACK_MODELS = [
        "gemini-2.5-flash-native-audio-preview-12-2025",
        "gemini-2.5-flash-native-audio-preview-09-2025",
    ]
    FALLBACK_MODELS = ["gemini-2.5-flash-preview-tts"]
    MODEL_ALIASES = {
        "gemini-2.5-flash-exp-native-audio-thinking": PRIMARY_MODEL,
    }

    def __init__(self):
        self.client = None
        self._daily_count: dict[str, int] = {}
        self._minute_requests: dict[str, List[datetime]] = {}
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
            self._daily_count = {}
            self._minute_requests = {}
            self._last_reset_date = today
            logger.info("TTS daily counter reset for %s", today)

    def _prune_minute_window(self, model: str):
        """Remove requests older than 60 seconds from minute tracking."""
        cutoff = datetime.now(timezone.utc).timestamp() - 60
        requests = self._minute_requests.get(model, [])
        self._minute_requests[model] = [
            ts for ts in requests
            if ts.timestamp() > cutoff
        ]

    @classmethod
    def _normalize_model_alias(cls, model: Optional[str]) -> Optional[str]:
        """Map deprecated model IDs to currently supported ones."""
        if not model:
            return model
        return cls.MODEL_ALIASES.get(model, model)

    def _get_model_chain(self) -> List[str]:
        """Build deduplicated model chain for TTS generation."""
        chain = [
            settings.live_model or self.PRIMARY_MODEL,
            settings.tts_model,
            self.PRIMARY_MODEL,
            *self.NATIVE_FALLBACK_MODELS,
            *self.FALLBACK_MODELS,
        ]
        deduped = []
        seen = set()
        for model in chain:
            model = self._normalize_model_alias(model)
            if not model or model in seen:
                continue
            seen.add(model)
            deduped.append(model)
        return deduped or [self.PRIMARY_MODEL]

    def _get_limits(self, model: str) -> tuple[int, int]:
        """Return rpm/rpd limits for model (0 = unlimited)."""
        quota = MODEL_QUOTAS.get(model, {})
        rpm_limit = int(quota.get("rpm", 3))
        rpd_limit = int(quota.get("rpd", 10))
        return rpm_limit, rpd_limit

    def _can_make_request(self, model: str) -> tuple[bool, str]:
        """Check if we can make a TTS request within rate limits."""
        self._reset_if_new_day()
        self._prune_minute_window(model)
        rpm_limit, rpd_limit = self._get_limits(model)
        daily = self._daily_count.get(model, 0)
        minute = len(self._minute_requests.get(model, []))

        if rpd_limit and daily >= rpd_limit:
            return False, f"Daily TTS quota exhausted for {model} ({rpd_limit}/day)"

        if rpm_limit and minute >= rpm_limit:
            return False, f"TTS rate limit reached for {model} ({rpm_limit}/minute)"

        return True, "OK"

    def _record_request(self, model: str):
        """Record a successful TTS request for rate limiting."""
        self._daily_count[model] = self._daily_count.get(model, 0) + 1
        self._minute_requests.setdefault(model, []).append(datetime.now(timezone.utc))

    def _mark_model_exhausted(self, model: str):
        """Mark model daily quota as exhausted when API returns quota errors."""
        _, rpd_limit = self._get_limits(model)
        if rpd_limit:
            self._daily_count[model] = rpd_limit

    @staticmethod
    def _is_native_audio_model(model: str) -> bool:
        """Return True when model requires bidi Live API for audio generation."""
        return "native-audio" in (model or "").lower()

    @staticmethod
    def _pcm_sample_rate(mime_type: Optional[str]) -> int:
        """Extract sample rate from mime_type like 'audio/pcm;rate=24000'."""
        if not mime_type:
            return 24000
        match = re.search(r"rate=(\d+)", mime_type)
        if not match:
            return 24000
        try:
            return max(8000, int(match.group(1)))
        except ValueError:
            return 24000

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
        """Wrap 16-bit mono PCM bytes in a WAV container for browser playback."""
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return output.getvalue()

    @staticmethod
    def _extract_audio_from_generate_content(response) -> Optional[bytes]:
        """Extract first audio payload from generate_content response."""
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data and getattr(inline_data, "data", None):
                    mime_type = str(getattr(inline_data, "mime_type", "") or "")
                    if mime_type.startswith("audio/"):
                        return inline_data.data
        return None

    async def _generate_native_audio_live(
        self,
        model: str,
        text: str,
        voice: str,
    ) -> Optional[bytes]:
        """Generate audio using Gemini Native Audio via Live API."""
        config = {
            "response_modalities": ["AUDIO"],
            # Passing voice name string keeps Native Audio stable with current SDK.
            "speech_config": voice,
        }
        audio_chunks: List[bytes] = []
        mime_type: Optional[str] = None

        async with self.client.aio.live.connect(model=model, config=config) as session:
            await session.send(text, end_of_turn=True)
            async for message in session.receive():
                server_content = getattr(message, "server_content", None)
                if not server_content:
                    continue

                model_turn = getattr(server_content, "model_turn", None)
                if model_turn and getattr(model_turn, "parts", None):
                    for part in model_turn.parts:
                        inline_data = getattr(part, "inline_data", None)
                        if inline_data and getattr(inline_data, "data", None):
                            audio_chunks.append(inline_data.data)
                            if getattr(inline_data, "mime_type", None):
                                mime_type = inline_data.mime_type

                if getattr(server_content, "turn_complete", False):
                    break

        if not audio_chunks:
            return None

        audio_data = b"".join(audio_chunks)
        if (mime_type or "").startswith("audio/pcm"):
            return self._pcm_to_wav(audio_data, self._pcm_sample_rate(mime_type))
        return audio_data

    async def _generate_preview_tts(
        self,
        model: str,
        text: str,
        voice: str,
    ) -> Optional[bytes]:
        """Generate audio with standard generate_content TTS models."""
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=model,
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
        return self._extract_audio_from_generate_content(response)

    async def generate_speech(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
    ) -> Optional[bytes]:
        """Generate speech audio from text."""
        if not self.client:
            logger.warning("TTS client not initialized")
            return None

        if not text or not text.strip():
            logger.warning("Empty text provided for TTS")
            return None

        # Truncate very long text to stay within token limits
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.info("TTS text truncated to %d characters", max_chars)

        # Validate voice
        valid_voices = [v["id"] for v in AVAILABLE_VOICES]
        if voice not in valid_voices:
            voice = DEFAULT_VOICE

        last_error: Optional[Exception] = None
        for model in self._get_model_chain():
            allowed, reason = self._can_make_request(model)
            if not allowed:
                logger.warning("TTS request blocked for %s: %s", model, reason)
                continue

            try:
                if self._is_native_audio_model(model):
                    audio_data = await self._generate_native_audio_live(model=model, text=text, voice=voice)
                else:
                    audio_data = await self._generate_preview_tts(model=model, text=text, voice=voice)

                if not audio_data:
                    logger.warning("TTS response contained no audio data for %s", model)
                    continue

                self._record_request(model)
                logger.info(
                    "Generated TTS audio with %s (%d bytes), voice=%s",
                    model,
                    len(audio_data),
                    voice,
                )
                return audio_data
            except Exception as e:
                last_error = e
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    logger.warning("TTS rate limited by API for %s: %s", model, error_str[:200])
                    self._mark_model_exhausted(model)
                    continue
                if is_retryable_model_error(e):
                    logger.warning("TTS model fallback from %s due to retryable error: %s", model, error_str[:160])
                    continue
                logger.error("TTS generation error with %s: %s", model, e)
                continue

        if last_error:
            logger.error("All TTS models failed. Last error: %s", last_error)
        return None

    async def generate_speech_base64(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
    ) -> Optional[str]:
        """Generate speech and return as base64-encoded string."""
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
        chain = self._get_model_chain()
        primary_model = chain[0]
        self._prune_minute_window(primary_model)
        rpm_limit, rpd_limit = self._get_limits(primary_model)
        rpm_used = len(self._minute_requests.get(primary_model, []))
        rpd_used = self._daily_count.get(primary_model, 0)

        per_model = {}
        available_models = []
        for model in chain:
            model = self._normalize_model_alias(model)
            self._prune_minute_window(model)
            m_rpm_limit, m_rpd_limit = self._get_limits(model)
            m_rpm_used = len(self._minute_requests.get(model, []))
            m_rpd_used = self._daily_count.get(model, 0)
            per_model[model] = {
                "rpm": {
                    "used": m_rpm_used,
                    "limit": m_rpm_limit,
                    "remaining": (max(0, m_rpm_limit - m_rpm_used) if m_rpm_limit else None),
                },
                "rpd": {
                    "used": m_rpd_used,
                    "limit": m_rpd_limit,
                    "remaining": (max(0, m_rpd_limit - m_rpd_used) if m_rpd_limit else None),
                },
            }
            allowed, _ = self._can_make_request(model)
            if allowed:
                available_models.append(model)

        return {
            "model": primary_model,
            "model_chain": chain,
            "available_models": available_models,
            "rpm": {
                "used": rpm_used,
                "limit": rpm_limit,
                "remaining": (max(0, rpm_limit - rpm_used) if rpm_limit else None),
            },
            "rpd": {
                "used": rpd_used,
                "limit": rpd_limit,
                "remaining": (max(0, rpd_limit - rpd_used) if rpd_limit else None),
            },
            "per_model": per_model,
            "available": self.client is not None and len(available_models) > 0,
        }

    def health_check(self) -> bool:
        """Check if TTS service is available."""
        return self.client is not None


# Global singleton
tts_service = TTSService()
