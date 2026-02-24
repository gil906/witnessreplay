"""Automatic follow-up question generation for witness interviews."""

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import random

logger = logging.getLogger(__name__)


class QuestionGenerator:
    """Generates intelligent follow-up questions based on witness statements."""
    
    def __init__(self):
        self._asked_questions: Dict[str, Set[str]] = {}
        
    def generate_questions(
        self,
        session_id: str,
        scene_elements: List[Dict[str, Any]],
        conversation_history: List[Dict[str, str]],
        contradictions: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate prioritized follow-up questions based on current scene state.
        
        Args:
            session_id: Session identifier
            scene_elements: Current scene elements extracted
            conversation_history: Full conversation so far
            contradictions: Any detected contradictions
            
        Returns:
            List of questions with priority and category
        """
        if session_id not in self._asked_questions:
            self._asked_questions[session_id] = set()
            
        questions = []
        
        # Priority 1: Address contradictions
        if contradictions:
            for contradiction in contradictions:
                if not contradiction.get('resolved', False):
                    question = self._generate_contradiction_question(contradiction)
                    if question:
                        questions.append({
                            'question': question,
                            'priority': 1,
                            'category': 'contradiction',
                            'element_id': contradiction.get('element_id'),
                            'element_type': contradiction.get('element_type')
                        })
        
        # Priority 2: Fill in missing critical attributes
        for element in scene_elements:
            missing_attrs = self._find_missing_attributes(element)
            for attr in missing_attrs:
                question = self._generate_attribute_question(element, attr)
                if question and question not in self._asked_questions[session_id]:
                    questions.append({
                        'question': question,
                        'priority': 2,
                        'category': 'missing_attribute',
                        'element_id': element.get('id'),
                        'element_type': element.get('type'),
                        'attribute': attr
                    })
        
        # Priority 3: Clarify spatial relationships
        if len(scene_elements) >= 2:
            relationship_questions = self._generate_relationship_questions(
                scene_elements,
                self._asked_questions[session_id]
            )
            questions.extend(relationship_questions)
        
        # Priority 4: Temporal sequence
        timeline_questions = self._generate_timeline_questions(
            conversation_history,
            self._asked_questions[session_id]
        )
        questions.extend(timeline_questions)
        
        # Priority 5: Confirmation questions
        if len(scene_elements) >= 3:
            confirmation = self._generate_confirmation_question(scene_elements)
            if confirmation and confirmation not in self._asked_questions[session_id]:
                questions.append({
                    'question': confirmation,
                    'priority': 5,
                    'category': 'confirmation',
                })
        
        # Sort by priority
        questions.sort(key=lambda q: q['priority'])
        
        return questions
        
    def _generate_contradiction_question(self, contradiction: Dict[str, Any]) -> Optional[str]:
        """Generate a question to resolve a contradiction."""
        element_type = contradiction.get('element_type', 'element')
        original = contradiction.get('original_value', '')
        new = contradiction.get('new_value', '')
        
        templates = [
            f"I want to make sure I have this right - was the {element_type} {new}, or was it {original}?",
            f"You mentioned the {element_type} was {original} earlier, but now you said {new}. Which is correct?",
            f"Just to clarify: the {element_type} was {new}, not {original}, is that right?",
        ]
        
        return random.choice(templates)
        
    def _find_missing_attributes(self, element: Dict[str, Any]) -> List[str]:
        """Identify missing critical attributes for an element."""
        element_type = element.get('type', '')
        missing = []
        
        # Critical attributes by type
        critical_attrs = {
            'person': ['color', 'position', 'clothing', 'height'],
            'vehicle': ['color', 'type', 'position', 'make'],
            'object': ['color', 'position', 'size'],
            'location_feature': ['position', 'size']
        }
        
        required = critical_attrs.get(element_type, ['position', 'color'])
        
        for attr in required:
            if attr not in element or not element.get(attr):
                missing.append(attr)
                
        return missing
        
    def _generate_attribute_question(
        self,
        element: Dict[str, Any],
        attribute: str
    ) -> Optional[str]:
        """Generate a question to fill in a missing attribute."""
        element_type = element.get('type', 'element')
        description = element.get('description', element_type)
        
        # Question templates by attribute
        templates = {
            'color': [
                f"What color was the {description}?",
                f"Can you describe the color of the {description}?",
            ],
            'position': [
                f"Where exactly was the {description} located?",
                f"Can you tell me where the {description} was positioned?",
                f"Where was the {description} in relation to where you were standing?",
            ],
            'size': [
                f"How large was the {description}?",
                f"Can you estimate the size of the {description}?",
                f"Was the {description} large or small?",
            ],
            'clothing': [
                f"What was the person wearing?",
                f"Can you describe their clothing?",
            ],
            'height': [
                f"How tall would you say they were?",
                f"Can you estimate their height?",
            ],
            'type': [
                f"What type of {element_type} was it?",
                f"Can you be more specific about what kind of {element_type} it was?",
            ],
            'make': [
                f"Do you remember the make or model of the vehicle?",
                f"What kind of car was it?",
            ]
        }
        
        if attribute in templates:
            return random.choice(templates[attribute])
            
        return None
        
    def _generate_relationship_questions(
        self,
        elements: List[Dict[str, Any]],
        asked: Set[str]
    ) -> List[Dict[str, Any]]:
        """Generate questions about spatial relationships between elements."""
        questions = []
        
        # Pick pairs of elements to ask about
        for i in range(len(elements)):
            for j in range(i + 1, len(elements)):
                elem1 = elements[i]
                elem2 = elements[j]
                
                # Skip if both have position
                if elem1.get('position') and elem2.get('position'):
                    continue
                    
                desc1 = elem1.get('description', elem1.get('type', 'element'))
                desc2 = elem2.get('description', elem2.get('type', 'element'))
                
                question = f"Where was the {desc1} in relation to the {desc2}?"
                
                if question not in asked:
                    questions.append({
                        'question': question,
                        'priority': 3,
                        'category': 'spatial_relationship',
                        'element_id': f"{elem1.get('id')}_{elem2.get('id')}",
                    })
                    
                    # Only ask one relationship question at a time
                    if len(questions) >= 1:
                        break
            if questions:
                break
                
        return questions
        
    def _generate_timeline_questions(
        self,
        conversation: List[Dict[str, str]],
        asked: Set[str]
    ) -> List[Dict[str, Any]]:
        """Generate questions about temporal sequence of events."""
        questions = []
        
        # Look for action words in conversation
        action_indicators = ['then', 'after', 'before', 'when', 'while', 'suddenly']
        has_timeline = any(
            any(word in msg.get('content', '').lower() for word in action_indicators)
            for msg in conversation
        )
        
        if has_timeline:
            templates = [
                "Can you walk me through the sequence of what happened?",
                "What happened first, and then what happened after that?",
                "Can you tell me the order of events as they unfolded?",
            ]
            
            for template in templates:
                if template not in asked:
                    questions.append({
                        'question': template,
                        'priority': 4,
                        'category': 'timeline',
                    })
                    break
                    
        return questions
        
    def _generate_confirmation_question(
        self,
        elements: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Generate a confirmation question summarizing key elements."""
        if len(elements) < 2:
            return None
            
        # Build a summary of key elements
        descriptions = []
        for elem in elements[:3]:  # Limit to 3 elements for brevity
            desc = elem.get('description', '')
            color = elem.get('color', '')
            if color:
                descriptions.append(f"a {color} {desc}")
            else:
                descriptions.append(f"a {desc}")
                
        if len(descriptions) >= 2:
            summary = ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"
            return f"Just to confirm: you saw {summary}. Is that correct?"
            
        return None
        
    def mark_question_asked(self, session_id: str, question: str):
        """Mark a question as having been asked."""
        if session_id not in self._asked_questions:
            self._asked_questions[session_id] = set()
        self._asked_questions[session_id].add(question)
        
    def get_next_question(
        self,
        session_id: str,
        scene_elements: List[Dict[str, Any]],
        conversation_history: List[Dict[str, str]],
        contradictions: List[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Get the single highest priority next question to ask."""
        questions = self.generate_questions(
            session_id,
            scene_elements,
            conversation_history,
            contradictions
        )
        
        if questions:
            next_q = questions[0]['question']
            self.mark_question_asked(session_id, next_q)
            return next_q
            
        return None


# Global singleton instance
question_generator = QuestionGenerator()
