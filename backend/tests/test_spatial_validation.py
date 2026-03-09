"""
Unit tests for spatial validation service.
"""

import pytest
from datetime import datetime
from app.services.spatial_validation import (
    SpatialValidator,
    ValidationSeverity,
    SpatialIssue,
    validate_scene_spatial,
    get_spatial_corrections,
)
from app.models.schemas import SceneElement, SceneVersion, ElementRelationship


@pytest.fixture
def validator():
    return SpatialValidator()


@pytest.fixture
def basic_scene():
    """Scene with no issues."""
    return SceneVersion(
        version=1,
        description="Test scene",
        elements=[
            SceneElement(
                id="car1",
                type="vehicle",
                description="Red car",
                position="on the road at (10, 5)",
                confidence=0.8
            ),
            SceneElement(
                id="person1",
                type="person",
                description="Adult male",
                position="on the sidewalk at (10, 20)",
                confidence=0.9
            )
        ]
    )


@pytest.fixture
def overlapping_scene():
    """Scene with overlapping elements."""
    return SceneVersion(
        version=1,
        description="Test scene with overlap",
        elements=[
            SceneElement(
                id="car1",
                type="vehicle",
                description="Red car",
                position="at (10, 10)",
                confidence=0.8
            ),
            SceneElement(
                id="car2",
                type="vehicle",
                description="Blue car",
                position="at (11, 10)",  # Very close to car1
                confidence=0.8
            )
        ]
    )


@pytest.fixture
def invalid_position_scene():
    """Scene with invalid element positions."""
    return SceneVersion(
        version=1,
        description="Test scene with invalid positions",
        elements=[
            SceneElement(
                id="car1",
                type="vehicle",
                description="Red car",
                position="on the sidewalk near shop",
                confidence=0.8
            ),
            SceneElement(
                id="car2",
                type="vehicle",
                description="Blue truck",
                position="inside the building lobby",
                confidence=0.7
            )
        ]
    )


class TestSpatialValidator:
    """Tests for SpatialValidator class."""

    def test_validate_empty_scene(self, validator):
        """Test validation of scene with no elements."""
        scene = SceneVersion(version=1, description="Empty", elements=[])
        result = validator.validate_scene(scene)
        
        assert result.is_valid is True
        assert len(result.issues) == 0
        assert "no issues" in result.summary.lower()

    def test_validate_basic_scene(self, validator, basic_scene):
        """Test validation of valid scene."""
        result = validator.validate_scene(basic_scene)
        
        # Should have no errors (may have info messages)
        errors = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(errors) == 0

    def test_detect_overlapping_elements(self, validator, overlapping_scene):
        """Test detection of overlapping elements."""
        result = validator.validate_scene(overlapping_scene)
        
        overlap_issues = [i for i in result.issues if i.category == "overlap"]
        assert len(overlap_issues) > 0
        assert "car1" in overlap_issues[0].element_ids or "car2" in overlap_issues[0].element_ids

    def test_detect_invalid_vehicle_position(self, validator, invalid_position_scene):
        """Test detection of vehicles in invalid positions."""
        result = validator.validate_scene(invalid_position_scene)
        
        position_issues = [i for i in result.issues if i.category == "position"]
        assert len(position_issues) > 0
        
        # Check that building issue is an error
        building_issues = [i for i in position_issues if "inside" in i.description.lower()]
        assert any(i.severity == ValidationSeverity.ERROR for i in building_issues)

    def test_extract_coordinates(self, validator):
        """Test coordinate extraction from position strings."""
        coords = validator._extract_coordinates("at (10, 20)")
        assert coords == (10.0, 20.0)
        
        coords = validator._extract_coordinates("position x:15 y:25")
        assert coords == (15.0, 25.0)
        
        coords = validator._extract_coordinates("somewhere on the road")
        assert coords is None

    def test_categorize_element(self, validator):
        """Test element categorization."""
        from app.services.spatial_validation import ElementCategory
        
        car = SceneElement(id="1", type="vehicle", description="Red sedan")
        assert validator._categorize_element(car) == ElementCategory.VEHICLE
        
        person = SceneElement(id="2", type="person", description="Man in blue shirt")
        assert validator._categorize_element(person) == ElementCategory.PERSON
        
        tree = SceneElement(id="3", type="location_feature", description="Oak tree")
        assert validator._categorize_element(tree) == ElementCategory.LOCATION

    def test_get_element_size(self, validator):
        """Test element size estimation."""
        car = SceneElement(id="1", type="vehicle", description="Sedan car")
        size = validator._get_element_size(car)
        assert size[0] > 10  # Cars are > 10 feet long
        
        motorcycle = SceneElement(id="2", type="vehicle", description="Motorcycle")
        moto_size = validator._get_element_size(motorcycle)
        assert moto_size[0] < size[0]  # Motorcycle smaller than car

    def test_suggest_corrections(self, validator, overlapping_scene):
        """Test correction suggestions."""
        result = validator.validate_scene(overlapping_scene)
        corrections = validator.suggest_corrections(overlapping_scene, result.issues)
        
        assert len(corrections) > 0
        assert any(c["action"] == "separate" for c in corrections)


class TestRelationshipValidation:
    """Tests for relationship consistency validation."""

    def test_contradictory_relationships(self, validator):
        """Test detection of contradictory spatial relationships."""
        scene = SceneVersion(
            version=1,
            description="Test",
            elements=[
                SceneElement(id="a", type="vehicle", description="Car A"),
                SceneElement(id="b", type="vehicle", description="Car B")
            ]
        )
        
        relationships = [
            ElementRelationship(
                id="r1",
                element_a_id="a",
                element_b_id="b",
                relationship_type="in_front_of",
                description="A is in front of B"
            ),
            ElementRelationship(
                id="r2",
                element_a_id="a",
                element_b_id="b",
                relationship_type="behind",
                description="A is behind B"
            )
        ]
        
        result = validator.validate_scene(scene, relationships)
        
        rel_issues = [i for i in result.issues if i.category == "relationship"]
        assert len(rel_issues) > 0
        assert rel_issues[0].severity == ValidationSeverity.ERROR


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_validate_scene_spatial(self, basic_scene):
        """Test validate_scene_spatial function."""
        result = validate_scene_spatial(basic_scene)
        
        assert "is_valid" in result
        assert "issues" in result
        assert "summary" in result
        assert "error_count" in result

    def test_get_spatial_corrections(self, overlapping_scene):
        """Test get_spatial_corrections function."""
        result = get_spatial_corrections(overlapping_scene)
        
        assert "validation" in result
        assert "corrections" in result
        assert isinstance(result["corrections"], list)


class TestDistanceValidation:
    """Tests for distance plausibility checks."""

    def test_distance_keyword_mismatch(self, validator):
        """Test detection of distance description mismatches."""
        scene = SceneVersion(
            version=1,
            description="Test",
            elements=[
                SceneElement(id="a", type="vehicle", description="Car A"),
                SceneElement(id="b", type="vehicle", description="Car B")
            ]
        )
        
        relationships = [
            ElementRelationship(
                id="r1",
                element_a_id="a",
                element_b_id="b",
                relationship_type="next_to",
                description="Car A is touching car B, 100 feet apart"
            )
        ]
        
        result = validator.validate_scene(scene, relationships)
        
        distance_issues = [i for i in result.issues if i.category == "distance"]
        assert len(distance_issues) > 0


class TestPersonPositionValidation:
    """Tests for person position validation."""

    def test_person_on_road_warning(self, validator):
        """Test info message for person on road without crosswalk."""
        scene = SceneVersion(
            version=1,
            description="Test",
            elements=[
                SceneElement(
                    id="p1",
                    type="person",
                    description="Pedestrian",
                    position="standing in the middle of the road"
                )
            ]
        )
        
        result = validator.validate_scene(scene)
        
        position_issues = [i for i in result.issues if i.category == "position"]
        assert len(position_issues) > 0
        assert position_issues[0].severity == ValidationSeverity.INFO


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
