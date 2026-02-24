import logging
import json
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from google import genai

from app.config import settings
from app.models.schemas import SceneElement, WitnessStatement, SceneVersion, SceneExtractionResponse
from app.services.usage_tracker import usage_tracker
from app.services.response_cache import response_cache
from app.services.token_estimator import token_estimator, TokenEstimate, QuotaCheckResult
from app.services.interview_branching import interview_branching
from google.genai import types
from app.services.model_selector import model_selector, call_with_retry
from typing import AsyncIterator
from app.agents.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_COMPACT,
    INITIAL_GREETING,
    CLARIFICATION_PROMPTS,
    CONTRADICTION_FOLLOW_UP,
)

logger = logging.getLogger(__name__)


class SceneReconstructionAgent:
    """
    Core agent for managing witness interviews and scene reconstruction.
    Uses Gemini to understand witness statements, ask questions, and track scene state.
    Supports dynamic interview branching based on detected topics.
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
        self.template: Optional[Dict[str, Any]] = None
        self.detected_topics: List[Dict[str, Any]] = []  # Topics detected during interview
        self._initialize_model()
    
    def _log_structured(self, event: str, **kwargs):
        """Emit structured log entry."""
        entry = {"event": event, "session_id": self.session_id, **kwargs}
        logger.info(json.dumps(entry))

    def _initialize_model(self):
        """Initialize the Gemini model for conversation."""
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                self._log_structured("agent_initialized")
            else:
                logger.warning("GOOGLE_API_KEY not set, agent not initialized")
        except Exception as e:
            logger.error(f"Failed to initialize scene agent: {e}")
            self.client = None
    
    def set_template(self, template: Dict[str, Any]) -> None:
        """
        Set an interview template for this session.
        
        Args:
            template: Template dict containing initial_questions, key_details, scene_elements
        """
        self.template = template
        self._log_structured("template_set", template_id=template.get("id"))
    
    async def start_interview(self) -> str:
        """Start the interview with an initial greeting, optionally using template."""
        self._log_structured("interview_started", template_id=self.template.get("id") if self.template else None)
        
        if self.template:
            # Use template-specific greeting
            template_greeting = self._generate_template_greeting()
            return template_greeting
        
        return INITIAL_GREETING
    
    def _generate_template_greeting(self) -> str:
        """Generate a greeting tailored to the template type."""
        if not self.template:
            return INITIAL_GREETING
        
        template_name = self.template.get("name", "incident")
        first_question = self.template.get("initial_questions", [INITIAL_GREETING])[0]
        
        greeting = f"""Hello, I'm Detective Ray — an AI scene reconstruction specialist here to help document what you witnessed.

I understand you're here to report a **{template_name}**. Everything you share helps build an accurate picture of what happened. Take your time, and don't worry if you can't remember every detail.

{first_question}"""
        
        return greeting
    
    async def process_statement(
        self,
        statement: str,
        is_correction: bool = False
    ) -> Tuple[str, bool, Optional[Dict[str, Any]]]:
        """
        Process a witness statement and generate a response.
        
        Args:
            statement: The witness's statement
            is_correction: Whether this is a correction to previous information
        
        Returns:
            Tuple of (agent_response, should_generate_image, token_info)
            token_info contains estimated tokens and quota status
        """
        if not self.client:
            return "I'm sorry, I'm having technical difficulties. Please try again later.", False, None
        
        try:
            # Initialize chat if not already done (lazy init with best model)
            if not self.chat:
                chat_model = await model_selector.get_best_model_for_task("chat")
                self.chat = self.client.chats.create(
                    model=chat_model,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.7,
                    }
                )
                self._log_structured("chat_initialized", model=chat_model)
            
            # Add context if this is a correction
            if is_correction:
                statement = f"[CORRECTION] {statement}"
            
            # Get current model for pre-check
            current_model = getattr(self.chat, '_model', None) or getattr(self.chat, 'model', settings.gemini_model)
            
            # Pre-check token quota before sending request
            quota_check, token_estimate = usage_tracker.precheck_request(
                model_name=current_model,
                prompt=statement,
                system_prompt=SYSTEM_PROMPT,
                history=self.conversation_history,
                task_type="chat",
                enforce=settings.enforce_rate_limits,
            )
            
            token_info = {
                "estimated": token_estimate.to_dict(),
                "quota_check": quota_check.to_dict(),
                "model": current_model,
            }
            
            # Log the pre-check result
            self._log_structured("statement_received",
                                 tokens_estimated=token_estimate.total_tokens,
                                 quota_allowed=quota_check.allowed,
                                 is_correction=is_correction)
            
            # Reject if quota exceeded and enforcement is on
            if not quota_check.allowed:
                return (
                    f"I'm sorry, I'm currently at my daily limit. {quota_check.rejection_reason} "
                    "Please try again tomorrow or use a lighter request.",
                    False,
                    token_info,
                )
            
            # Send to Gemini with automatic model fallback on rate limit
            response = None
            
            for attempt in range(3):
                try:
                    response = await call_with_retry(
                        asyncio.to_thread,
                        self.chat.send_message,
                        statement,
                    )
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
                        new_model = await model_selector.get_best_model_for_task("chat")
                        if new_model != current_model:
                            self._log_structured("model_switched",
                                                 old_model=current_model,
                                                 new_model=new_model)
                            self.chat = self.client.chats.create(
                                model=new_model,
                                config={
                                    "system_instruction": SYSTEM_PROMPT,
                                    "temperature": 0.7,
                                }
                            )
                            continue
                        
                        # If same model (all are rate limited), wait and retry
                        wait_time = (attempt + 1) * 10
                        logger.warning(f"All models rate limited, waiting {wait_time}s (attempt {attempt+1}/3)")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            if not response:
                return "I'm temporarily rate limited. Please wait a moment and try again.", False, token_info
            
            agent_response = response.text
            
            # Track usage with actual token counts
            input_tokens = self._estimate_tokens(statement)
            output_tokens = self._estimate_tokens(agent_response)
            usage_tracker.record_request(
                model_name=current_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )
            
            # Update token_info with actual output tokens
            token_info["actual_output_tokens"] = output_tokens
            token_info["actual_total_tokens"] = input_tokens + output_tokens
            
            # Detect topics for interview branching
            statement_index = len([m for m in self.conversation_history if m['role'] == 'user'])
            detected = interview_branching.detect_topics(statement, statement_index)
            if detected:
                self.detected_topics.extend([{
                    "category": t.category.value,
                    "trigger_phrase": t.trigger_phrase,
                    "confidence": t.confidence,
                    "statement_index": t.statement_index
                } for t in detected])
                self._log_structured("topics_detected",
                                     topics=[t.category.value for t in detected])
            
            # Store in history
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat(),
                "detected_topics": [t.category.value for t in detected] if detected else []
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
            
            self._log_structured("statement_processed",
                                 model=current_model or "chat",
                                 tokens_estimated=token_estimate.total_tokens,
                                 actual_tokens=input_tokens + output_tokens,
                                 elements_count=len(self.current_elements))
            return agent_response, should_generate, token_info
        
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                self._log_structured("error_rate_limited", error=str(e)[:200])
                return ("I'm experiencing high demand right now. Could you please "
                        "repeat that in a moment? Your testimony is important.",
                        False, None)
            elif "400" in str(e) or "INVALID_ARGUMENT" in str(e):
                self._log_structured("error_invalid_request", error=str(e)[:200])
                return ("I had trouble processing that. Could you rephrase?",
                        False, None)
            else:
                self._log_structured("error_unexpected", error=str(e)[:200])
                logger.error(f"Unexpected error processing statement: {e}", exc_info=True)
                raise
    
    async def process_statement_streaming(
        self,
        statement: str,
        is_correction: bool = False
    ) -> AsyncIterator[Tuple[str, bool, bool, Optional[Dict[str, Any]]]]:
        """
        Process a witness statement with streaming response.
        
        Yields:
            Tuple of (text_chunk, is_final, should_generate_image, token_info)
            token_info is only provided on the final chunk
        """
        if not self.client:
            yield "I'm sorry, I'm having technical difficulties. Please try again later.", True, False, None
            return
        
        try:
            # Initialize chat if not already done
            if not self.chat:
                chat_model = await model_selector.get_best_model_for_task("chat")
                self.chat = self.client.chats.create(
                    model=chat_model,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.7,
                    }
                )
                self._log_structured("chat_initialized", model=chat_model)
            
            if is_correction:
                statement = f"[CORRECTION] {statement}"
            
            # Get current model for pre-check
            current_model = getattr(self.chat, '_model', None) or getattr(self.chat, 'model', settings.gemini_model)
            
            # Pre-check token quota before sending request
            quota_check, token_estimate = usage_tracker.precheck_request(
                model_name=current_model,
                prompt=statement,
                system_prompt=SYSTEM_PROMPT,
                history=self.conversation_history,
                task_type="chat",
                enforce=settings.enforce_rate_limits,
            )
            
            token_info = {
                "estimated": token_estimate.to_dict(),
                "quota_check": quota_check.to_dict(),
                "model": current_model,
            }
            
            self._log_structured("statement_received_streaming",
                                 tokens_estimated=token_estimate.total_tokens,
                                 quota_allowed=quota_check.allowed,
                                 is_correction=is_correction)
            
            # Reject if quota exceeded and enforcement is on
            if not quota_check.allowed:
                yield (
                    f"I'm sorry, I'm currently at my daily limit. {quota_check.rejection_reason} "
                    "Please try again tomorrow or use a lighter request.",
                    True, False, token_info
                )
                return
            
            # Use streaming with Gemini
            full_response = ""
            
            for attempt in range(3):
                try:
                    # Send message with stream=True
                    response_stream = await asyncio.to_thread(
                        self.chat.send_message_stream,
                        statement,
                    )
                    
                    # Yield chunks as they arrive
                    for chunk in response_stream:
                        if hasattr(chunk, 'text') and chunk.text:
                            full_response += chunk.text
                            yield chunk.text, False, False, None
                    break
                    
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        if hasattr(self.chat, '_model'):
                            current_model = self.chat._model
                        elif hasattr(self.chat, 'model'):
                            current_model = self.chat.model
                        else:
                            current_model = settings.gemini_model
                        
                        logger.warning(f"Rate limited on model {current_model}, switching model...")
                        await model_selector.mark_rate_limited(current_model)
                        
                        new_model = await model_selector.get_best_model_for_task("chat")
                        if new_model != current_model:
                            self._log_structured("model_switched",
                                                 old_model=current_model,
                                                 new_model=new_model)
                            self.chat = self.client.chats.create(
                                model=new_model,
                                config={
                                    "system_instruction": SYSTEM_PROMPT,
                                    "temperature": 0.7,
                                }
                            )
                            continue
                        
                        wait_time = (attempt + 1) * 10
                        logger.warning(f"All models rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            if not full_response:
                yield "I'm temporarily rate limited. Please wait a moment and try again.", True, False, token_info
                return
            
            # Track usage with actual token counts
            input_tokens = self._estimate_tokens(statement)
            output_tokens = self._estimate_tokens(full_response)
            usage_tracker.record_request(
                model_name=current_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )
            
            # Update token_info with actual output tokens
            token_info["actual_output_tokens"] = output_tokens
            token_info["actual_total_tokens"] = input_tokens + output_tokens
            
            # Detect topics for interview branching
            statement_index = len([m for m in self.conversation_history if m['role'] == 'user'])
            detected = interview_branching.detect_topics(statement, statement_index)
            if detected:
                self.detected_topics.extend([{
                    "category": t.category.value,
                    "trigger_phrase": t.trigger_phrase,
                    "confidence": t.confidence,
                    "statement_index": t.statement_index
                } for t in detected])
                self._log_structured("topics_detected",
                                     topics=[t.category.value for t in detected])
            
            # Store in history
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat(),
                "detected_topics": [t.category.value for t in detected] if detected else []
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            if len(self.conversation_history) > 16:
                await self._summarize_history()
            
            should_generate = self._should_generate_image(full_response)
            
            if should_generate or len(self.conversation_history) > 6:
                await self._extract_scene_information()
            
            self._log_structured("statement_processed_streaming",
                                 model=current_model or "chat",
                                 tokens_estimated=token_estimate.total_tokens,
                                 actual_tokens=input_tokens + output_tokens,
                                 elements_count=len(self.current_elements))
            
            # Yield final signal with token info
            yield "", True, should_generate, token_info
        
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                self._log_structured("error_rate_limited", error=str(e)[:200])
                yield "I'm experiencing high demand right now. Could you please repeat that in a moment?", True, False, None
            elif "400" in str(e) or "INVALID_ARGUMENT" in str(e):
                self._log_structured("error_invalid_request", error=str(e)[:200])
                yield "I had trouble processing that. Could you rephrase?", True, False, None
            else:
                self._log_structured("error_unexpected", error=str(e)[:200])
                logger.error(f"Unexpected error processing statement: {e}", exc_info=True)
                yield f"An error occurred: {str(e)}", True, False, None
    
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
            prompt = f"Summarize this witness interview conversation in 3-4 bullet points, keeping all key facts, descriptions, and details:\n\n{summary_text}"
            
            # Check response cache first
            cached = await response_cache.get(prompt, context_key="summarize", threshold=0.92)
            if cached:
                summary, similarity = cached
                self._log_structured("history_summarize_cached", similarity=similarity)
            else:
                lightweight_model = await model_selector.get_best_model_for_task("lightweight")
                self._log_structured("history_summarize", model=lightweight_model,
                                     messages_to_summarize=len(old_messages))
                response = await call_with_retry(
                    asyncio.to_thread,
                    self.client.models.generate_content,
                    model=lightweight_model,
                    contents=prompt,
                    config={"temperature": 0.1},
                    model_name=lightweight_model,
                )
                
                summary = response.text.strip()
                # Cache the response for similar future queries
                await response_cache.set(prompt, summary, context_key="summarize", ttl_seconds=1800)
            
            # Replace old messages with summary
            self.conversation_history = [
                {"role": "system", "content": f"[Previous conversation summary]: {summary}", "timestamp": datetime.utcnow().isoformat()}
            ] + self.conversation_history[-8:]
            
            logger.info(f"Summarized {len(old_messages)} messages into conversation summary")
        except Exception as e:
            logger.warning(f"Failed to summarize history: {e}")
    
    async def assess_confidence(self) -> Dict[str, Any]:
        """Assess overall witness confidence and testimony reliability.
        Uses lightweight model (gemma-3) for its high RPM allowance."""
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
        Uses Gemini's structured JSON output mode with Pydantic schema for
        reliable, parseable responses that reduce token waste.
        Uses response cache for similar conversations to reduce API calls.
        """
        if not self.client:
            return
        
        try:
            # Create a summary of the conversation
            conversation_text = "\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in self.conversation_history
            ])
            
            # Build extraction prompt (simplified since schema enforces structure)
            extraction_prompt = f"""Analyze this witness interview and extract all scene information.

Conversation:
{conversation_text}

Extract every detail mentioned: people, vehicles, objects, locations, timeline, environmental conditions.
Rate confidence based on specificity and consistency of witness statements."""
            
            # Check response cache first for similar scene extraction requests
            cached = await response_cache.get(
                extraction_prompt, 
                context_key="scene_extraction", 
                threshold=0.93
            )
            
            if cached:
                response_text, similarity = cached
                self._log_structured("scene_extraction_cached", similarity=similarity)
            else:
                # Use best model for scene extraction
                scene_model = await model_selector.get_best_model_for_task("scene")
                self._log_structured("scene_extraction_started", model=scene_model, mode="structured_output")
                
                # Use structured JSON output mode with Pydantic schema
                response = await call_with_retry(
                    asyncio.to_thread,
                    self.client.models.generate_content,
                    model=scene_model,
                    contents=extraction_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        response_mime_type="application/json",
                        response_json_schema=SceneExtractionResponse,
                    ),
                    model_name=scene_model,
                )
                
                if not response:
                    logger.warning("Failed to extract scene information after retries")
                    return
                
                response_text = response.text
                
                # Track usage for extraction
                extraction_tokens_in = self._estimate_tokens(extraction_prompt)
                extraction_tokens_out = self._estimate_tokens(response_text)
                usage_tracker.record_request(
                    model_name=scene_model,
                    input_tokens=extraction_tokens_in,
                    output_tokens=extraction_tokens_out
                )
                
                # Cache the response for similar future extractions
                await response_cache.set(
                    extraction_prompt, 
                    response_text, 
                    context_key="scene_extraction", 
                    ttl_seconds=3600
                )
            
            # Parse structured response - guaranteed valid JSON matching schema
            try:
                scene_data = SceneExtractionResponse.model_validate_json(response_text)
                
                # Update scene description
                self.scene_description = scene_data.scene_description
                
                # Update elements from structured response
                self.current_elements = []
                for i, elem_data in enumerate(scene_data.elements):
                    element = SceneElement(
                        id=f"elem_{self.session_id}_{i}",
                        type=elem_data.type,
                        description=elem_data.description,
                        position=elem_data.position,
                        color=elem_data.color,
                        size=elem_data.size,
                        confidence=elem_data.confidence,
                        relationships=[],
                        evidence_tags=[]
                    )
                    self.current_elements.append(element)
                
                self._log_structured("scene_updated",
                                     elements_count=len(self.current_elements),
                                     mode="structured_output")
                
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
                
                # Detect contradictions using structured data
                await self._detect_contradictions(scene_data.model_dump())
            
            except Exception as e:
                logger.warning(f"Failed to parse structured scene extraction: {e}")
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
            "complexity_score": self._calculate_complexity_score(),
            "detected_topics": self.detected_topics,
            "branching_path": interview_branching.get_branching_path(self.session_id)
        }
    
    def get_branching_question(self, statement: str) -> Optional[Dict[str, Any]]:
        """
        Get a branching follow-up question based on the statement.
        
        Args:
            statement: The witness statement to analyze
            
        Returns:
            Branching question with metadata, or None if no relevant branch
        """
        statement_index = len([m for m in self.conversation_history if m['role'] == 'user'])
        return interview_branching.get_next_branching_question(
            self.session_id,
            statement,
            self.conversation_history,
            statement_index
        )
    
    def get_branching_path(self) -> Dict[str, Any]:
        """
        Get the complete interview branching path for audit.
        
        Returns:
            Dictionary with all branching nodes and explored topics
        """
        return interview_branching.get_branching_path(self.session_id)
    
    def get_suggested_topic(self, statement: str) -> Optional[str]:
        """
        Get a suggested unexplored topic to probe based on the statement.
        
        Args:
            statement: Latest witness statement
            
        Returns:
            Topic category string to explore, or None
        """
        topic = interview_branching.suggest_topic_to_explore(self.session_id, statement)
        return topic.value if topic else None
    
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
        self._log_structured("interview_completed",
                             total_statements=len([m for m in self.conversation_history if m["role"] == "user"]),
                             elements_count=len(self.current_elements),
                             branching_path=interview_branching.get_branching_path(self.session_id))
        self.conversation_history = []
        self.current_elements = []
        self.scene_description = ""
        self.contradictions = []
        self.key_facts = {}
        self.detected_topics = []
        self.chat = None
        # Reset branching state for this session
        interview_branching.reset_session(self.session_id)


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
