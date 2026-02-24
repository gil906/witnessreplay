"""Interview branching system for dynamic follow-up questions.

Detects key topics in witness statements and generates relevant follow-up
questions based on branching logic. Tracks the branching path for audit.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TopicCategory(Enum):
    """Categories of key topics detected in witness statements."""
    VIOLENCE = "violence"
    VEHICLE = "vehicle"
    WEAPON = "weapon"
    SUSPECT_DESCRIPTION = "suspect_description"
    INJURY = "injury"
    THEFT = "theft"
    DRUGS = "drugs"
    TEMPORAL = "temporal"
    LOCATION = "location"
    ESCAPE = "escape"
    MULTIPLE_SUSPECTS = "multiple_suspects"
    WITNESS_POSITION = "witness_position"
    ENVIRONMENTAL = "environmental"
    COMMUNICATION = "communication"


@dataclass
class DetectedTopic:
    """A topic detected in a witness statement."""
    category: TopicCategory
    trigger_phrase: str
    confidence: float
    statement_index: int
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class BranchNode:
    """A node in the interview branching tree."""
    id: str
    topic: TopicCategory
    question_asked: str
    response_summary: str
    child_branches: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class BranchingPath:
    """Complete branching path for audit purposes."""
    session_id: str
    nodes: List[BranchNode] = field(default_factory=list)
    topics_explored: Set[TopicCategory] = field(default_factory=set)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "session_id": self.session_id,
            "nodes": [
                {
                    "id": n.id,
                    "topic": n.topic.value,
                    "question_asked": n.question_asked,
                    "response_summary": n.response_summary,
                    "child_branches": n.child_branches,
                    "timestamp": n.timestamp
                }
                for n in self.nodes
            ],
            "topics_explored": [t.value for t in self.topics_explored],
            "created_at": self.created_at
        }


# Topic detection patterns - keywords and phrases that indicate specific topics
TOPIC_PATTERNS: Dict[TopicCategory, List[str]] = {
    TopicCategory.VIOLENCE: [
        r'\b(hit|punch|kick|attack|assault|fight|beat|push|shove|grab|choke|strangle)\b',
        r'\b(violent|aggressive|threatening)\b',
        r'\b(blood|bleeding|wound)\b',
    ],
    TopicCategory.VEHICLE: [
        r'\b(car|truck|van|suv|motorcycle|bike|vehicle|sedan|coupe)\b',
        r'\b(drove|driving|parked|speeding|crashed)\b',
        r'\b(license plate|plate number|bumper)\b',
    ],
    TopicCategory.WEAPON: [
        r'\b(gun|knife|weapon|pistol|rifle|blade|bat|crowbar)\b',
        r'\b(armed|pointing|aimed|fired|shot|stabbed)\b',
    ],
    TopicCategory.SUSPECT_DESCRIPTION: [
        r'\b(man|woman|person|guy|individual|suspect|perpetrator)\b',
        r'\b(wearing|dressed|clothes|jacket|hoodie|mask|hat|tattoo)\b',
        r'\b(tall|short|heavy|thin|young|old|age|height|build)\b',
    ],
    TopicCategory.INJURY: [
        r'\b(hurt|injured|bleeding|unconscious|fell|pain)\b',
        r'\b(ambulance|medic|hospital|doctor|ems)\b',
    ],
    TopicCategory.THEFT: [
        r'\b(stole|stolen|took|grabbed|snatched|robbed|robbery|theft|purse|wallet|bag)\b',
        r'\b(broke into|breaking in|burglary|burglar)\b',
    ],
    TopicCategory.DRUGS: [
        r'\b(drugs|pills|powder|needle|syringe|smoking|injection)\b',
        r'\b(deal|dealing|buying|selling|exchange)\b',
    ],
    TopicCategory.TEMPORAL: [
        r'\b(\d{1,2}:\d{2}|o\'clock|am|pm|morning|afternoon|evening|night|midnight)\b',
        r'\b(minute|hour|second|moment|while|before|after|during)\b',
    ],
    TopicCategory.LOCATION: [
        r'\b(street|avenue|road|intersection|corner|block|building|store|house|apartment)\b',
        r'\b(parking lot|alley|sidewalk|entrance|exit|door)\b',
        r'\b(north|south|east|west|left|right|across|behind|front)\b',
    ],
    TopicCategory.ESCAPE: [
        r'\b(ran|running|fled|escape|left|drove off|took off|disappeared)\b',
        r'\b(direction|headed|toward|away)\b',
    ],
    TopicCategory.MULTIPLE_SUSPECTS: [
        r'\b(two|three|four|five|several|multiple|both|group|together)\b',
        r'\b(accomplice|partner|together|with another)\b',
    ],
    TopicCategory.WITNESS_POSITION: [
        r'\b(i was|i stood|i saw from|my position|where i was|from where)\b',
        r'\b(feet away|meters|yards|distance|close|far)\b',
    ],
    TopicCategory.ENVIRONMENTAL: [
        r'\b(dark|light|bright|dim|shadow|streetlight|rain|snow|fog)\b',
        r'\b(loud|quiet|noisy|scream|yell|shout)\b',
    ],
    TopicCategory.COMMUNICATION: [
        r'\b(said|yelled|screamed|shouted|heard|told|asked|demanded)\b',
        r'\b(phone|call|text|spoke|talking)\b',
    ],
}


# Follow-up question templates based on detected topics
BRANCHING_QUESTIONS: Dict[TopicCategory, List[Dict[str, Any]]] = {
    TopicCategory.VIOLENCE: [
        {
            "question": "You mentioned there was physical contact. Can you describe exactly what happened? Who initiated it?",
            "priority": 1,
            "follow_ups": ["Did anyone try to intervene?", "How long did the altercation last?"]
        },
        {
            "question": "Did you see any injuries being inflicted? Where on the body?",
            "priority": 2,
            "follow_ups": ["Could you see any visible marks or wounds?"]
        },
    ],
    TopicCategory.VEHICLE: [
        {
            "question": "Can you describe the vehicle in more detail? Color, make, model, any distinguishing features?",
            "priority": 1,
            "follow_ups": ["Did you notice any damage or modifications?", "Any bumper stickers or decals?"]
        },
        {
            "question": "Did you get a look at the license plate? Even a partial plate would help.",
            "priority": 2,
            "follow_ups": ["Was it a local plate or out of state?"]
        },
        {
            "question": "Which direction did the vehicle go when it left?",
            "priority": 3,
            "follow_ups": ["Did you notice if anyone else was in the vehicle?"]
        },
    ],
    TopicCategory.WEAPON: [
        {
            "question": "You mentioned a weapon. Can you describe it in detail? Size, color, type?",
            "priority": 1,
            "follow_ups": ["Was it visible the entire time?", "How was it being held?"]
        },
        {
            "question": "Was the weapon pointed at anyone? Did you feel threatened?",
            "priority": 1,
            "follow_ups": ["Did anyone get hurt by the weapon?"]
        },
        {
            "question": "Did you see where the weapon came from? Where did it end up?",
            "priority": 2,
            "follow_ups": ["Was it concealed at any point?"]
        },
    ],
    TopicCategory.SUSPECT_DESCRIPTION: [
        {
            "question": "Let's build a clearer picture. Can you estimate their height and build?",
            "priority": 1,
            "follow_ups": ["Any facial features you remember?", "Hair color or style?"]
        },
        {
            "question": "What were they wearing? Top, bottom, footwear, accessories?",
            "priority": 1,
            "follow_ups": ["Did you notice any logos or distinctive patterns?"]
        },
        {
            "question": "Did you notice any distinguishing marks? Tattoos, scars, piercings?",
            "priority": 2,
            "follow_ups": ["Any accent or manner of speaking?"]
        },
    ],
    TopicCategory.INJURY: [
        {
            "question": "Can you describe the injuries you observed? Where on the body?",
            "priority": 1,
            "follow_ups": ["Did the person seem conscious?", "Were they able to move?"]
        },
        {
            "question": "Did emergency services arrive? What happened when they got there?",
            "priority": 2,
            "follow_ups": ["How long before help arrived?"]
        },
    ],
    TopicCategory.THEFT: [
        {
            "question": "What was taken? Can you describe the item or items?",
            "priority": 1,
            "follow_ups": ["Approximate value?", "Was force used to take it?"]
        },
        {
            "question": "How did they take the item? Did they conceal it?",
            "priority": 2,
            "follow_ups": ["Did anyone try to stop them?"]
        },
    ],
    TopicCategory.DRUGS: [
        {
            "question": "Can you describe what you saw? What made you think drugs were involved?",
            "priority": 1,
            "follow_ups": ["Did you see an exchange?", "How many people were involved?"]
        },
    ],
    TopicCategory.TEMPORAL: [
        {
            "question": "Let's pin down the timeline. What time did this start?",
            "priority": 1,
            "follow_ups": ["How long did the whole incident last?"]
        },
        {
            "question": "What happened just before the incident began?",
            "priority": 2,
            "follow_ups": ["And immediately after?"]
        },
    ],
    TopicCategory.LOCATION: [
        {
            "question": "Can you describe the exact location? Street names, landmarks nearby?",
            "priority": 1,
            "follow_ups": ["Were there any businesses or buildings nearby?"]
        },
        {
            "question": "Where were the key people positioned relative to each other?",
            "priority": 2,
            "follow_ups": ["Did anyone move during the incident?"]
        },
    ],
    TopicCategory.ESCAPE: [
        {
            "question": "Which direction did they go? Did you see where they ended up?",
            "priority": 1,
            "follow_ups": ["Were they running or walking?", "Did they get into a vehicle?"]
        },
        {
            "question": "Did anyone pursue them? Were police already on scene?",
            "priority": 2,
            "follow_ups": ["How long until they were out of sight?"]
        },
    ],
    TopicCategory.MULTIPLE_SUSPECTS: [
        {
            "question": "You mentioned multiple people. How many exactly were involved?",
            "priority": 1,
            "follow_ups": ["Did they seem to know each other?", "Were they acting together?"]
        },
        {
            "question": "Can you describe each person separately? Let's start with the most distinctive one.",
            "priority": 1,
            "follow_ups": ["What role did each person play?"]
        },
    ],
    TopicCategory.WITNESS_POSITION: [
        {
            "question": "Where exactly were you standing or positioned during this?",
            "priority": 1,
            "follow_ups": ["Did you have a clear view?", "Was anything blocking your sight?"]
        },
        {
            "question": "How far away were you from the main action?",
            "priority": 2,
            "follow_ups": ["Did you move at any point during the incident?"]
        },
    ],
    TopicCategory.ENVIRONMENTAL: [
        {
            "question": "What were the lighting conditions like? Could you see clearly?",
            "priority": 2,
            "follow_ups": ["Were there streetlights or other light sources?"]
        },
        {
            "question": "Was there any noise that made it hard to hear?",
            "priority": 3,
            "follow_ups": ["What sounds do you remember hearing?"]
        },
    ],
    TopicCategory.COMMUNICATION: [
        {
            "question": "You mentioned something was said. Can you remember the exact words?",
            "priority": 1,
            "follow_ups": ["What was the tone of voice?", "Did anyone respond?"]
        },
        {
            "question": "Did you hear anyone making a phone call?",
            "priority": 2,
            "follow_ups": ["Could you hear what was said?"]
        },
    ],
}


class InterviewBranchingService:
    """Service for managing dynamic interview branching based on witness responses."""
    
    def __init__(self):
        self._session_paths: Dict[str, BranchingPath] = {}
        self._session_asked: Dict[str, Set[str]] = {}
        self._node_counter: Dict[str, int] = {}
    
    def detect_topics(
        self,
        statement: str,
        statement_index: int = 0
    ) -> List[DetectedTopic]:
        """
        Detect key topics in a witness statement.
        
        Args:
            statement: The witness statement text
            statement_index: Index of this statement in the conversation
            
        Returns:
            List of detected topics with confidence scores
        """
        detected: List[DetectedTopic] = []
        statement_lower = statement.lower()
        
        for category, patterns in TOPIC_PATTERNS.items():
            matches = []
            for pattern in patterns:
                found = re.findall(pattern, statement_lower, re.IGNORECASE)
                matches.extend(found)
            
            if matches:
                # Calculate confidence based on number of matches
                confidence = min(0.5 + (len(matches) * 0.15), 1.0)
                
                # Use first match as trigger phrase
                trigger = matches[0] if isinstance(matches[0], str) else matches[0][0] if matches[0] else ""
                
                detected.append(DetectedTopic(
                    category=category,
                    trigger_phrase=trigger,
                    confidence=confidence,
                    statement_index=statement_index
                ))
        
        # Sort by confidence
        detected.sort(key=lambda t: t.confidence, reverse=True)
        
        logger.info(f"Detected {len(detected)} topics in statement: {[t.category.value for t in detected]}")
        return detected
    
    def generate_branching_questions(
        self,
        session_id: str,
        detected_topics: List[DetectedTopic],
        conversation_history: List[Dict[str, str]],
        max_questions: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Generate follow-up questions based on detected topics.
        
        Args:
            session_id: Session identifier
            detected_topics: Topics detected in the latest statement
            conversation_history: Full conversation history
            max_questions: Maximum number of questions to return
            
        Returns:
            List of prioritized follow-up questions with metadata
        """
        if session_id not in self._session_asked:
            self._session_asked[session_id] = set()
        
        asked = self._session_asked[session_id]
        questions: List[Dict[str, Any]] = []
        
        # Get branching path to check explored topics
        path = self._get_or_create_path(session_id)
        
        for topic in detected_topics:
            if topic.category not in BRANCHING_QUESTIONS:
                continue
            
            topic_questions = BRANCHING_QUESTIONS[topic.category]
            
            for q_data in topic_questions:
                question = q_data["question"]
                
                # Skip already asked questions
                if question in asked:
                    continue
                
                # Boost priority if topic hasn't been explored yet
                priority = q_data["priority"]
                if topic.category not in path.topics_explored:
                    priority -= 0.5  # Lower number = higher priority
                
                questions.append({
                    "question": question,
                    "topic": topic.category.value,
                    "priority": priority,
                    "confidence": topic.confidence,
                    "trigger_phrase": topic.trigger_phrase,
                    "follow_ups": q_data.get("follow_ups", []),
                    "branch_type": "topic_detection"
                })
        
        # Sort by priority (lower is better) and confidence
        questions.sort(key=lambda q: (q["priority"], -q["confidence"]))
        
        # Return top questions
        return questions[:max_questions]
    
    def get_next_branching_question(
        self,
        session_id: str,
        statement: str,
        conversation_history: List[Dict[str, str]],
        statement_index: int = 0
    ) -> Optional[Dict[str, Any]]:
        """
        Get the single best follow-up question based on the statement.
        
        Args:
            session_id: Session identifier
            statement: Latest witness statement
            conversation_history: Full conversation history
            statement_index: Index of this statement
            
        Returns:
            Best follow-up question with metadata, or None
        """
        # Detect topics in the statement
        topics = self.detect_topics(statement, statement_index)
        
        if not topics:
            return None
        
        # Generate questions based on detected topics
        questions = self.generate_branching_questions(
            session_id,
            topics,
            conversation_history
        )
        
        if not questions:
            return None
        
        # Get the best question
        best = questions[0]
        
        # Mark as asked
        self.mark_question_asked(session_id, best["question"])
        
        # Record in branching path
        self._record_branch(
            session_id,
            TopicCategory(best["topic"]),
            best["question"]
        )
        
        return best
    
    def mark_question_asked(self, session_id: str, question: str):
        """Mark a question as having been asked."""
        if session_id not in self._session_asked:
            self._session_asked[session_id] = set()
        self._session_asked[session_id].add(question)
    
    def _get_or_create_path(self, session_id: str) -> BranchingPath:
        """Get or create the branching path for a session."""
        if session_id not in self._session_paths:
            self._session_paths[session_id] = BranchingPath(session_id=session_id)
        return self._session_paths[session_id]
    
    def _record_branch(
        self,
        session_id: str,
        topic: TopicCategory,
        question: str,
        response_summary: str = ""
    ) -> str:
        """
        Record a branch taken in the interview.
        
        Returns:
            Node ID
        """
        path = self._get_or_create_path(session_id)
        
        # Generate node ID
        if session_id not in self._node_counter:
            self._node_counter[session_id] = 0
        self._node_counter[session_id] += 1
        node_id = f"branch_{session_id}_{self._node_counter[session_id]}"
        
        # Create node
        node = BranchNode(
            id=node_id,
            topic=topic,
            question_asked=question,
            response_summary=response_summary
        )
        
        # Link to previous node if exists
        if path.nodes:
            path.nodes[-1].child_branches.append(node_id)
        
        path.nodes.append(node)
        path.topics_explored.add(topic)
        
        logger.info(f"Recorded branch: {topic.value} -> {question[:50]}...")
        return node_id
    
    def update_branch_response(
        self,
        session_id: str,
        node_id: str,
        response_summary: str
    ):
        """Update a branch node with the witness response summary."""
        path = self._get_or_create_path(session_id)
        for node in path.nodes:
            if node.id == node_id:
                node.response_summary = response_summary
                break
    
    def get_branching_path(self, session_id: str) -> Dict[str, Any]:
        """
        Get the complete branching path for audit purposes.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary representation of the branching path
        """
        path = self._get_or_create_path(session_id)
        return path.to_dict()
    
    def get_unexplored_topics(
        self,
        session_id: str,
        detected_topics: List[DetectedTopic]
    ) -> List[TopicCategory]:
        """Get topics that have been detected but not yet explored."""
        path = self._get_or_create_path(session_id)
        unexplored = []
        
        for topic in detected_topics:
            if topic.category not in path.topics_explored:
                unexplored.append(topic.category)
        
        return unexplored
    
    def suggest_topic_to_explore(
        self,
        session_id: str,
        statement: str
    ) -> Optional[TopicCategory]:
        """
        Suggest the most important unexplored topic to explore next.
        
        Args:
            session_id: Session identifier
            statement: Latest witness statement
            
        Returns:
            Topic category to explore, or None
        """
        topics = self.detect_topics(statement)
        unexplored = self.get_unexplored_topics(session_id, topics)
        
        if not unexplored:
            return None
        
        # Priority order for topics
        priority_order = [
            TopicCategory.WEAPON,
            TopicCategory.VIOLENCE,
            TopicCategory.INJURY,
            TopicCategory.SUSPECT_DESCRIPTION,
            TopicCategory.ESCAPE,
            TopicCategory.VEHICLE,
            TopicCategory.THEFT,
            TopicCategory.MULTIPLE_SUSPECTS,
            TopicCategory.TEMPORAL,
            TopicCategory.LOCATION,
        ]
        
        for priority_topic in priority_order:
            if priority_topic in unexplored:
                return priority_topic
        
        return unexplored[0] if unexplored else None
    
    def reset_session(self, session_id: str):
        """Reset branching state for a session."""
        if session_id in self._session_paths:
            del self._session_paths[session_id]
        if session_id in self._session_asked:
            del self._session_asked[session_id]
        if session_id in self._node_counter:
            del self._node_counter[session_id]


# Global singleton instance
interview_branching = InterviewBranchingService()
