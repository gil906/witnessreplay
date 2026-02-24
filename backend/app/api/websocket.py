import time
import logging
import json
import asyncio
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
from app.services.model_selector import model_selector, quota_tracker
from app.services.imagen_service import imagen_service
from app.services.embedding_service import embedding_service
from app.services.translation_service import translation_service
from app.agents.scene_agent import get_agent, remove_agent
from app.config import settings

logger = logging.getLogger(__name__)


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
    
    async def connect(self):
        """Accept the WebSocket connection."""
        await self.websocket.accept()
        self.is_connected = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        logger.info(f"WebSocket connected for session {self.session_id}")
        
        # Only send greeting if the session has no prior statements (i.e. fresh session, not reconnect)
        session = await firestore_service.get_session(self.session_id)
        if session:
            # Load witness language preference
            await self._load_witness_language(session)
            
            if len(session.witness_statements) == 0:
                greeting = await self.agent.start_interview()
                # Translate greeting if witness language is not English
                await self._send_translated_agent_message(greeting)
            else:
                await self.send_message("status", {"status": "ready", "message": "Ready to listen"})
        else:
            await self.send_message("status", {"status": "ready", "message": "Ready to listen"})
    
    async def _load_witness_language(self, session):
        """Load the active witness's preferred language."""
        if session.active_witness_id:
            for witness in session.witnesses:
                if witness.id == session.active_witness_id:
                    self.witness_language = getattr(witness, 'preferred_language', 'en')
                    logger.debug(f"Loaded witness language: {self.witness_language}")
                    return
        self.witness_language = "en"
    
    async def _send_translated_agent_message(self, text: str, message_id: str = None):
        """Send an agent message, translating if necessary."""
        if self.witness_language != "en":
            translation_result = await translation_service.translate_for_witness(
                agent_response=text,
                witness_language=self.witness_language,
            )
            await self.send_message("text", {
                "text": translation_result["translated"],
                "original_text": translation_result["original"],
                "speaker": "agent",
                "language": self.witness_language,
                "message_id": message_id or str(uuid.uuid4())
            })
        else:
            await self.send_message("text", {
                "text": text,
                "speaker": "agent",
                "message_id": message_id or str(uuid.uuid4())
            })
    
    async def disconnect(self):
        """Close the WebSocket connection."""
        self.is_connected = False
        if hasattr(self, '_heartbeat_task'):
            self._heartbeat_task.cancel()
        remove_agent(self.session_id)
        logger.info(f"WebSocket disconnected for session {self.session_id}")
    
    async def _heartbeat(self):
        """Send periodic heartbeat to keep connection alive."""
        while self.is_connected:
            try:
                await asyncio.sleep(25)
                if self.is_connected:
                    # Include basic model availability in heartbeat
                    models_status = await model_selector.get_all_models_status()
                    available_count = sum(1 for m in models_status if m.get("available"))
                    await self.send_message("ping", {
                        "models_available": available_count,
                        "total_models": len(models_status),
                    })
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
        token_info: dict = None
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
            message = WebSocketMessage(type="text_stream", data=data)
            await self.websocket.send_json(message.model_dump(mode='json'))
        except Exception as e:
            logger.error(f"Error sending streaming chunk: {e}")
    
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
            
            if not audio_base64:
                await self.send_message("error", {"message": "No audio data provided"})
                return
            
            await self.send_message("status", {"status": "processing", "message": "Transcribing audio..."})
            
            # Use Gemini to transcribe audio
            if self.agent and self.agent.client:
                try:
                    import base64
                    audio_bytes = base64.b64decode(audio_base64)
                    audio_size_kb = len(audio_bytes) / 1024
                    logger.info(f"Received audio: {audio_size_kb:.1f}KB, format={audio_format}")
                    
                    if audio_size_kb < 1:
                        logger.warning(f"Audio too small ({audio_size_kb:.1f}KB) — likely empty recording")
                        await self.send_message("error", {"message": "Recording was too short. Hold the mic button and speak, then release."})
                        return
                    
                    mime_map = {
                        "webm": "audio/webm",
                        "ogg": "audio/ogg",
                        "mp4": "audio/mp4",
                        "wav": "audio/wav",
                    }
                    mime_type = mime_map.get(audio_format, "audio/webm")
                    
                    # Use Gemini multimodal to transcribe
                    from google.genai import types
                    from app.config import settings as app_settings
                    logger.info(f"Sending to Gemini ({app_settings.gemini_model}) for transcription...")
                    transcription_response = await asyncio.to_thread(
                        self.agent.client.models.generate_content,
                        model=app_settings.gemini_model,
                        contents=[
                            types.Content(parts=[
                                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                                types.Part.from_text("Transcribe this audio exactly. Return ONLY the transcribed text, nothing else."),
                            ])
                        ]
                    )
                    
                    transcribed_text = transcription_response.text.strip() if transcription_response.text else ""
                    
                    if transcribed_text:
                        logger.info(f"Transcribed audio ({audio_size_kb:.1f}KB): {transcribed_text[:100]}")
                        await self.send_message("text", {
                            "text": transcribed_text,
                            "speaker": "user"
                        })
                        await self.handle_text({"text": transcribed_text})
                        return
                    else:
                        logger.warning(f"Gemini returned empty transcription for {audio_size_kb:.1f}KB audio")
                        await self.send_message("error", {"message": "Could not understand the audio. Please try again or type your statement."})
                        return
                        
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"Gemini audio transcription failed: {error_str}", exc_info=True)
                    
                    # Send specific error back to client
                    if "429" in error_str or "quota" in error_str.lower():
                        user_msg = "API quota reached. Please type your statement instead."
                    elif "400" in error_str:
                        user_msg = f"Audio format issue. Try speaking longer. ({error_str[:80]})"
                    else:
                        user_msg = f"Transcription error: {error_str[:100]}. Try typing instead."
                    
                    await self.send_message("error", {"message": user_msg})
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
            
            # Send status update
            await self.send_message("status", {"status": "thinking", "message": "Analyzing..."})
            
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
            
            # Stream the response (now returns 4-tuple with token_info)
            async for chunk, is_final, should_gen, tok_info in self.agent.process_statement_streaming(
                text, is_correction
            ):
                if chunk:
                    full_response += chunk
                    # For non-English witnesses, we'll translate the full response after streaming
                    if self.witness_language == "en":
                        await self.send_streaming_chunk(chunk, is_final=False, message_id=message_id)
                if is_final:
                    should_generate_image = should_gen
                    token_info = tok_info
            
            # Translate full response if witness language is not English
            if self.witness_language != "en" and full_response:
                translation_result = await translation_service.translate_for_witness(
                    agent_response=full_response,
                    witness_language=self.witness_language,
                )
                # Send translated response
                await self.send_message("text", {
                    "text": translation_result["translated"],
                    "original_text": translation_result["original"],
                    "speaker": "agent",
                    "language": self.witness_language,
                    "message_id": message_id
                })
            else:
                # Send final marker for English responses
                await self.send_streaming_chunk("", is_final=True, message_id=message_id, token_info=token_info)
            
            # Get session to retrieve active witness info
            session = await firestore_service.get_session(self.session_id)
            
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
            
            # Generate image if needed
            if should_generate_image:
                await self.generate_and_send_scene_image()
            
            # Always send scene_state so the frontend evidence board stays current
            await self._send_scene_state()
            
            # After getting the AI response, try to extract evidence tags
            try:
                evidence_prompt = f"From this witness statement, list any physical evidence mentioned (weapons, vehicles, clothing, objects). Return as comma-separated list, or 'none'.\n\nStatement: {text[:300]}"
                evidence_resp = await asyncio.to_thread(
                    self.agent.client.models.generate_content,
                    model="gemini-2.0-flash-lite",
                    contents=[evidence_prompt]
                )
                evidence_text = evidence_resp.text.strip() if evidence_resp.text else "none"
                if evidence_text.lower() != "none":
                    tags = [t.strip() for t in evidence_text.split(",") if t.strip()]
                    if tags:
                        await self.send_message("evidence_tags", {"tags": tags, "source_text": text[:100]})
            except Exception:
                pass
            
            await self.send_message("status", {"status": "ready", "message": "Ready to listen"})
        
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
            await self.send_message("status", {
                "status": "generating",
                "message": "Generating scene reconstruction..."
            })
            
            # Get current scene state from agent
            scene_summary = self.agent.get_scene_summary()
            
            # Generate image
            image_bytes = await image_service.generate_scene_image(
                scene_description=scene_summary["description"],
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
                description=scene_summary["description"],
                image_url=image_url,
                elements=[SceneElement(**e) for e in scene_summary["elements"]]
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
                "description": scene_summary["description"],
                "elements": scene_summary["elements"]
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
        "type": "text|scene_update|question|status|error|pong",
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
            await handler.handle_message(message)
    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from session {session_id}")
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
