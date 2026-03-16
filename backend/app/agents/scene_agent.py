import logging
import json
import asyncio
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from app.config import settings
from app.models.schemas import SceneElement, WitnessStatement, SceneVersion, SceneExtractionResponse
from app.services.usage_tracker import usage_tracker
from app.services.response_cache import response_cache
from app.services.token_estimator import token_estimator, TokenEstimate, QuotaCheckResult
from app.services.interview_branching import interview_branching
from app.services.prompt_optimizer import prompt_optimizer
from app.services.timeline_disambiguator import timeline_disambiguator
from app.services.api_key_manager import get_genai_client
from google.genai import types
from app.services.model_selector import model_selector, call_with_retry, is_retryable_model_error
from typing import AsyncIterator
from app.agents.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_OPTIMIZED,
    SYSTEM_PROMPT_COMPACT,
    INITIAL_GREETING,
    CLARIFICATION_PROMPTS,
    CONTRADICTION_FOLLOW_UP,
    get_system_prompt,
    build_scene_extraction_prompt,
)

logger = logging.getLogger(__name__)


class SceneReconstructionAgent:
    """
    Core agent for managing witness interviews and scene reconstruction.
    Uses Gemini to understand witness statements, ask questions, and track scene state.
    Supports dynamic interview branching based on detected topics.
    Includes memory context from prior sessions for returning witnesses.
    """
    MAX_MODEL_STATEMENT_CHARS = 12_000
    
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
        self.memory_context: str = ""  # Context from prior sessions
        self.active_witness_id: Optional[str] = None  # Current witness for memory tracking
        self._current_prompt_level: str = "full"  # Track current prompt compression level
        self._pending_timeline_clarification: Optional[Dict[str, Any]] = None  # Timeline disambiguation
        self._timeline_events: List[Dict[str, Any]] = []  # Events for timeline building
        self._pending_completion_after_required_detail: bool = False
        self.last_response_kind: str = "interview"
        self.last_response_text: str = ""
        self._initialize_model()
    
    def _log_structured(self, event: str, **kwargs):
        """Emit structured log entry."""
        entry = {"event": event, "session_id": self.session_id, **kwargs}
        logger.info(json.dumps(entry))
    
    def _get_prompt_level_for_model(self, model_name: str) -> str:
        """Determine appropriate prompt compression level for model."""
        model_lower = model_name.lower()
        if any(x in model_lower for x in ["gemma", "4b", "12b"]):
            return "compact"
        elif any(x in model_lower for x in ["lite", "27b"]):
            return "optimized"
        return "full"

    @staticmethod
    def _is_retryable_model_error(error: Exception) -> bool:
        """Errors that should trigger model switch/fallback."""
        return is_retryable_model_error(error)

    def _truncate_statement_for_model(self, statement: str) -> str:
        """Trim oversized witness statements while preserving interview flow."""
        if not statement or len(statement) <= self.MAX_MODEL_STATEMENT_CHARS:
            return statement

        truncation_marker = "\n\n[... witness statement truncated for model limits ...]\n\n"
        payload_budget = max(0, self.MAX_MODEL_STATEMENT_CHARS - len(truncation_marker))
        if payload_budget <= 0:
            return statement[:self.MAX_MODEL_STATEMENT_CHARS]

        head_chars = int(payload_budget * 0.75)
        tail_chars = payload_budget - head_chars
        truncated = f"{statement[:head_chars]}{truncation_marker}{statement[-tail_chars:]}"

        self._log_structured(
            "statement_truncated",
            original_chars=len(statement),
            truncated_chars=len(truncated),
        )
        return truncated

    def _build_selected_prompt(self, model_name: Optional[str] = None) -> str:
        """Build the current system prompt, including memory context when available."""
        if model_name:
            self._current_prompt_level = self._get_prompt_level_for_model(model_name)

        selected_prompt = get_system_prompt(self._current_prompt_level)
        if self.memory_context:
            selected_prompt = f"{selected_prompt}\n{self.memory_context}"
        return selected_prompt

    def _extract_chat_history(self) -> List[Any]:
        """Read the SDK chat history so rebuilt chats keep prior witness context."""
        if not self.chat:
            return []

        for attr_name in ("_current_history", "get_history"):
            history_getter = getattr(self.chat, attr_name, None)
            if callable(history_getter):
                history = history_getter()
                if history:
                    return list(history)

        curated_history = getattr(self.chat, "_curated_history", None)
        if curated_history:
            return list(curated_history)
        return []

    def _create_chat_session(self, model_name: str):
        """Create a chat session with the right prompt and any existing history."""
        create_kwargs: Dict[str, Any] = {
            "model": model_name,
            "config": {
                "system_instruction": self._build_selected_prompt(model_name),
                "temperature": 0.4,
            },
        }
        history = self._extract_chat_history()
        if history:
            create_kwargs["history"] = history
        self.chat = self.client.chats.create(**create_kwargs)
        return self.chat

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Lowercase and normalize text for lightweight turn heuristics."""
        normalized = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _normalize_sentence_for_dedupe(self, sentence: str) -> str:
        """Normalize a sentence so minor phrasing differences still dedupe cleanly."""
        normalized = self._normalize_text(sentence)
        normalized = re.sub(r"^please\s+", "", normalized)
        normalized = re.sub(
            r"^(?:okay|ok|alright|well|thanks|thank you|got it|understood)\s+",
            "",
            normalized,
        )
        normalized = re.sub(r"^(?:please\s+)?(?:can|could|would|will)\s+you\s+", "", normalized)
        normalized = re.sub(r"^go ahead and\s+", "", normalized)
        normalized = re.sub(r"^just\s+", "", normalized)
        return normalized.strip()

    def _extract_report_intent_topic(self, statement: str) -> Optional[str]:
        """Return a friendly incident label for short report-intent openings."""
        normalized = self._normalize_text(statement)
        if not normalized:
            return None

        report_intent_markers = (
            r"\bi (?:want|would like|need|am here) to report\b",
            r"\bcan you (?:collect|take|file|make)? ?(?:the |a )?report\b",
            r"\bcould you (?:collect|take|file|make)? ?(?:the |a )?report\b",
            r"\bwould you (?:collect|take|file|make)? ?(?:the |a )?report\b",
            r"\bplease (?:collect|take|file|make)? ?(?:the |a )?report\b",
            r"\b(?:collect|take|file|make) (?:the |a )?report\b",
        )
        if not any(re.search(pattern, normalized) for pattern in report_intent_markers):
            return None

        topic_patterns = (
            ("hit-and-run", (r"\bhit and run\b",)),
            ("car crash", (r"\bcar crash\b", r"\bcar accident\b", r"\btraffic accident\b", r"\bvehicle accident\b", r"\bcollision\b", r"\bfender bender\b")),
            ("robbery", (r"\brobbery\b", r"\brobbed\b", r"\bmugging\b", r"\bhold up\b", r"\bstick up\b")),
            ("assault", (r"\bassault\b", r"\battack\b", r"\bfight\b", r"\bbeating\b")),
            ("theft", (r"\btheft\b", r"\bstole\b", r"\bstolen\b", r"\bstealing\b", r"\bburglary\b", r"\bbreak in\b")),
            ("vandalism", (r"\bvandalism\b", r"\bgraffiti\b", r"\bproperty damage\b", r"\bdamage\b")),
            ("suspicious activity", (r"\bsuspicious activity\b", r"\bsuspicious person\b", r"\bsuspicious vehicle\b")),
            ("domestic incident", (r"\bdomestic incident\b", r"\bdomestic dispute\b", r"\bfamily dispute\b")),
            ("crime", (r"\bcrime\b",)),
            ("incident", (r"\bincident\b",)),
        )
        for label, patterns in topic_patterns:
            if any(re.search(pattern, normalized) for pattern in patterns):
                return label

        if "crash" in normalized and ("car" in normalized or "vehicle" in normalized or "traffic" in normalized):
            return "car crash"
        if "accident" in normalized and ("car" in normalized or "vehicle" in normalized or "traffic" in normalized):
            return "car crash"
        return None

    def _is_topic_only_report_intent(self, statement: str) -> bool:
        """Detect early turns that only name the incident type instead of describing events."""
        normalized = self._normalize_text(statement)
        topic = self._extract_report_intent_topic(statement)
        if not normalized or not topic:
            return False

        topic_only_patterns = (
            r"^(?:i (?:want|would like|need|am here) to report|can you (?:collect|take|file|make)? ?(?:the |a )?report|could you (?:collect|take|file|make)? ?(?:the |a )?report|would you (?:collect|take|file|make)? ?(?:the |a )?report|please (?:collect|take|file|make)? ?(?:the |a )?report|(?:collect|take|file|make) (?:the |a )?report)(?: (?:against|about|for|of|on))? (?:a |an |the )?[a-z0-9\s-]+$",
            r"^i want to report (?:a |an |the )?[a-z0-9\s-]+$",
        )
        if not any(re.search(pattern, normalized) for pattern in topic_only_patterns):
            return False

        detail_markers = (
            "because",
            "after",
            "before",
            "when",
            "where",
            "around",
            "near",
            "at ",
            "on ",
            "today",
            "yesterday",
            "tonight",
            "this morning",
            "this afternoon",
            "this evening",
            "there was",
            "there were",
            "it happened",
            "i saw",
            "i heard",
            "someone",
            "somebody",
        )
        return not any(marker in normalized for marker in detail_markers)

    def _build_report_intent_follow_up(self, statement: str) -> Optional[str]:
        """Create a contextual first question for topic-only report-intent openings."""
        if not self._is_topic_only_report_intent(statement):
            return None

        topic = self._extract_report_intent_topic(statement)
        if not topic:
            return None
        return f"Okay. Tell me a little more about that {topic}."

    def _polish_response_style(self, response: str) -> str:
        """Light-touch cleanup so repaired and model responses stay conversational."""
        polished = (response or "").strip()
        if not polished:
            return ""

        polished = re.sub(r"\*\*(.*?)\*\*", r"\1", polished)
        polished = re.sub(r"\s+", " ", polished).strip()
        polished = re.sub(r"^thank you for reporting this[.!]?\s+", "Okay. ", polished, flags=re.IGNORECASE)
        polished = re.sub(r"^thanks for reporting this[.!]?\s+", "Okay. ", polished, flags=re.IGNORECASE)
        polished = re.sub(
            r"\bI want to make sure I capture the timeline accurately\.\s*",
            "",
            polished,
            flags=re.IGNORECASE,
        )
        polished = re.sub(
            r"\bBefore I finish the report,\s*",
            "Before I wrap this up, ",
            polished,
            flags=re.IGNORECASE,
        )
        polished = re.sub(
            r"^(Okay\.|Got it\.|All right\.|Alright\.|Understood\.)\s+(Okay\.|Got it\.|All right\.|Alright\.|Understood\.)\s+",
            r"\1 ",
            polished,
        )
        if polished and polished[0].islower():
            polished = polished[0].upper() + polished[1:]
        return polished.strip()

    def _dedupe_response_sentences(self, response: str) -> str:
        """Remove repeated sentences/questions from a single assistant turn."""
        base_response = (response or "").strip()
        if not base_response:
            return ""

        sentences = re.split(r"(?<=[.!?])\s+", base_response)
        deduped: List[str] = []
        seen_keys = set()
        for sentence in sentences:
            cleaned = sentence.strip()
            if not cleaned:
                continue
            dedupe_key = self._normalize_sentence_for_dedupe(cleaned)
            if dedupe_key and dedupe_key in seen_keys:
                continue
            if dedupe_key:
                seen_keys.add(dedupe_key)
            deduped.append(cleaned)

        return " ".join(deduped).strip() or base_response

    def _last_assistant_prompted_for_more(self) -> bool:
        """Check whether the previous assistant turn asked if the witness had more to add."""
        prompt_markers = (
            "anything else",
            "add more",
            "any more",
            "more details",
            "anything more",
            "anything further",
            "do you remember anything else",
            "is there anything else",
        )
        for message in reversed(self.conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return any(marker in content for marker in prompt_markers)
        return False

    def _witness_signaled_completion(self, statement: str) -> bool:
        """Heuristically detect when the witness indicates they are finished."""
        normalized = self._normalize_text(statement)
        if not normalized:
            return False

        limited_observation_patterns = (
            r"\bthat(?:s| is)? all i (?:can|could) (?:see|remember|recall|make out|tell)\b",
            r"\bthat(?:s| is)? all i (?:noticed|saw|heard)\b",
            r"\bi can(?:not| t)? remember anything else\b",
            r"\bi can(?:not| t)? see anything else\b",
        )
        if any(re.search(pattern, normalized) for pattern in limited_observation_patterns):
            return False

        explicit_phrases = (
            "im done",
            "i am done",
            "done talking",
            "thats everything",
            "that s everything",
            "that is everything",
            "i have nothing else",
            "i have nothing else to add",
            "i dont have anything else to add",
            "i do not have anything else to add",
            "there is nothing else to add",
            "thats all i have to add",
            "that s all i have to add",
            "that is all i have to add",
            "all set",
            "im finished",
            "i am finished",
        )
        if any(phrase in normalized for phrase in explicit_phrases):
            return True

        if normalized in {"done", "finished"}:
            return True

        prompted_completion_phrases = {
            "thats all",
            "that s all",
            "that is all",
            "thats it",
            "that s it",
            "nothing else",
            "no more",
            "no more details",
            "thats everything",
            "that s everything",
            "that is everything",
        }
        if self._last_assistant_prompted_for_more():
            prompted_normalized = re.sub(r"^(?:no|nope|nah)\s+", "", normalized).strip()
            if normalized in prompted_completion_phrases or prompted_normalized in prompted_completion_phrases:
                return True

        return normalized in {"no", "nope", "nah"} and self._last_assistant_prompted_for_more()

    @staticmethod
    def _build_completion_response(report_number: str = "") -> str:
        """Create a deterministic close-out response."""
        report_number = (report_number or "").strip()
        if report_number:
            return (
                f"Thank you for your report. Your report number is {report_number}. "
                "If you remember anything else later, you can use that number to add more details."
            )
        return (
            "Thank you for your report. I've saved what you've shared. "
            "If you remember anything else later, you can add more details."
        )

    def _should_skip_follow_up_repair(self, response: str) -> bool:
        """Skip local follow-up repair for technical or quota responses."""
        normalized = self._normalize_text(response)
        skip_markers = (
            "technical difficulties",
            "try again later",
            "temporarily rate limited",
            "high demand",
            "daily limit",
            "quota",
            "resource exhausted",
            "resource has been exhausted",
        )
        return any(marker in normalized for marker in skip_markers)

    def _response_restarts_interview(self, response: str, current_statement: str = "") -> bool:
        """Detect generic re-intros after the witness has already started the interview."""
        prior_user_turns = len([m for m in self.conversation_history if m.get("role") == "user"])
        if current_statement and current_statement.strip():
            prior_user_turns += 1
        if prior_user_turns < 1:
            return False

        normalized = self._normalize_text(response)
        generic_restart_markers = (
            "tell me what happened in your own words",
            "tell me what happened",
            "please tell me what happened",
            "go ahead and tell me what happened",
            "can you tell me what happened",
            "what can you help me with today",
        )
        intro_markers = (
            "im detective ray",
            "i m detective ray",
            "i am detective ray",
            "thank you for coming in",
            "here to take your report",
        )

        if not any(marker in normalized for marker in generic_restart_markers):
            return False
        if any(marker in normalized for marker in intro_markers):
            return True
        return len(normalized.split()) <= 24

    def _collect_user_text(self, current_statement: str = "") -> str:
        """Combine user statements so required-detail heuristics can inspect the interview so far."""
        parts = [
            (message.get("content") or "").strip()
            for message in self.conversation_history
            if message.get("role") == "user" and (message.get("content") or "").strip()
        ]
        if current_statement and current_statement.strip():
            parts.append(current_statement.strip())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def _statement_is_substantive(self, statement: str) -> bool:
        """Ignore trivial turns so required-timeline prompts do not fire too early."""
        normalized = self._normalize_text(statement)
        if not normalized:
            return False
        if self._is_topic_only_report_intent(statement):
            return False

        tokens = normalized.split()
        token_set = set(tokens)
        if len(tokens) < 3:
            return False
        if token_set <= {"yes", "yeah", "yep", "no", "nope", "nah", "ok", "okay", "maybe"}:
            return False
        if "report" in token_set and ({"crime", "incident", "accident"} & token_set) and len(tokens) <= 7:
            return False

        event_words = {
            "happened", "happen", "saw", "seen", "heard", "noticed", "hit", "crash",
            "crashed", "stole", "stolen", "grabbed", "ran", "running", "drove", "driving",
            "walked", "walking", "came", "approached", "started", "yelled", "said", "told",
        }
        return bool(token_set & event_words) or len(tokens) >= 6

    @staticmethod
    def _incident_day_status(text: str) -> str:
        """Return whether the interview already contains a usable incident day/date."""
        lowered = (text or "").lower()
        if not lowered:
            return "missing"

        unknown_patterns = (
            r"\b(?:don'?t know|do not know|not sure|can'?t remember|cannot remember|no idea|unsure)\b[^.?!]{0,40}\b(?:day|date)\b",
            r"\b(?:day|date)\b[^.?!]{0,40}\b(?:don'?t know|do not know|not sure|can'?t remember|cannot remember|no idea|unsure)\b",
            r"\b(?:don'?t know|do not know|not sure|can'?t remember|cannot remember|no idea|unsure)\s+when\s+(?:it|this|that)\s+happened\b",
        )
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in unknown_patterns):
            return "unknown"

        known_patterns = (
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b(?:today|yesterday|tonight|last night|this morning|this afternoon|this evening|earlier today|yesterday morning|yesterday afternoon|yesterday evening|last week)\b",
            r"\b(?:a couple of days ago|a couple days ago|a few days ago|a few days back|the other day|earlier this week|sometime last week|last weekend|recently)\b",
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?\b",
            r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
        )
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in known_patterns):
            return "known"
        return "missing"

    @staticmethod
    def _incident_time_status(text: str) -> str:
        """Return whether the interview already contains a usable incident time."""
        lowered = (text or "").lower()
        if not lowered:
            return "missing"

        unknown_patterns = (
            r"\b(?:don'?t know|do not know|not sure|can'?t remember|cannot remember|no idea|unsure)\b[^.?!]{0,40}\b(?:time|hour)\b",
            r"\b(?:time|hour)\b[^.?!]{0,40}\b(?:don'?t know|do not know|not sure|can'?t remember|cannot remember|no idea|unsure)\b",
            r"\b(?:don'?t know|do not know|not sure|can'?t remember|cannot remember|no idea|unsure)\s+when\s+(?:it|this|that)\s+happened\b",
        )
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in unknown_patterns):
            return "unknown"

        known_patterns = (
            r"\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?\b",
            r"\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?|o'?clock)\b",
            r"\b(?:morning|afternoon|evening|night|midnight|noon|sunrise|sunset|dawn|dusk)\b",
            r"\b(?:last night|this morning|this afternoon|this evening|tonight|yesterday morning|yesterday afternoon|yesterday evening)\b",
        )
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in known_patterns):
            return "known"
        return "missing"

    def _build_required_incident_timing_question(self, statement: str, *, closing: bool = False) -> Optional[str]:
        """Ask for incident day/time whenever that critical detail is still missing."""
        prior_user_turns = len([m for m in self.conversation_history if m.get("role") == "user"])
        if not closing and not self._statement_is_substantive(statement) and prior_user_turns < 1:
            return None

        conversation_text = self._collect_user_text(statement)
        if not conversation_text:
            return None

        day_status = self._incident_day_status(conversation_text)
        time_status = self._incident_time_status(conversation_text)
        if day_status != "missing" and time_status != "missing":
            return None

        prefix = "Before I wrap this up, " if closing else ""
        if day_status == "missing" and time_status == "missing":
            return f"{prefix}What day did this happen, and about what time was it?"
        if day_status == "missing":
            return f"{prefix}What day did this happen?"
        return f"{prefix}About what time was this?"

    def _response_asks_for_incident_timing(self, response: str) -> bool:
        """Detect whether the model already asked for day/date/time details."""
        normalized = self._normalize_text(response)
        prompt_markers = (
            "what day did this happen",
            "what date did this happen",
            "what day was this",
            "what day was it",
            "what date was it",
            "what day and about what time",
            "about what time did this happen",
            "what time did this happen",
            "what time did this start",
            "what time was it",
            "when did this happen",
            "when did it happen",
        )
        return any(marker in normalized for marker in prompt_markers)

    @staticmethod
    def _replace_follow_up_question(response: str, replacement_question: str) -> str:
        """Keep any short acknowledgment but replace unrelated question text."""
        base_response = (response or "").strip()
        if not base_response:
            return replacement_question

        prefix_parts = []
        for sentence in re.split(r"(?<=[.!?])\s+", base_response):
            cleaned = sentence.strip()
            if not cleaned:
                continue
            if "?" in cleaned:
                break
            prefix_parts.append(cleaned)

        prefix = " ".join(prefix_parts).strip()
        if not prefix:
            return replacement_question
        if prefix.endswith((".", "!", "?")):
            return f"{prefix} {replacement_question}"
        return f"{prefix}. {replacement_question}"

    def _build_repaired_interview_response(self, statement: str) -> str:
        """Replace reset-like replies with a contextual follow-up."""
        report_intent_follow_up = self._build_report_intent_follow_up(statement)
        if report_intent_follow_up:
            return report_intent_follow_up

        normalized = self._normalize_text(statement)
        tokens = set(normalized.split())
        if "report" in tokens and ({"crime", "incident", "accident"} & tokens):
            acknowledgment = ""
        else:
            acknowledgment = "Okay."

        next_question = self._build_required_incident_timing_question(statement) or self._build_follow_up_question(statement)
        if not acknowledgment:
            return next_question
        return f"{acknowledgment} {next_question}"

    def _build_follow_up_question(self, statement: str) -> str:
        """Fallback question when the model fails to continue the interview."""
        report_intent_follow_up = self._build_report_intent_follow_up(statement)
        if report_intent_follow_up:
            return report_intent_follow_up

        normalized = self._normalize_text(statement)
        tokens = set(normalized.split())

        if not tokens or tokens <= {"yes", "yeah", "yep", "ok", "okay"}:
            return "Tell me a little more about what happened."

        if "report" in tokens and ({"crime", "incident", "accident"} & tokens):
            return "Tell me a little more about what happened."

        weapon_words = {"gun", "knife", "weapon", "shot", "stabbed", "injured", "injury", "bleeding", "hurt"}
        vehicle_words = {"car", "truck", "van", "vehicle", "plate", "license", "motorcycle", "bike", "suv", "sedan"}
        person_words = {"man", "woman", "person", "suspect", "guy", "girl", "male", "female", "driver"}
        location_words = {"street", "road", "intersection", "parking", "store", "house", "apartment", "entrance"}
        time_words = {"before", "after", "later", "then", "when", "minute", "hour", "morning", "night"}

        if tokens & weapon_words:
            return "What do you remember about the weapon or any injuries?"
        if tokens & vehicle_words:
            return "What do you remember about the vehicle or where it went?"
        if tokens & person_words:
            return "What do you remember about the person?"
        if tokens & location_words:
            return "Where exactly was that?"
        if tokens & time_words:
            return "What happened right before that?"
        return "What else stands out to you about that?"

    def _ensure_follow_up_response(self, statement: str, response: str) -> str:
        """Make sure the agent keeps the interview moving after each witness turn."""
        base_response = self._polish_response_style(self._dedupe_response_sentences(response))
        if not base_response:
            self.last_response_kind = "interview"
            required_timing_question = self._build_required_incident_timing_question(statement)
            return self._polish_response_style(required_timing_question or self._build_follow_up_question(statement))

        if self._should_skip_follow_up_repair(base_response):
            self.last_response_kind = "error"
            return base_response

        required_timing_question = self._build_required_incident_timing_question(statement)
        if required_timing_question and not self._response_asks_for_incident_timing(base_response):
            self.last_response_kind = "interview"
            base_response = self._replace_follow_up_question(base_response, required_timing_question)
            base_response = self._polish_response_style(base_response)

        if self._response_restarts_interview(base_response, current_statement=statement):
            self.last_response_kind = "interview"
            return self._polish_response_style(self._build_repaired_interview_response(statement))

        if "?" in base_response:
            self.last_response_kind = "interview"
            return self._polish_response_style(base_response)

        follow_up = self._build_follow_up_question(statement)
        if base_response.endswith((".", "!", "?")):
            repaired = f"{base_response} {follow_up}"
        else:
            repaired = f"{base_response}. {follow_up}"
        self.last_response_kind = "interview"
        return self._polish_response_style(repaired)

    def _initialize_model(self):
        """Initialize the Gemini model for conversation."""
        try:
            if settings.google_api_key:
                self.client = get_genai_client()
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
        
        template_name = str(self.template.get("name", "incident")).strip().lower()
        return (
            f"Hi, I'm Detective Ray. I understand you'd like to report a {template_name}. "
            "Start wherever it makes sense, and tell me what happened."
        )
    
    async def load_witness_memories(self, witness_id: str, context_hint: str = "") -> str:
        """
        Load relevant memories for a witness into the agent's context.
        
        Args:
            witness_id: The witness ID
            context_hint: Optional current context to find relevant memories
            
        Returns:
            The memory context string added to the system prompt
        """
        try:
            from app.services.memory_service import memory_service
            
            self.active_witness_id = witness_id
            
            # Build memory context from prior sessions
            self.memory_context = await memory_service.build_memory_context(
                witness_id=witness_id,
                current_statement=context_hint or "starting interview",
                max_memories=5,
            )
            
            self._log_structured("memories_loaded", 
                               witness_id=witness_id,
                               context_length=len(self.memory_context))
            
            # If we have a chat, we'll inject memory context on next message
            return self.memory_context
        except Exception as e:
            logger.warning(f"Failed to load witness memories: {e}")
            return ""
    
    async def save_session_memories(self, witness_id: Optional[str] = None, case_id: Optional[str] = None) -> int:
        """
        Extract and save memories from the current session.
        
        Args:
            witness_id: Optional witness ID (uses active_witness_id if not provided)
            case_id: Optional case ID
            
        Returns:
            Number of memories saved
        """
        try:
            from app.services.memory_service import memory_service
            
            wid = witness_id or self.active_witness_id
            if not wid:
                logger.warning("No witness ID available for saving memories")
                return 0
            
            # Convert conversation history to statement format
            statements = [
                {"text": msg["content"], "timestamp": msg.get("timestamp")}
                for msg in self.conversation_history
                if msg["role"] == "user"
            ]
            
            if not statements:
                return 0
            
            memories = await memory_service.extract_memories_from_session(
                session_id=self.session_id,
                witness_id=wid,
                statements=statements,
                case_id=case_id,
            )
            
            self._log_structured("memories_saved",
                               witness_id=wid,
                               memories_count=len(memories))
            
            return len(memories)
        except Exception as e:
            logger.error(f"Failed to save session memories: {e}")
            return 0
    
    async def process_statement(
        self,
        statement: str,
        is_correction: bool = False,
        report_number: str = "",
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
            self.last_response_kind = "error"
            self.last_response_text = "I'm sorry, I'm having technical difficulties. Please try again later."
            return self.last_response_text, False, None

        if self._pending_completion_after_required_detail:
            agent_response = self._build_required_incident_timing_question(statement, closing=True)
            if agent_response:
                self.last_response_kind = "interview"
            else:
                agent_response = self._build_completion_response(report_number)
                self.last_response_kind = "completion"
                self._pending_completion_after_required_detail = False
            self.last_response_text = agent_response
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat(),
                "detected_topics": [],
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": agent_response,
                "timestamp": datetime.utcnow().isoformat(),
            })
            return agent_response, False, None

        if self._witness_signaled_completion(statement):
            required_timing_question = self._build_required_incident_timing_question(statement, closing=True)
            if required_timing_question:
                agent_response = required_timing_question
                self.last_response_kind = "interview"
                self._pending_completion_after_required_detail = True
            else:
                agent_response = self._build_completion_response(report_number)
                self.last_response_kind = "completion"
                self._pending_completion_after_required_detail = False
            self.last_response_text = agent_response
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat(),
                "detected_topics": [],
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": agent_response,
                "timestamp": datetime.utcnow().isoformat(),
            })
            return agent_response, False, None
        
        try:
            # Initialize chat if not already done (lazy init with best model)
            if not self.chat:
                chat_model = await model_selector.get_best_model_for_task("chat")
                self._create_chat_session(chat_model)
                self._log_structured("chat_initialized", 
                                     model=chat_model,
                                     prompt_level=self._current_prompt_level)
            
            # Add context if this is a correction
            if is_correction:
                statement = f"[CORRECTION] {statement}"
            # Wrap user input in structured boundary to prevent prompt injection
            statement_for_model = f"<witness_statement>\n{self._truncate_statement_for_model(statement)}\n</witness_statement>"
            
            # Get current model for pre-check
            current_model = getattr(self.chat, '_model', None) or getattr(self.chat, 'model', settings.gemini_model)
            
            # Get current prompt for quota estimation
            current_prompt = self._build_selected_prompt(current_model)
            
            # Optimize history if needed (compress older messages)
            optimized_history = self.conversation_history
            if len(self.conversation_history) > 6:
                optimized_history, hist_stats = prompt_optimizer.summarize_history(
                    self.conversation_history,
                    max_messages=6
                )
                if hist_stats.tokens_saved > 0:
                    self._log_structured("history_compressed",
                                         tokens_saved=hist_stats.tokens_saved)
            
            # Pre-check token quota before sending request
            quota_check, token_estimate = usage_tracker.precheck_request(
                model_name=current_model,
                prompt=statement_for_model,
                system_prompt=current_prompt,
                history=optimized_history,
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
                self.last_response_kind = "error"
                self.last_response_text = (
                    f"I'm sorry, I'm currently at my daily limit. {quota_check.rejection_reason} "
                    "Please try again tomorrow or use a lighter request."
                )
                return (self.last_response_text, False, token_info)
            
            # Send to Gemini with automatic model fallback on rate limit
            response = None
            
            for attempt in range(3):
                try:
                    response = await call_with_retry(
                        asyncio.to_thread,
                        self.chat.send_message,
                        statement_for_model,
                        model_name=current_model,
                        task_type="chat",
                    )
                    break
                except Exception as e:
                    if self._is_retryable_model_error(e):
                        # Mark current model as rate limited
                        if hasattr(self.chat, '_model'):
                            current_model = self.chat._model
                        elif hasattr(self.chat, 'model'):
                            current_model = self.chat.model
                        else:
                            current_model = settings.gemini_model
                        
                        logger.warning(f"Model unavailable/rate-limited on {current_model}, switching model...")
                        await model_selector.mark_rate_limited(current_model)
                        
                        # Try a different model
                        new_model = await model_selector.get_best_model_for_task("chat")
                        if new_model != current_model:
                            self._create_chat_session(new_model)
                            self._log_structured("model_switched",
                                                 old_model=current_model,
                                                 new_model=new_model,
                                                 prompt_level=self._current_prompt_level)
                            current_model = new_model
                            continue
                        
                        # If same model (all are rate limited), wait and retry
                        wait_time = (attempt + 1) * 10
                        logger.warning(f"All models rate limited, waiting {wait_time}s (attempt {attempt+1}/3)")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            if not response:
                self.last_response_kind = "error"
                self.last_response_text = "I'm temporarily rate limited. Please wait a moment and try again."
                return self.last_response_text, False, token_info
            
            agent_response = self._ensure_follow_up_response(statement, getattr(response, "text", "") or "")
            self.last_response_text = agent_response
            current_model = getattr(self.chat, '_model', None) or getattr(self.chat, 'model', current_model)
            
            # Track usage with actual token counts
            input_tokens = self._estimate_tokens(statement_for_model)
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
            
            # Detect timeline references and check for disambiguation needs
            time_refs = timeline_disambiguator.detect_time_references(statement, statement_index)
            if time_refs:
                self._log_structured("time_refs_detected",
                                     count=len(time_refs),
                                     types=[r.type.value for r in time_refs])
            
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
            
            should_generate_candidate = self._should_generate_image(agent_response)

            # Extract scene information before deciding whether rendering is worthwhile.
            if should_generate_candidate or len(self.conversation_history) > 6:
                await self._extract_scene_information()

            should_generate = should_generate_candidate and self._scene_has_renderable_detail()
            
            self._log_structured("statement_processed",
                                 model=current_model or "chat",
                                 tokens_estimated=token_estimate.total_tokens,
                                 actual_tokens=input_tokens + output_tokens,
                                 elements_count=len(self.current_elements))
            return agent_response, should_generate, token_info
        
        except Exception as e:
            if self._is_retryable_model_error(e):
                self.last_response_kind = "error"
                self._log_structured("error_rate_limited", error=str(e)[:200])
                self.last_response_text = (
                    "I'm experiencing high demand right now. Could you please "
                    "repeat that in a moment? Your testimony is important."
                )
                return (self.last_response_text, False, None)
            elif "400" in str(e) or "INVALID_ARGUMENT" in str(e):
                self.last_response_kind = "error"
                self._log_structured("error_invalid_request", error=str(e)[:200])
                self.last_response_text = "I had trouble processing that. Could you rephrase?"
                return (self.last_response_text, False, None)
            else:
                self.last_response_kind = "error"
                self._log_structured("error_unexpected", error=str(e)[:200])
                logger.error(f"Unexpected error processing statement: {e}", exc_info=True)
                raise
    
    async def process_statement_streaming(
        self,
        statement: str,
        is_correction: bool = False,
        report_number: str = "",
    ) -> AsyncIterator[Tuple[str, bool, bool, Optional[Dict[str, Any]]]]:
        """
        Process a witness statement with streaming response.
        
        Yields:
            Tuple of (text_chunk, is_final, should_generate_image, token_info)
            token_info is only provided on the final chunk
        """
        if not self.client:
            self.last_response_kind = "error"
            self.last_response_text = "I'm sorry, I'm having technical difficulties. Please try again later."
            yield self.last_response_text, True, False, None
            return

        if self._pending_completion_after_required_detail:
            completion_response = self._build_required_incident_timing_question(statement, closing=True)
            if completion_response:
                self.last_response_kind = "interview"
            else:
                completion_response = self._build_completion_response(report_number)
                self.last_response_kind = "completion"
                self._pending_completion_after_required_detail = False
            self.last_response_text = completion_response
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat(),
                "detected_topics": [],
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": completion_response,
                "timestamp": datetime.utcnow().isoformat(),
            })
            yield completion_response, False, False, None
            yield "", True, False, None
            return

        if self._witness_signaled_completion(statement):
            required_timing_question = self._build_required_incident_timing_question(statement, closing=True)
            if required_timing_question:
                completion_response = required_timing_question
                self.last_response_kind = "interview"
                self._pending_completion_after_required_detail = True
            else:
                completion_response = self._build_completion_response(report_number)
                self.last_response_kind = "completion"
                self._pending_completion_after_required_detail = False
            self.last_response_text = completion_response
            self.conversation_history.append({
                "role": "user",
                "content": statement,
                "timestamp": datetime.utcnow().isoformat(),
                "detected_topics": [],
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": completion_response,
                "timestamp": datetime.utcnow().isoformat(),
            })
            yield completion_response, False, False, None
            yield "", True, False, None
            return
        
        try:
            # Initialize chat if not already done
            if not self.chat:
                chat_model = await model_selector.get_best_model_for_task("chat")
                self._create_chat_session(chat_model)
                self._log_structured("chat_initialized", 
                                     model=chat_model,
                                     has_memory_context=bool(self.memory_context))
            
            if is_correction:
                statement = f"[CORRECTION] {statement}"
            # Wrap user input in structured boundary to prevent prompt injection
            statement_for_model = f"<witness_statement>\n{self._truncate_statement_for_model(statement)}\n</witness_statement>"
            
            # Get current model for pre-check
            current_model = getattr(self.chat, '_model', None) or getattr(self.chat, 'model', settings.gemini_model)
            current_prompt = self._build_selected_prompt(current_model)
            
            # Pre-check token quota before sending request
            quota_check, token_estimate = usage_tracker.precheck_request(
                model_name=current_model,
                prompt=statement_for_model,
                system_prompt=current_prompt,
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
                self.last_response_kind = "error"
                self.last_response_text = (
                    f"I'm sorry, I'm currently at my daily limit. {quota_check.rejection_reason} "
                    "Please try again tomorrow or use a lighter request."
                )
                yield (self.last_response_text, True, False, token_info)
                return
            
            # Use streaming with Gemini
            full_response = ""
            
            for attempt in range(3):
                try:
                    # Prefer native streaming when available; fall back to non-streaming.
                    if hasattr(self.chat, "send_message_stream"):
                        response_stream = await asyncio.to_thread(
                            self.chat.send_message_stream,
                            statement_for_model,
                        )

                        # Yield chunks as they arrive
                        for chunk in response_stream:
                            if hasattr(chunk, 'text') and chunk.text:
                                full_response += chunk.text
                                yield chunk.text, False, False, None
                    else:
                        response = await asyncio.to_thread(
                            self.chat.send_message,
                            statement_for_model,
                        )
                        response_text = (getattr(response, "text", "") or "").strip()
                        if response_text:
                            full_response += response_text
                            yield response_text, False, False, None
                    break
                    
                except Exception as e:
                    if self._is_retryable_model_error(e):
                        if hasattr(self.chat, '_model'):
                            current_model = self.chat._model
                        elif hasattr(self.chat, 'model'):
                            current_model = self.chat.model
                        else:
                            current_model = settings.gemini_model
                        
                        logger.warning(f"Model unavailable/rate-limited on {current_model}, switching model...")
                        await model_selector.mark_rate_limited(current_model)
                        
                        new_model = await model_selector.get_best_model_for_task("chat")
                        if new_model != current_model:
                            self._log_structured("model_switched",
                                                 old_model=current_model,
                                                 new_model=new_model)
                            self._create_chat_session(new_model)
                            current_model = new_model
                            continue
                        
                        wait_time = (attempt + 1) * 10
                        logger.warning(f"All models rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            if not full_response:
                self.last_response_kind = "error"
                self.last_response_text = "I'm temporarily rate limited. Please wait a moment and try again."
                yield self.last_response_text, True, False, token_info
                return

            repaired_response = self._ensure_follow_up_response(statement, full_response)
            full_response = repaired_response
            self.last_response_text = full_response
            current_model = getattr(self.chat, '_model', None) or getattr(self.chat, 'model', current_model)
            
            # Track usage with actual token counts
            input_tokens = self._estimate_tokens(statement_for_model)
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
            
            should_generate_candidate = self._should_generate_image(full_response)

            if should_generate_candidate or len(self.conversation_history) > 6:
                await self._extract_scene_information()

            should_generate = should_generate_candidate and self._scene_has_renderable_detail()
            
            self._log_structured("statement_processed_streaming",
                                 model=current_model or "chat",
                                 tokens_estimated=token_estimate.total_tokens,
                                 actual_tokens=input_tokens + output_tokens,
                                 elements_count=len(self.current_elements))
            
            # Yield final signal with token info
            yield "", True, should_generate, token_info
        
        except Exception as e:
            if self._is_retryable_model_error(e):
                self.last_response_kind = "error"
                self._log_structured("error_rate_limited", error=str(e)[:200])
                self.last_response_text = "I'm experiencing high demand right now. Could you please repeat that in a moment?"
                yield self.last_response_text, True, False, None
            elif "400" in str(e) or "INVALID_ARGUMENT" in str(e):
                self.last_response_kind = "error"
                self._log_structured("error_invalid_request", error=str(e)[:200])
                self.last_response_text = "I had trouble processing that. Could you rephrase?"
                yield self.last_response_text, True, False, None
            else:
                self.last_response_kind = "error"
                self._log_structured("error_unexpected", error=str(e)[:200])
                logger.error(f"Unexpected error processing statement: {e}", exc_info=True)
                self.last_response_text = f"An error occurred: {str(e)}"
                yield self.last_response_text, True, False, None
    
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

    def _scene_has_renderable_detail(self) -> bool:
        """Return True when the extracted scene is detailed enough to render."""
        description = (self.scene_description or "").strip()
        if len(description) < 80:
            return False

        if len(self.current_elements) < 2:
            return False

        generic_markers = (
            "witness described an incident",
            "incident scene",
            "reported incident",
            "scene still unclear",
            "limited detail",
            "unknown location",
        )
        if any(marker in description.lower() for marker in generic_markers) and len(self.current_elements) < 4:
            return False

        high_confidence_elements = sum(
            1
            for element in self.current_elements
            if float(getattr(element, "confidence", 0.0) or 0.0) >= max(0.45, settings.low_confidence_threshold)
            and (element.description or "").strip()
        )
        return high_confidence_elements >= 2 or len(self.current_elements) >= 4
    
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
                    task_type="lightweight",
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
    
    def _detect_incident_type_from_conversation(self, conversation_text: str) -> Optional[str]:
        """Detect incident type from conversation text for few-shot example selection.
        
        Args:
            conversation_text: The full conversation text
            
        Returns:
            Incident type string or None if unclear
        """
        text_lower = conversation_text.lower()
        
        # Traffic accident keywords
        if any(kw in text_lower for kw in ['collision', 'crashed', 'ran the light', 'ran the red', 
                                            'car accident', 'vehicle accident', 'fender bender']):
            return "traffic_accident"
        
        # Hit and run keywords
        if any(kw in text_lower for kw in ['hit and run', 'didn\'t stop', 'drove off', 'fled', 
                                            'pedestrian hit', 'struck and left']):
            return "hit_and_run"
        
        # Armed robbery keywords
        if any(kw in text_lower for kw in ['gun', 'weapon', 'robbery', 'robbed', 'stick up', 
                                            'holdup', 'hold up', 'pointed at']):
            return "armed_robbery"
        
        # Assault keywords
        if any(kw in text_lower for kw in ['punch', 'beat', 'assault', 'attacked', 'fight', 
                                            'hitting', 'beating']):
            return "assault"
        
        # Theft keywords
        if any(kw in text_lower for kw in ['stole', 'stolen', 'theft', 'stealing', 'took my', 
                                            'package theft', 'shoplifting']):
            return "theft"
        
        return None
    
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
            
            # Detect incident type hints from conversation for selecting relevant examples
            detected_incident_type = self._detect_incident_type_from_conversation(conversation_text)
            
            # Build extraction prompt with few-shot examples
            base_prompt = build_scene_extraction_prompt(
                include_examples=True,
                incident_type=detected_incident_type,
                compact=False  # Use full examples for better accuracy
            )
            
            extraction_prompt = f"""{base_prompt}

Analyze this witness interview and extract all scene information.

Conversation:
{conversation_text}

Extract every detail mentioned: people, vehicles, objects, locations, timeline, environmental conditions.

CONFIDENCE SCORING GUIDELINES (0.0-1.0):
- 0.9-1.0: Very specific details with exact values (e.g., "red Honda Civic", "6 feet tall")
- 0.7-0.9: Clear descriptions with some specifics (e.g., "dark colored sedan", "about 30 years old")
- 0.5-0.7: General descriptions lacking details (e.g., "a car", "a man")
- 0.3-0.5: Vague or uncertain mentions (e.g., "I think there was a car", "maybe someone")
- 0.0-0.3: Highly uncertain or contradicted information

Rate each element and timeline event confidence based on specificity and witness certainty.
Items with confidence below 0.7 will be flagged for review."""
            
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
                    task_type="scene",
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
                
                # Update elements from structured response with confidence thresholds
                self.current_elements = []
                for i, elem_data in enumerate(scene_data.elements):
                    confidence = elem_data.confidence
                    # Flag for review if below confidence threshold
                    needs_review = confidence < settings.confidence_threshold
                    element = SceneElement(
                        id=f"elem_{self.session_id}_{i}",
                        type=elem_data.type,
                        description=elem_data.description,
                        position=elem_data.position,
                        color=elem_data.color,
                        size=elem_data.size,
                        confidence=confidence,
                        needs_review=needs_review,
                        relationships=[],
                        evidence_tags=[]
                    )
                    self.current_elements.append(element)
                
                # Log elements flagged for review
                review_count = sum(1 for e in self.current_elements if e.needs_review)
                self._log_structured("scene_updated",
                                     elements_count=len(self.current_elements),
                                     needs_review_count=review_count,
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
        self.memory_context = ""
        self.active_witness_id = None
        self.last_response_kind = "interview"
        self.chat = None
        self._pending_completion_after_required_detail = False
        # Reset branching state for this session
        interview_branching.reset_session(self.session_id)
        # Reset timeline disambiguation state
        timeline_disambiguator.reset_session(self.session_id)
        self._pending_timeline_clarification = None
        self._timeline_events = []
    
    def get_timeline_disambiguation_prompt(self) -> Optional[Dict[str, Any]]:
        """
        Check if timeline disambiguation is needed and return a clarifying question.
        
        Returns:
            Dict with disambiguation question and metadata, or None
        """
        if len(self.conversation_history) < 4:
            return None
        
        # Prepare statements for analysis
        user_statements = [
            {"content": msg["content"]}
            for msg in self.conversation_history
            if msg["role"] == "user"
        ]
        
        # Get recent events mentioned (from scene elements and timeline)
        events_mentioned = [
            e.description[:40] for e in self.current_elements[:5]
        ] if self.current_elements else []
        
        # Check if disambiguation is needed
        prompt = timeline_disambiguator.get_next_disambiguation_prompt(
            self.session_id,
            user_statements,
            events_mentioned
        )
        
        if prompt:
            self._pending_timeline_clarification = prompt
            self._log_structured("timeline_disambiguation_needed",
                                 target_ref=prompt.get("target_reference"),
                                 clarity_issue=prompt.get("clarity_issue"))
        
        return prompt
    
    def get_timeline_clarity_analysis(self) -> Dict[str, Any]:
        """
        Get analysis of the current timeline clarity.
        
        Returns:
            Dict with clarity scores and issues
        """
        user_statements = [
            {"content": msg["content"]}
            for msg in self.conversation_history
            if msg["role"] == "user"
        ]
        
        return timeline_disambiguator.analyze_timeline_clarity(
            self.session_id,
            user_statements
        )
    
    def build_disambiguated_timeline(self) -> List[Dict[str, Any]]:
        """
        Build a relative timeline from the conversation with disambiguation status.
        
        Returns:
            List of timeline events with clarity indicators
        """
        # Extract events from conversation for timeline
        events = []
        for idx, msg in enumerate(self.conversation_history):
            if msg["role"] == "user":
                events.append({
                    "description": msg["content"][:100],
                    "time_ref": msg["content"],
                    "statement_index": idx,
                })
        
        # Build the timeline
        disambiguated = timeline_disambiguator.build_relative_timeline(
            self.session_id,
            events
        )
        
        self._log_structured("timeline_built",
                             event_count=len(disambiguated),
                             needs_clarification=sum(1 for e in disambiguated if e.needs_clarification))
        
        return [
            {
                "id": e.id,
                "description": e.description,
                "sequence": e.sequence,
                "original_time_ref": e.original_time_ref,
                "clarity": e.clarity.value,
                "confidence": e.confidence,
                "needs_clarification": e.needs_clarification,
                "clarification_question": e.clarification_question,
                "relative_position": e.offset_description,
            }
            for e in disambiguated
        ]
    
    def apply_timeline_clarification(self, event_id: str, clarification: Dict[str, Any]) -> bool:
        """
        Apply a witness's clarification to a timeline event.
        
        Args:
            event_id: ID of the event being clarified
            clarification: Dict with 'offset_description', 'relative_to', 'sequence'
            
        Returns:
            True if applied successfully
        """
        success = timeline_disambiguator.apply_clarification(
            self.session_id,
            event_id,
            clarification
        )
        
        if success:
            self._pending_timeline_clarification = None
            self._log_structured("timeline_clarification_applied", event_id=event_id)
        
        return success
    
    def get_pending_timeline_clarifications(self) -> List[Dict[str, Any]]:
        """Get events that still need timeline clarification."""
        return timeline_disambiguator.get_pending_clarifications(self.session_id)
    
    async def reset_async(self, save_memories: bool = True, case_id: Optional[str] = None):
        """
        Async reset that optionally saves memories before clearing state.
        
        Args:
            save_memories: Whether to extract and save memories from this session
            case_id: Optional case ID for memory association
        """
        if save_memories and self.active_witness_id and self.conversation_history:
            await self.save_session_memories(case_id=case_id)
        
        self.reset()


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
