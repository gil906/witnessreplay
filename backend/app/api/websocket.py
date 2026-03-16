import time
import logging
import json
import re
import asyncio
import base64
from typing import Optional
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
import uuid

from app.models.schemas import (
    WebSocketMessage,
    WitnessStatement,
    SceneVersion,
    SceneElement,
)
from app.services.firestore import firestore_service
from app.services.storage import storage_service
from app.services.image_gen import image_service
from app.services.model_selector import generate_content_with_fallback, model_selector, quota_tracker
from app.services.imagen_service import imagen_service
from app.services.embedding_service import embedding_service
from app.services.translation_service import translation_service
from app.services.case_manager import case_manager
from app.services.api_key_manager import get_genai_client
from app.services.tts_service import tts_service
from app.agents.scene_agent import get_agent, remove_agent
from app.config import settings

logger = logging.getLogger(__name__)

active_connections: set[str] = set()
active_handlers: dict[str, "WebSocketHandler"] = {}


async def shutdown_active_session_handler(session_id: str, reason: str = "client_tab_close") -> bool:
    """Best-effort shutdown of the active websocket handler for a session."""
    handler = active_handlers.get(session_id)
    if not handler:
        return False
    await handler.force_shutdown(reason=reason)
    return True


class WebSocketHandler:
    """Handles WebSocket connections for real-time voice streaming."""
    
    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.agent = get_agent(session_id)
        self.is_connected = False
        self.version_counter = 0
        self.witness_language = "en"  # Current witness's preferred language
        self.last_activity = None
        self._message_times = []
        self._max_messages_per_second = 10
        self.connected_at = datetime.now(timezone.utc)
        self.call_status = "connecting"
        self.is_recording = False
        self.is_speaking = False
        self._last_voice_hint_state = None
        self._background_tasks: set[asyncio.Task] = set()
        self._active_message_tasks: set[asyncio.Task] = set()
        self._last_auto_transcript_text = ""
        self._last_auto_transcript_at = 0.0
        self._shutdown_reason = ""
        self._disconnect_complete = False

    def _elapsed_seconds(self) -> int:
        """Seconds elapsed since websocket connect."""
        return max(0, int((datetime.now(timezone.utc) - self.connected_at).total_seconds()))

    async def _get_statement_count(self, session=None) -> int:
        """Get current statement count for call state/metrics."""
        current_session = session or await firestore_service.get_session(self.session_id)
        if not current_session:
            return 0
        return len(getattr(current_session, "witness_statements", []) or [])

    async def _build_call_state_payload(self, status: Optional[str] = None, session=None) -> dict:
        """Build current call-state payload."""
        return {
            "status": status or self.call_status,
            "is_recording": self.is_recording,
            "is_speaking": self.is_speaking,
            "statement_count": await self._get_statement_count(session=session),
            "elapsed_sec": self._elapsed_seconds(),
        }

    async def _send_call_state(self, status: Optional[str] = None, session=None):
        """Emit call_state message."""
        payload = await self._build_call_state_payload(status=status, session=session)
        await self.send_message("call_state", payload)

    def _get_session_voice_preferences(self, session=None) -> dict:
        """Read lightweight voice preferences stored in session metadata."""
        metadata = dict(getattr(session, "metadata", {}) or {})
        raw_preferences = metadata.get("voice_preferences") if isinstance(metadata.get("voice_preferences"), dict) else {}
        available_voices = {voice["id"] for voice in tts_service.get_available_voices()}
        selected_voice = raw_preferences.get("voice")
        voice = selected_voice if isinstance(selected_voice, str) and selected_voice in available_voices else "Charon"
        return {
            "tts_enabled": raw_preferences.get("tts_enabled") is not False,
            "voice": voice,
        }

    def _agent_tts_mode(self, session=None) -> Optional[str]:
        """Return the playback mode that should be used for agent speech."""
        preferences = self._get_session_voice_preferences(session=session)
        if not preferences.get("tts_enabled"):
            return None
        if not self.is_connected or not tts_service.health_check():
            return None
        return "native_stream"

    async def _build_call_metrics_payload(self, model_availability_count: int = 0) -> dict:
        """Build periodic call metrics payload."""
        return {
            "elapsed_sec": self._elapsed_seconds(),
            "statement_count": await self._get_statement_count(),
            "model_availability_count": model_availability_count,
        }

    async def _send_voice_hint(self, state: str, message: str, *, force: bool = False):
        """Emit voice_hint message when state changes."""
        if not force and self._last_voice_hint_state == state:
            return
        self._last_voice_hint_state = state
        await self.send_message("voice_hint", {"state": state, "message": message})

    async def _set_speaking(self, speaking: bool, *, emit_ready_hint: bool = True):
        """Update speaking state and emit voice hints/call state."""
        previous = self.is_speaking
        self.is_speaking = speaking
        if previous == speaking:
            return

        if speaking:
            await self._send_voice_hint("agent_speaking", "Agent is speaking now.")
        elif emit_ready_hint:
            await self._send_voice_hint("ready_to_talk", "You're ready to speak.")
        await self._send_call_state()

    async def _set_status(self, status_value: str, message: str, *, emit_ready_hint: bool = True):
        """Send status updates with call_state sync."""
        self.call_status = status_value
        await self.send_message("status", {"status": status_value, "message": message})
        await self._send_call_state(status=status_value)
        if status_value == "ready" and not self.is_speaking and emit_ready_hint:
            await self._send_voice_hint("ready_to_talk", "You're ready to speak.")
    
    async def connect(self):
        """Accept the WebSocket connection."""
        await self.websocket.accept()
        self.is_connected = True
        self.connected_at = datetime.now(timezone.utc)
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        active_connections.add(self.session_id)
        active_handlers[self.session_id] = self
        logger.info(f"WebSocket connected for session {self.session_id}")
        
        # Send opening greeting only once per session to avoid repeated reconnect prompts.
        session = await firestore_service.get_session(self.session_id)
        if session:
            # Load witness language preference
            await self._load_witness_language(session)

            metadata = dict(session.metadata or {})
            greeting_sent = bool(metadata.get("initial_greeting_sent"))

            if len(session.witness_statements) == 0 and not greeting_sent:
                greeting = await self.agent.start_interview()
                message_id = str(uuid.uuid4())
                tts_mode = self._agent_tts_mode(session=session)
                voice_preferences = self._get_session_voice_preferences(session=session)
                await self._set_speaking(True)
                try:
                    # Translate greeting if witness language is not English
                    spoken_greeting = await self._send_translated_agent_message(
                        greeting,
                        message_id=message_id,
                        tts_mode=tts_mode,
                    )
                    if tts_mode:
                        await self._stream_agent_tts(
                            spoken_greeting,
                            context="greeting",
                            message_id=message_id,
                            voice=voice_preferences["voice"],
                        )
                finally:
                    await self._set_speaking(False)

                metadata["initial_greeting_sent"] = True
                metadata["initial_greeting_sent_at"] = datetime.utcnow().isoformat()
                session.metadata = metadata
                try:
                    await firestore_service.update_session(session)
                except Exception as update_error:
                    logger.debug("Failed to persist greeting metadata for %s: %s", self.session_id, update_error)

                await self._set_status("ready", "Ready to listen")
            elif len(session.witness_statements) == 0:
                await self._set_status("ready", "Waiting for witness input...")
            else:
                await self._set_status("ready", "Ready to listen")
        else:
            await self._set_status("ready", "Ready to listen")
        await self._send_call_state(session=session)
    
    async def _load_witness_language(self, session):
        """Load the active witness's preferred language."""
        if session.active_witness_id:
            for witness in session.witnesses:
                if witness.id == session.active_witness_id:
                    self.witness_language = getattr(witness, 'preferred_language', 'en')
                    logger.debug(f"Loaded witness language: {self.witness_language}")
                    return
        self.witness_language = "en"
    
    async def _send_translated_agent_message(
        self,
        text: str,
        message_id: str = None,
        tts_mode: Optional[str] = None,
        response_kind: Optional[str] = None,
    ) -> str:
        """Send an agent message, translating if necessary, and return displayed text."""
        if self.witness_language != "en":
            translation_result = await translation_service.translate_for_witness(
                agent_response=text,
                witness_language=self.witness_language,
            )
            payload = {
                "text": translation_result["translated"],
                "original_text": translation_result["original"],
                "speaker": "agent",
                "language": self.witness_language,
                "message_id": message_id or str(uuid.uuid4()),
            }
            if tts_mode:
                payload["tts_mode"] = tts_mode
            if response_kind:
                payload["response_kind"] = response_kind
            await self.send_message("text", payload)
            return translation_result["translated"]
        else:
            payload = {
                "text": text,
                "speaker": "agent",
                "message_id": message_id or str(uuid.uuid4()),
            }
            if tts_mode:
                payload["tts_mode"] = tts_mode
            if response_kind:
                payload["response_kind"] = response_kind
            await self.send_message("text", payload)
            return text
    
    async def disconnect(self):
        """Close the WebSocket connection and auto-generate report."""
        if self._disconnect_complete:
            return
        self._disconnect_complete = True
        self.is_connected = False
        await self._cancel_runtime_tasks()

        # ── Auto-generate report on disconnect ──
        # If the witness provided statements, finalize the report
        skip_disconnect_automation = self._shutdown_reason in {"tab_close", "client_tab_close", "client_close"}
        if not skip_disconnect_automation:
            try:
                session = await firestore_service.get_session(self.session_id)
                if session and len(session.witness_statements) >= 1:
                    logger.info(f"Auto-generating report for session {self.session_id} ({len(session.witness_statements)} statements)")

                    # Mark session as completed
                    session.status = "completed"

                    # Generate AI summary if not already present
                    if not session.metadata.get("ai_summary"):
                        try:
                            all_text = " ".join([s.text for s in session.witness_statements if s.text])
                            if all_text.strip():
                                model = await model_selector.get_best_model_for_task("analysis")
                                client = get_genai_client()
                                summary_prompt = (
                                    "You are a law enforcement report writer. Based on the following witness statements, "
                                    "generate a concise incident report summary. Include: what happened, when, where, "
                                    "who was involved, and any important details.\n\n"
                                    f"Witness statements:\n{all_text}\n\n"
                                    "Write a professional incident report summary (2-3 paragraphs):"
                                )
                                response = client.models.generate_content(
                                    model=model,
                                    contents=summary_prompt
                                )
                                if response and response.text:
                                    metadata = dict(session.metadata or {})
                                    metadata["ai_summary"] = response.text
                                    metadata["report_generated_at"] = datetime.utcnow().isoformat()
                                    session.metadata = metadata
                                    logger.info(f"Generated AI summary for session {self.session_id}")
                        except Exception as summary_err:
                            logger.warning(f"Failed to generate AI summary on disconnect: {summary_err}")

                    # Reconcile the case assignment using the full report before closing.
                    if session.witness_statements:
                        try:
                            case_id = await case_manager.assign_report_to_case(session)
                            session.case_id = case_id
                            logger.info(f"Reconciled session {self.session_id} to case {case_id}")
                        except Exception as case_err:
                            logger.warning(f"Failed to reconcile case on disconnect: {case_err}")

                    # Generate scene image if none exists
                    if not session.scene_versions and len(session.witness_statements) >= 2:
                        try:
                            all_text = " ".join([s.text for s in session.witness_statements if s.text])
                            scene_description = all_text[:500]  # Use first 500 chars for image prompt
                            if imagen_service and imagen_service.client:
                                img_result = await asyncio.to_thread(
                                    imagen_service.generate_scene, scene_description
                                )
                                if img_result:
                                    scene_version = SceneVersion(
                                        id=str(uuid.uuid4()),
                                        description=scene_description[:200],
                                        image_url=img_result.get("url", ""),
                                        elements=[]
                                    )
                                    session.scene_versions.append(scene_version)
                                    logger.info(f"Generated scene image for session {self.session_id}")
                        except Exception as img_err:
                            logger.warning(f"Failed to generate scene image on disconnect: {img_err}")

                    # Save everything
                    await firestore_service.update_session(session)

                    # Also update case summary if assigned
                    if session.case_id:
                        try:
                            await case_manager.generate_case_summary(session.case_id)
                        except Exception as case_sum_err:
                            logger.warning(f"Failed to update case summary: {case_sum_err}")

            except Exception as e:
                logger.error(f"Error during auto-report generation on disconnect: {e}")

        active_connections.discard(self.session_id)
        active_handlers.pop(self.session_id, None)
        remove_agent(self.session_id)
        logger.info(f"WebSocket disconnected for session {self.session_id}")

    def _track_background_task(self, coro):
        """Track cancellable background tasks tied to this socket lifecycle."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _track_message_task(self, coro):
        """Track the currently running request task so it can be cancelled on client exit."""
        task = asyncio.create_task(coro)
        self._active_message_tasks.add(task)
        task.add_done_callback(self._active_message_tasks.discard)
        return task

    async def _cancel_runtime_tasks(self):
        """Cancel socket-scoped runtime tasks."""
        if hasattr(self, '_heartbeat_task'):
            self._heartbeat_task.cancel()
        for task in list(self._background_tasks):
            task.cancel()
        for task in list(self._active_message_tasks):
            task.cancel()
        self._background_tasks.clear()
        self._active_message_tasks.clear()

    async def force_shutdown(self, reason: str = "client_tab_close"):
        """Stop all socket work immediately when the client intentionally exits."""
        self._shutdown_reason = (reason or "client_tab_close")[:80]
        self.is_connected = False
        await self._cancel_runtime_tasks()
        try:
            await self.websocket.close(code=1001, reason=self._shutdown_reason)
        except Exception:
            pass
    
    async def _heartbeat(self):
        """Send periodic heartbeat to keep connection alive."""
        while self.is_connected:
            try:
                await asyncio.sleep(25)
                if self.is_connected:
                    # Include basic model availability in heartbeat
                    models_status = await model_selector.get_all_models_status()
                    available_count = sum(1 for m in models_status if m.get("available"))
                    call_metrics = await self._build_call_metrics_payload(available_count)
                    await self.send_message("ping", {
                        "models_available": available_count,
                        "total_models": len(models_status),
                        "call_metrics": call_metrics,
                    })
                    await self.send_message("call_metrics", call_metrics)
            except Exception:
                break

    async def send_message(self, message_type: str, data: dict):
        """Send a message to the client."""
        if not self.is_connected:
            return
        
        try:
            message = WebSocketMessage(type=message_type, data=data)
            await self.websocket.send_json(message.model_dump(mode='json'))
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")
    
    async def send_streaming_chunk(
        self, 
        chunk: str, 
        is_final: bool = False, 
        message_id: str = None,
        token_info: dict = None,
        response_kind: Optional[str] = None,
        tts_mode: Optional[str] = None,
        full_text: Optional[str] = None,
    ):
        """Send a streaming text chunk to the client."""
        if not self.is_connected:
            return
        
        try:
            data = {
                "chunk": chunk,
                "is_final": is_final,
                "speaker": "agent",
                "message_id": message_id or str(uuid.uuid4())
            }
            # Include token estimation info on final chunk
            if is_final and token_info:
                data["token_info"] = token_info
            if is_final and response_kind:
                data["response_kind"] = response_kind
            if is_final and tts_mode:
                data["tts_mode"] = tts_mode
            if is_final and full_text is not None:
                data["full_text"] = full_text
            message = WebSocketMessage(type="text_stream", data=data)
            await self.websocket.send_json(message.model_dump(mode='json'))
        except Exception as e:
            logger.error(f"Error sending streaming chunk: {e}")

    async def _stream_agent_tts(
        self,
        text: str,
        *,
        context: str,
        message_id: str,
        voice: str,
    ) -> bool:
        """Stream Detective Ray audio to the client over websocket."""
        if not self.is_connected or not text or not text.strip():
            return False

        stream_started = False
        try:
            async for chunk_bytes, mime_type, sample_rate in tts_service.stream_native_audio(
                text=text,
                voice=voice,
                context=context,
            ):
                if not self.is_connected:
                    return False

                if not stream_started:
                    await self.send_message("tts_stream_start", {
                        "message_id": message_id,
                        "mime_type": mime_type,
                        "sample_rate": sample_rate,
                        "context": context,
                    })
                    stream_started = True

                await self.send_message("tts_stream_chunk", {
                    "message_id": message_id,
                    "audio_base64": base64.b64encode(chunk_bytes).decode("ascii"),
                })

            if stream_started:
                await self.send_message("tts_stream_end", {
                    "message_id": message_id,
                    "context": context,
                })
                return True
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Native TTS stream failed for session %s: %s", self.session_id, error)
            if stream_started:
                await self.send_message("tts_stream_end", {
                    "message_id": message_id,
                    "context": context,
                })
                return False

        await self.send_message("tts_stream_error", {
            "message_id": message_id,
            "text": text,
            "context": context,
        })
        return False
    
    async def handle_message(self, message: dict):
        """Handle incoming WebSocket messages."""
        if not isinstance(message, dict):
            await self.send_message("error", {"message": "Invalid message format"})
            return
        message_type = message.get("type", "")
        if not message_type or not isinstance(message_type, str) or len(message_type) > 50:
            await self.send_message("error", {"message": "Invalid message type"})
            return
        data = message.get("data", {})
        if not isinstance(data, dict):
            data = {}
        self.last_activity = datetime.now(timezone.utc)
        
        # Rate limit messages
        now = time.time()
        self._message_times = [t for t in self._message_times if now - t < 1.0]
        if len(self._message_times) >= self._max_messages_per_second:
            await self.send_message("error", {"message": "Too many messages. Please slow down.", "type": "rate_limited"})
            return
        self._message_times.append(now)
        
        try:
            
            if message_type == "audio":
                await self.handle_audio(data)
            elif message_type == "text":
                await self.handle_text(data)
            elif message_type == "correction":
                await self.handle_correction(data)
            elif message_type == "ping":
                await self.send_message("pong", {})
            elif message_type == "health_check":
                await self._send_health_status()
            elif message_type == "set_language":
                await self._handle_set_language(data)
            else:
                logger.warning(f"Unknown message type: {message_type}")
        
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            await self.send_message("error", {"message": str(e)})
    
    async def _handle_set_language(self, data: dict):
        """Handle language preference change from client."""
        language_code = data.get("language", "en")
        from app.services.translation_service import SUPPORTED_LANGUAGES
        
        if language_code not in SUPPORTED_LANGUAGES:
            await self.send_message("error", {
                "message": f"Unsupported language: {language_code}"
            })
            return
        
        self.witness_language = language_code
        logger.info(f"Session {self.session_id} language set to: {language_code}")
        
        # Update witness in session if there's an active witness
        session = await firestore_service.get_session(self.session_id)
        if session and session.active_witness_id:
            for witness in session.witnesses:
                if witness.id == session.active_witness_id:
                    witness.preferred_language = language_code
                    await firestore_service.update_session(session)
                    break
        
        await self.send_message("language_changed", {
            "language": language_code,
            "language_name": SUPPORTED_LANGUAGES[language_code]
        })
    
    async def handle_audio(self, data: dict):
        """Handle audio data from the client using Gemini for transcription."""
        try:
            audio_base64 = data.get("audio")
            audio_format = data.get("format", "webm")
            capture_mode = str(data.get("capture_mode", "manual") or "manual").lower()
            
            if not audio_base64:
                await self.send_message("error", {"message": "No audio data provided"})
                return
            
            await self._set_status("processing", "Transcribing audio...")
            
            # Use Gemini to transcribe audio
            if self.agent and self.agent.client:
                try:
                    import base64
                    audio_bytes = base64.b64decode(audio_base64)
                    audio_size_kb = len(audio_bytes) / 1024
                    logger.info(f"Received audio: {audio_size_kb:.1f}KB, format={audio_format}")
                    
                    min_audio_kb = 1.5 if capture_mode == "auto_listen" else 1.0
                    if audio_size_kb < min_audio_kb:
                        if capture_mode == "auto_listen":
                            logger.info(
                                "Ignoring tiny auto-listen audio for session %s (%.1fKB)",
                                self.session_id,
                                audio_size_kb,
                            )
                            await self._set_status("ready", "Waiting for witness input...")
                            await self.send_message("voice_hint", {
                                "state": "ready_to_talk",
                                "message": "Waiting for witness to start speaking.",
                            })
                            return

                        logger.warning(f"Audio too small ({audio_size_kb:.1f}KB) — likely empty recording")
                        await self.send_message("error", {"message": "Recording was too short. Speak, then tap the mic again when you're finished."})
                        return
                    
                    mime_map = {
                        "webm": "audio/webm",
                        "ogg": "audio/ogg",
                        "mp3": "audio/mpeg",
                        "mp4": "audio/mp4",
                        "wav": "audio/wav",
                    }
                    mime_type = mime_map.get(audio_format, "audio/webm")
                    
                    # Use quota-aware Gemini model for transcription with full fallback chain
                    from google.genai import types
                    transcription_response, transcription_model = await generate_content_with_fallback(
                        self.agent.client,
                        "transcription",
                        contents=[
                            types.Content(parts=[
                                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                                types.Part.from_text(
                                    text="Transcribe this audio exactly. Return ONLY the transcribed text, nothing else."
                                ),
                            ])
                        ],
                    )
                    logger.info("Transcription succeeded with Gemini model %s", transcription_model)

                    transcribed_text = transcription_response.text.strip() if transcription_response.text else ""
                    if self._looks_like_instructional_transcript(transcribed_text):
                        logger.warning(
                            "Discarding instruction-like transcription for session %s: %s",
                            self.session_id,
                            transcribed_text[:120],
                        )
                        cleaned_text = ""
                    else:
                        cleaned_text = self._sanitize_transcribed_text(transcribed_text)

                    if cleaned_text:
                        if capture_mode == "auto_listen" and self._is_low_signal_auto_transcript(cleaned_text):
                            logger.info(
                                "Ignoring low-signal auto-listen transcript for session %s: %s",
                                self.session_id,
                                cleaned_text[:80],
                            )
                            await self._set_status("ready", "Waiting for witness input...")
                            await self.send_message("voice_hint", {
                                "state": "ready_to_talk",
                                "message": "No clear witness speech detected yet.",
                            })
                            return

                        if capture_mode == "auto_listen" and self._is_duplicate_auto_transcript(cleaned_text):
                            logger.info(
                                "Ignoring duplicate auto-listen transcript for session %s: %s",
                                self.session_id,
                                cleaned_text[:80],
                            )
                            await self._set_status("ready", "Waiting for witness input...")
                            return

                        logger.info(f"Transcribed audio ({audio_size_kb:.1f}KB): {cleaned_text[:100]}")
                        await self.send_message("text", {
                            "text": cleaned_text,
                            "speaker": "user"
                        })
                        await self.handle_text({"text": cleaned_text})
                        return
                    else:
                        logger.warning(f"Gemini returned empty transcription for {audio_size_kb:.1f}KB audio")
                        if capture_mode == "auto_listen":
                            await self._set_status("ready", "Waiting for witness input...")
                            return

                        await self.send_message("error", {"message": "Could not understand the audio. Please try again or type your statement."})
                        await self._set_status("ready", "Ready to listen")
                        return
                        
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"Gemini audio transcription failed: {error_str}", exc_info=True)
                    
                    # Send specific error back to client
                    if "429" in error_str or "quota" in error_str.lower():
                        user_msg = "Voice transcription models are busy right now. Please try again in a moment, or type your statement instead."
                    elif "400" in error_str:
                        user_msg = f"Audio format issue. Try speaking longer. ({error_str[:80]})"
                    else:
                        user_msg = f"Transcription error: {error_str[:100]}. Try typing instead."
                    
                    await self.send_message("error", {"message": user_msg})
                    await self._set_status("ready", "Ready to listen")
                    return
            
            await self.send_message("error", {
                "message": "Audio transcription not available. Please type your statement."
            })
        
        except Exception as e:
            logger.error(f"Error handling audio: {e}")
            await self.send_message("error", {"message": f"Audio processing error: {str(e)}"})
    
    async def handle_text(self, data: dict):
        """Handle text input from the client with streaming response and translation."""
        try:
            text = data.get("text", "").strip()
            if not text:
                return

            session = await firestore_service.get_session(self.session_id)
            report_number = getattr(session, "report_number", "") if session else ""
            
            # Send status update
            await self._set_status("thinking", "Analyzing...")
            
            # Detect and translate witness input if needed
            original_text = text
            detected_language = None
            
            if self.witness_language != "en":
                # Process witness input - translate to English for the AI
                translation_result = await translation_service.process_witness_input(
                    witness_text=text,
                    expected_language=self.witness_language,
                )
                text = translation_result["english_text"]
                detected_language = translation_result["detected_language"]
                logger.debug(f"Translated witness input from {detected_language} to English")
            
            # Process with agent using streaming
            is_correction = data.get("is_correction", False)
            message_id = str(uuid.uuid4())
            should_generate_image = False
            token_info = None
            full_response = ""
            is_completion_response = False
            tts_mode = self._agent_tts_mode(session=session)
            voice_preferences = self._get_session_voice_preferences(session=session)
            await self._set_speaking(True)
            try:
                # Stream the response (now returns 4-tuple with token_info)
                async for chunk, is_final, should_gen, tok_info in self.agent.process_statement_streaming(
                    text,
                    is_correction,
                    report_number=report_number,
                ):
                    if chunk:
                        full_response += chunk
                        # For non-English witnesses, we'll translate the full response after streaming
                        if self.witness_language == "en":
                            await self.send_streaming_chunk(chunk, is_final=False, message_id=message_id)
                    if is_final:
                        should_generate_image = should_gen
                        token_info = tok_info
                is_completion_response = self.agent.last_response_kind == "completion"
                spoken_response = (self.agent.last_response_text or full_response or "").strip()
                
                # Translate full response if witness language is not English
                if self.witness_language != "en" and spoken_response:
                    translation_result = await translation_service.translate_for_witness(
                        agent_response=spoken_response,
                        witness_language=self.witness_language,
                    )
                    spoken_response = translation_result["translated"]
                    # Send translated response
                    await self.send_message("text", {
                        "text": spoken_response,
                        "original_text": translation_result["original"],
                        "speaker": "agent",
                        "language": self.witness_language,
                        "message_id": message_id,
                        "response_kind": self.agent.last_response_kind,
                        "tts_mode": tts_mode,
                    })
                else:
                    spoken_response = full_response
                    # Send final marker for English responses
                    await self.send_streaming_chunk(
                        "",
                        is_final=True,
                        message_id=message_id,
                        token_info=token_info,
                        response_kind=self.agent.last_response_kind,
                        tts_mode=tts_mode,
                        full_text=spoken_response,
                    )
                if tts_mode and spoken_response:
                    await self._stream_agent_tts(
                        spoken_response,
                        context="response",
                        message_id=message_id,
                        voice=voice_preferences["voice"],
                    )
            finally:
                await self._set_speaking(False, emit_ready_hint=not is_completion_response)
            
            # Determine witness info for this statement
            witness_id = None
            witness_name = None
            if session:
                # Check if client specified a witness_id
                if data.get("witness_id"):
                    witness_id = data.get("witness_id")
                    witnesses = getattr(session, 'witnesses', []) or []
                    witness = next((w for w in witnesses if w.id == witness_id), None)
                    if witness:
                        witness_name = witness.name
                # Otherwise use active witness
                elif getattr(session, 'active_witness_id', None):
                    witness_id = session.active_witness_id
                    witnesses = getattr(session, 'witnesses', []) or []
                    witness = next((w for w in witnesses if w.id == witness_id), None)
                    if witness:
                        witness_name = witness.name
                # Fallback to session-level witness name
                if not witness_name:
                    witness_name = session.witness_name
            
            # Save witness statement to session with witness info and translation data
            statement = WitnessStatement(
                id=str(uuid.uuid4()),
                text=text,  # English text (for AI processing)
                original_text=original_text if original_text != text else None,  # Original in witness's language
                detected_language=detected_language,
                is_correction=is_correction,
                witness_id=witness_id,
                witness_name=witness_name
            )
            
            if session:
                session.witness_statements.append(statement)
                await firestore_service.update_session(session)

                # Auto-assign only when the report reaches a completion response.
                # This preserves unique report IDs while avoiding duplicate cases
                # created from partial early statements.
                if text and is_completion_response:
                    try:
                        assigned_case_id = await case_manager.assign_report_to_case(session)
                        if assigned_case_id:
                            session.case_id = assigned_case_id
                            await firestore_service.update_session(session)
                    except Exception as e:
                        if self._is_quota_error(e):
                            logger.warning(
                                "Case assignment skipped for session %s due to quota/rate-limit",
                                self.session_id,
                            )
                        else:
                            logger.warning("Case assignment failed for session %s: %s", self.session_id, e)

                # Non-critical automation runs in background to keep websocket responsive
                auto_scene_summary = self.agent.get_scene_summary()
                statement_count = len(session.witness_statements)
                self._track_background_task(
                    self._run_non_critical_scene_automation(
                        statement_count=statement_count,
                        scene_summary=auto_scene_summary,
                    )
                )
            
            # Generate image if needed
            if should_generate_image:
                await self.generate_and_send_scene_image()
            
            # Always send scene_state so the frontend evidence board stays current
            await self._send_scene_state()
            
            if is_completion_response:
                await self._set_status(
                    "ready",
                    "Report saved. Tap the mic if you remember more.",
                    emit_ready_hint=False,
                )
                await self._send_voice_hint(
                    "report_complete",
                    "Report saved. Tap the mic if you want to add more later.",
                    force=True,
                )
            else:
                await self._set_status("ready", "Ready to listen")
        
        except Exception as e:
            logger.error(f"Error handling text: {e}")
            error_msg = str(e).lower()
            if "429" in error_msg or "quota" in error_msg or "resource has been exhausted" in error_msg or "rate limit" in error_msg:
                await self.send_message("error", {
                    "message": "🔄 AI is busy right now. Please wait a moment and try again.",
                    "type": "quota_exceeded",
                    "retry_after": 10
                })
            else:
                await self.send_message("error", {"message": f"Something went wrong: {str(e)[:100]}"})

    @staticmethod
    def _is_quota_error(error: Exception) -> bool:
        """Detect quota/rate-limit failures."""
        error_msg = str(error).lower()
        return (
            "429" in error_msg
            or "resource_exhausted" in error_msg
            or "resource has been exhausted" in error_msg
            or "quota" in error_msg
            or "rate limit" in error_msg
            or "rate_limit" in error_msg
        )

    @staticmethod
    def _sanitize_transcribed_text(text: str) -> str:
        """Normalize model transcription output and drop punctuation-only noise."""
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return ""
        if not re.search(r"[A-Za-z0-9]", cleaned):
            return ""
        return cleaned

    @staticmethod
    def _looks_like_instructional_transcript(text: str) -> bool:
        """Detect model meta-responses that ask for audio instead of transcribing it."""
        normalized = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return False

        audio_markers = (
            "audio file",
            "audio clip",
            "audio recording",
            "recording",
            "voice note",
            "link to it",
        )
        request_markers = (
            "please provide",
            "please upload",
            "please send",
            "share the audio",
            "send me the audio",
            "i will transcribe",
            "to transcribe it",
            "exactly as requested",
        )
        return any(marker in normalized for marker in audio_markers) and any(
            marker in normalized for marker in request_markers
        )

    @staticmethod
    def _is_low_signal_auto_transcript(text: str) -> bool:
        """Heuristic guard for unattended auto-listen noise transcriptions."""
        normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        tokens = [tok for tok in normalized.split() if tok]
        if not tokens:
            return True

        allowed_single = {"yes", "no", "ok", "okay", "stop", "wait", "help", "done", "finished", "enough"}
        filler = {"um", "uh", "hmm", "mmm", "mm", "ah", "er", "huh", "noise", "static"}
        if len(tokens) == 1:
            token = tokens[0]
            if token in allowed_single:
                return False
            if token in filler:
                return True
            if len(token) <= 2:
                return True

        alpha_chars = sum(ch.isalpha() for ch in "".join(tokens))
        return alpha_chars < 3

    def _is_duplicate_auto_transcript(self, text: str) -> bool:
        """Suppress repeated auto-listen transcripts within a short window."""
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not normalized:
            return True

        now = time.monotonic()
        if (
            normalized == self._last_auto_transcript_text
            and (now - self._last_auto_transcript_at) < 12
        ):
            return True

        self._last_auto_transcript_text = normalized
        self._last_auto_transcript_at = now
        return False

    async def _run_non_critical_scene_automation(self, statement_count: int, scene_summary: dict):
        """Background auto-generation for report and case scene images."""
        try:
            session = await firestore_service.get_session(self.session_id)
            if not session:
                return

            metadata = dict(session.metadata or {})
            metadata_changed = False

            elements = scene_summary.get("elements", []) or [
                elem.model_dump() for elem in (getattr(session, "current_scene_elements", []) or [])[:12]
            ]
            statement_fragments = [
                (getattr(statement, "original_text", None) or getattr(statement, "text", None) or "").strip()
                for statement in (getattr(session, "witness_statements", []) or [])
            ]
            latest_scene_description = (
                (session.scene_versions[-1].description if session.scene_versions else "") or ""
            ).strip()
            description = imagen_service.build_report_scene_description(
                primary_description=(scene_summary.get("description") or "").strip(),
                statements=statement_fragments,
                elements=elements,
                title=session.title or "",
                ai_summary=str(metadata.get("ai_summary", "") or ""),
                latest_scene_description=latest_scene_description,
            )
            if not description:
                return

            # Report image generation (quota-aware + throttled)
            last_report_gen_count = metadata.get("report_scene_statement_count", 0)
            try:
                last_report_gen_count = int(last_report_gen_count or 0)
            except Exception:
                last_report_gen_count = 0

            has_report_scene = bool(metadata.get("report_scene_image_url"))
            should_generate_report_scene = (
                statement_count >= 1
                and (
                    not has_report_scene
                    or statement_count >= (last_report_gen_count + 3)
                )
            )

            if should_generate_report_scene:
                try:
                    report_result = await imagen_service.generate_report_scene_with_fallback(
                        self.session_id,
                        description,
                        elements,
                        quality="standard",
                    )
                    report_path = report_result.get("path")
                    if report_path:
                        metadata["report_scene_image_url"] = report_path
                        metadata["report_scene_statement_count"] = statement_count
                        metadata["report_scene_updated_at"] = datetime.utcnow().isoformat()
                        metadata_changed = True
                        await firestore_service.save_generated_image({
                            "id": f"auto-scene-report-{self.session_id}-{uuid.uuid4().hex[:8]}",
                            "entity_type": "report",
                            "entity_id": self.session_id,
                            "image_path": report_path,
                            "model_used": report_result.get("model_used") or "ai_generated",
                            "prompt": (report_result.get("prompt") or description)[:500],
                        })
                except Exception as e:
                    if self._is_quota_error(e):
                        logger.warning(
                            "Auto report scene generation skipped for session %s due to quota/rate-limit",
                            self.session_id,
                        )
                    else:
                        logger.warning("Auto report scene generation failed for session %s: %s", self.session_id, e)

            # Case image generation/update (quota-aware + throttled)
            if session.case_id:
                try:
                    case = await firestore_service.get_case(session.case_id)
                    if case:
                        last_case_gen_count = metadata.get("case_scene_statement_count", 0)
                        try:
                            last_case_gen_count = int(last_case_gen_count or 0)
                        except Exception:
                            last_case_gen_count = 0

                        should_generate_case_scene = (
                            not case.scene_image_url
                            or statement_count >= (last_case_gen_count + 4)
                        )

                        if should_generate_case_scene:
                            report_fragments = []
                            case_elements = []
                            seen_case_elements = set()
                            for report_id in case.report_ids[:8]:
                                report = await firestore_service.get_session(report_id)
                                if not report:
                                    continue
                                report_metadata = dict(getattr(report, "metadata", {}) or {})
                                latest_report_scene = (
                                    (report.scene_versions[-1].description if report.scene_versions else "") or ""
                                ).strip()
                                if latest_report_scene:
                                    report_fragments.append(latest_report_scene)
                                ai_summary = str(report_metadata.get("ai_summary", "") or "").strip()
                                if ai_summary:
                                    report_fragments.append(ai_summary)
                                for statement in (getattr(report, "witness_statements", []) or []):
                                    text = (
                                        getattr(statement, "original_text", None)
                                        or getattr(statement, "text", None)
                                        or ""
                                    ).strip()
                                    if text:
                                        report_fragments.append(text)

                                latest_scene_elements = (
                                    list(getattr(report.scene_versions[-1], "elements", []) or [])
                                    if getattr(report, "scene_versions", None)
                                    else []
                                )
                                for candidate in latest_scene_elements + list(getattr(report, "current_scene_elements", []) or []):
                                    if isinstance(candidate, dict):
                                        elem_type = str(candidate.get("type", "") or "").strip().lower()
                                        description = str(candidate.get("description", "") or "").strip().lower()
                                        position = str(candidate.get("position", "") or "").strip().lower()
                                        color = str(candidate.get("color", "") or "").strip().lower()
                                    else:
                                        elem_type = str(getattr(candidate, "type", "") or "").strip().lower()
                                        description = str(getattr(candidate, "description", "") or "").strip().lower()
                                        position = str(getattr(candidate, "position", "") or "").strip().lower()
                                        color = str(getattr(candidate, "color", "") or "").strip().lower()

                                    dedupe_key = "|".join((elem_type, description, position, color))
                                    if not dedupe_key.strip("|") or dedupe_key in seen_case_elements:
                                        continue
                                    seen_case_elements.add(dedupe_key)
                                    case_elements.append(candidate)
                                    if len(case_elements) >= 16:
                                        break
                                if len(case_elements) >= 16:
                                    break

                            case_summary = (case.summary or case.title or "").strip()
                            case_scene_description = imagen_service.build_case_scene_description(
                                case_summary=case_summary,
                                scene_description=str(((case.metadata or {}).get("scene_description", "") or "")).strip(),
                                report_fragments=report_fragments,
                                title=case.title or "",
                            )
                            if imagen_service._is_low_information_text(case_summary):
                                case_summary = case_scene_description or case.title or ""

                            case_result = await imagen_service.generate_case_scene_with_fallback(
                                case.id,
                                case_summary,
                                case_scene_description,
                                elements=case_elements,
                                quality="standard",
                            )
                            case_path = case_result.get("path")
                            if case_path:
                                case.scene_image_url = case_path
                                await firestore_service.update_case(case)
                                metadata["case_scene_statement_count"] = statement_count
                                metadata["case_scene_updated_at"] = datetime.utcnow().isoformat()
                                metadata_changed = True
                                await firestore_service.save_generated_image({
                                    "id": f"auto-scene-case-{case.id}-{uuid.uuid4().hex[:8]}",
                                    "entity_type": "case",
                                    "entity_id": case.id,
                                    "image_path": case_path,
                                    "model_used": case_result.get("model_used") or "ai_generated",
                                    "prompt": (case_result.get("prompt") or case_scene_description)[:500],
                                })
                except Exception as e:
                    if self._is_quota_error(e):
                        logger.warning(
                            "Auto case scene generation skipped for case %s due to quota/rate-limit",
                            session.case_id,
                        )
                    else:
                        logger.warning(
                            "Auto case scene generation failed for case %s: %s",
                            session.case_id,
                            e,
                        )

            if metadata_changed:
                session.metadata = metadata
                await firestore_service.update_session(session)

        except Exception as e:
            logger.warning("Non-critical scene automation failed for session %s: %s", self.session_id, e)
    
    async def handle_correction(self, data: dict):
        """Handle a correction from the user."""
        data["is_correction"] = True
        await self.handle_text(data)
    
    async def _send_health_status(self):
        """Send model availability and quota health info to the client."""
        try:
            quota_status = await quota_tracker.get_quota_status()
            health_data = {
                "type": "health_status",
                "models_available": quota_status,
                "imagen_quota": imagen_service.get_quota_status(),
                "embedding_quota": embedding_service.get_quota_status(),
            }
            await self.send_message("health_status", health_data)
        except Exception as e:
            logger.error(f"Error sending health status: {e}")
    
    async def _send_scene_state(self):
        """Send current scene state (elements, completeness, categories) to client."""
        try:
            summary = self.agent.get_scene_summary()
            elements_raw = summary.get("elements", [])
            contradictions = summary.get("contradictions", [])
            complexity = summary.get("complexity_score", 0)

            # Determine which categories are filled
            types_present = set()
            for e in elements_raw:
                types_present.add(e.get("type", ""))
            has_location = any(
                e.get("type") == "location_feature" or e.get("position")
                for e in elements_raw
            )
            has_people = "person" in types_present
            has_vehicles = "vehicle" in types_present
            has_objects = "object" in types_present
            statement_count = summary.get("statement_count", 0)
            has_timeline = statement_count >= 4

            categories = {
                "location": has_location,
                "people": has_people,
                "vehicles": has_vehicles,
                "timeline": has_timeline,
                "evidence": has_objects,
            }

            filled = sum(1 for v in categories.values() if v)
            completeness = filled / len(categories) if categories else 0

            # Get witness confidence assessment
            confidence = await self.agent.assess_confidence()

            # Count elements needing review
            needs_review_count = sum(
                1 for e in elements_raw 
                if e.get("needs_review", False) or e.get("confidence", 0.5) < settings.confidence_threshold
            )

            await self.send_message("scene_state", {
                "elements": elements_raw,
                "completeness": round(completeness, 2),
                "categories": categories,
                "contradictions": contradictions,
                "complexity": round(complexity, 3),
                "statement_count": statement_count,
                "confidence": confidence,
                "confidence_threshold": settings.confidence_threshold,
                "low_confidence_threshold": settings.low_confidence_threshold,
                "needs_review_count": needs_review_count,
            })
        except Exception as e:
            logger.error(f"Error sending scene_state: {e}")
    
    async def generate_and_send_scene_image(self):
        """Generate a scene image and send it to the client."""
        try:
            await self._set_status("generating", "Generating scene reconstruction...")
            
            # Get current scene state from agent
            scene_summary = self.agent.get_scene_summary()
            scene_description = (scene_summary.get("description") or "").strip()
            scene_elements = scene_summary.get("elements") or []

            if len(scene_description) < 80 or len(scene_elements) < 2:
                logger.info(
                    "Skipping scene image generation for session %s until more concrete scene detail is available",
                    self.session_id,
                )
                await self._set_status("ready", "Gathering more scene detail before generating the image.")
                return
            
            # Generate image
            image_bytes = await image_service.generate_scene_image(
                scene_description=scene_description,
                elements=self.agent.current_elements
            )
            
            if not image_bytes:
                await self.send_message("error", {"message": "Failed to generate image"})
                return
            
            # Try GCS upload first, fall back to base64 data URL
            image_url = None
            try:
                filename = f"scene_v{self.version_counter}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
                image_url = await storage_service.upload_image(
                    image_data=image_bytes,
                    filename=filename,
                    session_id=self.session_id
                )
            except Exception:
                pass
            
            if not image_url:
                # Fallback: serve as base64 data URL (works without GCS)
                import base64
                b64 = base64.b64encode(image_bytes).decode('utf-8')
                image_url = f"data:image/png;base64,{b64}"
            
            # Create scene version
            self.version_counter += 1
            scene_version = SceneVersion(
                version=self.version_counter,
                description=scene_description,
                image_url=image_url,
                elements=[SceneElement(**e) for e in scene_elements]
            )
            
            # Save to session
            session = await firestore_service.get_session(self.session_id)
            if session:
                session.scene_versions.append(scene_version)
                session.current_scene_elements = scene_version.elements
                await firestore_service.update_session(session)
            
            # Send scene update to client
            await self.send_message("scene_update", {
                "version": self.version_counter,
                "image_url": image_url,
                "description": scene_description,
                "elements": scene_elements
            })
        
        except Exception as e:
            logger.error(f"Error generating scene image: {e}")
            await self.send_message("error", {"message": f"Image generation error: {str(e)}"})


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time voice/text communication.
    
    Message format (client -> server):
    {
        "type": "audio|text|correction|ping",
        "data": {
            // For audio: {"audio": "base64_data", "format": "webm"}
            // For text: {"text": "witness statement"}
            // For correction: {"text": "correction statement"}
        }
    }
    
    Message format (server -> client):
    {
        "type": "text|scene_update|question|status|call_state|voice_hint|call_metrics|error|pong",
        "data": {...},
        "timestamp": "ISO8601"
    }
    """
    # Validate session exists before accepting connection
    session = await firestore_service.get_session(session_id)
    if not session:
        logger.warning(f"WebSocket connection rejected: session {session_id} not found")
        await websocket.close(code=4004, reason="Session not found")
        return
    
    handler = WebSocketHandler(websocket, session_id)
    
    try:
        await handler.connect()
        
        while handler.is_connected:
            # Check idle timeout
            if handler.last_activity and (datetime.now(timezone.utc) - handler.last_activity).total_seconds() > 600:
                logger.info(f"Session {session_id} idle timeout")
                await handler.send_message("error", {"message": "Connection idle timeout. Please reconnect."})
                break
            # Receive message with timeout
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=300.0)
            except asyncio.TimeoutError:
                await handler.send_message("error", {"message": "Connection timed out due to inactivity"})
                break
            message_task = handler._track_message_task(handler.handle_message(message))
            await message_task
    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from session {session_id}")
    except asyncio.CancelledError:
        logger.info(f"WebSocket task cancelled for session {session_id}")
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON from client in session {session_id}: {e}")
        try:
            await handler.send_message("error", {"message": "Invalid message format"})
        except Exception:
            pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await handler.send_message("error", {"message": "Internal server error"})
        except Exception:
            pass
    finally:
        await handler.disconnect()
