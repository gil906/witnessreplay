"""Contradiction detection and tracking for witness statements."""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


@dataclass
class Contradiction:
    """Represents a detected contradiction in witness statements."""
    id: str
    timestamp: datetime
    element_type: str  # person, vehicle, object, environment
    element_id: str
    original_statement: str
    contradicting_statement: str
    original_value: str
    new_value: str
    confidence: float  # 0.0-1.0 how confident we are this is a contradiction
    resolved: bool
    resolution_note: Optional[str] = None


class ContradictionDetector:
    """Detects and tracks contradictions in witness statements."""
    
    def __init__(self):
        self.contradictions: Dict[str, List[Contradiction]] = {}
        self._element_history: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        
    def track_element_mention(
        self,
        session_id: str,
        element_type: str,
        element_id: str,
        attribute: str,
        value: Any,
        statement: str,
        timestamp: Optional[datetime] = None
    ):
        """
        Track a mention of an element attribute.
        
        Args:
            session_id: Session identifier
            element_type: Type of element (person, vehicle, object, etc.)
            element_id: Unique identifier for this element
            attribute: The attribute being mentioned (color, position, size, etc.)
            value: The value of the attribute
            statement: The full statement where this was mentioned
            timestamp: When this was mentioned (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
            
        # Initialize session tracking if needed
        if session_id not in self._element_history:
            self._element_history[session_id] = {}
            self.contradictions[session_id] = []
            
        # Create element key
        element_key = f"{element_type}:{element_id}"
        if element_key not in self._element_history[session_id]:
            self._element_history[session_id][element_key] = {}
            
        # Track attribute history
        if attribute not in self._element_history[session_id][element_key]:
            self._element_history[session_id][element_key][attribute] = []
            
        # Check for contradictions
        history = self._element_history[session_id][element_key][attribute]
        if history:
            # Compare with most recent value
            last_entry = history[-1]
            if self._values_contradict(last_entry['value'], value):
                contradiction = self._create_contradiction(
                    session_id=session_id,
                    element_type=element_type,
                    element_id=element_id,
                    attribute=attribute,
                    original_entry=last_entry,
                    new_value=value,
                    new_statement=statement,
                    timestamp=timestamp
                )
                self.contradictions[session_id].append(contradiction)
                logger.info(
                    f"Contradiction detected in session {session_id}: "
                    f"{element_key}.{attribute} changed from {last_entry['value']} to {value}"
                )
        
        # Add to history
        history.append({
            'value': value,
            'statement': statement,
            'timestamp': timestamp.isoformat()
        })
        
    def _values_contradict(self, old_value: Any, new_value: Any) -> bool:
        """Determine if two values contradict each other."""
        # Normalize values for comparison
        old_str = str(old_value).lower().strip()
        new_str = str(new_value).lower().strip()
        
        # Same value = no contradiction
        if old_str == new_str:
            return False
            
        # Color contradictions (different colors)
        color_keywords = ['red', 'blue', 'green', 'black', 'white', 'yellow', 'gray', 'brown', 'orange', 'purple']
        old_colors = [c for c in color_keywords if c in old_str]
        new_colors = [c for c in color_keywords if c in new_str]
        if old_colors and new_colors and not any(c in new_colors for c in old_colors):
            return True
            
        # Directional contradictions
        direction_opposites = [
            (['left', 'west'], ['right', 'east']),
            (['front', 'ahead', 'forward'], ['back', 'behind', 'rear']),
            (['up', 'above', 'top'], ['down', 'below', 'bottom']),
            (['north'], ['south']),
            (['inside', 'indoor'], ['outside', 'outdoor'])
        ]
        for group1, group2 in direction_opposites:
            if any(d in old_str for d in group1) and any(d in new_str for d in group2):
                return True
            if any(d in old_str for d in group2) and any(d in new_str for d in group1):
                return True
                
        # Size contradictions
        size_opposites = [
            (['large', 'big', 'huge', 'tall'], ['small', 'tiny', 'short']),
        ]
        for group1, group2 in size_opposites:
            if any(s in old_str for s in group1) and any(s in new_str for s in group2):
                return True
            if any(s in old_str for s in group2) and any(s in new_str for s in group1):
                return True
                
        # Number contradictions (if both are numbers and differ significantly)
        try:
            old_num = float(old_value)
            new_num = float(new_value)
            # Consider it a contradiction if difference is > 20%
            if old_num > 0:
                diff_pct = abs(new_num - old_num) / old_num
                if diff_pct > 0.2:
                    return True
        except (ValueError, TypeError):
            pass
            
        return False
        
    def _create_contradiction(
        self,
        session_id: str,
        element_type: str,
        element_id: str,
        attribute: str,
        original_entry: Dict[str, Any],
        new_value: Any,
        new_statement: str,
        timestamp: datetime
    ) -> Contradiction:
        """Create a contradiction object."""
        contradiction_id = f"{session_id}_{element_type}_{element_id}_{attribute}_{timestamp.isoformat()}"
        
        # Calculate confidence based on how different the values are
        confidence = 0.8  # Default high confidence
        
        return Contradiction(
            id=contradiction_id,
            timestamp=timestamp,
            element_type=element_type,
            element_id=element_id,
            original_statement=original_entry['statement'],
            contradicting_statement=new_statement,
            original_value=str(original_entry['value']),
            new_value=str(new_value),
            confidence=confidence,
            resolved=False
        )
        
    def get_contradictions(
        self,
        session_id: str,
        unresolved_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Get contradictions for a session."""
        if session_id not in self.contradictions:
            return []
            
        contradictions = self.contradictions[session_id]
        if unresolved_only:
            contradictions = [c for c in contradictions if not c.resolved]
            
        return [
            {
                'id': c.id,
                'timestamp': c.timestamp.isoformat(),
                'element_type': c.element_type,
                'element_id': c.element_id,
                'original_statement': c.original_statement,
                'contradicting_statement': c.contradicting_statement,
                'original_value': c.original_value,
                'new_value': c.new_value,
                'confidence': c.confidence,
                'resolved': c.resolved,
                'resolution_note': c.resolution_note
            }
            for c in contradictions
        ]
        
    def resolve_contradiction(
        self,
        session_id: str,
        contradiction_id: str,
        resolution_note: str
    ) -> bool:
        """Mark a contradiction as resolved."""
        if session_id not in self.contradictions:
            return False
            
        for contradiction in self.contradictions[session_id]:
            if contradiction.id == contradiction_id:
                contradiction.resolved = True
                contradiction.resolution_note = resolution_note
                logger.info(f"Resolved contradiction {contradiction_id}: {resolution_note}")
                return True
                
        return False
        
    def get_element_history(
        self,
        session_id: str,
        element_type: str,
        element_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get the full history of mentions for an element."""
        if session_id not in self._element_history:
            return {}
            
        element_key = f"{element_type}:{element_id}"
        return self._element_history[session_id].get(element_key, {})


# Global singleton instance
contradiction_detector = ContradictionDetector()
