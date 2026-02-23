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
from app.agents.scene_agent import get_agent, remove_agent

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """Handles WebSocket connections for real-time voice streaming."""
    
    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.agent = get_agent(session_id)
        self.is_connected = False
        self.version_counter = 0
    
    async def connect(self):
        """Accept the WebSocket connection."""
        await self.websocket.accept()
        self.is_connected = True
        logger.info(f"WebSocket connected for session {self.session_id}")
        
        # Send initial greeting
        greeting = await self.agent.start_interview()
        await self.send_message("text", {"text": greeting, "speaker": "agent"})
        await self.send_message("status", {"status": "ready", "message": "Ready to listen"})
    
    async def disconnect(self):
        """Close the WebSocket connection."""
        self.is_connected = False
        logger.info(f"WebSocket disconnected for session {self.session_id}")
    
    async def send_message(self, message_type: str, data: dict):
        """Send a message to the client."""
        if not self.is_connected:
            return
        
        try:
            message = WebSocketMessage(type=message_type, data=data)
            await self.websocket.send_json(message.model_dump(mode='json'))
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")
    
    async def handle_message(self, message: dict):
        """Handle incoming WebSocket messages."""
        try:
            message_type = message.get("type")
            data = message.get("data", {})
            
            if message_type == "audio":
                await self.handle_audio(data)
            elif message_type == "text":
                await self.handle_text(data)
            elif message_type == "correction":
                await self.handle_correction(data)
            elif message_type == "ping":
                await self.send_message("pong", {})
            else:
                logger.warning(f"Unknown message type: {message_type}")
        
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            await self.send_message("error", {"message": str(e)})
    
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
                    
                    transcribed_text = transcription_response.text.strip()
                    
                    if transcribed_text:
                        logger.info(f"Transcribed audio: {transcribed_text[:100]}")
                        await self.send_message("text", {
                            "text": transcribed_text,
                            "speaker": "user"
                        })
                        await self.handle_text({"text": transcribed_text})
                        return
                    else:
                        await self.send_message("error", {"message": "Could not transcribe audio. Please try again or type your statement."})
                        return
                        
                except Exception as e:
                    logger.warning(f"Gemini audio transcription failed: {e}")
                    await self.send_message("status", {
                        "status": "error",
                        "message": "Audio transcription failed. Please type your statement instead."
                    })
                    return
            
            await self.send_message("error", {
                "message": "Audio transcription not available. Please type your statement."
            })
        
        except Exception as e:
            logger.error(f"Error handling audio: {e}")
            await self.send_message("error", {"message": f"Audio processing error: {str(e)}"})
    
    async def handle_text(self, data: dict):
        """Handle text input from the client."""
        try:
            text = data.get("text", "").strip()
            if not text:
                return
            
            # Send status update
            await self.send_message("status", {"status": "thinking", "message": "Analyzing..."})
            
            # Process with agent
            is_correction = data.get("is_correction", False)
            response, should_generate_image = await self.agent.process_statement(
                text, is_correction
            )
            
            # Save witness statement to session
            statement = WitnessStatement(
                id=str(uuid.uuid4()),
                text=text,
                is_correction=is_correction
            )
            
            session = await firestore_service.get_session(self.session_id)
            if session:
                session.witness_statements.append(statement)
                await firestore_service.update_session(session)
            
            # Send agent response
            await self.send_message("text", {
                "text": response,
                "speaker": "agent"
            })
            
            # Generate image if needed
            if should_generate_image:
                await self.generate_and_send_scene_image()
            
            await self.send_message("status", {"status": "ready", "message": "Ready to listen"})
        
        except Exception as e:
            logger.error(f"Error handling text: {e}")
            await self.send_message("error", {"message": f"Processing error: {str(e)}"})
    
    async def handle_correction(self, data: dict):
        """Handle a correction from the user."""
        data["is_correction"] = True
        await self.handle_text(data)
    
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
            
            # Upload to GCS
            filename = f"scene_v{self.version_counter}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
            image_url = await storage_service.upload_image(
                image_data=image_bytes,
                filename=filename,
                session_id=self.session_id
            )
            
            if not image_url:
                await self.send_message("error", {"message": "Failed to upload image"})
                return
            
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
    handler = WebSocketHandler(websocket, session_id)
    
    try:
        await handler.connect()
        
        while handler.is_connected:
            # Receive message
            message = await websocket.receive_json()
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
