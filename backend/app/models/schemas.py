from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


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


class TimelineEvent(BaseModel):
    """Represents an event in the timeline."""
    id: str
    sequence: int
    description: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    image_url: Optional[str] = None


class SceneVersion(BaseModel):
    """Represents a version of the scene reconstruction."""
    version: int
    description: str
    image_url: Optional[str] = None
    elements: List[SceneElement] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    changes_from_previous: Optional[str] = None


class WitnessStatement(BaseModel):
    """Represents a witness statement."""
    id: str
    text: str
    audio_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    is_correction: bool = False


class ReconstructionSession(BaseModel):
    """Represents a complete reconstruction session."""
    id: str
    title: str = "Untitled Session"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "active"  # active, completed, archived
    witness_statements: List[WitnessStatement] = []
    scene_versions: List[SceneVersion] = []
    timeline: List[TimelineEvent] = []
    current_scene_elements: List[SceneElement] = []
    metadata: Dict[str, Any] = {}


class SessionCreate(BaseModel):
    """Request model for creating a new session."""
    title: Optional[str] = "Untitled Session"
    metadata: Optional[Dict[str, Any]] = {}


class SessionUpdate(BaseModel):
    """Request model for updating a session."""
    title: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionResponse(BaseModel):
    """Response model for session data."""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str
    statement_count: int
    version_count: int


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
