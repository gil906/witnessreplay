import logging
import json
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from google import genai

from app.config import settings
from app.models.schemas import SceneElement, WitnessStatement, SceneVersion
from app.services.usage_tracker import usage_tracker
from app.services.model_selector import model_selector
from app.agents.prompts import (
    SYSTEM_PROMPT,
    INITIAL_GREETING,
    SCENE_EXTRACTION_PROMPT,
    CLARIFICATION_PROMPTS,
    CONTRADICTION_FOLLOW_UP,
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
        self.contradictions: List[Dict[str, Any]] = []
        self.key_facts: Dict[str, Any] = {}
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the Gemini model for conversation."""
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                # Note: Chat is initialized lazily to use best available model
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
        if not self.client:
            return "I'm sorry, I'm having technical difficulties. Please try again later.", False
        
        try:
            # Initialize chat if not already done (lazy init with best model)
            if not self.chat:
                chat_model = await model_selector.get_best_model_for_chat()
                self.chat = self.client.chats.create(
                    model=chat_model,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.7,
                    }
                )
                logger.info(f"Initialized chat with model {chat_model}")
            
            # Add context if this is a correction
            if is_correction:
                statement = f"[CORRECTION] {statement}"
            
            # Send to Gemini with automatic model fallback on rate limit
            response = None
            current_model = None
            
            for attempt in range(3):
                try:
                    response = await asyncio.to_thread(self.chat.send_message, statement)
                    break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        # Mark current model as rate limited
                        if hasattr(self.chat, '_model'):
                            current_model = self.chat._model
                        elif hasattr(self.chat, 'model'):
                            current_model = self.chat.model
                        else:
                            current_model = settings.gemini_model
                        
                        logger.warning(f"Rate limited on model {current_model}, switching model...")
                        await model_selector.mark_rate_limited(current_model)
                        
                        # Try a different model
                        new_model = await model_selector.get_best_model_for_chat()
                        if new_model != current_model:
                            logger.info(f"Switching from {current_model} to {new_model}")
                            self.chat = self.client.chats.create(
                                model=new_model,
                                config={
                                    "system_instruction": SYSTEM_PROMPT,
                                    "temperature": 0.7,
                                }
                            )
                            # Retry with new model immediately
                            continue
                        
                        # If same model (all are rate limited), wait and retry
                        wait_time = (attempt + 1) * 10
                        logger.warning(f"All models rate limited, waiting {wait_time}s (attempt {attempt+1}/3)")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            if not response:
                return "I'm temporarily rate limited. Please wait a moment and try again.", False
            
            agent_response = response.text
            
            # Track usage (estimate tokens with improved approximation)
            input_tokens = self._estimate_tokens(statement)
            output_tokens = self._estimate_tokens(agent_response)
            usage_tracker.record_request(
                model_name=settings.gemini_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )
            
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
            
            # Optimize token usage: summarize history when it gets long
            if len(self.conversation_history) > 16:
                await self._summarize_history()
            
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
        """
        indicators = [
            "let me generate",
            "i'll create",
            "let me show you",
            "i'll show you",
            "here's what i'm picturing",
            "based on your description",
            "let me reconstruct",
            "i'll reconstruct",
            "scene reconstruction",
            "building the scene",
            "generating",
            "i have enough",
            "clear picture",
        ]
        
        response_lower = response.lower()
        keyword_match = any(indicator in response_lower for indicator in indicators)
        
        # Also trigger after every 3 user statements (enough info to visualize)
        user_messages = [m for m in self.conversation_history if m['role'] == 'user']
        periodic_trigger = len(user_messages) >= 3 and len(user_messages) % 3 == 0
        
        return keyword_match or periodic_trigger
    
    async def _summarize_history(self):
        """Summarize conversation history to optimize token usage."""
        if not self.client or len(self.conversation_history) <= 8:
            return
        try:
            # Keep last 8 messages, summarize the rest
            old_messages = self.conversation_history[:-8]
            summary_text = "\n".join([f"{m['role']}: {m['content']}" for m in old_messages])
            
            chat_model = await model_selector.get_best_model_for_chat()
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=chat_model,
                contents=f"Summarize this witness interview conversation in 3-4 bullet points, keeping all key facts, descriptions, and details:\n\n{summary_text}",
                config={"temperature": 0.1}
            )
            
            summary = response.text.strip()
            # Replace old messages with summary
            self.conversation_history = [
                {"role": "system", "content": f"[Previous conversation summary]: {summary}", "timestamp": datetime.utcnow().isoformat()}
            ] + self.conversation_history[-8:]
            
            logger.info(f"Summarized {len(old_messages)} messages into conversation summary")
        except Exception as e:
            logger.warning(f"Failed to summarize history: {e}")
    
    async def assess_confidence(self) -> Dict[str, Any]:
        """Assess overall witness confidence and testimony reliability."""
        user_messages = [m for m in self.conversation_history if m['role'] == 'user']
        
        # Basic metrics
        total_statements = len(user_messages)
        contradictions = len(self.contradictions)
        
        # Calculate scores
        detail_score = min(1.0, total_statements / 8)  # More detail = higher
        consistency_score = max(0.0, 1.0 - (contradictions * 0.15))
        specificity_score = 0.0
        
        # Check for specific details (colors, numbers, times)
        for msg in user_messages:
            content = msg['content'].lower()
            if any(c in content for c in ['red', 'blue', 'black', 'white', 'green', 'gray', 'silver']):
                specificity_score += 0.1
            if any(c in content for c in ['feet', 'inches', 'meters', 'miles', 'blocks']):
                specificity_score += 0.1
            if any(c in content for c in ['am', 'pm', 'o\'clock', 'morning', 'afternoon', 'evening']):
                specificity_score += 0.1
        
        specificity_score = min(1.0, specificity_score)
        
        overall = (detail_score * 0.3 + consistency_score * 0.4 + specificity_score * 0.3)
        
        return {
            "overall_confidence": round(overall, 2),
            "detail_level": round(detail_score, 2),
            "consistency": round(consistency_score, 2),
            "specificity": round(specificity_score, 2),
            "total_statements": total_statements,
            "contradictions_found": contradictions,
            "rating": "high" if overall > 0.7 else "medium" if overall > 0.4 else "low"
        }
    
    async def _extract_scene_information(self):
        """
        Extract structured scene information from the conversation.
        Uses best model for scene reconstruction (Idea #3).
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
            
            # Use best model for scene extraction (Idea #3: Use best models for scene reconstruction)
            scene_model = await model_selector.get_best_model_for_scene()
            logger.info(f"Using {scene_model} for scene extraction")
            
            # Generate content using the best available model
            def extract():
                try:
                    response = self.client.models.generate_content(
                        model=scene_model,
                        contents=extraction_prompt,
                        config={
                            "temperature": 0.3,  # Lower temperature for more consistent extraction
                        }
                    )
                    return response
                except Exception as e:
                    # Handle rate limits
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        logger.warning(f"Scene model {scene_model} rate limited during extraction")
                        raise
                    raise
            
            response = None
            for attempt in range(2):
                try:
                    response = await asyncio.to_thread(extract)
                    break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        # Mark as rate limited and try fallback
                        await model_selector.mark_rate_limited(scene_model)
                        scene_model = await model_selector.get_best_model_for_scene()
                        logger.info(f"Retrying with fallback model {scene_model}")
                        continue
                    else:
                        raise
            
            if not response:
                logger.warning("Failed to extract scene information after retries")
                return
            
            # Track usage for extraction
            extraction_tokens_in = self._estimate_tokens(extraction_prompt)
            extraction_tokens_out = self._estimate_tokens(response.text)
            usage_tracker.record_request(
                model_name=scene_model,
                input_tokens=extraction_tokens_in,
                output_tokens=extraction_tokens_out
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
                        confidence=elem_data.get("confidence", 0.5),
                        relationships=[],
                        evidence_tags=[]
                    )
                    self.current_elements.append(element)
                
                logger.info(f"Extracted {len(self.current_elements)} scene elements")
                
                # Auto-detect relationships from latest statement
                if self.conversation_history:
                    latest_statement = next(
                        (msg['content'] for msg in reversed(self.conversation_history) 
                         if msg['role'] == 'user'),
                        ""
                    )
                    if latest_statement:
                        from app.services.relationships import relationship_tracker
                        detected_rels = relationship_tracker.extract_relationships_from_statement(
                            latest_statement,
                            self.current_elements
                        )
                        for rel in detected_rels:
                            relationship_tracker.add_relationship(rel)
                            # Link relationship IDs to elements
                            for elem in self.current_elements:
                                if elem.id == rel.element_a_id or elem.id == rel.element_b_id:
                                    elem.relationships.append(rel.id)
                        
                        logger.info(f"Detected {len(detected_rels)} relationships")
                        
                        # Auto-tag evidence
                        from app.services.evidence import evidence_manager
                        for elem in self.current_elements:
                            tags = evidence_manager.auto_tag_element(elem, latest_statement)
                            elem.evidence_tags = [tag.id for tag in tags]
                        
                        logger.info(f"Auto-tagged {len(self.current_elements)} elements with evidence categories")
                
                # Detect contradictions
                await self._detect_contradictions(scene_data)
            
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse scene extraction JSON: {e}")
                return
        
        except Exception as e:
            logger.error(f"Error extracting scene information: {e}")
    
    async def _detect_contradictions(self, scene_data: Dict[str, Any]):
        """
        Detect contradictions between current and previous statements.
        
        Args:
            scene_data: Newly extracted scene data
        """
        try:
            # Extract new facts
            new_facts = {}
            for elem in scene_data.get("elements", []):
                elem_type = elem.get("type", "")
                desc = elem.get("description", "")
                
                # Track key attributes
                key = f"{elem_type}_{desc[:30]}"
                new_facts[key] = {
                    "color": elem.get("color"),
                    "position": elem.get("position"),
                    "size": elem.get("size"),
                }
            
            # Compare with previous facts
            for key, new_value in new_facts.items():
                if key in self.key_facts:
                    old_value = self.key_facts[key]
                    
                    # Check for contradictions
                    for attr in ["color", "position", "size"]:
                        if (old_value.get(attr) and new_value.get(attr) and 
                            old_value[attr] != new_value[attr]):
                            contradiction = {
                                "element": key,
                                "attribute": attr,
                                "old_value": old_value[attr],
                                "new_value": new_value[attr],
                                "timestamp": datetime.utcnow().isoformat()
                            }
                            self.contradictions.append(contradiction)
                            logger.info(f"Contradiction detected: {contradiction}")
            
            # Update key facts
            self.key_facts.update(new_facts)
        
        except Exception as e:
            logger.error(f"Error detecting contradictions: {e}")
    
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
            "conversation_history": self.conversation_history,
            "contradictions": self.contradictions,
            "key_facts": self.key_facts,
            "complexity_score": self._calculate_complexity_score()
        }
    
    def _calculate_complexity_score(self) -> float:
        """
        Calculate scene complexity score (0-1).
        
        Based on:
        - Number of elements
        - Number of statements
        - Number of contradictions
        - Attribute completeness
        """
        try:
            score = 0.0
            
            # Element count (up to 20 elements = max)
            element_score = min(len(self.current_elements) / 20.0, 1.0) * 0.3
            
            # Statement count (up to 10 statements = max)
            statement_count = len([m for m in self.conversation_history if m["role"] == "user"])
            statement_score = min(statement_count / 10.0, 1.0) * 0.3
            
            # Attribute completeness (how many elements have color, position, size)
            if self.current_elements:
                complete_attrs = 0
                total_attrs = len(self.current_elements) * 3  # color, position, size
                for elem in self.current_elements:
                    if elem.color:
                        complete_attrs += 1
                    if elem.position:
                        complete_attrs += 1
                    if elem.size:
                        complete_attrs += 1
                completeness_score = (complete_attrs / total_attrs) * 0.3 if total_attrs > 0 else 0.0
            else:
                completeness_score = 0.0
            
            # Contradictions (reduce score slightly)
            contradiction_penalty = min(len(self.contradictions) * 0.02, 0.1)
            
            score = element_score + statement_score + completeness_score - contradiction_penalty
            return max(0.0, min(1.0, score))
        
        except Exception as e:
            logger.error(f"Error calculating complexity score: {e}")
            return 0.0
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Uses a better approximation than simple character division:
        - Splits on whitespace to count words
        - Accounts for punctuation and special characters
        - Roughly: 1 token = 0.75 words for English
        
        Args:
            text: Input text
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        
        # Split into words (whitespace-separated)
        words = text.split()
        word_count = len(words)
        
        # Count special characters that typically become separate tokens
        special_chars = sum(1 for c in text if c in "{}[]()<>.,;:!?\"'`@#$%^&*")
        
        # Estimate: ~0.75 tokens per word + special chars
        # This is more accurate than the 1 token per 4 characters rule
        estimated = int(word_count * 0.75 + special_chars * 0.5)
        
        return max(1, estimated)  # Minimum 1 token
    
    def reset(self):
        """Reset the agent state."""
        self.conversation_history = []
        self.current_elements = []
        self.scene_description = ""
        self.contradictions = []
        self.key_facts = {}
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
