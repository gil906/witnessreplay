"""Scene complexity scoring to determine when to generate images."""

import logging
from typing import List, Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class ComplexityScorer:
    """Scores scene complexity to determine readiness for image generation."""
    
    def __init__(self):
        # Thresholds for image generation
        self.min_score = 40  # Minimum score to generate first image
        self.incremental_score = 20  # Additional score needed for updates
        
    def calculate_complexity_score(
        self,
        scene_elements: List[Dict[str, Any]],
        conversation_turns: int,
        contradictions: int = 0
    ) -> Dict[str, Any]:
        """
        Calculate a complexity score for the current scene.
        
        Args:
            scene_elements: List of extracted scene elements
            conversation_turns: Number of conversation turns so far
            contradictions: Number of unresolved contradictions
            
        Returns:
            Dictionary with score, breakdown, and recommendation
        """
        score_breakdown = {
            'element_count': 0,
            'attribute_completeness': 0,
            'spatial_relationships': 0,
            'temporal_sequence': 0,
            'detail_richness': 0,
            'conversation_depth': 0,
        }
        
        # 1. Element count (0-20 points)
        # More elements = more complex scene
        num_elements = len(scene_elements)
        score_breakdown['element_count'] = min(20, num_elements * 5)
        
        # 2. Attribute completeness (0-25 points)
        # How well-described are the elements?
        completeness = self._calculate_attribute_completeness(scene_elements)
        score_breakdown['attribute_completeness'] = int(completeness * 25)
        
        # 3. Spatial relationships (0-20 points)
        # Are element positions specified?
        spatial_score = self._calculate_spatial_score(scene_elements)
        score_breakdown['spatial_relationships'] = int(spatial_score * 20)
        
        # 4. Temporal sequence (0-15 points)
        # Is there a timeline of events?
        temporal_score = self._calculate_temporal_score(scene_elements)
        score_breakdown['temporal_sequence'] = int(temporal_score * 15)
        
        # 5. Detail richness (0-10 points)
        # Are descriptions detailed (colors, sizes, specific features)?
        detail_score = self._calculate_detail_richness(scene_elements)
        score_breakdown['detail_richness'] = int(detail_score * 10)
        
        # 6. Conversation depth (0-10 points)
        # Has there been enough back-and-forth?
        conv_score = min(1.0, conversation_turns / 6.0)
        score_breakdown['conversation_depth'] = int(conv_score * 10)
        
        # Calculate total
        total_score = sum(score_breakdown.values())
        
        # Determine recommendation
        recommendation = self._get_recommendation(
            total_score,
            num_elements,
            contradictions
        )
        
        return {
            'total_score': total_score,
            'max_score': 100,
            'breakdown': score_breakdown,
            'recommendation': recommendation,
            'ready_for_generation': total_score >= self.min_score,
            'quality_level': self._get_quality_level(total_score),
        }
        
    def _calculate_attribute_completeness(
        self,
        elements: List[Dict[str, Any]]
    ) -> float:
        """Calculate how complete the attribute coverage is (0.0-1.0)."""
        if not elements:
            return 0.0
            
        # Critical attributes by type
        critical_attrs = {
            'person': ['description', 'position', 'color', 'clothing'],
            'vehicle': ['description', 'type', 'color', 'position'],
            'object': ['description', 'position', 'color', 'size'],
            'location_feature': ['description', 'position'],
        }
        
        total_possible = 0
        total_present = 0
        
        for element in elements:
            element_type = element.get('type', 'object')
            required = critical_attrs.get(element_type, ['description', 'position'])
            
            total_possible += len(required)
            for attr in required:
                if element.get(attr):
                    total_present += 1
                    
        if total_possible == 0:
            return 0.0
            
        return total_present / total_possible
        
    def _calculate_spatial_score(self, elements: List[Dict[str, Any]]) -> float:
        """Calculate spatial relationship score (0.0-1.0)."""
        if not elements:
            return 0.0
            
        # Check how many elements have position information
        with_position = sum(1 for e in elements if e.get('position'))
        return with_position / len(elements)
        
    def _calculate_temporal_score(self, elements: List[Dict[str, Any]]) -> float:
        """Calculate temporal sequence score (0.0-1.0)."""
        # Look for sequence or timeline information
        has_sequence = any(
            'sequence' in e or 'timestamp' in e or 'order' in e
            for e in elements
        )
        
        # Look for action verbs indicating events
        action_indicators = ['running', 'walking', 'moving', 'driving', 'standing', 'sitting']
        has_actions = any(
            any(action in str(e.get('description', '')).lower() for action in action_indicators)
            for e in elements
        )
        
        score = 0.0
        if has_sequence:
            score += 0.6
        if has_actions:
            score += 0.4
            
        return min(1.0, score)
        
    def _calculate_detail_richness(self, elements: List[Dict[str, Any]]) -> float:
        """Calculate level of detail in descriptions (0.0-1.0)."""
        if not elements:
            return 0.0
            
        # Check for specific details
        detail_indicators = {
            'color': ['red', 'blue', 'green', 'black', 'white', 'yellow', 'gray'],
            'size': ['large', 'small', 'tall', 'short', 'big', 'tiny'],
            'material': ['metal', 'wood', 'glass', 'plastic', 'concrete'],
            'condition': ['new', 'old', 'damaged', 'broken', 'clean', 'dirty'],
        }
        
        total_details = 0
        for element in elements:
            desc = str(element.get('description', '')).lower()
            
            # Check for color
            if element.get('color'):
                total_details += 1
                
            # Check for size
            if element.get('size'):
                total_details += 1
                
            # Check for specific detail words in description
            for category, words in detail_indicators.items():
                if any(word in desc for word in words):
                    total_details += 0.5
                    
        # Normalize by number of elements
        if not elements:
            return 0.0
            
        avg_details = total_details / len(elements)
        return min(1.0, avg_details / 3.0)  # 3 details per element = perfect score
        
    def _get_recommendation(
        self,
        score: int,
        num_elements: int,
        contradictions: int
    ) -> str:
        """Get a recommendation based on the score."""
        if contradictions > 0:
            return "resolve_contradictions"
        elif score < 20:
            return "gather_more_info"
        elif score < 40:
            return "ask_clarifying_questions"
        elif score < 60:
            return "ready_for_basic_generation"
        elif score < 80:
            return "ready_for_detailed_generation"
        else:
            return "ready_for_high_quality_generation"
            
    def _get_quality_level(self, score: int) -> str:
        """Get quality level label."""
        if score < 20:
            return "insufficient"
        elif score < 40:
            return "minimal"
        elif score < 60:
            return "basic"
        elif score < 80:
            return "good"
        else:
            return "excellent"
            
    def should_generate_image(
        self,
        current_score: int,
        last_generation_score: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Determine if an image should be generated now.
        
        Args:
            current_score: Current complexity score
            last_generation_score: Score when last image was generated
            
        Returns:
            Tuple of (should_generate, reason)
        """
        # First image
        if last_generation_score is None:
            if current_score >= self.min_score:
                return True, "sufficient_information"
            else:
                return False, "need_more_details"
                
        # Incremental update
        score_delta = current_score - last_generation_score
        if score_delta >= self.incremental_score:
            return True, "significant_new_information"
        else:
            return False, "insufficient_new_information"


# Global singleton instance
complexity_scorer = ComplexityScorer()
