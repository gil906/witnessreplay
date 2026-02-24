from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class ElementRelationship(BaseModel):
    """Represents a spatial or temporal relationship between scene elements."""
    id: str
    element_a_id: str
    element_b_id: str
    relationship_type: str  # "next_to", "in_front_of", "behind", "above", "below", "inside", "before", "after"
    description: str
    confidence: float = 0.5
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EvidenceTag(BaseModel):
    """Represents an evidence tag for categorizing scene elements."""
    id: str
    element_id: str
    category: str  # "physical_evidence", "witness_observation", "environmental", "temporal"
    tag: str  # "critical", "corroborated", "disputed", "uncertain"
    notes: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SceneElement(BaseModel):
    """Represents a single element in the reconstructed scene."""
    id: str
    type: str  # "person", "vehicle", "object", "location_feature"
    description: str
    position: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    confidence: float = 0.5
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    relationships: List[str] = []  # IDs of related ElementRelationship objects
    evidence_tags: List[str] = []  # IDs of related EvidenceTag objects


class TimelineEvent(BaseModel):
    """Represents an event in the timeline."""
    id: str
    sequence: int
    description: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    image_url: Optional[str] = None


class AnimationKeyframe(BaseModel):
    """Represents a keyframe in the scene animation timeline."""
    id: str
    time_offset: float = Field(ge=0.0, description="Time offset in seconds from animation start")
    element_id: str = Field(description="ID of the scene element this keyframe affects")
    action: str = Field(description="Action type: appear, disappear, move, highlight, pulse")
    duration: float = Field(default=0.5, ge=0.0, description="Duration of this action in seconds")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Action-specific properties (position, color, etc.)")
    description: Optional[str] = Field(default=None, description="Description of what happens at this keyframe")


class SceneAnimation(BaseModel):
    """Represents animation data for a scene version."""
    id: str
    scene_version: int = Field(description="Scene version this animation applies to")
    total_duration: float = Field(default=10.0, ge=0.0, description="Total animation duration in seconds")
    keyframes: List[AnimationKeyframe] = Field(default_factory=list)
    auto_generated: bool = Field(default=True, description="Whether animation was auto-generated from timeline")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SceneMeasurementPoint(BaseModel):
    """A point in the scene for measurements (normalized 0-1 coordinates)."""
    x: float = Field(ge=0.0, le=1.0, description="Normalized X coordinate (0-1)")
    y: float = Field(ge=0.0, le=1.0, description="Normalized Y coordinate (0-1)")


class SceneMeasurement(BaseModel):
    """Represents a measurement annotation on a scene."""
    id: str
    type: str = Field(description="Measurement type: 'distance' or 'angle'")
    points: List[SceneMeasurementPoint] = Field(description="2 points for distance, 3 for angle")
    value: float = Field(description="Measured value in feet (distance) or degrees (angle)")
    unit: str = Field(default="feet", description="Unit: 'feet', 'meters', or 'degrees'")
    label: Optional[str] = Field(default=None, description="Optional user label")
    color: str = Field(default="#00d4ff", description="Display color (hex)")
    scene_version: int = Field(description="Which scene version this applies to")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EnvironmentalConditions(BaseModel):
    """Environmental conditions for a scene."""
    weather: str = Field(default="clear", description="Weather: clear, rain, snow, fog")
    lighting: str = Field(default="daylight", description="Lighting: daylight, dusk, night, artificial")
    visibility: str = Field(default="good", description="Visibility: good, moderate, poor")

    @field_validator('weather')
    @classmethod
    def validate_weather(cls, v):
        valid = ['clear', 'rain', 'snow', 'fog']
        if v not in valid:
            raise ValueError(f'weather must be one of {valid}')
        return v

    @field_validator('lighting')
    @classmethod
    def validate_lighting(cls, v):
        valid = ['daylight', 'dusk', 'night', 'artificial']
        if v not in valid:
            raise ValueError(f'lighting must be one of {valid}')
        return v

    @field_validator('visibility')
    @classmethod
    def validate_visibility(cls, v):
        valid = ['good', 'moderate', 'poor']
        if v not in valid:
            raise ValueError(f'visibility must be one of {valid}')
        return v


class EvidenceMarkerPoint(BaseModel):
    """A point for evidence marker placement (normalized 0-1 coordinates)."""
    x: float = Field(ge=0.0, le=1.0, description="Normalized X coordinate (0-1)")
    y: float = Field(ge=0.0, le=1.0, description="Normalized Y coordinate (0-1)")


class EvidenceMarker(BaseModel):
    """Represents an evidence marker placed on a scene."""
    id: str
    number: int = Field(ge=1, le=20, description="Marker number (1-20)")
    position: EvidenceMarkerPoint = Field(description="Position in normalized coordinates")
    label: str = Field(default="", max_length=200, description="Marker label/description")
    description: str = Field(default="", max_length=1000, description="Detailed description of evidence")
    category: str = Field(default="general", description="Category: general, physical, biological, digital, trace")
    color: str = Field(default="#fbbf24", description="Display color (hex)")
    scene_version: int = Field(description="Which scene version this applies to")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SceneVersion(BaseModel):
    """Represents a version of the scene reconstruction."""
    version: int
    description: str
    image_url: Optional[str] = None
    elements: List[SceneElement] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    changes_from_previous: Optional[str] = None
    measurements: List[SceneMeasurement] = []  # Measurements for this version
    evidence_markers: List[EvidenceMarker] = []  # Evidence markers for this version
    animation: Optional[SceneAnimation] = None  # Animation keyframes for this version
    environmental_conditions: EnvironmentalConditions = Field(default_factory=EnvironmentalConditions)


class WitnessSketch(BaseModel):
    """Represents a hand-drawn sketch uploaded by a witness."""
    id: str
    image_url: str  # URL to the uploaded sketch image
    thumbnail_url: Optional[str] = None  # Optional thumbnail for display
    description: Optional[str] = None  # Witness description of the sketch
    ai_interpretation: Optional[str] = None  # AI analysis of the sketch
    extracted_elements: List[Dict[str, Any]] = []  # Elements extracted by AI
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    witness_id: Optional[str] = None
    witness_name: Optional[str] = None


class WitnessStatement(BaseModel):
    """Represents a witness statement."""
    id: str
    text: str
    audio_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    is_correction: bool = False
    witness_id: Optional[str] = None  # ID of the witness who made this statement
    witness_name: Optional[str] = None  # Name of the witness (denormalized for convenience)
    detected_topics: List[str] = []  # Topics detected in this statement for branching


class InterviewBranchNode(BaseModel):
    """A node in the interview branching tree for audit tracking."""
    id: str
    topic: str  # Topic category that triggered this branch
    question_asked: str  # The question that was asked
    response_summary: str = ""  # Summary of the witness response
    child_branches: List[str] = []  # IDs of child branch nodes
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InterviewBranchingPath(BaseModel):
    """Complete interview branching path for audit purposes."""
    session_id: str
    nodes: List[InterviewBranchNode] = []
    topics_explored: List[str] = []  # List of topic categories explored
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Witness(BaseModel):
    """Represents an individual witness in a multi-witness session."""
    id: str
    name: str = "Anonymous Witness"
    contact: Optional[str] = None
    location: Optional[str] = None  # Location at time of incident
    source_type: str = "chat"  # chat, phone, voice, email
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = {}


class ReconstructionSession(BaseModel):
    """Represents a complete reconstruction session."""
    id: str
    title: str = "Untitled Session"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "active"  # active, completed, archived
    source_type: str = "chat"  # chat, phone, voice, email
    report_number: str = ""  # e.g. "RPT-2026-0001"
    case_id: Optional[str] = None
    witness_name: Optional[str] = None
    witness_contact: Optional[str] = None
    witness_location: Optional[str] = None
    witnesses: List[Witness] = []  # Multi-witness support: list of witnesses contributing to this session
    active_witness_id: Optional[str] = None  # Currently active witness for new statements
    witness_statements: List[WitnessStatement] = []
    scene_versions: List[SceneVersion] = []
    timeline: List[TimelineEvent] = []
    current_scene_elements: List[SceneElement] = []
    element_relationships: List[ElementRelationship] = []
    evidence_tags: List[EvidenceTag] = []
    witness_sketches: List[WitnessSketch] = []  # Hand-drawn sketches uploaded by witnesses
    interview_branching_path: Optional[InterviewBranchingPath] = None  # Interview branching path for audit
    metadata: Dict[str, Any] = {}


class SessionCreate(BaseModel):
    """Request model for creating a new session."""
    title: str = "Untitled Session"
    source_type: str = "chat"
    template_id: Optional[str] = None
    witness_name: Optional[str] = None
    witness_contact: Optional[str] = None
    witness_location: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

    @field_validator('source_type')
    @classmethod
    def validate_source_type(cls, v):
        valid = ['chat', 'phone', 'voice', 'email']
        if v not in valid:
            raise ValueError(f'source_type must be one of {valid}')
        return v

    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if len(v) > 200:
            raise ValueError('Title must be 200 characters or less')
        return v.strip()


class SessionUpdate(BaseModel):
    """Request model for updating a session."""
    title: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class WitnessCreate(BaseModel):
    """Request model for adding a witness to a session."""
    name: str = "Anonymous Witness"
    contact: Optional[str] = None
    location: Optional[str] = None
    source_type: str = "chat"
    metadata: Optional[Dict[str, Any]] = {}

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if len(v) > 100:
            raise ValueError('Witness name must be 100 characters or less')
        return v.strip() or "Anonymous Witness"


class WitnessUpdate(BaseModel):
    """Request model for updating a witness."""
    name: Optional[str] = None
    contact: Optional[str] = None
    location: Optional[str] = None
    source_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class WitnessResponse(BaseModel):
    """Response model for witness data."""
    id: str
    name: str
    contact: Optional[str] = None
    location: Optional[str] = None
    source_type: str = "chat"
    created_at: datetime
    statement_count: int = 0
    metadata: Dict[str, Any] = {}


class SessionResponse(BaseModel):
    """Response model for session data."""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str
    statement_count: int
    version_count: int
    witness_count: int = 0  # Number of witnesses in this session
    source_type: str = "chat"
    report_number: str = ""
    case_id: Optional[str] = None
    witness_name: Optional[str] = None
    witness_contact: Optional[str] = None
    witness_location: Optional[str] = None
    active_witness_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    type: str  # "audio", "text", "scene_update", "question", "error", "status"
    data: Any
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    services: Dict[str, bool] = {}


class ModelInfo(BaseModel):
    """Information about a Gemini model."""
    name: str
    display_name: str
    description: Optional[str] = None
    version: Optional[str] = None
    input_token_limit: Optional[int] = None
    output_token_limit: Optional[int] = None
    supported_generation_methods: List[str] = []
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None


class UsageQuota(BaseModel):
    """Quota and usage information for a model."""
    model: str
    tier: str
    requests: Dict[str, Dict[str, int]]
    tokens: Dict[str, Dict[str, int]]
    reset_time: str
    note: str


class ModelConfigUpdate(BaseModel):
    """Request to update model configuration."""
    model_name: str


class ModelsListResponse(BaseModel):
    """Response containing list of available models."""
    models: List[ModelInfo]


class Case(BaseModel):
    """A case groups multiple witness reports about the same incident."""
    id: str
    case_number: str  # e.g. "CASE-2026-0001"
    title: str = "Untitled Case"
    summary: str = ""
    location: str = ""
    timeframe: Dict[str, Any] = {}  # {"start": "...", "end": "...", "description": "..."}
    scene_image_url: Optional[str] = None
    report_ids: List[str] = []
    status: str = "open"  # open, under_review, closed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = {}


class CaseCreate(BaseModel):
    title: str = "Untitled Case"
    location: Optional[str] = ""
    metadata: Optional[Dict[str, Any]] = {}

    @field_validator('title')
    @classmethod
    def validate_case_title(cls, v):
        if not v or len(v.strip()) < 3:
            raise ValueError('Case title must be at least 3 characters')
        return v.strip()


class CaseResponse(BaseModel):
    id: str
    case_number: str
    title: str
    summary: str
    location: str
    status: str
    report_count: int
    created_at: datetime
    updated_at: datetime
    scene_image_url: Optional[str] = None
    timeframe: Dict[str, Any] = {}
    incident_type: Optional[str] = None


class SceneGenerateRequest(BaseModel):
    """Request to generate a scene image."""
    description: Optional[str] = None
    quality: str = "standard"

    @field_validator('quality')
    @classmethod
    def validate_quality(cls, v):
        valid = ['fast', 'standard', 'hd']
        if v not in valid:
            raise ValueError(f'quality must be one of {valid}')
        return v


class MeasurementCreate(BaseModel):
    """Request to create a new measurement."""
    type: str = Field(description="'distance' or 'angle'")
    points: List[Dict[str, float]] = Field(description="List of {x, y} points")
    value: float = Field(description="Measured value")
    unit: str = Field(default="feet", description="Unit of measurement")
    label: Optional[str] = None
    color: str = "#00d4ff"
    scene_version: int = Field(description="Scene version number")

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        valid = ['distance', 'angle']
        if v not in valid:
            raise ValueError(f'type must be one of {valid}')
        return v

    @field_validator('unit')
    @classmethod
    def validate_unit(cls, v):
        valid = ['feet', 'meters', 'degrees']
        if v not in valid:
            raise ValueError(f'unit must be one of {valid}')
        return v


class MeasurementUpdate(BaseModel):
    """Request to update a measurement."""
    value: Optional[float] = None
    unit: Optional[str] = None
    label: Optional[str] = None
    color: Optional[str] = None

    @field_validator('unit')
    @classmethod
    def validate_unit(cls, v):
        if v is None:
            return v
        valid = ['feet', 'meters', 'degrees']
        if v not in valid:
            raise ValueError(f'unit must be one of {valid}')
        return v


class EvidenceMarkerCreate(BaseModel):
    """Request to create a new evidence marker."""
    number: int = Field(ge=1, le=20, description="Marker number (1-20)")
    position: Dict[str, float] = Field(description="{x, y} normalized coordinates")
    label: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    category: str = Field(default="general")
    color: str = Field(default="#fbbf24")
    scene_version: int = Field(description="Scene version number")

    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        valid = ['general', 'physical', 'biological', 'digital', 'trace']
        if v not in valid:
            raise ValueError(f'category must be one of {valid}')
        return v


class EvidenceMarkerUpdate(BaseModel):
    """Request to update an evidence marker."""
    number: Optional[int] = Field(default=None, ge=1, le=20)
    position: Optional[Dict[str, float]] = None
    label: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    category: Optional[str] = None
    color: Optional[str] = None

    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        if v is None:
            return v
        valid = ['general', 'physical', 'biological', 'digital', 'trace']
        if v not in valid:
            raise ValueError(f'category must be one of {valid}')
        return v


class BackgroundTaskResponse(BaseModel):
    """Response for a background task submission."""
    task_id: str
    status: str = "pending"
    message: str = ""


class SearchRequest(BaseModel):
    """Semantic search query."""
    q: str
    limit: int = 10


# ============================================================================
# AI Structured Output Schemas
# These schemas are used with Gemini's structured JSON output mode to ensure
# consistent, parseable responses from the AI. Using response_json_schema
# reduces token waste from formatting errors and improves reliability.
# ============================================================================

class SceneElementExtracted(BaseModel):
    """A scene element extracted from witness testimony."""
    type: str = Field(description="Element type: person, vehicle, object, location_feature, or environmental")
    description: str = Field(description="Detailed physical description of the element")
    position: Optional[str] = Field(default=None, description="Spatial position relative to other elements")
    color: Optional[str] = Field(default=None, description="Specific color if mentioned")
    size: Optional[str] = Field(default=None, description="Dimensions or size comparison")
    movement: Optional[str] = Field(default=None, description="Actions or direction if mentioned")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    mentioned_by: Optional[str] = Field(default=None, description="Which statement mentioned this")


class TimelineEventExtracted(BaseModel):
    """A timeline event extracted from witness testimony."""
    sequence: int = Field(description="Order in the sequence of events")
    time: Optional[str] = Field(default=None, description="Specific time if mentioned")
    description: str = Field(description="What happened at this point")
    elements_involved: List[str] = Field(default_factory=list, description="Elements involved in this event")


class LocationInfo(BaseModel):
    """Location information extracted from testimony."""
    description: str = Field(default="", description="Full location description")
    type: str = Field(default="other", description="Location type: intersection, building, road, parking_lot, or other")
    landmarks: List[str] = Field(default_factory=list, description="Nearby landmarks mentioned")


class EnvironmentalInfo(BaseModel):
    """Environmental conditions extracted from testimony."""
    weather: Optional[str] = Field(default=None, description="Weather conditions if mentioned")
    lighting: Optional[str] = Field(default=None, description="Lighting conditions")
    time_of_day: Optional[str] = Field(default=None, description="Time of day: morning, afternoon, evening, or night")
    visibility: Optional[str] = Field(default=None, description="Visibility: good, moderate, or poor")


class SketchElementExtracted(BaseModel):
    """An element identified in a hand-drawn sketch."""
    type: str = Field(description="Element type: person, vehicle, object, location_feature, arrow, text, symbol")
    description: str = Field(description="Description of what this element appears to represent")
    position: str = Field(description="Position in the sketch: top-left, center, bottom-right, etc.")
    size: str = Field(default="medium", description="Relative size: small, medium, large")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence in identification")
    possible_labels: List[str] = Field(default_factory=list, description="Possible text labels near this element")


class SketchInterpretationResponse(BaseModel):
    """Structured response for AI interpretation of a hand-drawn witness sketch.
    
    Used with Gemini's vision capabilities to analyze sketches and extract
    scene elements for reconstruction.
    """
    overall_description: str = Field(description="A 2-3 sentence description of what the sketch depicts")
    sketch_quality: str = Field(default="readable", description="Quality: clear, readable, unclear, or illegible")
    scene_type: str = Field(default="other", description="Type of scene: intersection, building_interior, parking_lot, street, other")
    elements: List[SketchElementExtracted] = Field(default_factory=list, description="All identifiable elements in the sketch")
    spatial_relationships: List[str] = Field(default_factory=list, description="Spatial relationships between elements, e.g., 'car is left of building'")
    movement_indicators: List[str] = Field(default_factory=list, description="Any arrows or movement indicators, e.g., 'arrow pointing north'")
    text_annotations: List[str] = Field(default_factory=list, description="Any readable text in the sketch")
    scale_reference: Optional[str] = Field(default=None, description="Any scale reference if present")
    clarification_needed: List[str] = Field(default_factory=list, description="Aspects that need clarification from the witness")


class SceneExtractionResponse(BaseModel):
    """Structured response schema for scene extraction from witness testimony.
    
    This schema is used with Gemini's response_json_schema feature to ensure
    consistent, parseable JSON output for scene reconstruction.
    """
    scene_description: str = Field(description="A vivid 3-4 sentence description of the entire scene")
    incident_type: str = Field(default="other", description="Type: accident, crime, incident, or other")
    incident_subtype: Optional[str] = Field(default=None, description="Specific type like traffic_collision, armed_robbery, etc.")
    elements: List[SceneElementExtracted] = Field(default_factory=list, description="All scene elements extracted")
    timeline: List[TimelineEventExtracted] = Field(default_factory=list, description="Sequence of events")
    location: LocationInfo = Field(default_factory=LocationInfo, description="Location information")
    environmental: EnvironmentalInfo = Field(default_factory=EnvironmentalInfo, description="Environmental conditions")
    contradictions: List[str] = Field(default_factory=list, description="Any contradictions noticed in testimony")
    confidence_assessment: str = Field(default="medium", description="Overall reliability: high, medium, or low")
    ambiguities: List[str] = Field(default_factory=list, description="Things that need clarification")
    next_question: Optional[str] = Field(default=None, description="The most important follow-up question")


class IncidentClassificationResponse(BaseModel):
    """Structured response for incident type classification."""
    type: str = Field(description="Incident type: accident, crime, incident, or other")
    subtype: str = Field(description="Specific incident subtype")
    severity: str = Field(description="Severity level: critical, high, medium, or low")


class CaseTimeframe(BaseModel):
    """Timeframe information for a case."""
    start: Optional[str] = Field(default=None, description="Estimated start time/date")
    end: Optional[str] = Field(default=None, description="Estimated end time/date if applicable")
    description: str = Field(default="", description="Human-readable timeframe description")


class CaseSummaryResponse(BaseModel):
    """Structured response for case summary generation."""
    summary: str = Field(description="A comprehensive 2-3 paragraph summary of the incident")
    title: str = Field(description="A clear, descriptive title for this case")
    location: str = Field(default="", description="The specific location if mentioned")
    timeframe: CaseTimeframe = Field(default_factory=CaseTimeframe, description="Timeframe information")
    key_elements: List[str] = Field(default_factory=list, description="List of key elements")
    scene_description: str = Field(default="", description="Description for generating a scene image")


class CaseMatchResponse(BaseModel):
    """Structured response for case matching decisions."""
    matches_existing_case: bool = Field(description="Whether the report matches an existing case")
    matched_case_id: Optional[str] = Field(default=None, description="ID of matched case if any")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence in the match")
    reasoning: str = Field(default="", description="Brief explanation of match decision")


# ============================================================================
# Case Linking Schemas
# ============================================================================

class CaseRelationship(BaseModel):
    """Represents a relationship between two cases."""
    id: str
    case_a_id: str
    case_b_id: str
    relationship_type: str  # "related", "same_incident", "serial"
    link_reason: str  # "suspect", "location", "mo", "time_proximity", "semantic", "manual"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: Optional[str] = None
    created_by: str = "system"  # "system" or "manual"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CaseRelationshipCreate(BaseModel):
    """Request model for creating a case relationship."""
    case_a_id: str
    case_b_id: str
    relationship_type: str = "related"
    link_reason: str = "manual"
    notes: Optional[str] = None

    @field_validator('relationship_type')
    @classmethod
    def validate_relationship_type(cls, v):
        valid = ['related', 'same_incident', 'serial']
        if v not in valid:
            raise ValueError(f'relationship_type must be one of {valid}')
        return v

    @field_validator('link_reason')
    @classmethod
    def validate_link_reason(cls, v):
        valid = ['suspect', 'location', 'mo', 'time_proximity', 'semantic', 'manual']
        if v not in valid:
            raise ValueError(f'link_reason must be one of {valid}')
        return v


class CaseRelationshipResponse(BaseModel):
    """Response model for a case relationship with resolved case info."""
    id: str
    related_case_id: str
    related_case_number: str
    related_case_title: str
    relationship_type: str
    link_reason: str
    confidence: float
    notes: Optional[str]
    created_by: str
    created_at: datetime


class CaseSimilarityResult(BaseModel):
    """Result from similarity analysis between cases."""
    case_id: str
    case_number: str
    title: str
    similarity_score: float
    matching_factors: List[str]  # e.g. ["location", "time_proximity", "semantic"]
