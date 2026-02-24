"""
Service for tracking and analyzing spatial and temporal relationships between scene elements.
"""
import logging
import uuid
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from app.models.schemas import ElementRelationship, SceneElement

logger = logging.getLogger(__name__)


# Spatial relationship keywords mapping
SPATIAL_KEYWORDS = {
    "next_to": ["next to", "beside", "adjacent to", "near", "close to"],
    "in_front_of": ["in front of", "ahead of", "before"],
    "behind": ["behind", "back of", "rear of"],
    "above": ["above", "over", "on top of"],
    "below": ["below", "under", "underneath"],
    "inside": ["inside", "in", "within"],
    "outside": ["outside", "out of"],
    "across_from": ["across from", "opposite", "facing"],
}

# Temporal relationship keywords
TEMPORAL_KEYWORDS = {
    "before": ["before", "prior to", "earlier than"],
    "after": ["after", "following", "later than"],
    "during": ["during", "while", "as"],
    "simultaneous": ["at the same time", "simultaneously", "concurrently"],
}


class RelationshipTracker:
    """Tracks and analyzes relationships between scene elements."""
    
    def __init__(self):
        self.relationships: Dict[str, ElementRelationship] = {}
    
    def extract_relationships_from_statement(
        self,
        statement: str,
        elements: List[SceneElement]
    ) -> List[ElementRelationship]:
        """
        Extract potential relationships from a witness statement.
        
        Args:
            statement: The witness statement text
            elements: List of scene elements to analyze
        
        Returns:
            List of detected relationships
        """
        relationships = []
        statement_lower = statement.lower()
        
        # Check for spatial relationships
        for rel_type, keywords in SPATIAL_KEYWORDS.items():
            for keyword in keywords:
                if keyword in statement_lower:
                    # Try to identify which elements are being related
                    rel = self._create_relationship_from_context(
                        statement, elements, rel_type, keyword
                    )
                    if rel:
                        relationships.append(rel)
        
        # Check for temporal relationships
        for rel_type, keywords in TEMPORAL_KEYWORDS.items():
            for keyword in keywords:
                if keyword in statement_lower:
                    rel = self._create_relationship_from_context(
                        statement, elements, rel_type, keyword, temporal=True
                    )
                    if rel:
                        relationships.append(rel)
        
        return relationships
    
    def _create_relationship_from_context(
        self,
        statement: str,
        elements: List[SceneElement],
        rel_type: str,
        keyword: str,
        temporal: bool = False
    ) -> Optional[ElementRelationship]:
        """
        Create a relationship based on context in the statement.
        Uses simple heuristics to identify related elements.
        """
        if len(elements) < 2:
            return None
        
        # Simple heuristic: find elements mentioned around the keyword
        statement_lower = statement.lower()
        keyword_pos = statement_lower.find(keyword)
        
        if keyword_pos == -1:
            return None
        
        # Look for element descriptions before and after the keyword
        before_text = statement_lower[:keyword_pos]
        after_text = statement_lower[keyword_pos + len(keyword):]
        
        element_a = None
        element_b = None
        
        # Find elements in the before/after context
        for elem in elements:
            desc_lower = elem.description.lower()
            # Check if element description appears near the keyword
            if desc_lower in before_text[-100:]:  # Look in last 100 chars before keyword
                element_a = elem
            if desc_lower in after_text[:100]:  # Look in first 100 chars after keyword
                element_b = elem
        
        if element_a and element_b and element_a.id != element_b.id:
            return ElementRelationship(
                id=str(uuid.uuid4()),
                element_a_id=element_a.id,
                element_b_id=element_b.id,
                relationship_type=rel_type,
                description=f"{element_a.description} {rel_type.replace('_', ' ')} {element_b.description}",
                confidence=0.6 if temporal else 0.7,
                timestamp=datetime.utcnow()
            )
        
        return None
    
    def add_relationship(self, relationship: ElementRelationship):
        """Add a relationship to the tracker."""
        self.relationships[relationship.id] = relationship
        logger.info(f"Added relationship: {relationship.description}")
    
    def get_relationships_for_element(
        self,
        element_id: str
    ) -> List[ElementRelationship]:
        """Get all relationships involving a specific element."""
        return [
            rel for rel in self.relationships.values()
            if rel.element_a_id == element_id or rel.element_b_id == element_id
        ]
    
    def get_spatial_graph(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        Get a spatial graph showing how elements are connected.
        Returns a dict mapping element IDs to list of (related_element_id, relationship_type) tuples.
        """
        graph: Dict[str, List[Tuple[str, str]]] = {}
        
        for rel in self.relationships.values():
            # Only include spatial relationships (not temporal)
            if rel.relationship_type in SPATIAL_KEYWORDS:
                if rel.element_a_id not in graph:
                    graph[rel.element_a_id] = []
                if rel.element_b_id not in graph:
                    graph[rel.element_b_id] = []
                
                graph[rel.element_a_id].append((rel.element_b_id, rel.relationship_type))
                # Add reverse relationship
                reverse_type = self._get_reverse_relationship(rel.relationship_type)
                graph[rel.element_b_id].append((rel.element_a_id, reverse_type))
        
        return graph
    
    def _get_reverse_relationship(self, rel_type: str) -> str:
        """Get the reverse of a spatial relationship."""
        reverses = {
            "next_to": "next_to",
            "in_front_of": "behind",
            "behind": "in_front_of",
            "above": "below",
            "below": "above",
            "inside": "outside",
            "outside": "inside",
            "across_from": "across_from",
        }
        return reverses.get(rel_type, rel_type)
    
    def get_timeline_sequence(self) -> List[Tuple[str, str, str]]:
        """
        Get a timeline sequence from temporal relationships.
        Returns list of (element_a_id, relationship, element_b_id) ordered by time.
        """
        temporal_rels = [
            rel for rel in self.relationships.values()
            if rel.relationship_type in TEMPORAL_KEYWORDS
        ]
        
        # Sort by confidence and timestamp
        temporal_rels.sort(key=lambda r: (r.confidence, r.timestamp), reverse=True)
        
        return [
            (rel.element_a_id, rel.relationship_type, rel.element_b_id)
            for rel in temporal_rels
        ]
    
    def validate_consistency(self) -> List[str]:
        """
        Check for inconsistent relationships.
        Returns list of inconsistency warnings.
        """
        warnings = []
        
        # Check for contradictory spatial relationships
        for elem_id, connections in self.get_spatial_graph().items():
            # Check if element is both inside and outside something
            inside_rels = [c for c in connections if c[1] == "inside"]
            outside_rels = [c for c in connections if c[1] == "outside"]
            
            if inside_rels and outside_rels:
                warnings.append(
                    f"Element {elem_id} has contradictory inside/outside relationships"
                )
            
            # Check for circular "above/below" relationships
            above_rels = [c[0] for c in connections if c[1] == "above"]
            below_rels = [c[0] for c in connections if c[1] == "below"]
            
            if set(above_rels) & set(below_rels):
                warnings.append(
                    f"Element {elem_id} has circular above/below relationships"
                )
        
        return warnings


# Global relationship tracker
relationship_tracker = RelationshipTracker()
