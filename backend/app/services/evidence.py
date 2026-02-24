"""
Service for evidence tagging and categorization.
Helps organize and prioritize scene elements based on their evidentiary value.
"""
import logging
import uuid
from typing import List, Dict, Optional
from datetime import datetime

from app.models.schemas import EvidenceTag, SceneElement

logger = logging.getLogger(__name__)


# Evidence categories with detection keywords
EVIDENCE_CATEGORIES = {
    "physical_evidence": ["blood", "fingerprint", "weapon", "evidence", "DNA", "trace", "debris"],
    "witness_observation": ["saw", "heard", "noticed", "observed", "witnessed"],
    "environmental": ["weather", "lighting", "temperature", "condition", "visibility"],
    "temporal": ["time", "when", "duration", "before", "after", "during"],
}

# Evidence quality tags with keywords
QUALITY_INDICATORS = {
    "critical": ["definitely", "absolutely", "certain", "sure", "clearly", "obviously"],
    "corroborated": ["confirmed", "verified", "multiple", "others saw", "also said"],
    "disputed": ["maybe", "possibly", "might", "could be", "not sure", "unclear"],
    "uncertain": ["think", "guess", "believe", "probably", "approximately", "around"],
}


class EvidenceManager:
    """Manages evidence tags and categorization for scene elements."""
    
    def __init__(self):
        self.tags: Dict[str, EvidenceTag] = {}
    
    def auto_tag_element(
        self,
        element: SceneElement,
        statement_text: str
    ) -> List[EvidenceTag]:
        """
        Automatically generate evidence tags for an element based on statement context.
        
        Args:
            element: The scene element to tag
            statement_text: The witness statement that mentioned this element
        
        Returns:
            List of generated evidence tags
        """
        tags = []
        statement_lower = statement_text.lower()
        
        # Detect category
        category = self._detect_category(element, statement_lower)
        
        # Detect quality/reliability
        quality = self._detect_quality(statement_lower)
        
        # Create primary category tag
        if category:
            tag = EvidenceTag(
                id=str(uuid.uuid4()),
                element_id=element.id,
                category=category,
                tag="auto_categorized",
                notes=f"Automatically categorized as {category}",
                timestamp=datetime.utcnow()
            )
            tags.append(tag)
            self.tags[tag.id] = tag
        
        # Create quality tag
        if quality:
            tag = EvidenceTag(
                id=str(uuid.uuid4()),
                element_id=element.id,
                category="witness_observation",
                tag=quality,
                notes=f"Statement reliability: {quality}",
                timestamp=datetime.utcnow()
            )
            tags.append(tag)
            self.tags[tag.id] = tag
        
        return tags
    
    def _detect_category(self, element: SceneElement, statement: str) -> Optional[str]:
        """Detect the evidence category based on element and statement."""
        # Check element description and statement for category keywords
        combined_text = f"{element.description} {statement}".lower()
        
        scores = {}
        for category, keywords in EVIDENCE_CATEGORIES.items():
            score = sum(1 for keyword in keywords if keyword in combined_text)
            if score > 0:
                scores[category] = score
        
        if scores:
            # Return category with highest score
            return max(scores, key=scores.get)
        
        # Default based on element type
        type_defaults = {
            "person": "witness_observation",
            "vehicle": "physical_evidence",
            "object": "physical_evidence",
            "location_feature": "environmental",
        }
        return type_defaults.get(element.type, "witness_observation")
    
    def _detect_quality(self, statement: str) -> Optional[str]:
        """Detect the quality/reliability tag based on statement language."""
        statement_lower = statement.lower()
        
        scores = {}
        for quality, keywords in QUALITY_INDICATORS.items():
            score = sum(1 for keyword in keywords if keyword in statement_lower)
            if score > 0:
                scores[quality] = score
        
        if scores:
            return max(scores, key=scores.get)
        
        return None
    
    def add_manual_tag(
        self,
        element_id: str,
        category: str,
        tag: str,
        notes: Optional[str] = None
    ) -> EvidenceTag:
        """
        Manually add an evidence tag.
        
        Args:
            element_id: ID of the element to tag
            category: Evidence category
            tag: Tag label
            notes: Optional notes
        
        Returns:
            The created EvidenceTag
        """
        evidence_tag = EvidenceTag(
            id=str(uuid.uuid4()),
            element_id=element_id,
            category=category,
            tag=tag,
            notes=notes,
            timestamp=datetime.utcnow()
        )
        self.tags[evidence_tag.id] = evidence_tag
        logger.info(f"Added manual tag '{tag}' to element {element_id}")
        return evidence_tag
    
    def get_tags_for_element(self, element_id: str) -> List[EvidenceTag]:
        """Get all tags for a specific element."""
        return [
            tag for tag in self.tags.values()
            if tag.element_id == element_id
        ]
    
    def get_critical_evidence(self) -> List[str]:
        """Get IDs of elements tagged as critical evidence."""
        return [
            tag.element_id for tag in self.tags.values()
            if tag.tag == "critical"
        ]
    
    def get_disputed_evidence(self) -> List[str]:
        """Get IDs of elements tagged as disputed."""
        return [
            tag.element_id for tag in self.tags.values()
            if tag.tag == "disputed"
        ]
    
    def get_evidence_by_category(self, category: str) -> List[str]:
        """Get element IDs for a specific evidence category."""
        return [
            tag.element_id for tag in self.tags.values()
            if tag.category == category
        ]
    
    def generate_evidence_summary(self, elements: List[SceneElement]) -> Dict[str, any]:
        """
        Generate a summary of evidence categorization.
        
        Returns:
            Dictionary with evidence statistics and breakdowns
        """
        element_map = {elem.id: elem for elem in elements}
        
        # Count by category
        category_counts = {}
        for category in EVIDENCE_CATEGORIES.keys():
            category_counts[category] = len(self.get_evidence_by_category(category))
        
        # Count by quality
        quality_counts = {}
        for quality in QUALITY_INDICATORS.keys():
            quality_counts[quality] = len([
                tag for tag in self.tags.values()
                if tag.tag == quality
            ])
        
        # Get critical items
        critical_elements = []
        for elem_id in self.get_critical_evidence():
            if elem_id in element_map:
                critical_elements.append({
                    "id": elem_id,
                    "description": element_map[elem_id].description,
                    "type": element_map[elem_id].type
                })
        
        # Get disputed items
        disputed_elements = []
        for elem_id in self.get_disputed_evidence():
            if elem_id in element_map:
                disputed_elements.append({
                    "id": elem_id,
                    "description": element_map[elem_id].description,
                    "type": element_map[elem_id].type
                })
        
        return {
            "total_tags": len(self.tags),
            "category_breakdown": category_counts,
            "quality_breakdown": quality_counts,
            "critical_evidence": critical_elements,
            "disputed_evidence": disputed_elements,
        }


# Global evidence manager
evidence_manager = EvidenceManager()
