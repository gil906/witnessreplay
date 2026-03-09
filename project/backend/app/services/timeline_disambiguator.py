"""Timeline disambiguation service for witness interviews.

Helps witnesses clarify temporal relationships by:
- Detecting vague time references
- Asking clarifying questions about sequence
- Building relative timeline from responses
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TimeReferenceType(Enum):
    """Types of time references found in statements."""
    ABSOLUTE = "absolute"  # "at 3:00 PM", "around noon"
    RELATIVE = "relative"  # "a few minutes later", "shortly after"
    VAGUE = "vague"        # "at some point", "eventually"
    SEQUENCE = "sequence"  # "first", "then", "next"
    DURATION = "duration"  # "for about 5 minutes"


class ClarityLevel(Enum):
    """How clear a time reference is."""
    CLEAR = "clear"
    NEEDS_ANCHOR = "needs_anchor"  # Relative but no anchor point
    AMBIGUOUS = "ambiguous"        # Could mean different things
    UNKNOWN = "unknown"            # No temporal info at all


@dataclass
class TimeReference:
    """A time reference extracted from a statement."""
    text: str                      # Original text fragment
    type: TimeReferenceType
    clarity: ClarityLevel
    anchor_event: Optional[str] = None  # What it's relative to
    estimated_offset_seconds: Optional[int] = None
    statement_index: int = 0
    confidence: float = 0.5
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class TimelineAnchor:
    """A fixed point in the timeline used to resolve relative references."""
    id: str
    description: str
    event_time: Optional[datetime] = None
    relative_position: int = 0  # Ordering when no absolute time
    source_statement_index: int = 0
    confidence: float = 0.7


@dataclass
class DisambiguatedEvent:
    """An event with clarified temporal positioning."""
    id: str
    description: str
    sequence: int
    original_time_ref: str
    clarity: ClarityLevel
    anchor_id: Optional[str] = None
    relative_to_anchor: str = ""  # "before", "after", "during"
    offset_description: str = ""  # "about 2 minutes after"
    confidence: float = 0.5
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# Patterns for detecting different time reference types
ABSOLUTE_TIME_PATTERNS = [
    r'\b(\d{1,2}:\d{2})\s*(am|pm|AM|PM)?\b',
    r'\b(noon|midnight|morning|afternoon|evening)\b',
    r'\b(around|about|approximately)\s+(\d{1,2})\s*(am|pm|o\'?clock)\b',
    r'\b(\d{1,2})\s*(am|pm|AM|PM)\b',
    r'\b(sunrise|sunset|dusk|dawn)\b',
]

RELATIVE_TIME_PATTERNS = [
    (r'\b(a few|several|a couple of?|some)\s+(minutes?|seconds?|hours?)\s+(later|before|after)\b', 'vague_duration'),
    (r'\b(shortly|right|immediately|soon)\s+(after|before)\b', 'short_offset'),
    (r'\b(about|around|roughly)\s+(\d+)\s+(minutes?|seconds?|hours?)\s+(later|earlier|before|after)\b', 'estimated_duration'),
    (r'\b(\d+)\s+(minutes?|seconds?|hours?)\s+(later|earlier|before|after)\b', 'specific_duration'),
    (r'\b(moments?|instant)\s+(later|before)\b', 'very_short'),
    (r'\bwhen\s+(that|this|it)\s+happened\b', 'concurrent'),
    (r'\b(while|during|as)\s+\w+\s+(was|were)\b', 'concurrent'),
    (r'\b(at the same time|simultaneously)\b', 'concurrent'),
]

VAGUE_TIME_PATTERNS = [
    r'\b(at some point|eventually|at one point|sometime)\b',
    r'\b(I\'m not sure when|not sure of the time|can\'t remember when)\b',
    r'\b(before I knew it|next thing I knew)\b',
    r'\b(it all happened so fast|happened quickly)\b',
    r'\b(I think it was|maybe|probably)\s+(before|after|around)\b',
]

SEQUENCE_PATTERNS = [
    (r'\b(first|firstly|to start|initially|to begin with)\b', 1),
    (r'\b(then|next|after that|afterwards|following that)\b', 0),  # 0 = relative
    (r'\b(finally|lastly|in the end|eventually|at last)\b', 99),
    (r'\b(second|secondly)\b', 2),
    (r'\b(third|thirdly)\b', 3),
    (r'\b(before\s+that|prior to that|earlier)\b', -1),  # -1 = before current
]

# Clarification question templates
DISAMBIGUATION_QUESTIONS = {
    'no_anchor': [
        "You mentioned this happened {time_ref}. Can you help me understand what it was relative to? What happened just before?",
        "When you say {time_ref}, what were you comparing it to? What event did this come after?",
    ],
    'vague_duration': [
        "You said {time_ref}. Can you estimate roughly how long that was — seconds, a minute, or several minutes?",
        "When you mentioned {time_ref}, was that more like 30 seconds or closer to 5 minutes?",
    ],
    'sequence_unclear': [
        "I want to make sure I have the order right. Did {event_a} happen before or after {event_b}?",
        "Help me understand the sequence: which came first — {event_a} or {event_b}?",
    ],
    'confirm_sequence': [
        "So just to confirm: first {event_a}, then {event_b}. Is that correct?",
        "Let me make sure I have the timeline right: {event_a} happened, and then {event_b}. Did I get that right?",
    ],
    'anchor_needed': [
        "When you say {time_ref}, what had just happened before that moment?",
        "Can you tie {time_ref} to something specific that happened? What did you notice right before or after?",
    ],
    'estimate_gap': [
        "Roughly how much time passed between {event_a} and {event_b}?",
        "Was there a gap between {event_a} and {event_b}, or did they happen almost back-to-back?",
    ],
}


class TimelineDisambiguator:
    """Service for detecting and clarifying vague time references in witness statements."""
    
    def __init__(self):
        self._session_timelines: Dict[str, Dict[str, Any]] = {}
    
    def detect_time_references(
        self,
        statement: str,
        statement_index: int = 0
    ) -> List[TimeReference]:
        """
        Detect all time references in a statement.
        
        Args:
            statement: The witness statement text
            statement_index: Index of this statement in the conversation
            
        Returns:
            List of detected time references
        """
        references: List[TimeReference] = []
        statement_lower = statement.lower()
        
        # Check for absolute times
        for pattern in ABSOLUTE_TIME_PATTERNS:
            matches = re.finditer(pattern, statement_lower, re.IGNORECASE)
            for match in matches:
                references.append(TimeReference(
                    text=match.group(0),
                    type=TimeReferenceType.ABSOLUTE,
                    clarity=ClarityLevel.CLEAR,
                    statement_index=statement_index,
                    confidence=0.9,
                ))
        
        # Check for relative times
        for pattern, subtype in RELATIVE_TIME_PATTERNS:
            matches = re.finditer(pattern, statement_lower, re.IGNORECASE)
            for match in matches:
                # Determine clarity based on subtype
                if subtype == 'specific_duration':
                    clarity = ClarityLevel.CLEAR
                    conf = 0.85
                elif subtype == 'estimated_duration':
                    clarity = ClarityLevel.NEEDS_ANCHOR
                    conf = 0.7
                elif subtype == 'vague_duration':
                    clarity = ClarityLevel.AMBIGUOUS
                    conf = 0.5
                else:
                    clarity = ClarityLevel.NEEDS_ANCHOR
                    conf = 0.6
                
                references.append(TimeReference(
                    text=match.group(0),
                    type=TimeReferenceType.RELATIVE,
                    clarity=clarity,
                    statement_index=statement_index,
                    confidence=conf,
                ))
        
        # Check for vague times
        for pattern in VAGUE_TIME_PATTERNS:
            matches = re.finditer(pattern, statement_lower, re.IGNORECASE)
            for match in matches:
                references.append(TimeReference(
                    text=match.group(0),
                    type=TimeReferenceType.VAGUE,
                    clarity=ClarityLevel.AMBIGUOUS,
                    statement_index=statement_index,
                    confidence=0.3,
                ))
        
        # Check for sequence indicators
        for pattern, seq in SEQUENCE_PATTERNS:
            matches = re.finditer(pattern, statement_lower, re.IGNORECASE)
            for match in matches:
                references.append(TimeReference(
                    text=match.group(0),
                    type=TimeReferenceType.SEQUENCE,
                    clarity=ClarityLevel.NEEDS_ANCHOR if seq == 0 else ClarityLevel.CLEAR,
                    statement_index=statement_index,
                    confidence=0.75,
                ))
        
        logger.debug(f"Detected {len(references)} time references in statement {statement_index}")
        return references
    
    def analyze_timeline_clarity(
        self,
        session_id: str,
        statements: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze the overall clarity of timeline from all statements.
        
        Args:
            session_id: Session identifier
            statements: List of statement dicts with 'content' key
            
        Returns:
            Analysis dict with clarity score and issues
        """
        all_refs: List[TimeReference] = []
        
        for idx, stmt in enumerate(statements):
            content = stmt.get('content', '')
            refs = self.detect_time_references(content, idx)
            all_refs.extend(refs)
        
        # Calculate clarity metrics
        total_refs = len(all_refs)
        if total_refs == 0:
            return {
                "overall_clarity": "unknown",
                "clarity_score": 0.0,
                "has_anchor_points": False,
                "vague_references": 0,
                "clear_references": 0,
                "needs_disambiguation": True,
                "issues": ["No time references found in statements"],
            }
        
        clear_refs = [r for r in all_refs if r.clarity == ClarityLevel.CLEAR]
        vague_refs = [r for r in all_refs if r.clarity in (ClarityLevel.AMBIGUOUS, ClarityLevel.UNKNOWN)]
        needs_anchor = [r for r in all_refs if r.clarity == ClarityLevel.NEEDS_ANCHOR]
        
        clarity_score = len(clear_refs) / total_refs
        
        issues = []
        if vague_refs:
            issues.append(f"{len(vague_refs)} vague time reference(s): {[r.text for r in vague_refs[:3]]}")
        if needs_anchor:
            issues.append(f"{len(needs_anchor)} relative reference(s) need anchor points")
        
        # Check for absolute anchors
        has_absolute = any(r.type == TimeReferenceType.ABSOLUTE for r in all_refs)
        
        return {
            "overall_clarity": "high" if clarity_score > 0.7 else "medium" if clarity_score > 0.4 else "low",
            "clarity_score": round(clarity_score, 2),
            "has_anchor_points": has_absolute,
            "vague_references": len(vague_refs),
            "clear_references": len(clear_refs),
            "needs_anchor_count": len(needs_anchor),
            "total_references": total_refs,
            "needs_disambiguation": clarity_score < 0.6 or len(needs_anchor) > 2,
            "issues": issues,
            "references": [
                {
                    "text": r.text,
                    "type": r.type.value,
                    "clarity": r.clarity.value,
                    "confidence": r.confidence,
                    "statement_index": r.statement_index,
                }
                for r in all_refs
            ]
        }
    
    def generate_disambiguation_question(
        self,
        session_id: str,
        time_ref: TimeReference,
        recent_events: List[str] = None
    ) -> Optional[str]:
        """
        Generate a clarifying question for a vague time reference.
        
        Args:
            session_id: Session identifier
            time_ref: The time reference needing clarification
            recent_events: List of recently mentioned events for context
            
        Returns:
            A clarifying question string, or None
        """
        recent_events = recent_events or []
        
        if time_ref.clarity == ClarityLevel.CLEAR:
            return None
        
        # Select question template based on clarity issue
        if time_ref.clarity == ClarityLevel.NEEDS_ANCHOR:
            if time_ref.type == TimeReferenceType.RELATIVE:
                templates = DISAMBIGUATION_QUESTIONS['no_anchor']
            else:
                templates = DISAMBIGUATION_QUESTIONS['anchor_needed']
        elif time_ref.clarity == ClarityLevel.AMBIGUOUS:
            if 'few' in time_ref.text or 'several' in time_ref.text:
                templates = DISAMBIGUATION_QUESTIONS['vague_duration']
            else:
                templates = DISAMBIGUATION_QUESTIONS['anchor_needed']
        else:
            templates = DISAMBIGUATION_QUESTIONS['anchor_needed']
        
        # Select template (rotate based on session usage)
        template_idx = hash(session_id + time_ref.text) % len(templates)
        template = templates[template_idx]
        
        # Format the question
        question = template.format(
            time_ref=f'"{time_ref.text}"',
            event_a=recent_events[0] if recent_events else "that event",
            event_b=recent_events[1] if len(recent_events) > 1 else "what you just described",
        )
        
        return question
    
    def get_next_disambiguation_prompt(
        self,
        session_id: str,
        statements: List[Dict[str, Any]],
        events_mentioned: List[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the next disambiguation prompt needed for the timeline.
        
        Args:
            session_id: Session identifier
            statements: All statements so far
            events_mentioned: List of events mentioned (for context)
            
        Returns:
            Dict with question and metadata, or None if no disambiguation needed
        """
        events_mentioned = events_mentioned or []
        
        # Analyze current timeline clarity
        analysis = self.analyze_timeline_clarity(session_id, statements)
        
        if not analysis.get('needs_disambiguation'):
            return None
        
        # Find the most problematic reference
        refs_data = analysis.get('references', [])
        problematic = [
            r for r in refs_data 
            if r['clarity'] in ('ambiguous', 'needs_anchor')
        ]
        
        if not problematic:
            return None
        
        # Prioritize: vague duration > no anchor > ambiguous
        problematic.sort(key=lambda r: (
            0 if 'few' in r['text'] or 'several' in r['text'] else 1,
            r['confidence']
        ))
        
        worst_ref = problematic[0]
        
        # Create TimeReference from dict
        ref = TimeReference(
            text=worst_ref['text'],
            type=TimeReferenceType(worst_ref['type']),
            clarity=ClarityLevel(worst_ref['clarity']),
            statement_index=worst_ref['statement_index'],
            confidence=worst_ref['confidence'],
        )
        
        question = self.generate_disambiguation_question(
            session_id, ref, events_mentioned
        )
        
        if not question:
            return None
        
        return {
            "question": question,
            "target_reference": worst_ref['text'],
            "reference_type": worst_ref['type'],
            "clarity_issue": worst_ref['clarity'],
            "statement_index": worst_ref['statement_index'],
            "disambiguation_type": "timeline_clarity",
        }
    
    def build_relative_timeline(
        self,
        session_id: str,
        events: List[Dict[str, Any]],
        clarifications: List[Dict[str, Any]] = None
    ) -> List[DisambiguatedEvent]:
        """
        Build a relative timeline from events and clarifications.
        
        Args:
            session_id: Session identifier
            events: List of event dicts with description and time_ref
            clarifications: Answers to disambiguation questions
            
        Returns:
            List of disambiguated events in sequence order
        """
        clarifications = clarifications or []
        disambiguated: List[DisambiguatedEvent] = []
        
        # Create anchors from absolute times
        anchors: List[TimelineAnchor] = []
        for idx, event in enumerate(events):
            time_ref = event.get('time_ref', event.get('time', ''))
            refs = self.detect_time_references(time_ref, idx)
            
            for ref in refs:
                if ref.type == TimeReferenceType.ABSOLUTE:
                    anchors.append(TimelineAnchor(
                        id=f"anchor_{idx}",
                        description=event.get('description', ''),
                        relative_position=idx,
                        source_statement_index=idx,
                        confidence=ref.confidence,
                    ))
                    break
        
        # Build sequence from events
        for idx, event in enumerate(events):
            time_ref = event.get('time_ref', event.get('time', ''))
            refs = self.detect_time_references(time_ref, idx) if time_ref else []
            
            # Determine clarity
            if refs:
                best_ref = max(refs, key=lambda r: r.confidence)
                clarity = best_ref.clarity
                needs_clarification = clarity in (ClarityLevel.AMBIGUOUS, ClarityLevel.NEEDS_ANCHOR)
            else:
                clarity = ClarityLevel.UNKNOWN
                needs_clarification = True
            
            # Find closest anchor
            anchor_id = None
            relative_to = ""
            offset_desc = ""
            
            if anchors:
                # Find the nearest anchor before this event
                preceding_anchors = [a for a in anchors if a.relative_position < idx]
                if preceding_anchors:
                    closest = max(preceding_anchors, key=lambda a: a.relative_position)
                    anchor_id = closest.id
                    relative_to = "after"
                    offset_desc = f"after {closest.description[:50]}"
            
            # Check if clarification exists for this event
            for clarification in clarifications:
                if clarification.get('event_index') == idx:
                    # Apply clarification
                    needs_clarification = False
                    clarity = ClarityLevel.CLEAR
                    if clarification.get('offset_description'):
                        offset_desc = clarification['offset_description']
                    break
            
            # Generate clarification question if needed
            clarify_question = None
            if needs_clarification and refs:
                clarify_question = self.generate_disambiguation_question(
                    session_id,
                    refs[0] if refs else TimeReference(
                        text="",
                        type=TimeReferenceType.VAGUE,
                        clarity=ClarityLevel.UNKNOWN,
                    ),
                    [e.get('description', '')[:30] for e in events[max(0, idx-2):idx]]
                )
            
            disambiguated.append(DisambiguatedEvent(
                id=f"event_{idx}",
                description=event.get('description', ''),
                sequence=idx + 1,
                original_time_ref=time_ref,
                clarity=clarity,
                anchor_id=anchor_id,
                relative_to_anchor=relative_to,
                offset_description=offset_desc,
                confidence=refs[0].confidence if refs else 0.3,
                needs_clarification=needs_clarification,
                clarification_question=clarify_question,
            ))
        
        # Store in session
        self._session_timelines[session_id] = {
            "events": [
                {
                    "id": e.id,
                    "description": e.description,
                    "sequence": e.sequence,
                    "original_time_ref": e.original_time_ref,
                    "clarity": e.clarity.value,
                    "anchor_id": e.anchor_id,
                    "relative_to_anchor": e.relative_to_anchor,
                    "offset_description": e.offset_description,
                    "confidence": e.confidence,
                    "needs_clarification": e.needs_clarification,
                }
                for e in disambiguated
            ],
            "anchors": [
                {"id": a.id, "description": a.description, "position": a.relative_position}
                for a in anchors
            ],
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        return disambiguated
    
    def get_session_timeline(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the current disambiguated timeline for a session."""
        return self._session_timelines.get(session_id)
    
    def apply_clarification(
        self,
        session_id: str,
        event_id: str,
        clarification: Dict[str, Any]
    ) -> bool:
        """
        Apply a clarification response to an event in the timeline.
        
        Args:
            session_id: Session identifier
            event_id: ID of the event being clarified
            clarification: Dict with 'relative_to', 'offset', 'sequence' etc.
            
        Returns:
            True if applied successfully
        """
        timeline = self._session_timelines.get(session_id)
        if not timeline:
            return False
        
        for event in timeline['events']:
            if event['id'] == event_id:
                if 'offset_description' in clarification:
                    event['offset_description'] = clarification['offset_description']
                if 'relative_to' in clarification:
                    event['relative_to_anchor'] = clarification['relative_to']
                if 'sequence' in clarification:
                    event['sequence'] = clarification['sequence']
                
                event['clarity'] = 'clear'
                event['needs_clarification'] = False
                event['confidence'] = min(event['confidence'] + 0.2, 1.0)
                
                timeline['updated_at'] = datetime.utcnow().isoformat()
                logger.info(f"Applied clarification to event {event_id} in session {session_id}")
                return True
        
        return False
    
    def get_pending_clarifications(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all events that still need timeline clarification."""
        timeline = self._session_timelines.get(session_id)
        if not timeline:
            return []
        
        return [
            event for event in timeline['events']
            if event.get('needs_clarification')
        ]
    
    def reset_session(self, session_id: str):
        """Reset timeline disambiguation state for a session."""
        if session_id in self._session_timelines:
            del self._session_timelines[session_id]


# Global singleton instance
timeline_disambiguator = TimelineDisambiguator()
