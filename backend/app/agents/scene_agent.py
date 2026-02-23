import logging
import json
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from google import genai

from app.config import settings
from app.models.schemas import SceneElement, WitnessStatement, SceneVersion
from app.agents.prompts import (
    SYSTEM_PROMPT,
    INITIAL_GREETING,
    SCENE_EXTRACTION_PROMPT,
    CLARIFICATION_PROMPTS,
)

logger = logging.getLogger(__name__)


class SceneReconstructionAgent:
    """
    Core agent for managing witness interviews and scene reconstruction.
    Uses Gemini to understand witness statements, ask questions, and track scene state.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.client = None
        self.chat = None
        self.conversation_history: List[Dict[str, str]] = []
        self.current_elements: List[SceneElement] = []
        self.scene_description: str = ""
        self.needs_image_generation: bool = False
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the Gemini model for conversation."""
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                # Initialize chat with system instruction
                self.chat = self.client.chats.create(
                    model=settings.gemini_model,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.7,
                    }
                )
                logger.info(f"Initialized scene agent for session {self.session_id}")
            else:
                logger.warning("GOOGLE_API_KEY not set, agent not initialized")
        except Exception as e:
            logger.error(f"Failed to initialize scene agent: {e}")
            self.client = None
    
    async def start_interview(self) -> str:
        """Start the interview with an initial greeting."""
        return INITIAL_GREETING
    
    async def process_statement(
        self,
        statement: str,
        is_correction: bool = False
    ) -> Tuple[str, bool]:
        """
        Process a witness statement and generate a response.
        
        Args:
            statement: The witness's statement
            is_correction: Whether this is a correction to previous information
        
        Returns:
            Tuple of (agent_response, should_generate_image)
        """
        if not self.chat:
            return "I'm sorry, I'm having technical difficulties. Please try again later.", False
        
        try:
            # Add context if this is a correction
            if is_correction:
                statement = f"[CORRECTION] {statement}"
            
            # Send to Gemini
            response = self.chat.send_message(statement)
            agent_response = response.text
            
            # Store in history
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat()
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": agent_response,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Determine if we should generate an image
            should_generate = self._should_generate_image(agent_response)
            
            # Extract scene information if we have enough detail
            if should_generate or len(self.conversation_history) > 6:
                await self._extract_scene_information()
            
            logger.info(f"Processed statement for session {self.session_id}")
            return agent_response, should_generate
        
        except Exception as e:
            logger.error(f"Error processing statement: {e}")
            return "I'm having trouble understanding. Could you rephrase that?", False
    
    def _should_generate_image(self, response: str) -> bool:
        """
        Determine if we should generate an image based on the conversation state.
        
        Criteria:
        - Agent has asked enough questions
        - Agent indicates readiness ("Let me show you...", "I'll create...")
        - Significant new information has been provided
        """
        indicators = [
            "let me generate",
            "i'll create",
            "let me show you",
            "i'll show you",
            "here's what i'm picturing",
            "based on your description",
        ]
        
        response_lower = response.lower()
        return any(indicator in response_lower for indicator in indicators)
    
    async def _extract_scene_information(self):
        """
        Extract structured scene information from the conversation.
        Uses Gemini to analyze the conversation and extract scene elements.
        """
        if not self.client:
            return
        
        try:
            # Create a summary of the conversation
            conversation_text = "\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in self.conversation_history
            ])
            
            # Ask Gemini to extract structured information
            extraction_prompt = f"{SCENE_EXTRACTION_PROMPT}\n\nConversation:\n{conversation_text}"
            
            # Use client to generate content
            response = self.client.models.generate_content(
                model=settings.gemini_model,
                contents=extraction_prompt
            )
            
            # Try to parse JSON from the response
            try:
                # Extract JSON from markdown code blocks if present
                text = response.text
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]
                
                scene_data = json.loads(text.strip())
                
                # Update scene description
                self.scene_description = scene_data.get("scene_description", "")
                
                # Update elements
                elements_data = scene_data.get("elements", [])
                self.current_elements = []
                for i, elem_data in enumerate(elements_data):
                    element = SceneElement(
                        id=f"elem_{self.session_id}_{i}",
                        type=elem_data.get("type", "object"),
                        description=elem_data.get("description", ""),
                        position=elem_data.get("position"),
                        color=elem_data.get("color"),
                        size=elem_data.get("size"),
                        confidence=elem_data.get("confidence", 0.5)
                    )
                    self.current_elements.append(element)
                
                logger.info(f"Extracted {len(self.current_elements)} scene elements")
            
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse scene extraction JSON: {e}")
        
        except Exception as e:
            logger.error(f"Error extracting scene information: {e}")
    
    async def generate_clarifying_question(
        self,
        element_type: str,
        element_name: str
    ) -> str:
        """Generate a clarifying question about a specific element."""
        if element_type in CLARIFICATION_PROMPTS:
            return CLARIFICATION_PROMPTS[element_type].format(element=element_name)
        return f"Can you tell me more about {element_name}?"
    
    def get_scene_summary(self) -> Dict[str, Any]:
        """Get a summary of the current scene state."""
        return {
            "description": self.scene_description,
            "elements": [elem.model_dump() for elem in self.current_elements],
            "statement_count": len([m for m in self.conversation_history if m["role"] == "user"]),
            "conversation_history": self.conversation_history
        }
    
    def reset(self):
        """Reset the agent state."""
        self.conversation_history = []
        self.current_elements = []
        self.scene_description = ""
        if self.client:
            self.chat = self.client.chats.create(
                model=settings.gemini_model,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 0.7,
                }
            )


# Agent instance cache
_agent_cache: Dict[str, SceneReconstructionAgent] = {}


def get_agent(session_id: str) -> SceneReconstructionAgent:
    """Get or create an agent for a session."""
    if session_id not in _agent_cache:
        _agent_cache[session_id] = SceneReconstructionAgent(session_id)
    return _agent_cache[session_id]


def remove_agent(session_id: str):
    """Remove an agent from the cache."""
    if session_id in _agent_cache:
        del _agent_cache[session_id]
