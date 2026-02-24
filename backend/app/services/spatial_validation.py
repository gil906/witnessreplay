"""
Spatial validation service for scene reconstruction.
Validates physical plausibility of scenes including element overlaps,
realistic distances, and position constraints.
"""

import logging
import math
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.models.schemas import SceneElement, SceneVersion, ElementRelationship

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""
    ERROR = "error"      # Invalid configuration that must be fixed
    WARNING = "warning"  # Potentially unrealistic but may be intentional
    INFO = "info"        # Suggestion for improvement


class ElementCategory(str, Enum):
    """Categories of scene elements for position validation."""
    VEHICLE = "vehicle"
    PERSON = "person"
    OBJECT = "object"
    LOCATION = "location"


@dataclass
class SpatialIssue:
    """Represents a spatial validation issue."""
    issue_id: str
    severity: ValidationSeverity
    category: str
    element_ids: List[str]
    description: str
    suggestion: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "severity": self.severity.value,
            "category": self.category,
            "element_ids": self.element_ids,
            "description": self.description,
            "suggestion": self.suggestion
        }


@dataclass
class ValidationResult:
    """Result of spatial validation."""
    is_valid: bool
    issues: List[SpatialIssue]
    summary: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": [issue.to_dict() for issue in self.issues],
            "summary": self.summary,
            "error_count": len([i for i in self.issues if i.severity == ValidationSeverity.ERROR]),
            "warning_count": len([i for i in self.issues if i.severity == ValidationSeverity.WARNING]),
            "info_count": len([i for i in self.issues if i.severity == ValidationSeverity.INFO])
        }


# Standard dimensions for elements (in feet)
ELEMENT_DIMENSIONS = {
    "vehicle": {"car": (14, 6), "truck": (20, 8), "motorcycle": (7, 3), "bicycle": (6, 2), "bus": (40, 8)},
    "person": {"adult": (2, 2), "child": (1.5, 1.5)},
    "object": {"default": (2, 2)}
}

# Realistic distance ranges (in feet)
DISTANCE_RANGES = {
    "very_close": (0, 3),
    "close": (3, 10),
    "nearby": (10, 30),
    "moderate": (30, 100),
    "far": (100, 500),
    "very_far": (500, float("inf"))
}

# Position keywords for surface types
ROAD_KEYWORDS = ["road", "street", "highway", "lane", "intersection", "crosswalk", "pavement", "asphalt"]
SIDEWALK_KEYWORDS = ["sidewalk", "pavement", "walkway", "path", "pedestrian"]
PARKING_KEYWORDS = ["parking", "lot", "garage", "space", "driveway"]

# Element-location constraints: what elements should be on what surfaces
POSITION_CONSTRAINTS = {
    "vehicle": {
        "allowed": ["road", "parking", "driveway", "intersection"],
        "warning": ["sidewalk", "grass", "building"],
        "forbidden": ["inside_building", "underwater"]
    },
    "person": {
        "allowed": ["sidewalk", "road", "crosswalk", "building", "parking", "grass"],
        "warning": [],
        "forbidden": []
    }
}


class SpatialValidator:
    """
    Validates spatial relationships and physical plausibility of scene elements.
    """
    
    def __init__(self):
        self._issue_counter = 0
    
    def _generate_issue_id(self) -> str:
        """Generate unique issue ID."""
        self._issue_counter += 1
        return f"spatial_{self._issue_counter:04d}"
    
    def validate_scene(self, scene: SceneVersion, relationships: Optional[List[ElementRelationship]] = None) -> ValidationResult:
        """
        Validate entire scene for spatial plausibility.
        
        Args:
            scene: SceneVersion containing elements to validate
            relationships: Optional list of element relationships
            
        Returns:
            ValidationResult with all issues found
        """
        self._issue_counter = 0
        issues: List[SpatialIssue] = []
        
        elements = scene.elements
        
        # Run all validation checks
        issues.extend(self._check_element_overlaps(elements))
        issues.extend(self._check_distance_plausibility(elements, relationships or []))
        issues.extend(self._check_position_constraints(elements))
        issues.extend(self._check_relationship_consistency(elements, relationships or []))
        
        # Determine overall validity
        error_count = len([i for i in issues if i.severity == ValidationSeverity.ERROR])
        warning_count = len([i for i in issues if i.severity == ValidationSeverity.WARNING])
        
        is_valid = error_count == 0
        
        if error_count == 0 and warning_count == 0:
            summary = "Scene is spatially valid with no issues detected."
        elif error_count == 0:
            summary = f"Scene is valid but has {warning_count} warning(s) to review."
        else:
            summary = f"Scene has {error_count} error(s) and {warning_count} warning(s) requiring attention."
        
        return ValidationResult(is_valid=is_valid, issues=issues, summary=summary)
    
    def _categorize_element(self, element: SceneElement) -> ElementCategory:
        """Determine category of element based on type and description."""
        element_type = element.type.lower()
        desc = element.description.lower() if element.description else ""
        
        if element_type == "vehicle" or any(v in desc for v in ["car", "truck", "motorcycle", "bus", "van"]):
            return ElementCategory.VEHICLE
        elif element_type == "person" or any(p in desc for p in ["person", "man", "woman", "child", "pedestrian"]):
            return ElementCategory.PERSON
        elif element_type == "location_feature":
            return ElementCategory.LOCATION
        return ElementCategory.OBJECT
    
    def _extract_position_info(self, element: SceneElement) -> Dict[str, Any]:
        """Extract position information from element's position field."""
        position = element.position or ""
        pos_lower = position.lower()
        
        info = {
            "raw": position,
            "on_road": any(k in pos_lower for k in ROAD_KEYWORDS),
            "on_sidewalk": any(k in pos_lower for k in SIDEWALK_KEYWORDS),
            "in_parking": any(k in pos_lower for k in PARKING_KEYWORDS),
            "coordinates": self._extract_coordinates(position)
        }
        return info
    
    def _extract_coordinates(self, position: str) -> Optional[Tuple[float, float]]:
        """Try to extract numeric coordinates from position string."""
        if not position:
            return None
        
        # Look for patterns like (x, y) or x,y or "at 10, 20"
        coord_patterns = [
            r'\((\d+\.?\d*),\s*(\d+\.?\d*)\)',
            r'(\d+\.?\d*),\s*(\d+\.?\d*)',
            r'x[:\s]*(\d+\.?\d*).*y[:\s]*(\d+\.?\d*)'
        ]
        
        for pattern in coord_patterns:
            match = re.search(pattern, position, re.IGNORECASE)
            if match:
                try:
                    return (float(match.group(1)), float(match.group(2)))
                except ValueError:
                    continue
        return None
    
    def _get_element_size(self, element: SceneElement) -> Tuple[float, float]:
        """Get estimated size of element (width, depth) in feet."""
        category = self._categorize_element(element)
        desc = (element.description or "").lower()
        size_str = (element.size or "").lower()
        
        if category == ElementCategory.VEHICLE:
            if "truck" in desc or "large" in size_str:
                return ELEMENT_DIMENSIONS["vehicle"]["truck"]
            elif "motorcycle" in desc:
                return ELEMENT_DIMENSIONS["vehicle"]["motorcycle"]
            elif "bicycle" in desc or "bike" in desc:
                return ELEMENT_DIMENSIONS["vehicle"]["bicycle"]
            elif "bus" in desc:
                return ELEMENT_DIMENSIONS["vehicle"]["bus"]
            return ELEMENT_DIMENSIONS["vehicle"]["car"]
        
        elif category == ElementCategory.PERSON:
            if "child" in desc or "small" in size_str:
                return ELEMENT_DIMENSIONS["person"]["child"]
            return ELEMENT_DIMENSIONS["person"]["adult"]
        
        return ELEMENT_DIMENSIONS["object"]["default"]
    
    def _check_element_overlaps(self, elements: List[SceneElement]) -> List[SpatialIssue]:
        """Check for overlapping elements that cannot physically coexist."""
        issues = []
        
        # Only check elements with extractable coordinates
        elements_with_coords = []
        for elem in elements:
            coords = self._extract_coordinates(elem.position or "")
            if coords:
                size = self._get_element_size(elem)
                elements_with_coords.append((elem, coords, size))
        
        # Check each pair for overlap
        for i, (elem1, coord1, size1) in enumerate(elements_with_coords):
            for j, (elem2, coord2, size2) in enumerate(elements_with_coords[i+1:], i+1):
                # Calculate bounding box overlap
                overlap = self._check_bounding_box_overlap(coord1, size1, coord2, size2)
                
                if overlap > 0.5:  # Significant overlap
                    cat1 = self._categorize_element(elem1)
                    cat2 = self._categorize_element(elem2)
                    
                    # Two solid objects overlapping significantly is an error
                    if cat1 != ElementCategory.LOCATION and cat2 != ElementCategory.LOCATION:
                        issues.append(SpatialIssue(
                            issue_id=self._generate_issue_id(),
                            severity=ValidationSeverity.ERROR,
                            category="overlap",
                            element_ids=[elem1.id, elem2.id],
                            description=f"Elements '{elem1.description}' and '{elem2.description}' overlap by {overlap*100:.0f}%",
                            suggestion=f"Adjust positions to separate these elements by at least {max(size1[0], size2[0]):.1f} feet"
                        ))
                elif overlap > 0.1:  # Minor overlap
                    issues.append(SpatialIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.WARNING,
                        category="overlap",
                        element_ids=[elem1.id, elem2.id],
                        description=f"Elements '{elem1.description}' and '{elem2.description}' may be too close ({overlap*100:.0f}% overlap)",
                        suggestion="Consider adjusting positions for clearer separation"
                    ))
        
        return issues
    
    def _check_bounding_box_overlap(
        self, 
        coord1: Tuple[float, float], 
        size1: Tuple[float, float],
        coord2: Tuple[float, float], 
        size2: Tuple[float, float]
    ) -> float:
        """Calculate overlap ratio between two bounding boxes (0-1)."""
        # Calculate bounding boxes (assuming coord is center)
        x1_min, x1_max = coord1[0] - size1[0]/2, coord1[0] + size1[0]/2
        y1_min, y1_max = coord1[1] - size1[1]/2, coord1[1] + size1[1]/2
        
        x2_min, x2_max = coord2[0] - size2[0]/2, coord2[0] + size2[0]/2
        y2_min, y2_max = coord2[1] - size2[1]/2, coord2[1] + size2[1]/2
        
        # Calculate intersection
        x_overlap = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
        y_overlap = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
        
        intersection = x_overlap * y_overlap
        
        # Calculate areas
        area1 = size1[0] * size1[1]
        area2 = size2[0] * size2[1]
        min_area = min(area1, area2)
        
        if min_area == 0:
            return 0
        
        return intersection / min_area
    
    def _check_distance_plausibility(
        self, 
        elements: List[SceneElement], 
        relationships: List[ElementRelationship]
    ) -> List[SpatialIssue]:
        """Check if distances described in relationships are realistic."""
        issues = []
        
        # Check relationship descriptions for distance mentions
        distance_keywords = {
            "touching": (0, 1),
            "adjacent": (0, 3),
            "next to": (0, 5),
            "nearby": (5, 30),
            "across the street": (30, 100),
            "far": (100, 500)
        }
        
        for rel in relationships:
            desc_lower = rel.description.lower()
            
            for keyword, (min_dist, max_dist) in distance_keywords.items():
                if keyword in desc_lower:
                    # Check if there's a contradicting explicit distance
                    distance_match = re.search(r'(\d+)\s*(feet|ft|meters|m)', desc_lower)
                    if distance_match:
                        stated_dist = float(distance_match.group(1))
                        if distance_match.group(2) in ["meters", "m"]:
                            stated_dist *= 3.28  # Convert to feet
                        
                        if stated_dist < min_dist or stated_dist > max_dist:
                            issues.append(SpatialIssue(
                                issue_id=self._generate_issue_id(),
                                severity=ValidationSeverity.WARNING,
                                category="distance",
                                element_ids=[rel.element_a_id, rel.element_b_id],
                                description=f"Relationship describes '{keyword}' but states {stated_dist:.0f} feet (expected {min_dist}-{max_dist} feet)",
                                suggestion=f"Verify the distance or use a more appropriate relationship term"
                            ))
        
        # Check coordinate-based distances
        elements_with_coords = {
            elem.id: (elem, self._extract_coordinates(elem.position or ""))
            for elem in elements
        }
        
        for rel in relationships:
            if rel.element_a_id in elements_with_coords and rel.element_b_id in elements_with_coords:
                elem_a, coord_a = elements_with_coords[rel.element_a_id]
                elem_b, coord_b = elements_with_coords[rel.element_b_id]
                
                if coord_a and coord_b:
                    distance = math.sqrt((coord_a[0] - coord_b[0])**2 + (coord_a[1] - coord_b[1])**2)
                    
                    # Check for unrealistic distances based on relationship type
                    if "next_to" in rel.relationship_type and distance > 10:
                        issues.append(SpatialIssue(
                            issue_id=self._generate_issue_id(),
                            severity=ValidationSeverity.WARNING,
                            category="distance",
                            element_ids=[rel.element_a_id, rel.element_b_id],
                            description=f"Relationship 'next_to' implies proximity but elements are {distance:.1f} units apart",
                            suggestion="Either move elements closer or change relationship type"
                        ))
        
        return issues
    
    def _check_position_constraints(self, elements: List[SceneElement]) -> List[SpatialIssue]:
        """Check if elements are in appropriate locations."""
        issues = []
        
        for element in elements:
            category = self._categorize_element(element)
            pos_info = self._extract_position_info(element)
            
            if category == ElementCategory.VEHICLE:
                # Vehicles should typically be on roads or in parking areas
                if pos_info["on_sidewalk"] and not pos_info["on_road"]:
                    issues.append(SpatialIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.WARNING,
                        category="position",
                        element_ids=[element.id],
                        description=f"Vehicle '{element.description}' appears to be on sidewalk",
                        suggestion="Move vehicle to road or parking area, or clarify if this is intentional (e.g., accident scene)"
                    ))
                
                # Check for unrealistic vehicle positions
                pos_lower = (element.position or "").lower()
                if "inside" in pos_lower and "building" in pos_lower:
                    issues.append(SpatialIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.ERROR,
                        category="position",
                        element_ids=[element.id],
                        description=f"Vehicle '{element.description}' positioned inside a building",
                        suggestion="Reposition vehicle outside the building"
                    ))
            
            elif category == ElementCategory.PERSON:
                # People in the middle of a road without crosswalk context
                pos_lower = (element.position or "").lower()
                if pos_info["on_road"] and "crosswalk" not in pos_lower and "crossing" not in pos_lower:
                    issues.append(SpatialIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.INFO,
                        category="position",
                        element_ids=[element.id],
                        description=f"Person '{element.description}' positioned on road without crosswalk mention",
                        suggestion="Clarify if person is jaywalking, in a crosswalk, or if this is an accident scene"
                    ))
        
        return issues
    
    def _check_relationship_consistency(
        self, 
        elements: List[SceneElement], 
        relationships: List[ElementRelationship]
    ) -> List[SpatialIssue]:
        """Check for contradictory spatial relationships."""
        issues = []
        element_ids = {elem.id for elem in elements}
        
        # Build relationship graph
        rel_map: Dict[Tuple[str, str], List[ElementRelationship]] = {}
        for rel in relationships:
            # Skip if elements don't exist
            if rel.element_a_id not in element_ids or rel.element_b_id not in element_ids:
                continue
            
            key = tuple(sorted([rel.element_a_id, rel.element_b_id]))
            if key not in rel_map:
                rel_map[key] = []
            rel_map[key].append(rel)
        
        # Contradictory relationship types
        contradictions = {
            ("in_front_of", "behind"),
            ("above", "below"),
            ("inside", "outside"),
            ("left_of", "right_of")
        }
        
        for key, rels in rel_map.items():
            if len(rels) > 1:
                rel_types = {r.relationship_type.lower() for r in rels}
                
                for contra_pair in contradictions:
                    if contra_pair[0] in rel_types and contra_pair[1] in rel_types:
                        issues.append(SpatialIssue(
                            issue_id=self._generate_issue_id(),
                            severity=ValidationSeverity.ERROR,
                            category="relationship",
                            element_ids=list(key),
                            description=f"Contradictory relationships: '{contra_pair[0]}' and '{contra_pair[1]}' between same elements",
                            suggestion="Review witness statements and resolve the contradictory spatial descriptions"
                        ))
        
        return issues
    
    def suggest_corrections(self, scene: SceneVersion, issues: List[SpatialIssue]) -> List[Dict[str, Any]]:
        """
        Generate specific correction suggestions for identified issues.
        
        Args:
            scene: The scene being validated
            issues: List of issues from validation
            
        Returns:
            List of correction suggestions with element modifications
        """
        corrections = []
        
        for issue in issues:
            if issue.severity == ValidationSeverity.INFO:
                continue
            
            correction = {
                "issue_id": issue.issue_id,
                "category": issue.category,
                "elements": issue.element_ids,
                "action": "review",
                "details": issue.suggestion or "Review and correct manually"
            }
            
            if issue.category == "overlap":
                correction["action"] = "separate"
                correction["details"] = "Increase distance between overlapping elements"
            elif issue.category == "position":
                correction["action"] = "relocate"
                correction["details"] = issue.suggestion
            elif issue.category == "relationship":
                correction["action"] = "resolve_conflict"
                correction["details"] = "Determine correct spatial relationship from evidence"
            
            corrections.append(correction)
        
        return corrections


# Singleton instance
spatial_validator = SpatialValidator()


def validate_scene_spatial(scene: SceneVersion, relationships: Optional[List[ElementRelationship]] = None) -> Dict[str, Any]:
    """
    Convenience function to validate a scene's spatial plausibility.
    
    Args:
        scene: SceneVersion to validate
        relationships: Optional list of element relationships
        
    Returns:
        Dictionary with validation results
    """
    result = spatial_validator.validate_scene(scene, relationships)
    return result.to_dict()


def get_spatial_corrections(scene: SceneVersion, relationships: Optional[List[ElementRelationship]] = None) -> Dict[str, Any]:
    """
    Get validation results and correction suggestions.
    
    Args:
        scene: SceneVersion to validate
        relationships: Optional list of element relationships
        
    Returns:
        Dictionary with validation results and corrections
    """
    result = spatial_validator.validate_scene(scene, relationships)
    corrections = spatial_validator.suggest_corrections(scene, result.issues)
    
    return {
        "validation": result.to_dict(),
        "corrections": corrections
    }
