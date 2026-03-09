"""Contradiction detection and tracking for witness statements."""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


@dataclass
class ContradictionSeverity:
    """Severity scoring for a contradiction."""
    level: str  # low, medium, high, critical
    score: float  # 0.0-1.0 numeric score
    factors: Dict[str, float]  # Individual factor scores
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "score": self.score,
            "factors": self.factors
        }


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
    severity: Optional[ContradictionSeverity] = None


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
    
    def _calculate_severity(
        self,
        session_id: str,
        element_type: str,
        attribute: str,
        original_entry: Dict[str, Any],
        new_value: Any,
        new_timestamp: datetime
    ) -> ContradictionSeverity:
        """
        Calculate severity score for a contradiction.
        
        Factors:
        - time_discrepancy: How much time passed between statements (shorter = more severe)
        - location_mismatch: Whether it's a spatial/positional attribute
        - witness_count: Number of different mentions of this element
        - detail_specificity: How specific/concrete the values are
        """
        factors = {}
        
        # 1. Time discrepancy factor (0.0-1.0)
        # Shorter time between contradicting statements = more severe
        try:
            original_ts = datetime.fromisoformat(original_entry['timestamp'])
            time_diff = (new_timestamp - original_ts).total_seconds()
            # Very short time (< 60s) = high severity, long time (> 3600s) = low
            if time_diff < 60:
                factors['time_discrepancy'] = 1.0
            elif time_diff < 300:  # 5 minutes
                factors['time_discrepancy'] = 0.8
            elif time_diff < 900:  # 15 minutes
                factors['time_discrepancy'] = 0.5
            elif time_diff < 3600:  # 1 hour
                factors['time_discrepancy'] = 0.3
            else:
                factors['time_discrepancy'] = 0.1
        except (ValueError, KeyError):
            factors['time_discrepancy'] = 0.5
        
        # 2. Location/spatial mismatch factor
        location_attrs = ['position', 'location', 'direction', 'side', 'lane', 'street', 'address']
        if any(loc in attribute.lower() for loc in location_attrs):
            factors['location_mismatch'] = 0.9
        elif attribute.lower() in ['left', 'right', 'north', 'south', 'east', 'west']:
            factors['location_mismatch'] = 0.85
        else:
            factors['location_mismatch'] = 0.3
        
        # 3. Witness/element count factor
        # More mentions of an element = more reliable baseline = more severe contradiction
        element_key = f"{element_type}:{attribute}"
        mentions = 1
        if session_id in self._element_history:
            for key, attrs in self._element_history[session_id].items():
                if attribute in attrs:
                    mentions += len(attrs[attribute])
        if mentions >= 5:
            factors['witness_count'] = 0.9
        elif mentions >= 3:
            factors['witness_count'] = 0.7
        elif mentions >= 2:
            factors['witness_count'] = 0.5
        else:
            factors['witness_count'] = 0.3
        
        # 4. Detail specificity factor
        # More specific values (numbers, specific colors, etc.) = more severe when contradicted
        old_val = str(original_entry['value']).lower()
        new_val = str(new_value).lower()
        
        specificity_score = 0.3
        # Check for numbers (very specific)
        try:
            float(old_val)
            float(new_val)
            specificity_score = 0.95
        except ValueError:
            pass
        
        # Check for specific colors
        specific_colors = ['red', 'blue', 'green', 'black', 'white', 'yellow', 'orange', 'purple', 'brown', 'gray', 'silver']
        if any(c in old_val for c in specific_colors) and any(c in new_val for c in specific_colors):
            specificity_score = max(specificity_score, 0.8)
        
        # Check for directional specifics
        directions = ['left', 'right', 'north', 'south', 'east', 'west', 'front', 'back', 'behind', 'ahead']
        if any(d in old_val for d in directions) and any(d in new_val for d in directions):
            specificity_score = max(specificity_score, 0.85)
        
        factors['detail_specificity'] = specificity_score
        
        # Calculate overall score (weighted average)
        weights = {
            'time_discrepancy': 0.2,
            'location_mismatch': 0.3,
            'witness_count': 0.2,
            'detail_specificity': 0.3
        }
        
        total_score = sum(factors.get(k, 0) * w for k, w in weights.items())
        
        # Determine severity level
        if total_score >= 0.8:
            level = 'critical'
        elif total_score >= 0.6:
            level = 'high'
        elif total_score >= 0.4:
            level = 'medium'
        else:
            level = 'low'
        
        return ContradictionSeverity(
            level=level,
            score=round(total_score, 3),
            factors={k: round(v, 3) for k, v in factors.items()}
        )
        
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
        """Create a contradiction object with severity scoring."""
        contradiction_id = f"{session_id}_{element_type}_{element_id}_{attribute}_{timestamp.isoformat()}"
        
        # Calculate confidence based on how different the values are
        confidence = 0.8  # Default high confidence
        
        # Calculate severity
        severity = self._calculate_severity(
            session_id, element_type, attribute, original_entry, new_value, timestamp
        )
        
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
            resolved=False,
            severity=severity
        )
        
    def get_contradictions(
        self,
        session_id: str,
        unresolved_only: bool = False,
        sort_by: str = "timestamp"
    ) -> List[Dict[str, Any]]:
        """
        Get contradictions for a session.
        
        Args:
            session_id: Session identifier
            unresolved_only: If True, only return unresolved contradictions
            sort_by: Sort order - "timestamp", "severity", or "severity_desc"
        """
        if session_id not in self.contradictions:
            return []
            
        contradictions = self.contradictions[session_id]
        if unresolved_only:
            contradictions = [c for c in contradictions if not c.resolved]
        
        # Sort contradictions
        if sort_by == "severity" or sort_by == "severity_asc":
            contradictions = sorted(
                contradictions,
                key=lambda c: c.severity.score if c.severity else 0
            )
        elif sort_by == "severity_desc":
            contradictions = sorted(
                contradictions,
                key=lambda c: c.severity.score if c.severity else 0,
                reverse=True
            )
        # Default: timestamp order (already in order)
            
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
                'resolution_note': c.resolution_note,
                'severity': c.severity.to_dict() if c.severity else {
                    'level': 'medium',
                    'score': 0.5,
                    'factors': {}
                }
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
