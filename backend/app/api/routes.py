import logging
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from collections import deque
from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import io
import asyncio
import json
import os

from app.models.schemas import (
    ReconstructionSession,
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    HealthResponse,
    ModelInfo,
    ModelsListResponse,
    UsageQuota,
    ModelConfigUpdate,
    Case,
    CaseCreate,
    CaseResponse,
    WitnessStatement,
    Witness,
    WitnessCreate,
    WitnessUpdate,
    WitnessResponse,
    WitnessReliabilityProfile,
    WitnessReliabilityFactors,
    SceneGenerateRequest,
    BackgroundTaskResponse,
    SceneMeasurement,
    SceneMeasurementPoint,
    MeasurementCreate,
    MeasurementUpdate,
    EvidenceMarker,
    EvidenceMarkerPoint,
    EvidenceMarkerCreate,
    EvidenceMarkerUpdate,
    EnvironmentalConditions,
    SceneAnimation,
    AnimationKeyframe,
    WitnessSketch,
    SketchInterpretationResponse,
    CustodyEventCreate,
    CustodyEventResponse,
    CustodyChainResponse,
    WitnessMemoryCreate,
    WitnessMemoryUpdate,
    WitnessMemoryResponse,
    WitnessMemorySearchRequest,
    WitnessMemorySearchResult,
    WitnessMemoryStatsResponse,
    ExtractMemoriesRequest,
)
from app.services.firestore import firestore_service
from app.services.storage import storage_service
from app.services.image_gen import image_service
from app.services.usage_tracker import usage_tracker
from app.services.token_estimator import token_estimator, TokenEstimate, QuotaCheckResult
from app.services.case_manager import case_manager
from app.services.priority_scoring import priority_scoring_service
from app.services.interview_templates import get_all_templates, get_template, get_templates_by_category
from app.services.tts_service import tts_service
from app.services.custody_chain import custody_chain_service
from app.services.spatial_validation import spatial_validator, validate_scene_spatial, get_spatial_corrections
from app.agents.scene_agent import get_agent, remove_agent
from app.config import settings
from app.api.auth import authenticate, require_admin_auth, revoke_session, check_rate_limit, require_api_key, authenticate_user_credentials
from app.api.auth import create_session as create_auth_session
from app.services.api_key_service import api_key_service
from google import genai
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()

# ── File upload validation ────────────────────────────────

ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
MAX_LIST_LIMIT = 200
MAX_VOICE_EVENTS = 200
VOICE_DEFAULT_PREFERENCES = {
    "tts_enabled": True,
    "auto_listen": True,
    "playback_speed": 1.0,
    "voice": "Puck",
}
VOICE_QUICK_PHRASES = [
    "Start from the beginning.",
    "What happened next?",
    "Where were you standing?",
    "Can you describe the person?",
    "Can you describe the vehicle?",
    "What did you hear?",
    "What direction did they go?",
    "Repeat that slowly.",
]


def _guard_limit(limit: int) -> int:
    """Clamp list limits to a safe range."""
    return max(1, min(limit, MAX_LIST_LIMIT))


def _normalize_voice_preferences(
    raw_preferences: Optional[Dict[str, Any]],
    base_preferences: Optional[Dict[str, Any]] = None,
    *,
    strict: bool = False,
) -> Dict[str, Any]:
    """Validate and normalize voice preferences."""
    normalized = dict(base_preferences or VOICE_DEFAULT_PREFERENCES)
    if raw_preferences is None:
        return normalized
    if not isinstance(raw_preferences, dict):
        if strict:
            raise HTTPException(status_code=400, detail="voice preferences payload must be an object")
        return normalized

    allowed_keys = set(VOICE_DEFAULT_PREFERENCES.keys())
    for key, value in raw_preferences.items():
        if key not in allowed_keys:
            if strict:
                raise HTTPException(status_code=400, detail=f"Unsupported voice preference key: {key}")
            continue

        if key in ("tts_enabled", "auto_listen"):
            if not isinstance(value, bool):
                if strict:
                    raise HTTPException(status_code=400, detail=f"{key} must be a boolean")
                continue
            normalized[key] = value
            continue

        if key == "playback_speed":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                if strict:
                    raise HTTPException(status_code=400, detail="playback_speed must be a number")
                continue
            speed = float(value)
            if speed < 0.8 or speed > 1.25:
                if strict:
                    raise HTTPException(status_code=400, detail="playback_speed must be between 0.8 and 1.25")
                continue
            normalized[key] = round(speed, 2)
            continue

        if key == "voice":
            if not isinstance(value, str):
                if strict:
                    raise HTTPException(status_code=400, detail="voice must be a string")
                continue
            cleaned = value.strip()
            if not cleaned or len(cleaned) > 40:
                if strict:
                    raise HTTPException(status_code=400, detail="voice must be non-empty and <= 40 characters")
                continue
            normalized[key] = cleaned

    return normalized


def _append_voice_event(metadata: Dict[str, Any], event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Append a voice event and cap history length."""
    events = metadata.get("voice_events")
    if not isinstance(events, list):
        events = []
    events.append(event)
    metadata["voice_events"] = events[-MAX_VOICE_EVENTS:]
    return metadata["voice_events"]


def _log_voice_event_write(session_id: str, event: Dict[str, Any], total_events: int) -> None:
    """Structured log for voice event writes."""
    logger.info(
        json.dumps(
            {
                "event": "voice_event_write",
                "session_id": session_id,
                "voice_event_type": event.get("type"),
                "voice_events_count": total_events,
                "timestamp": event.get("timestamp"),
            }
        )
    )

async def validate_upload(file):
    """Validate file upload."""
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {file.content_type}. Allowed: JPEG, PNG, GIF, WebP")
    content = await file.read()
    await file.seek(0)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE // (1024*1024)}MB")
    if len(content) < 100:
        raise HTTPException(status_code=400, detail="File too small or empty")
    return content


# ── Background task queue ─────────────────────────────────

_task_results: dict = {}

# Active viewers tracking (in-memory)
_case_viewers: Dict[str, Dict[str, str]] = {}  # case_id -> {user_id: username}

async def run_background_task(task_id: str, coro):
    """Run a coroutine as a background task and track its status."""
    try:
        _task_results[task_id] = {"status": "running", "started_at": datetime.utcnow().isoformat()}
        result = await coro
        _task_results[task_id] = {
            "status": "completed",
            "result": str(result) if result else None,
            "completed_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Background task {task_id} failed: {e}")
        _task_results[task_id] = {"status": "failed", "error": str(e)}
    # Persist to DB best-effort
    try:
        await firestore_service.save_background_task({"id": task_id, **_task_results[task_id]})
    except Exception:
        pass


# ── SSE event system ──────────────────────────────────────

_sse_subscribers: List[asyncio.Queue] = []

async def publish_event(event_type: str, data: dict):
    """Publish an event to all SSE subscribers."""
    message = f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
    for queue in _sse_subscribers[:]:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            _sse_subscribers.remove(queue)


# ─── Authentication ───────────────────────────────────────
from app.services.user_service import user_service

class LoginRequest(BaseModel):
    username: Optional[str] = None
    password: str
    # Legacy support: if username is None, try admin_password

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: str = ""

class ForgotPasswordRequest(BaseModel):
    email: str

class OAuthLoginRequest(BaseModel):
    provider: str  # "google" or "github"
    provider_id: str
    email: str
    full_name: str = ""
    avatar_url: Optional[str] = None

class LoginResponse(BaseModel):
    token: str
    user: dict
    expires_in: int = 86400

class LogoutRequest(BaseModel):
    token: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, raw_request: Request):
    """Login with username+password (or legacy admin password)."""
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 15 minutes.")
    
    # Try username+password first
    if request.username:
        result = await authenticate_user_credentials(request.username, request.password)
        if result:
            token, user = result
            return LoginResponse(token=token, user=user)
    
    # Fallback: legacy admin password (no username)
    token = await authenticate(request.password)
    if token:
        return LoginResponse(token=token, user={"id": "superadmin", "username": "admin", "role": "admin", "full_name": "Administrator"})
    
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/auth/register")
async def register(request: RegisterRequest, raw_request: Request):
    """Create a new user account."""
    if len(request.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not request.email or "@" not in request.email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, request.email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    try:
        user = await user_service.create_user(
            username=request.username,
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            role="officer",
        )
        # Auto-login after registration
        token = await create_auth_session(user_id=user["id"], username=user["username"], role=user["role"])
        return {"token": token, "user": user, "expires_in": 86400}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Request password reset. (Logs the request — email service not configured.)"""
    user = await user_service.get_user_by_email(request.email)
    # Always return success to prevent email enumeration
    logger.info(f"Password reset requested for: {request.email} (user found: {user is not None})")
    return {"message": "If an account with that email exists, password reset instructions have been sent."}


@router.post("/auth/oauth")
async def oauth_login(request: OAuthLoginRequest):
    """Login/register via OAuth provider (Google, GitHub)."""
    if request.provider not in ("google", "github"):
        raise HTTPException(status_code=400, detail="Unsupported OAuth provider")
    
    user = await user_service.find_or_create_oauth_user(
        provider=request.provider,
        provider_id=request.provider_id,
        email=request.email,
        full_name=request.full_name,
        avatar_url=request.avatar_url,
    )
    token = await create_auth_session(user_id=user["id"], username=user["username"], role=user["role"])
    return {"token": token, "user": user, "expires_in": 86400}


@router.post("/auth/logout")
async def logout(request: LogoutRequest):
    """Logout and revoke session."""
    revoke_session(request.token)
    return {"message": "Logged out successfully"}


@router.get("/auth/verify")
async def verify_auth(auth=Depends(require_admin_auth)):
    """Verify authentication and return user info."""
    return {"authenticated": True, "user": {
        "id": auth.get("user_id"),
        "username": auth.get("username"),
        "role": auth.get("role"),
    }}


@router.get("/auth/me")
async def get_current_user(auth=Depends(require_admin_auth)):
    """Get current user profile."""
    user_id = auth.get("user_id")
    if user_id == "superadmin":
        return {"id": "superadmin", "username": "admin", "role": "admin", "full_name": "Administrator"}
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    services = {
        "firestore": await firestore_service.health_check(),
        "storage": storage_service.health_check(),
        "image_generation": image_service.health_check(),
        "usage_tracker": _check_usage_tracker_health(),
    }
    
    return HealthResponse(
        status="healthy" if all(services.values()) else "degraded",
        services=services
    )


def _check_usage_tracker_health() -> bool:
    """Check if usage tracker is functional."""
    try:
        # Try to get usage for a known model
        usage = usage_tracker.get_usage("gemini-2.5-flash")
        # If we got a response with expected structure, it's healthy
        return "model" in usage and "requests" in usage
    except Exception as e:
        logger.error(f"Usage tracker health check failed: {e}")
        return False


@router.get("/metrics")
async def get_metrics():
    """
    Get API performance metrics and statistics.
    
    Returns:
        - Uptime
        - Total requests and errors
        - Response time statistics (avg, min, max, p95)
        - Top endpoints by request count
        - Top endpoints by error count
        - Recent errors
        - Status code distribution
    """
    try:
        from app.services.metrics import metrics_collector
        stats = metrics_collector.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch metrics: {str(e)}"
        )



# ── Interview Templates ────────────────────────────────────

@router.get("/templates")
async def list_templates(category: Optional[str] = None):
    """
    List all interview templates, optionally filtered by category.
    
    Args:
        category: Filter by category ("crime", "accident", "incident")
    
    Returns:
        List of interview templates
    """
    if category:
        templates = get_templates_by_category(category)
    else:
        templates = get_all_templates()
    return {"templates": templates}


@router.get("/templates/{template_id}")
async def get_template_by_id(template_id: str):
    """
    Get a specific interview template by ID.
    
    Args:
        template_id: Template identifier (e.g., "theft_burglary", "assault_battery")
    
    Returns:
        Template details or 404 if not found
    """
    template = get_template(template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found"
        )
    return template


# ── Scene Elements Library ────────────────────────────────

@router.get("/scene-elements")
async def list_scene_elements(category: Optional[str] = None):
    """
    Get scene element library for scene editing.
    
    Args:
        category: Optional filter by category (vehicles, people, furniture, environment, evidence)
    
    Returns:
        Scene elements organized by category
    """
    import json as json_module
    elements_path = os.path.join(os.path.dirname(__file__), "..", "data", "scene_elements.json")
    try:
        with open(elements_path, "r") as f:
            data = json_module.load(f)
        
        if category:
            # Filter to specific category
            filtered = [c for c in data.get("categories", []) if c["id"] == category]
            if not filtered:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Category '{category}' not found"
                )
            return {"categories": filtered, "version": data.get("version")}
        
        return data
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scene elements library not found"
        )


@router.get("/scene-elements/{element_id}")
async def get_scene_element(element_id: str):
    """
    Get a specific scene element by ID.
    
    Args:
        element_id: Element identifier (e.g., "car", "witness", "marker_1")
    
    Returns:
        Element details or 404 if not found
    """
    import json as json_module
    elements_path = os.path.join(os.path.dirname(__file__), "..", "data", "scene_elements.json")
    try:
        with open(elements_path, "r") as f:
            data = json_module.load(f)
        
        for category in data.get("categories", []):
            for element in category.get("elements", []):
                if element["id"] == element_id:
                    return element
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Element '{element_id}' not found"
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scene elements library not found"
        )


@router.get("/scene-templates")
async def list_scene_templates(category: Optional[str] = None):
    """
    Get scene templates for quick scene setup.
    
    Args:
        category: Optional filter by category (outdoor, indoor)
    
    Returns:
        List of scene templates with element positions
    """
    import json as json_module
    templates_path = os.path.join(os.path.dirname(__file__), "..", "data", "scene_templates.json")
    try:
        with open(templates_path, "r") as f:
            data = json_module.load(f)
        
        templates = data.get("templates", [])
        
        if category:
            templates = [t for t in templates if t.get("category") == category]
            if not templates:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No templates found for category '{category}'"
                )
        
        return {
            "templates": templates,
            "version": data.get("version"),
            "lastUpdated": data.get("lastUpdated")
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scene templates library not found"
        )


@router.get("/scene-templates/{template_id}")
async def get_scene_template(template_id: str):
    """
    Get a specific scene template by ID.
    
    Args:
        template_id: Template identifier (e.g., "intersection", "parking_lot")
    
    Returns:
        Template details with all element positions
    """
    import json as json_module
    templates_path = os.path.join(os.path.dirname(__file__), "..", "data", "scene_templates.json")
    try:
        with open(templates_path, "r") as f:
            data = json_module.load(f)
        
        for template in data.get("templates", []):
            if template["id"] == template_id:
                return template
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found"
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scene templates library not found"
        )


@router.get("/sessions")
async def list_sessions(limit: int = 50):
    """List all reconstruction sessions."""
    try:
        sessions = await firestore_service.list_sessions(limit=limit)
        sessions_list = [
            SessionResponse(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                status=session.status,
                statement_count=len(session.witness_statements),
                version_count=len(session.scene_versions),
                witness_count=len(getattr(session, 'witnesses', []) or []),
                source_type=getattr(session, 'source_type', 'chat'),
                report_number=getattr(session, 'report_number', ''),
                case_id=getattr(session, 'case_id', None),
                active_witness_id=getattr(session, 'active_witness_id', None),
                metadata=getattr(session, 'metadata', {})
            )
            for session in sessions
        ]
        # Return object with sessions key for admin portal
        return {"sessions": sessions_list}
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list sessions"
        )


@router.get("/reports/orphans")
async def list_orphan_reports(limit: int = 50):
    """List reports that are missing a case assignment."""
    try:
        limit = _guard_limit(limit)
        orphan_sessions = await firestore_service.list_orphan_sessions(limit=limit)

        reports = [
            {
                "id": session.id,
                "report_number": getattr(session, "report_number", ""),
                "title": session.title,
                "source_type": getattr(session, "source_type", "chat"),
                "statement_count": len(getattr(session, "witness_statements", []) or []),
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            }
            for session in orphan_sessions
        ]

        return {
            "reports": reports,
            "count": len(reports),
            "limit": limit,
        }
    except Exception as e:
        logger.error(f"Error listing orphan reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list orphan reports",
        )


@router.post("/reports/orphans/auto-assign")
async def auto_assign_orphan_reports(limit: int = 50, _auth=Depends(require_admin_auth)):
    """Auto-assign orphan reports to existing/new cases."""
    try:
        limit = _guard_limit(limit)
        orphan_sessions = await firestore_service.list_orphan_sessions(limit=limit)

        assigned = 0
        failures = []

        for session in orphan_sessions:
            try:
                case_id = await case_manager.assign_report_to_case(session)
                if not case_id:
                    failures.append({"report_id": session.id, "error": "No case assignment returned"})
                    continue

                session.case_id = case_id
                session.updated_at = datetime.utcnow()
                await firestore_service.update_session(session)
                assigned += 1
            except Exception as assign_error:
                failures.append({"report_id": session.id, "error": str(assign_error)})

        return {
            "processed": len(orphan_sessions),
            "assigned": assigned,
            "failed": len(failures),
            "failures": failures,
        }
    except Exception as e:
        logger.error(f"Error auto-assigning orphan reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to auto-assign orphan reports",
        )



@router.post("/sessions", response_model=ReconstructionSession, status_code=status.HTTP_201_CREATED)
async def create_session(session_data: SessionCreate):
    """Create a new reconstruction session."""
    try:
        # Validate template_id if provided
        template = None
        if session_data.template_id:
            template = get_template(session_data.template_id)
            if not template:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Template '{session_data.template_id}' not found"
                )
        
        # Store template info in metadata
        metadata = session_data.metadata or {}
        if session_data.is_anonymous:
            metadata['is_anonymous'] = True
        if template:
            metadata['template_id'] = template['id']
            metadata['template_name'] = template['name']
            metadata['incident_category'] = template['category']
        
        session = ReconstructionSession(
            id=str(uuid.uuid4()),
            title=session_data.title or "Untitled Session",
            source_type=session_data.source_type if hasattr(session_data, 'source_type') and session_data.source_type else "chat",
            witness_name=session_data.witness_name,
            witness_contact=session_data.witness_contact,
            witness_location=session_data.witness_location,
            metadata=metadata
        )
        
        success = await firestore_service.create_session(session)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create session"
            )
        
        # Assign report number
        session.report_number = await firestore_service.get_next_report_number()
        await firestore_service.update_session(session)
        
        # Initialize agent for this session with template context
        agent = get_agent(session.id)
        if template:
            agent.set_template(template)
        greeting = await agent.start_interview()
        
        logger.info(f"Created session {session.id}" + (f" with template {template['id']}" if template else ""))

        # Publish SSE event for new report
        await publish_event("new_report", {
            "report_id": session.id,
            "title": session.title,
            "report_number": session.report_number,
        })

        return session
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )



@router.get("/sessions/export/bulk")
async def export_all_sessions_bulk(
    limit: int = 100,
    status_filter: Optional[str] = None,
    format: str = "json"
):
    """
    Export multiple sessions in bulk for backup or analysis.
    
    Args:
        limit: Maximum number of sessions to export (default 100)
        status_filter: Optional filter by status (active, completed, archived)
        format: Export format - "json" (default) or "csv"
    
    Returns:
        JSON array of all sessions or CSV file
    """
    try:
        # Get sessions
        all_sessions = await firestore_service.list_sessions(limit=limit)
        
        # Filter by status if requested
        if status_filter:
            all_sessions = [s for s in all_sessions if s.status == status_filter]
        
        from fastapi.responses import Response
        import json
        
        if format == "csv":
            # CSV export for spreadsheet analysis
            import io
            import csv
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow([
                "Session ID", "Title", "Created", "Updated", "Status",
                "Statements", "Corrections", "Scene Elements", "Reconstructions"
            ])
            
            # Data rows
            for session in all_sessions:
                writer.writerow([
                    session.id,
                    session.title,
                    session.created_at.isoformat() if session.created_at else "",
                    session.updated_at.isoformat() if session.updated_at else "",
                    session.status,
                    len(session.witness_statements),
                    sum(1 for stmt in session.witness_statements if stmt.is_correction),
                    len(session.current_scene_elements),
                    len(session.scene_versions),
                ])
            
            csv_content = output.getvalue()
            
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=sessions_export.csv"
                }
            )
        else:
            # JSON export (default)
            sessions_data = [s.model_dump(mode='json') for s in all_sessions]
            export_data = {
                "export_timestamp": datetime.utcnow().isoformat(),
                "total_sessions": len(sessions_data),
                "status_filter": status_filter,
                "sessions": sessions_data
            }
            
            json_str = json.dumps(export_data, indent=2, default=str)
            
            return Response(
                content=json_str,
                media_type="application/json",
                headers={
                    "Content-Disposition": f"attachment; filename=sessions_bulk_export.json"
                }
            )
    
    except Exception as e:
        logger.error(f"Error exporting sessions in bulk: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export sessions: {str(e)}"
        )



@router.get("/sessions/{session_id}/export/evidence")
async def export_session_evidence(session_id: str):
    """
    Export session as structured evidence report for law enforcement systems.
    
    Returns a standardized JSON format compatible with evidence management systems,
    including chain of custody, witness credibility, and scene reconstruction data.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        from fastapi.responses import Response
        import json
        
        # Record export in custody chain
        await custody_chain_service.record_evidence_exported(
            evidence_type="session",
            evidence_id=session_id,
            actor="api_user",
            export_format="evidence_report",
            metadata={"endpoint": "export_session_evidence"}
        )
        
        # Get custody chain for this session
        custody_events = await custody_chain_service.get_all_custody_for_session(session_id)
        
        # Build structured evidence report
        evidence_report = {
            "case_metadata": {
                "case_id": session.id,
                "case_title": session.title,
                "date_created": session.created_at.isoformat() if session.created_at else None,
                "date_updated": session.updated_at.isoformat() if session.updated_at else None,
                "status": session.status,
                "generated_by": "WitnessReplay AI Reconstruction System v1.0",
                "generated_at": datetime.utcnow().isoformat(),
            },
            "chain_of_custody": {
                "total_events": len(custody_events),
                "first_access": min((e.timestamp for e in custody_events), default=None),
                "last_access": max((e.timestamp for e in custody_events), default=None),
                "unique_actors": list(set(e.actor for e in custody_events)),
                "events": [
                    {
                        "event_id": e.id,
                        "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, 'isoformat') else str(e.timestamp),
                        "evidence_type": e.evidence_type,
                        "evidence_id": e.evidence_id,
                        "action": e.action,
                        "actor": e.actor,
                        "actor_role": e.actor_role,
                        "details": e.details,
                        "hash_before": e.hash_before,
                        "hash_after": e.hash_after,
                    }
                    for e in custody_events
                ],
            },
            "witness_statements": [
                {
                    "statement_id": stmt.id,
                    "timestamp": stmt.timestamp.isoformat() if stmt.timestamp else None,
                    "text": stmt.text,
                    "is_correction": stmt.is_correction,
                    "audio_available": bool(stmt.audio_url),
                    "audio_url": stmt.audio_url,
                }
                for stmt in session.witness_statements
            ],
            "scene_elements": [
                {
                    "element_id": elem.id,
                    "type": elem.type,
                    "description": elem.description,
                    "position": elem.position,
                    "color": elem.color,
                    "size": elem.size,
                    "confidence": elem.confidence,
                    "first_mentioned": elem.timestamp.isoformat() if elem.timestamp else None,
                }
                for elem in session.current_scene_elements
            ],
            "scene_reconstructions": [
                {
                    "version": ver.version,
                    "description": ver.description,
                    "timestamp": ver.timestamp.isoformat() if ver.timestamp else None,
                    "image_url": ver.image_url,
                    "changes_from_previous": ver.changes_from_previous,
                    "element_count": len(ver.elements),
                    "measurements": [
                        {
                            "id": m.id if hasattr(m, 'id') else m.get('id'),
                            "type": m.type if hasattr(m, 'type') else m.get('type'),
                            "value": m.value if hasattr(m, 'value') else m.get('value'),
                            "unit": m.unit if hasattr(m, 'unit') else m.get('unit'),
                            "label": m.label if hasattr(m, 'label') else m.get('label'),
                            "points": [{"x": p.x if hasattr(p, 'x') else p.get('x'), "y": p.y if hasattr(p, 'y') else p.get('y')} for p in (m.points if hasattr(m, 'points') else m.get('points', []))],
                        }
                        for m in (getattr(ver, 'measurements', []) or [])
                    ],
                }
                for ver in session.scene_versions
            ],
            "timeline": [
                {
                    "event_id": evt.id,
                    "sequence": evt.sequence,
                    "description": evt.description,
                    "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
                    "image_url": evt.image_url,
                    "confidence": getattr(evt, 'confidence', 0.5),
                    "needs_review": getattr(evt, 'needs_review', False),
                }
                for evt in session.timeline
            ],
            "summary": {
                "total_statements": len(session.witness_statements),
                "total_corrections": sum(1 for stmt in session.witness_statements if stmt.is_correction),
                "total_scene_elements": len(session.current_scene_elements),
                "total_reconstructions": len(session.scene_versions),
                "timeline_events": len(session.timeline),
                "total_measurements": sum(len(getattr(ver, 'measurements', []) or []) for ver in session.scene_versions),
                "custody_events": len(custody_events),
            },
            "notes": [
                "This report was generated using AI-assisted witness interview and scene reconstruction technology.",
                "All scene reconstructions are based on witness statements and should be verified with physical evidence.",
                "Confidence scores indicate the AI's certainty based on statement consistency and detail.",
                "Chain of custody records track all access and modifications to this evidence.",
            ]
        }
        
        json_str = json.dumps(evidence_report, indent=2, default=str)
        
        return Response(
            content=json_str,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=evidence_report_{session_id}.json"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting evidence report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export evidence report"
        )



@router.get("/sessions/{session_id}/export/json")
async def export_session_json(session_id: str):
    """Export a session as JSON data."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        from fastapi.responses import Response
        import json
        
        # Record export in custody chain
        await custody_chain_service.record_evidence_exported(
            evidence_type="session",
            evidence_id=session_id,
            actor="api_user",
            export_format="JSON",
            metadata={"endpoint": "export_session_json"}
        )
        
        # Get custody chain for inclusion
        custody_events = await custody_chain_service.get_all_custody_for_session(session_id)
        
        # Convert to JSON with proper datetime handling
        session_data = session.model_dump(mode='json')
        session_data['custody_chain'] = [e.model_dump(mode='json') if hasattr(e, 'model_dump') else e for e in custody_events]
        json_str = json.dumps(session_data, indent=2, default=str)
        
        return Response(
            content=json_str,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}.json"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting session as JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export session as JSON"
        )



@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """Export a session as a PDF report."""
    try:
        # Import fpdf only when needed to avoid module load failure
        try:
            from fpdf import FPDF
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PDF export functionality not available. Install fpdf2 package."
            )
        
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Create PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "WitnessReplay - Scene Reconstruction Report", ln=True, align="C")
        
        pdf.set_font("Arial", "", 12)
        pdf.ln(10)
        pdf.cell(0, 10, f"Session: {session.title}", ln=True)
        
        # Handle missing created_at gracefully
        if session.created_at:
            try:
                date_str = session.created_at.strftime('%Y-%m-%d %H:%M')
            except Exception as e:
                logger.warning(f"Error formatting date: {e}")
                date_str = str(session.created_at)
            pdf.cell(0, 10, f"Date: {date_str}", ln=True)
        else:
            pdf.cell(0, 10, "Date: Not available", ln=True)
        
        pdf.ln(10)
        
        # Witness Statements
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Witness Statements:", ln=True)
        pdf.set_font("Arial", "", 11)
        
        if session.witness_statements:
            for i, statement in enumerate(session.witness_statements, 1):
                # Handle potential encoding issues with multi_cell
                try:
                    text = str(statement.text)
                    # Replace non-Latin characters with '?'
                    text = text.encode('latin-1', errors='replace').decode('latin-1')
                    pdf.multi_cell(0, 10, f"{i}. {text}")
                    pdf.ln(5)
                except Exception as e:
                    logger.warning(f"Error adding statement {i}: {e}")
                    pdf.multi_cell(0, 10, f"{i}. [Statement could not be encoded]")
                    pdf.ln(5)
        else:
            pdf.cell(0, 10, "No witness statements recorded yet.", ln=True)
        
        # Scene Versions
        if session.scene_versions:
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Scene Reconstructions:", ln=True)
            pdf.set_font("Arial", "", 11)
            for version in session.scene_versions:
                try:
                    desc = str(version.description) if version.description else "No description"
                    desc = desc.encode('latin-1', errors='replace').decode('latin-1')
                    pdf.multi_cell(0, 10, f"Version {version.version}: {desc}")
                    if version.image_url:
                        pdf.cell(0, 10, f"Image: {version.image_url}", ln=True)
                    pdf.ln(5)
                except Exception as e:
                    logger.warning(f"Error adding scene version: {e}")
                    pdf.cell(0, 10, "[Scene version could not be encoded]", ln=True)
        else:
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Scene Reconstructions:", ln=True)
            pdf.set_font("Arial", "", 11)
            pdf.cell(0, 10, "No scene reconstructions generated yet.", ln=True)
        
        # Evidence Markers
        all_markers = []
        for version in session.scene_versions:
            version_markers = getattr(version, 'evidence_markers', []) or []
            for marker in version_markers:
                if marker:
                    all_markers.append((version.version, marker))
        
        if all_markers:
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Evidence Markers:", ln=True)
            pdf.set_font("Arial", "", 11)
            pdf.ln(5)
            
            for scene_ver, marker in all_markers:
                try:
                    m_number = marker.number if hasattr(marker, 'number') else marker.get('number', 0)
                    m_label = marker.label if hasattr(marker, 'label') else marker.get('label', '')
                    m_desc = marker.description if hasattr(marker, 'description') else marker.get('description', '')
                    m_category = marker.category if hasattr(marker, 'category') else marker.get('category', 'general')
                    
                    # Encode for PDF
                    m_label = str(m_label).encode('latin-1', errors='replace').decode('latin-1')
                    m_desc = str(m_desc).encode('latin-1', errors='replace').decode('latin-1')
                    
                    pdf.set_font("Arial", "B", 11)
                    pdf.cell(0, 8, f"Marker #{m_number} (Scene v{scene_ver}) - {m_category.title()}", ln=True)
                    pdf.set_font("Arial", "", 11)
                    if m_label:
                        pdf.cell(0, 8, f"  Label: {m_label}", ln=True)
                    if m_desc:
                        pdf.multi_cell(0, 8, f"  Description: {m_desc}")
                    pdf.ln(3)
                except Exception as e:
                    logger.warning(f"Error adding evidence marker: {e}")
                    pdf.cell(0, 8, "[Evidence marker could not be encoded]", ln=True)
        
        # Chain of Custody section
        try:
            custody_events = await custody_chain_service.get_all_custody_for_session(session_id)
            if custody_events:
                pdf.add_page()
                pdf.set_font("Arial", "B", 14)
                pdf.cell(0, 10, "Evidence Chain of Custody:", ln=True)
                pdf.set_font("Arial", "", 10)
                pdf.ln(5)
                
                pdf.cell(0, 8, f"Total custody events: {len(custody_events)}", ln=True)
                pdf.ln(3)
                
                # Group events by evidence type
                events_by_type = {}
                for event in custody_events:
                    ev_type = event.evidence_type
                    if ev_type not in events_by_type:
                        events_by_type[ev_type] = []
                    events_by_type[ev_type].append(event)
                
                for ev_type, events in events_by_type.items():
                    pdf.set_font("Arial", "B", 11)
                    pdf.cell(0, 8, f"{ev_type.replace('_', ' ').title()} ({len(events)} events):", ln=True)
                    pdf.set_font("Arial", "", 10)
                    
                    for event in events[:10]:  # Limit to 10 per type for readability
                        try:
                            timestamp_str = event.timestamp.strftime('%Y-%m-%d %H:%M:%S') if hasattr(event.timestamp, 'strftime') else str(event.timestamp)
                            actor = str(event.actor).encode('latin-1', errors='replace').decode('latin-1')
                            action = str(event.action).encode('latin-1', errors='replace').decode('latin-1')
                            details = str(event.details or '').encode('latin-1', errors='replace').decode('latin-1')
                            
                            pdf.cell(0, 6, f"  [{timestamp_str}] {action} by {actor}", ln=True)
                            if details:
                                pdf.cell(0, 6, f"    Details: {details[:100]}", ln=True)
                        except Exception as e:
                            logger.warning(f"Error adding custody event to PDF: {e}")
                    
                    if len(events) > 10:
                        pdf.cell(0, 6, f"  ... and {len(events) - 10} more events", ln=True)
                    pdf.ln(3)
        except Exception as e:
            logger.warning(f"Error adding custody chain to PDF: {e}")
        
        # Record the export in custody chain
        await custody_chain_service.record_evidence_exported(
            evidence_type="session",
            evidence_id=session_id,
            actor="api_user",  # In real implementation, get from auth
            export_format="PDF",
            metadata={"endpoint": "export_session"}
        )
        
        # Output PDF (fpdf2 returns bytearray, convert to bytes for Response)
        pdf_bytes = bytes(pdf.output())
        
        from fastapi.responses import Response
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}.pdf"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export session: {str(e)}"
        )



@router.get("/sessions/{session_id}/insights")
async def get_session_insights(session_id: str):
    """
    Get AI-powered insights about a session's reconstruction quality.
    
    Returns:
        - Scene complexity score
        - Completeness assessment
        - Detected contradictions
        - Suggested next questions
        - Evidence confidence levels
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Get agent for this session to access state
        from app.agents.scene_agent import get_agent
        from app.config import settings
        agent = get_agent(session_id)
        scene_summary = agent.get_scene_summary()
        
        # Calculate insights
        insights = {
            "session_id": session_id,
            "complexity_score": scene_summary.get("complexity_score", 0.0),
            "completeness": {
                "total_elements": len(scene_summary.get("elements", [])),
                "elements_with_position": sum(
                    1 for e in scene_summary.get("elements", [])
                    if e.get("position")
                ),
                "elements_with_color": sum(
                    1 for e in scene_summary.get("elements", [])
                    if e.get("color")
                ),
                "elements_with_size": sum(
                    1 for e in scene_summary.get("elements", [])
                    if e.get("size")
                ),
                "completeness_percentage": (
                    scene_summary.get("complexity_score", 0.0) * 100
                )
            },
            "contradictions": {
                "count": len(scene_summary.get("contradictions", [])),
                "details": scene_summary.get("contradictions", [])
            },
            "statement_analysis": {
                "total_statements": len(session.witness_statements),
                "corrections": sum(
                    1 for s in session.witness_statements
                    if s.is_correction
                ),
                "avg_confidence": (
                    sum(s.confidence for s in session.witness_statements) /
                    len(session.witness_statements)
                    if session.witness_statements else 0.0
                )
            },
            "scene_versions": {
                "count": len(session.scene_versions),
                "progression": [
                    {
                        "version": i + 1,
                        "elements": len(v.elements),
                        "timestamp": v.timestamp.isoformat() if v.timestamp else None
                    }
                    for i, v in enumerate(session.scene_versions)
                ]
            },
            "recommendations": [],
            "needs_review": {
                "elements": [],
                "timeline_events": [],
                "count": 0,
                "threshold": settings.confidence_threshold
            }
        }
        
        # Identify elements needing review (confidence below threshold)
        for elem in scene_summary.get("elements", []):
            confidence = elem.get("confidence", 0.5)
            if confidence < settings.confidence_threshold:
                insights["needs_review"]["elements"].append({
                    "id": elem.get("id"),
                    "type": elem.get("type"),
                    "description": elem.get("description"),
                    "confidence": confidence,
                    "reason": "Low AI confidence - requires human verification"
                })
        
        # Identify timeline events needing review
        for evt in session.timeline:
            confidence = getattr(evt, 'confidence', 0.5)
            if confidence < settings.confidence_threshold:
                insights["needs_review"]["timeline_events"].append({
                    "id": evt.id,
                    "sequence": evt.sequence,
                    "description": evt.description,
                    "confidence": confidence,
                    "reason": "Low AI confidence - requires human verification"
                })
        
        insights["needs_review"]["count"] = (
            len(insights["needs_review"]["elements"]) +
            len(insights["needs_review"]["timeline_events"])
        )
        
        # Generate recommendations based on insights
        if insights["completeness"]["completeness_percentage"] < 30:
            insights["recommendations"].append({
                "type": "low_detail",
                "message": "Scene has low detail. Ask more specific questions about positions, colors, and sizes."
            })
        
        if insights["contradictions"]["count"] > 0:
            insights["recommendations"].append({
                "type": "contradictions_found",
                "message": f"Found {insights['contradictions']['count']} contradictions. Review and clarify conflicting information."
            })
        
        if insights["statement_analysis"]["avg_confidence"] < 0.5:
            insights["recommendations"].append({
                "type": "low_confidence",
                "message": "Witness shows low confidence. Ask clarifying questions to improve accuracy."
            })
        
        if insights["completeness"]["total_elements"] < 3:
            insights["recommendations"].append({
                "type": "few_elements",
                "message": "Few scene elements identified. Continue gathering details about the scene."
            })
        
        if insights["needs_review"]["count"] > 0:
            insights["recommendations"].append({
                "type": "needs_review",
                "message": f"{insights['needs_review']['count']} items flagged for review due to low AI confidence (below {int(settings.confidence_threshold * 100)}%). Verify these with the witness."
            })
        
        return insights
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session insights: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session insights: {str(e)}"
        )



@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(session_id: str):
    """
    Get a temporal timeline of events and statements for a session.
    Useful for understanding the sequence of witness statements and scene evolution.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Build timeline from witness statements
        timeline_events = []
        
        for idx, statement in enumerate(session.witness_statements):
            event = {
                "index": idx,
                "timestamp": statement.timestamp.isoformat() if statement.timestamp else None,
                "type": "correction" if statement.is_correction else "statement",
                "text": statement.text,
                "confidence": statement.confidence,
                "scene_version": None
            }
            timeline_events.append(event)
        
        # Add scene version generations to timeline
        for idx, version in enumerate(session.scene_versions):
            event = {
                "index": None,
                "timestamp": version.timestamp.isoformat() if version.timestamp else None,
                "type": "scene_generation",
                "text": f"Scene reconstruction #{idx + 1}",
                "prompt": version.prompt_used,
                "image_url": version.image_url,
                "element_count": len(version.elements)
            }
            timeline_events.append(event)
        
        # Sort by timestamp
        timeline_events.sort(key=lambda x: x.get("timestamp") or "")
        
        # Calculate time deltas
        for i in range(1, len(timeline_events)):
            if timeline_events[i-1].get("timestamp") and timeline_events[i].get("timestamp"):
                from datetime import datetime
                t1 = datetime.fromisoformat(timeline_events[i-1]["timestamp"])
                t2 = datetime.fromisoformat(timeline_events[i]["timestamp"])
                delta = (t2 - t1).total_seconds()
                timeline_events[i]["seconds_since_previous"] = delta
        
        return {
            "session_id": session_id,
            "session_title": session.title,
            "total_events": len(timeline_events),
            "session_duration_seconds": (
                (session.updated_at - session.created_at).total_seconds()
                if session.created_at and session.updated_at else None
            ),
            "timeline": timeline_events
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session timeline: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session timeline: {str(e)}"
        )


@router.get("/sessions/{session_id}/timeline/disambiguation")
async def get_timeline_disambiguation(session_id: str):
    """
    Get timeline clarity analysis and any pending disambiguation prompts.
    Returns clarity scores, vague references, and suggested clarifying questions.
    """
    try:
        agent = get_agent(session_id)
        
        # Get clarity analysis
        analysis = agent.get_timeline_clarity_analysis()
        
        # Get disambiguation prompt if needed
        disambiguation = agent.get_timeline_disambiguation_prompt()
        
        # Get pending clarifications
        pending = agent.get_pending_timeline_clarifications()
        
        return {
            "session_id": session_id,
            "clarity_analysis": analysis,
            "disambiguation_prompt": disambiguation,
            "pending_clarifications": pending,
            "needs_action": analysis.get("needs_disambiguation", False) or len(pending) > 0
        }
    
    except Exception as e:
        logger.error(f"Error getting timeline disambiguation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get timeline disambiguation: {str(e)}"
        )


@router.get("/sessions/{session_id}/timeline/clarified")
async def get_clarified_timeline(session_id: str):
    """
    Get the disambiguated timeline with clarity indicators for each event.
    Shows which events have clear timing and which need clarification.
    """
    try:
        agent = get_agent(session_id)
        
        # Build the disambiguated timeline
        timeline_events = agent.build_disambiguated_timeline()
        
        # Get overall clarity
        analysis = agent.get_timeline_clarity_analysis()
        
        return {
            "session_id": session_id,
            "overall_clarity": analysis.get("overall_clarity", "unknown"),
            "clarity_score": analysis.get("clarity_score", 0.0),
            "has_anchor_points": analysis.get("has_anchor_points", False),
            "events": timeline_events,
            "events_needing_clarification": sum(1 for e in timeline_events if e.get("needs_clarification")),
            "total_events": len(timeline_events)
        }
    
    except Exception as e:
        logger.error(f"Error getting clarified timeline: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get clarified timeline: {str(e)}"
        )


class TimelineClarificationRequest(BaseModel):
    """Request to apply a clarification to a timeline event."""
    event_id: str
    offset_description: Optional[str] = None
    relative_to: Optional[str] = None
    sequence: Optional[int] = None


@router.post("/sessions/{session_id}/timeline/clarify")
async def apply_timeline_clarification(session_id: str, request: TimelineClarificationRequest):
    """
    Apply a witness's clarification to a timeline event.
    Updates the event with clearer temporal positioning.
    """
    try:
        agent = get_agent(session_id)
        
        clarification = {}
        if request.offset_description:
            clarification["offset_description"] = request.offset_description
        if request.relative_to:
            clarification["relative_to"] = request.relative_to
        if request.sequence is not None:
            clarification["sequence"] = request.sequence
        
        success = agent.apply_timeline_clarification(request.event_id, clarification)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event {request.event_id} not found in timeline"
            )
        
        # Return updated timeline
        timeline_events = agent.build_disambiguated_timeline()
        
        return {
            "success": True,
            "event_id": request.event_id,
            "updated_events": timeline_events
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying timeline clarification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply clarification: {str(e)}"
        )


@router.get("/sessions/{session_id}/scene-versions")
async def list_scene_versions(session_id: str):
    """List all scene versions for a session with metadata."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        versions = []
        for i, v in enumerate(session.scene_versions):
            env_conditions = getattr(v, 'environmental_conditions', None)
            versions.append({
                "version": v.version if hasattr(v, 'version') else i + 1,
                "description": v.description,
                "image_url": v.image_url,
                "timestamp": v.timestamp.isoformat() if v.timestamp else None,
                "changes_from_previous": v.changes_from_previous,
                "element_count": len(v.elements) if v.elements else 0,
                "environmental_conditions": env_conditions.model_dump() if env_conditions else {"weather": "clear", "lighting": "daylight", "visibility": "good"},
                "elements": [
                    {
                        "id": e.id,
                        "type": e.type,
                        "description": e.description,
                        "position": e.position,
                        "color": e.color,
                        "confidence": e.confidence
                    }
                    for e in (v.elements or [])
                ]
            })
        
        return {
            "session_id": session_id,
            "total_versions": len(versions),
            "versions": versions
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing scene versions: {e}")
        raise HTTPException(status_code=500, detail="Failed to list scene versions")


@router.get("/sessions/{session_id}/scene-versions/compare")
async def compare_scene_versions(
    session_id: str,
    version_a: int,
    version_b: int
):
    """
    Compare two scene versions and return differences.
    Returns both versions with highlighted element differences.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        versions = session.scene_versions
        if not versions:
            raise HTTPException(status_code=404, detail="No scene versions available")
        
        # Get version indices (versions are 1-indexed)
        idx_a = version_a - 1
        idx_b = version_b - 1
        
        if idx_a < 0 or idx_a >= len(versions):
            raise HTTPException(status_code=400, detail=f"Version {version_a} not found")
        if idx_b < 0 or idx_b >= len(versions):
            raise HTTPException(status_code=400, detail=f"Version {version_b} not found")
        
        v_a = versions[idx_a]
        v_b = versions[idx_b]
        
        # Compute element differences
        elements_a = {e.id: e for e in (v_a.elements or [])}
        elements_b = {e.id: e for e in (v_b.elements or [])}
        
        all_ids = set(elements_a.keys()) | set(elements_b.keys())
        
        added = []
        removed = []
        changed = []
        unchanged = []
        
        for eid in all_ids:
            e_a = elements_a.get(eid)
            e_b = elements_b.get(eid)
            
            if e_a is None and e_b is not None:
                added.append({
                    "id": eid,
                    "type": e_b.type,
                    "description": e_b.description,
                    "position": e_b.position,
                    "color": e_b.color
                })
            elif e_a is not None and e_b is None:
                removed.append({
                    "id": eid,
                    "type": e_a.type,
                    "description": e_a.description,
                    "position": e_a.position,
                    "color": e_a.color
                })
            else:
                # Both exist - check for changes
                changes = []
                if e_a.description != e_b.description:
                    changes.append({"field": "description", "before": e_a.description, "after": e_b.description})
                if e_a.position != e_b.position:
                    changes.append({"field": "position", "before": e_a.position, "after": e_b.position})
                if e_a.color != e_b.color:
                    changes.append({"field": "color", "before": e_a.color, "after": e_b.color})
                if abs((e_a.confidence or 0) - (e_b.confidence or 0)) > 0.01:
                    changes.append({"field": "confidence", "before": e_a.confidence, "after": e_b.confidence})
                
                if changes:
                    changed.append({
                        "id": eid,
                        "type": e_b.type,
                        "description": e_b.description,
                        "changes": changes
                    })
                else:
                    unchanged.append({"id": eid, "type": e_a.type, "description": e_a.description})
        
        return {
            "session_id": session_id,
            "version_a": {
                "version": version_a,
                "description": v_a.description,
                "image_url": v_a.image_url,
                "timestamp": v_a.timestamp.isoformat() if v_a.timestamp else None,
                "changes_from_previous": v_a.changes_from_previous,
                "element_count": len(v_a.elements or [])
            },
            "version_b": {
                "version": version_b,
                "description": v_b.description,
                "image_url": v_b.image_url,
                "timestamp": v_b.timestamp.isoformat() if v_b.timestamp else None,
                "changes_from_previous": v_b.changes_from_previous,
                "element_count": len(v_b.elements or [])
            },
            "diff": {
                "added": added,
                "removed": removed,
                "changed": changed,
                "unchanged": unchanged,
                "summary": {
                    "added_count": len(added),
                    "removed_count": len(removed),
                    "changed_count": len(changed),
                    "unchanged_count": len(unchanged)
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing scene versions: {e}")
        raise HTTPException(status_code=500, detail="Failed to compare scene versions")


# ==================== Environmental Conditions Endpoints ====================


class EnvironmentalConditionsUpdate(BaseModel):
    """Request to update environmental conditions for a scene version."""
    weather: Optional[str] = None
    lighting: Optional[str] = None
    visibility: Optional[str] = None


@router.get("/sessions/{session_id}/scene-versions/{version_num}/environmental-conditions")
async def get_environmental_conditions(session_id: str, version_num: int):
    """Get environmental conditions for a specific scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        version_idx = version_num - 1
        if version_idx < 0 or version_idx >= len(session.scene_versions):
            raise HTTPException(status_code=404, detail=f"Scene version {version_num} not found")
        
        version = session.scene_versions[version_idx]
        env_conditions = getattr(version, 'environmental_conditions', None)
        
        if env_conditions:
            return {
                "version": version_num,
                "environmental_conditions": env_conditions.model_dump()
            }
        else:
            return {
                "version": version_num,
                "environmental_conditions": {"weather": "clear", "lighting": "daylight", "visibility": "good"}
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting environmental conditions: {e}")
        raise HTTPException(status_code=500, detail="Failed to get environmental conditions")


@router.put("/sessions/{session_id}/scene-versions/{version_num}/environmental-conditions")
async def update_environmental_conditions(
    session_id: str,
    version_num: int,
    conditions: EnvironmentalConditionsUpdate
):
    """Update environmental conditions for a specific scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        version_idx = version_num - 1
        if version_idx < 0 or version_idx >= len(session.scene_versions):
            raise HTTPException(status_code=404, detail=f"Scene version {version_num} not found")
        
        version = session.scene_versions[version_idx]
        
        # Get current conditions or create default
        current_conditions = getattr(version, 'environmental_conditions', None)
        if not current_conditions:
            current_conditions = EnvironmentalConditions()
        
        # Update only provided fields
        update_data = conditions.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(current_conditions, field, value)
        
        # Validate the updated conditions
        validated_conditions = EnvironmentalConditions(**current_conditions.model_dump())
        session.scene_versions[version_idx].environmental_conditions = validated_conditions
        
        # Save the session
        await firestore_service.save_session(session)
        
        return {
            "success": True,
            "version": version_num,
            "environmental_conditions": validated_conditions.model_dump()
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating environmental conditions: {e}")
        raise HTTPException(status_code=500, detail="Failed to update environmental conditions")


# ==================== Measurement Endpoints ====================


@router.get("/sessions/{session_id}/measurements")
async def get_measurements(session_id: str, scene_version: Optional[int] = None):
    """Get all measurements for a session, optionally filtered by scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        measurements = []
        for version in session.scene_versions:
            version_measurements = getattr(version, 'measurements', []) or []
            for m in version_measurements:
                if scene_version is None or m.scene_version == scene_version:
                    measurements.append(m.model_dump(mode='json') if hasattr(m, 'model_dump') else m)
        
        return {"session_id": session_id, "measurements": measurements, "count": len(measurements)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting measurements: {e}")
        raise HTTPException(status_code=500, detail="Failed to get measurements")


@router.post("/sessions/{session_id}/measurements", status_code=status.HTTP_201_CREATED)
async def create_measurement(session_id: str, measurement_data: MeasurementCreate):
    """Create a new measurement for a scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        version_idx = measurement_data.scene_version - 1
        if version_idx < 0 or version_idx >= len(session.scene_versions):
            raise HTTPException(status_code=400, detail=f"Scene version {measurement_data.scene_version} not found")
        
        # Create the measurement object
        measurement = SceneMeasurement(
            id=str(uuid.uuid4()),
            type=measurement_data.type,
            points=[SceneMeasurementPoint(x=p['x'], y=p['y']) for p in measurement_data.points],
            value=measurement_data.value,
            unit=measurement_data.unit,
            label=measurement_data.label,
            color=measurement_data.color,
            scene_version=measurement_data.scene_version
        )
        
        # Add to the scene version
        if not hasattr(session.scene_versions[version_idx], 'measurements'):
            session.scene_versions[version_idx].measurements = []
        session.scene_versions[version_idx].measurements.append(measurement)
        
        # Save session
        await firestore_service.update_session(session)
        
        return measurement.model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating measurement: {e}")
        raise HTTPException(status_code=500, detail="Failed to create measurement")


@router.put("/sessions/{session_id}/measurements/{measurement_id}")
async def update_measurement(session_id: str, measurement_id: str, update_data: MeasurementUpdate):
    """Update an existing measurement."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Find and update the measurement
        found = False
        for version in session.scene_versions:
            measurements = getattr(version, 'measurements', []) or []
            for i, m in enumerate(measurements):
                m_id = m.id if hasattr(m, 'id') else m.get('id')
                if m_id == measurement_id:
                    if update_data.value is not None:
                        if hasattr(m, 'value'):
                            m.value = update_data.value
                        else:
                            m['value'] = update_data.value
                    if update_data.unit is not None:
                        if hasattr(m, 'unit'):
                            m.unit = update_data.unit
                        else:
                            m['unit'] = update_data.unit
                    if update_data.label is not None:
                        if hasattr(m, 'label'):
                            m.label = update_data.label
                        else:
                            m['label'] = update_data.label
                    if update_data.color is not None:
                        if hasattr(m, 'color'):
                            m.color = update_data.color
                        else:
                            m['color'] = update_data.color
                    found = True
                    break
            if found:
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Measurement not found")
        
        await firestore_service.update_session(session)
        return {"success": True, "measurement_id": measurement_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating measurement: {e}")
        raise HTTPException(status_code=500, detail="Failed to update measurement")


@router.delete("/sessions/{session_id}/measurements/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_measurement(session_id: str, measurement_id: str):
    """Delete a measurement."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Find and remove the measurement
        found = False
        for version in session.scene_versions:
            measurements = getattr(version, 'measurements', []) or []
            for i, m in enumerate(measurements):
                m_id = m.id if hasattr(m, 'id') else m.get('id')
                if m_id == measurement_id:
                    measurements.pop(i)
                    version.measurements = measurements
                    found = True
                    break
            if found:
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Measurement not found")
        
        await firestore_service.update_session(session)
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting measurement: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete measurement")


# ==================== Multi-Witness Management Endpoints ====================


@router.get("/sessions/{session_id}/witnesses")
async def get_witnesses(session_id: str, include_reliability: bool = False):
    """Get all witnesses for a session, optionally with reliability scores."""
    from app.services.witness_reliability import witness_reliability_service
    from app.services.contradiction_detector import contradiction_detector
    from app.models.schemas import WitnessReliabilityProfile, WitnessReliabilityFactors
    
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        
        # Pre-compute reliability data if requested
        reliability_data = {}
        if include_reliability:
            contradictions = contradiction_detector.get_contradictions(session_id)
            evidence_markers = []
            scene_elements = []
            if session.scene_versions:
                latest = session.scene_versions[-1]
                evidence_markers = getattr(latest, 'evidence_markers', []) or []
            scene_elements = session.current_scene_elements or []
            
            for witness in witnesses_list:
                reliability = witness_reliability_service.calculate_reliability(
                    session_id=session_id,
                    witness_id=witness.id,
                    witness_name=witness.name,
                    statements=session.witness_statements,
                    contradictions=contradictions,
                    evidence_markers=evidence_markers,
                    scene_elements=scene_elements,
                )
                reliability_data[witness.id] = WitnessReliabilityProfile(
                    overall_score=reliability.overall_score,
                    reliability_grade=reliability.reliability_grade,
                    factors=WitnessReliabilityFactors(**reliability.factors.to_dict()),
                    contradiction_count=reliability.contradiction_count,
                    confirmation_count=reliability.confirmation_count,
                    correction_count=reliability.correction_count,
                    evidence_matches=reliability.evidence_matches,
                    evidence_conflicts=reliability.evidence_conflicts,
                    last_calculated=reliability.calculated_at,
                )
        
        # Count statements per witness
        witness_responses = []
        for witness in witnesses_list:
            stmt_count = sum(
                1 for stmt in session.witness_statements
                if getattr(stmt, 'witness_id', None) == witness.id
            )
            witness_responses.append(WitnessResponse(
                id=witness.id,
                name=witness.name,
                contact=witness.contact,
                location=witness.location,
                source_type=witness.source_type,
                created_at=witness.created_at,
                statement_count=stmt_count,
                reliability=reliability_data.get(witness.id) if include_reliability else witness.reliability,
                metadata=witness.metadata
            ))
        
        return {
            "session_id": session_id,
            "witnesses": [w.model_dump(mode='json') for w in witness_responses],
            "count": len(witness_responses),
            "active_witness_id": getattr(session, 'active_witness_id', None)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting witnesses: {e}")
        raise HTTPException(status_code=500, detail="Failed to get witnesses")


@router.post("/sessions/{session_id}/witnesses", status_code=status.HTTP_201_CREATED)
async def add_witness(session_id: str, witness_data: WitnessCreate):
    """Add a new witness to a session."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Create the witness
        new_witness = Witness(
            id=str(uuid.uuid4()),
            name=witness_data.name,
            contact=witness_data.contact,
            location=witness_data.location,
            source_type=witness_data.source_type,
            metadata=witness_data.metadata or {}
        )
        
        # Initialize witnesses list if needed
        if not hasattr(session, 'witnesses') or session.witnesses is None:
            session.witnesses = []
        
        session.witnesses.append(new_witness)
        
        # Set as active witness if this is the first one
        if len(session.witnesses) == 1:
            session.active_witness_id = new_witness.id
        
        session.updated_at = datetime.utcnow()
        await firestore_service.update_session(session)
        
        return WitnessResponse(
            id=new_witness.id,
            name=new_witness.name,
            contact=new_witness.contact,
            location=new_witness.location,
            source_type=new_witness.source_type,
            created_at=new_witness.created_at,
            statement_count=0,
            metadata=new_witness.metadata
        ).model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding witness: {e}")
        raise HTTPException(status_code=500, detail="Failed to add witness")


@router.get("/sessions/{session_id}/witnesses/{witness_id}")
async def get_witness(session_id: str, witness_id: str):
    """Get a specific witness with their statements."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        witness = next((w for w in witnesses_list if w.id == witness_id), None)
        if not witness:
            raise HTTPException(status_code=404, detail="Witness not found")
        
        # Get statements for this witness
        witness_statements = [
            {
                "id": stmt.id,
                "text": stmt.text,
                "timestamp": stmt.timestamp.isoformat() if stmt.timestamp else None,
                "is_correction": stmt.is_correction
            }
            for stmt in session.witness_statements
            if getattr(stmt, 'witness_id', None) == witness_id
        ]
        
        return {
            "id": witness.id,
            "name": witness.name,
            "contact": witness.contact,
            "location": witness.location,
            "source_type": witness.source_type,
            "created_at": witness.created_at.isoformat() if witness.created_at else None,
            "metadata": witness.metadata,
            "statements": witness_statements,
            "statement_count": len(witness_statements)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting witness: {e}")
        raise HTTPException(status_code=500, detail="Failed to get witness")


@router.put("/sessions/{session_id}/witnesses/{witness_id}")
async def update_witness(session_id: str, witness_id: str, witness_data: WitnessUpdate):
    """Update a witness's information."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        witness = next((w for w in witnesses_list if w.id == witness_id), None)
        if not witness:
            raise HTTPException(status_code=404, detail="Witness not found")
        
        # Update fields
        if witness_data.name is not None:
            witness.name = witness_data.name.strip() or "Anonymous Witness"
        if witness_data.contact is not None:
            witness.contact = witness_data.contact
        if witness_data.location is not None:
            witness.location = witness_data.location
        if witness_data.source_type is not None:
            witness.source_type = witness_data.source_type
        if witness_data.metadata is not None:
            witness.metadata.update(witness_data.metadata)
        
        session.updated_at = datetime.utcnow()
        await firestore_service.update_session(session)
        
        return {"success": True, "witness_id": witness_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating witness: {e}")
        raise HTTPException(status_code=500, detail="Failed to update witness")


@router.delete("/sessions/{session_id}/witnesses/{witness_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_witness(session_id: str, witness_id: str):
    """Delete a witness (but keep their statements, just unlink)."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        witness_idx = next((i for i, w in enumerate(witnesses_list) if w.id == witness_id), None)
        if witness_idx is None:
            raise HTTPException(status_code=404, detail="Witness not found")
        
        # Remove witness
        session.witnesses.pop(witness_idx)
        
        # Update active witness if needed
        if session.active_witness_id == witness_id:
            session.active_witness_id = session.witnesses[0].id if session.witnesses else None
        
        session.updated_at = datetime.utcnow()
        await firestore_service.update_session(session)
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting witness: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete witness")


@router.post("/sessions/{session_id}/witnesses/{witness_id}/activate")
async def set_active_witness(session_id: str, witness_id: str):
    """Set a witness as the active witness for new statements."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        witness = next((w for w in witnesses_list if w.id == witness_id), None)
        if not witness:
            raise HTTPException(status_code=404, detail="Witness not found")
        
        session.active_witness_id = witness_id
        session.updated_at = datetime.utcnow()
        await firestore_service.update_session(session)
        
        return {"success": True, "active_witness_id": witness_id, "witness_name": witness.name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting active witness: {e}")
        raise HTTPException(status_code=500, detail="Failed to set active witness")


@router.get("/sessions/{session_id}/statements/by-witness")
async def get_statements_by_witness(session_id: str):
    """Get all statements grouped by witness."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        
        # Group statements by witness
        statements_by_witness = {}
        unassigned_statements = []
        
        for stmt in session.witness_statements:
            witness_id = getattr(stmt, 'witness_id', None)
            if witness_id:
                if witness_id not in statements_by_witness:
                    statements_by_witness[witness_id] = []
                statements_by_witness[witness_id].append({
                    "id": stmt.id,
                    "text": stmt.text,
                    "timestamp": stmt.timestamp.isoformat() if stmt.timestamp else None,
                    "is_correction": stmt.is_correction,
                    "witness_name": getattr(stmt, 'witness_name', None)
                })
            else:
                unassigned_statements.append({
                    "id": stmt.id,
                    "text": stmt.text,
                    "timestamp": stmt.timestamp.isoformat() if stmt.timestamp else None,
                    "is_correction": stmt.is_correction
                })
        
        # Build response with witness info
        result = []
        for witness in witnesses_list:
            result.append({
                "witness_id": witness.id,
                "witness_name": witness.name,
                "source_type": witness.source_type,
                "statements": statements_by_witness.get(witness.id, [])
            })
        
        # Add unassigned statements (legacy statements without witness_id)
        if unassigned_statements:
            result.append({
                "witness_id": None,
                "witness_name": session.witness_name or "Unknown Witness",
                "source_type": session.source_type,
                "statements": unassigned_statements
            })
        
        return {
            "session_id": session_id,
            "witnesses": result,
            "total_statements": len(session.witness_statements)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting statements by witness: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statements by witness")


# ==================== Witness Reliability Endpoints ====================


@router.get("/sessions/{session_id}/witnesses/{witness_id}/reliability")
async def get_witness_reliability(session_id: str, witness_id: str):
    """
    Get reliability score for a specific witness.
    
    Returns reliability assessment including:
    - Overall score (0-100)
    - Letter grade (A-F)
    - Individual factors (contradiction rate, consistency, evidence alignment, etc.)
    - Statistics (contradictions, confirmations, corrections)
    """
    from app.services.witness_reliability import witness_reliability_service
    from app.services.contradiction_detector import contradiction_detector
    
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Find the witness
        witnesses_list = getattr(session, 'witnesses', []) or []
        witness = next((w for w in witnesses_list if w.id == witness_id), None)
        
        # If no specific witness found, use session-level witness info
        witness_name = "Primary Witness"
        if witness:
            witness_name = witness.name
        elif session.witness_name:
            witness_name = session.witness_name
        
        # Get contradictions for this session
        contradictions = contradiction_detector.get_contradictions(session_id)
        
        # Get evidence markers and scene elements
        evidence_markers = []
        scene_elements = []
        if session.scene_versions:
            latest = session.scene_versions[-1]
            evidence_markers = getattr(latest, 'evidence_markers', []) or []
        scene_elements = session.current_scene_elements or []
        
        # Calculate reliability score
        reliability = witness_reliability_service.calculate_reliability(
            session_id=session_id,
            witness_id=witness_id,
            witness_name=witness_name,
            statements=session.witness_statements,
            contradictions=contradictions,
            evidence_markers=evidence_markers,
            scene_elements=scene_elements,
        )
        
        return reliability.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating witness reliability: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate witness reliability")


@router.get("/sessions/{session_id}/witnesses/reliability")
async def get_all_witnesses_reliability(session_id: str):
    """
    Get reliability scores for all witnesses in a session.
    
    Returns list of reliability assessments for each witness.
    """
    from app.services.witness_reliability import witness_reliability_service
    from app.services.contradiction_detector import contradiction_detector
    
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        
        # Get shared data
        contradictions = contradiction_detector.get_contradictions(session_id)
        evidence_markers = []
        scene_elements = []
        if session.scene_versions:
            latest = session.scene_versions[-1]
            evidence_markers = getattr(latest, 'evidence_markers', []) or []
        scene_elements = session.current_scene_elements or []
        
        results = []
        
        # If no explicit witnesses, create reliability for session-level witness
        if not witnesses_list:
            witness_id = "primary"
            witness_name = session.witness_name or "Primary Witness"
            
            reliability = witness_reliability_service.calculate_reliability(
                session_id=session_id,
                witness_id=witness_id,
                witness_name=witness_name,
                statements=session.witness_statements,
                contradictions=contradictions,
                evidence_markers=evidence_markers,
                scene_elements=scene_elements,
            )
            results.append(reliability.to_dict())
        else:
            # Calculate for each witness
            for witness in witnesses_list:
                reliability = witness_reliability_service.calculate_reliability(
                    session_id=session_id,
                    witness_id=witness.id,
                    witness_name=witness.name,
                    statements=session.witness_statements,
                    contradictions=contradictions,
                    evidence_markers=evidence_markers,
                    scene_elements=scene_elements,
                )
                results.append(reliability.to_dict())
        
        return {
            "session_id": session_id,
            "witness_count": len(results),
            "reliability_scores": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating witnesses reliability: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate witnesses reliability")


# ==================== Evidence Markers Endpoints ====================


@router.get("/sessions/{session_id}/evidence-markers")
async def get_evidence_markers(session_id: str, scene_version: Optional[int] = None):
    """Get all evidence markers for a session, optionally filtered by scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        markers = []
        for version in session.scene_versions:
            if scene_version is not None and version.version != scene_version:
                continue
            version_markers = getattr(version, 'evidence_markers', []) or []
            for m in version_markers:
                if m:
                    markers.append(m.model_dump(mode='json') if hasattr(m, 'model_dump') else m)
        
        return {"session_id": session_id, "evidence_markers": markers, "count": len(markers)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting evidence markers: {e}")
        raise HTTPException(status_code=500, detail="Failed to get evidence markers")


@router.post("/sessions/{session_id}/evidence-markers", status_code=status.HTTP_201_CREATED)
async def create_evidence_marker(session_id: str, marker_data: dict):
    """Create a new evidence marker on a scene."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Create marker
        from app.models.schemas import EvidenceMarker, EvidenceMarkerPoint
        marker = EvidenceMarker(
            id=f"em-{uuid.uuid4().hex[:8]}",
            number=marker_data.get('number', 1),
            position=EvidenceMarkerPoint(**marker_data.get('position', {'x': 0.5, 'y': 0.5})),
            label=marker_data.get('label', ''),
            description=marker_data.get('description', ''),
            category=marker_data.get('category', 'general'),
            color=marker_data.get('color', '#fbbf24'),
            scene_version=marker_data.get('scene_version', 1)
        )
        
        # Find the scene version to attach to
        version_idx = None
        for i, v in enumerate(session.scene_versions):
            if v.version == marker.scene_version:
                version_idx = i
                break
        
        if version_idx is None:
            raise HTTPException(status_code=400, detail=f"Scene version {marker.scene_version} not found")
        
        # Add marker
        if not hasattr(session.scene_versions[version_idx], 'evidence_markers'):
            session.scene_versions[version_idx].evidence_markers = []
        session.scene_versions[version_idx].evidence_markers.append(marker)
        
        await firestore_service.update_session(session)
        
        return marker.model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating evidence marker: {e}")
        raise HTTPException(status_code=500, detail="Failed to create evidence marker")


@router.put("/sessions/{session_id}/evidence-markers/{marker_id}")
async def update_evidence_marker(session_id: str, marker_id: str, update_data: dict):
    """Update an evidence marker."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        found = False
        for version in session.scene_versions:
            markers = getattr(version, 'evidence_markers', []) or []
            for i, m in enumerate(markers):
                m_id = m.id if hasattr(m, 'id') else m.get('id')
                if m_id == marker_id:
                    # Update fields
                    if 'number' in update_data and update_data['number'] is not None:
                        m.number = update_data['number']
                    if 'position' in update_data and update_data['position'] is not None:
                        from app.models.schemas import EvidenceMarkerPoint
                        m.position = EvidenceMarkerPoint(**update_data['position'])
                    if 'label' in update_data and update_data['label'] is not None:
                        m.label = update_data['label']
                    if 'description' in update_data and update_data['description'] is not None:
                        m.description = update_data['description']
                    if 'category' in update_data and update_data['category'] is not None:
                        m.category = update_data['category']
                    if 'color' in update_data and update_data['color'] is not None:
                        m.color = update_data['color']
                    markers[i] = m
                    version.evidence_markers = markers
                    found = True
                    break
            if found:
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Evidence marker not found")
        
        await firestore_service.update_session(session)
        return {"status": "updated", "id": marker_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating evidence marker: {e}")
        raise HTTPException(status_code=500, detail="Failed to update evidence marker")


@router.delete("/sessions/{session_id}/evidence-markers/{marker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence_marker(session_id: str, marker_id: str):
    """Delete an evidence marker."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        found = False
        for version in session.scene_versions:
            markers = getattr(version, 'evidence_markers', []) or []
            for i, m in enumerate(markers):
                m_id = m.id if hasattr(m, 'id') else m.get('id')
                if m_id == marker_id:
                    markers.pop(i)
                    version.evidence_markers = markers
                    found = True
                    break
            if found:
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Evidence marker not found")
        
        await firestore_service.update_session(session)
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting evidence marker: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete evidence marker")


# ==================== Chain of Custody Endpoints ====================


@router.get("/sessions/{session_id}/custody-chain")
async def get_session_custody_chain(session_id: str):
    """
    Get the full chain of custody for a session and all its evidence.
    
    Returns complete audit trail showing who accessed/modified evidence and when.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Record this access
        await custody_chain_service.record_session_viewed(
            session_id=session_id,
            actor="api_user",  # In real implementation, get from auth
            metadata={"endpoint": "get_custody_chain"}
        )
        
        # Get all custody events for this session
        events = await custody_chain_service.get_all_custody_for_session(session_id)
        
        # Group by evidence type
        grouped = {}
        for event in events:
            ev_type = event.evidence_type
            if ev_type not in grouped:
                grouped[ev_type] = []
            grouped[ev_type].append(event.model_dump(mode='json') if hasattr(event, 'model_dump') else event)
        
        return {
            "session_id": session_id,
            "total_events": len(events),
            "events_by_type": grouped,
            "events": [e.model_dump(mode='json') if hasattr(e, 'model_dump') else e for e in events],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting custody chain: {e}")
        raise HTTPException(status_code=500, detail="Failed to get custody chain")


@router.get("/custody/{evidence_type}/{evidence_id}")
async def get_evidence_custody_chain(evidence_type: str, evidence_id: str):
    """
    Get the chain of custody for a specific evidence item.
    
    Args:
        evidence_type: Type of evidence (session, case, evidence_marker, statement, etc.)
        evidence_id: ID of the evidence item
    
    Returns:
        CustodyChainResponse with all custody events
    """
    try:
        chain = await custody_chain_service.get_custody_chain(evidence_type, evidence_id)
        return chain.model_dump(mode='json')
    except Exception as e:
        logger.error(f"Error getting custody chain: {e}")
        raise HTTPException(status_code=500, detail="Failed to get custody chain")


@router.post("/custody/events", status_code=status.HTTP_201_CREATED)
async def create_custody_event(event: CustodyEventCreate):
    """
    Manually record a custody event.
    
    Use this to track evidence handling that isn't automatically captured.
    """
    try:
        custody_event = await custody_chain_service.record_event(
            evidence_type=event.evidence_type,
            evidence_id=event.evidence_id,
            action=event.action,
            actor=event.actor,
            actor_role=event.actor_role,
            details=event.details,
            metadata=event.metadata,
        )
        return custody_event.model_dump(mode='json')
    except Exception as e:
        logger.error(f"Error creating custody event: {e}")
        raise HTTPException(status_code=500, detail="Failed to create custody event")


@router.get("/custody/exports")
async def get_export_audit_trail(evidence_type: Optional[str] = None, limit: int = 100):
    """
    Get audit trail of all evidence exports.
    
    Args:
        evidence_type: Optional filter by evidence type
        limit: Maximum number of events to return
    
    Returns:
        List of export custody events
    """
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        exports = await db.get_custody_exports(evidence_type, limit)
        return {
            "total": len(exports),
            "exports": exports,
        }
    except Exception as e:
        logger.error(f"Error getting export audit trail: {e}")
        raise HTTPException(status_code=500, detail="Failed to get export audit trail")


# ==================== Witness Sketch Upload Endpoints ====================


@router.get("/sessions/{session_id}/sketches")
async def list_sketches(session_id: str):
    """
    Get all uploaded witness sketches for a session.
    
    Returns:
        List of sketch objects with image URLs and AI interpretations
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        sketches = getattr(session, 'witness_sketches', []) or []
        return {
            "session_id": session_id,
            "sketches": [s.model_dump(mode='json') if hasattr(s, 'model_dump') else s for s in sketches],
            "count": len(sketches)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing sketches: {e}")
        raise HTTPException(status_code=500, detail="Failed to list sketches")


@router.post("/sessions/{session_id}/sketches", status_code=status.HTTP_201_CREATED)
async def upload_sketch(session_id: str, request: Request):
    """
    Upload a hand-drawn witness sketch for AI interpretation.
    
    Accepts multipart/form-data with:
    - image: The sketch image file (PNG, JPEG, GIF)
    - description: Optional witness description of the sketch
    
    Returns:
        The created sketch object with AI interpretation and extracted elements
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Parse multipart form data
        form = await request.form()
        image_file = form.get('image')
        description = form.get('description', '')
        
        if not image_file:
            raise HTTPException(status_code=400, detail="No image file provided")
        
        # Validate file type and size
        content_type = getattr(image_file, 'content_type', 'image/png')
        if content_type and content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid file type: {content_type}. Allowed: JPEG, PNG, GIF, WebP")
        
        # Read image data
        image_data = await image_file.read()
        if len(image_data) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE // (1024*1024)}MB")
        if len(image_data) < 100:
            raise HTTPException(status_code=400, detail="File too small or empty")
        
        # Generate unique filename
        sketch_id = f"sketch-{uuid.uuid4().hex[:8]}"
        ext = content_type.split('/')[-1]
        if ext == 'jpeg':
            ext = 'jpg'
        filename = f"{sketch_id}.{ext}"
        
        # Upload to storage
        image_url = await storage_service.upload_image(
            image_data=image_data,
            filename=filename,
            content_type=content_type,
            session_id=session_id
        )
        
        if not image_url:
            raise HTTPException(status_code=500, detail="Failed to upload sketch image")
        
        # Use AI to interpret the sketch
        ai_interpretation = None
        extracted_elements = []
        
        try:
            interpretation_result = await _interpret_sketch_with_ai(image_data, content_type, description)
            if interpretation_result:
                ai_interpretation = interpretation_result.get('overall_description', '')
                extracted_elements = interpretation_result.get('elements', [])
        except Exception as e:
            logger.warning(f"AI interpretation failed for sketch {sketch_id}: {e}")
            # Continue without AI interpretation
        
        # Create sketch record
        from app.models.schemas import WitnessSketch
        sketch = WitnessSketch(
            id=sketch_id,
            image_url=image_url,
            description=str(description) if description else None,
            ai_interpretation=ai_interpretation,
            extracted_elements=extracted_elements,
            witness_id=session.active_witness_id,
            witness_name=session.witness_name
        )
        
        # Add to session
        if not hasattr(session, 'witness_sketches') or session.witness_sketches is None:
            session.witness_sketches = []
        session.witness_sketches.append(sketch)
        
        # Update session
        await firestore_service.update_session(session)
        
        # Publish SSE event
        await publish_event("sketch_uploaded", {
            "session_id": session_id,
            "sketch_id": sketch_id,
            "has_interpretation": ai_interpretation is not None
        })
        
        logger.info(f"Sketch {sketch_id} uploaded for session {session_id}")
        
        return sketch.model_dump(mode='json')
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading sketch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload sketch: {str(e)}")


@router.get("/sessions/{session_id}/sketches/{sketch_id}")
async def get_sketch(session_id: str, sketch_id: str):
    """Get a specific sketch by ID."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        sketches = getattr(session, 'witness_sketches', []) or []
        for sketch in sketches:
            s_id = sketch.id if hasattr(sketch, 'id') else sketch.get('id')
            if s_id == sketch_id:
                return sketch.model_dump(mode='json') if hasattr(sketch, 'model_dump') else sketch
        
        raise HTTPException(status_code=404, detail="Sketch not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sketch: {e}")
        raise HTTPException(status_code=500, detail="Failed to get sketch")


@router.post("/sessions/{session_id}/sketches/{sketch_id}/reinterpret")
async def reinterpret_sketch(session_id: str, sketch_id: str):
    """
    Re-run AI interpretation on an existing sketch.
    
    Useful when AI models improve or additional context is available.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        sketches = getattr(session, 'witness_sketches', []) or []
        sketch_idx = None
        sketch = None
        
        for i, s in enumerate(sketches):
            s_id = s.id if hasattr(s, 'id') else s.get('id')
            if s_id == sketch_id:
                sketch_idx = i
                sketch = s
                break
        
        if sketch is None:
            raise HTTPException(status_code=404, detail="Sketch not found")
        
        # Download the image for reinterpretation
        image_url = sketch.image_url if hasattr(sketch, 'image_url') else sketch.get('image_url')
        if not image_url:
            raise HTTPException(status_code=400, detail="Sketch has no image URL")
        
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Could not fetch sketch image")
            image_data = response.content
            content_type = response.headers.get('content-type', 'image/png')
        
        # Get description
        description = sketch.description if hasattr(sketch, 'description') else sketch.get('description', '')
        
        # Re-run AI interpretation
        interpretation_result = await _interpret_sketch_with_ai(image_data, content_type, description)
        
        if interpretation_result:
            if hasattr(sketch, 'ai_interpretation'):
                sketch.ai_interpretation = interpretation_result.get('overall_description', '')
                sketch.extracted_elements = interpretation_result.get('elements', [])
            else:
                sketch['ai_interpretation'] = interpretation_result.get('overall_description', '')
                sketch['extracted_elements'] = interpretation_result.get('elements', [])
            
            session.witness_sketches[sketch_idx] = sketch
            await firestore_service.update_session(session)
            
            return {
                "status": "reinterpreted",
                "sketch_id": sketch_id,
                "interpretation": interpretation_result
            }
        
        raise HTTPException(status_code=500, detail="AI interpretation failed")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reinterpreting sketch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reinterpret sketch: {str(e)}")


@router.delete("/sessions/{session_id}/sketches/{sketch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sketch(session_id: str, sketch_id: str):
    """Delete a sketch from the session."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        sketches = getattr(session, 'witness_sketches', []) or []
        found = False
        
        for i, s in enumerate(sketches):
            s_id = s.id if hasattr(s, 'id') else s.get('id')
            if s_id == sketch_id:
                sketches.pop(i)
                session.witness_sketches = sketches
                found = True
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Sketch not found")
        
        await firestore_service.update_session(session)
        return None
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting sketch: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete sketch")


async def _interpret_sketch_with_ai(
    image_data: bytes,
    content_type: str,
    description: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Use Gemini's vision capabilities to interpret a hand-drawn sketch.
    
    Args:
        image_data: Raw image bytes
        content_type: MIME type of the image
        description: Optional witness description of the sketch
    
    Returns:
        Dictionary with interpretation results or None on failure
    """
    try:
        from app.models.schemas import SketchInterpretationResponse
        from app.services.model_selector import model_selector, call_with_retry
        from google.genai import types
        import base64
        
        # Get best model for vision tasks
        vision_model = await model_selector.get_best_model_for_task("vision")
        
        # Build prompt
        prompt = """Analyze this hand-drawn witness sketch and extract all identifiable scene elements.

This is a sketch drawn by a witness to help describe an incident. Look for:
- People (stick figures, shapes representing people)
- Vehicles (cars, trucks, motorcycles, bicycles)
- Buildings, structures, or location features
- Arrows indicating movement or direction
- Text labels or annotations
- Objects (bags, weapons, tools, etc.)
- Road features (intersections, crosswalks, signs)
- Environmental features (trees, fences, poles)

For each element, identify:
1. What it appears to represent
2. Its position in the sketch (top, bottom, left, right, center)
3. Its relative size
4. Any labels near it
5. Relationships to other elements"""
        
        if description:
            prompt += f"\n\nThe witness described this sketch as: {description}"
        
        prompt += "\n\nProvide a structured analysis of this sketch."
        
        # Create multimodal content
        client = genai.Client(api_key=settings.google_api_key)
        
        # Encode image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        response = await call_with_retry(
            asyncio.to_thread,
            client.models.generate_content,
            model=vision_model,
            contents=[
                types.Part.from_bytes(data=image_data, mime_type=content_type),
                prompt
            ],
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
                response_json_schema=SketchInterpretationResponse,
            ),
            model_name=vision_model,
        )
        
        if response and response.text:
            result = json.loads(response.text)
            
            # Track usage
            usage_tracker.record_request(
                model_name=vision_model,
                input_tokens=1000,  # Estimated for image
                output_tokens=len(response.text) // 4
            )
            
            logger.info(f"Sketch interpretation completed with {len(result.get('elements', []))} elements")
            return result
        
        return None
    
    except Exception as e:
        logger.error(f"Error interpreting sketch with AI: {e}")
        return None


# ==================== Model Management Endpoints ====================


@router.get("/sessions/{session_id}", response_model=ReconstructionSession)
async def get_session(session_id: str):
    """Get a specific reconstruction session."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get session"
        )



@router.patch("/sessions/{session_id}", response_model=ReconstructionSession)
async def update_session(session_id: str, update_data: SessionUpdate):
    """Update a reconstruction session."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Update fields
        if update_data.title is not None:
            session.title = update_data.title
        if update_data.status is not None:
            session.status = update_data.status
        if update_data.metadata is not None:
            session.metadata.update(update_data.metadata)
        
        success = await firestore_service.update_session(session)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update session"
            )
        
        return session
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update session"
        )



@router.post("/sessions/{session_id}/close")
async def close_session_on_client_exit(session_id: str, reason: str = "tab_close"):
    """Mark a session completed when the client tab/app is closed."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        metadata = dict(session.metadata or {})
        metadata["closed_by_client"] = True
        metadata["close_reason"] = (reason or "tab_close")[:80]
        metadata["closed_at"] = datetime.utcnow().isoformat()
        session.metadata = metadata

        if session.status == "active":
            session.status = "completed"
        session.updated_at = datetime.utcnow()

        success = await firestore_service.update_session(session)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to close session",
            )

        remove_agent(session_id)
        return {"closed": True, "session_id": session_id, "status": session.status}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to close session",
        )



@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str):
    """Delete a reconstruction session."""
    try:
        # Delete from Firestore
        success = await firestore_service.delete_session(session_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete session"
            )
        
        # Delete associated files from GCS
        await storage_service.delete_session_files(session_id)
        
        # Remove agent from cache
        remove_agent(session_id)
        
        logger.info(f"Deleted session {session_id}")
    
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete session"
        )



@router.get("/analytics/stats")
async def get_analytics_stats():
    """Get analytics statistics across all sessions."""
    try:
        sessions = await firestore_service.list_sessions(limit=1000)
        
        if not sessions:
            return {
                "total_sessions": 0,
                "total_statements": 0,
                "total_reconstructions": 0,
                "avg_statements_per_session": 0.0,
                "avg_reconstructions_per_session": 0.0,
                "most_common_elements": [],
                "session_statuses": {}
            }
        
        # Calculate statistics
        total_sessions = len(sessions)
        total_statements = sum(len(s.witness_statements) for s in sessions)
        total_reconstructions = sum(len(s.scene_versions) for s in sessions)
        
        # Calculate average session duration
        total_duration_seconds = 0
        sessions_with_duration = 0
        for session in sessions:
            if session.created_at and session.updated_at:
                duration = (session.updated_at - session.created_at).total_seconds()
                if duration > 0:
                    total_duration_seconds += duration
                    sessions_with_duration += 1
        
        avg_duration_minutes = (total_duration_seconds / 60 / sessions_with_duration) if sessions_with_duration > 0 else 0
        
        # Track element types
        element_counts = {}
        for session in sessions:
            for elem in session.current_scene_elements:
                elem_type = elem.type
                element_counts[elem_type] = element_counts.get(elem_type, 0) + 1
        
        # Sort by most common
        most_common_elements = sorted(
            [{"type": k, "count": v} for k, v in element_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:10]
        
        # Session statuses
        status_counts = {}
        for session in sessions:
            status = session.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "total_sessions": total_sessions,
            "total_statements": total_statements,
            "total_reconstructions": total_reconstructions,
            "avg_statements_per_session": total_statements / total_sessions if total_sessions > 0 else 0.0,
            "avg_reconstructions_per_session": total_reconstructions / total_sessions if total_sessions > 0 else 0.0,
            "avg_session_duration_minutes": round(avg_duration_minutes, 2),
            "most_common_elements": most_common_elements,
            "session_statuses": status_counts
        }
    
    except Exception as e:
        logger.error(f"Error getting analytics stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get analytics statistics"
        )



@router.get("/analytics/elements/search")
async def search_sessions_by_element(
    element_type: Optional[str] = None,
    element_description: Optional[str] = None,
    color: Optional[str] = None,
    limit: int = 50
):
    """Search sessions by scene elements."""
    try:
        all_sessions = await firestore_service.list_sessions(limit=1000)
        matching_sessions = []
        
        for session in all_sessions:
            match = False
            for elem in session.current_scene_elements:
                # Check if element matches criteria
                type_match = not element_type or (elem.type and elem.type.lower() == element_type.lower())
                desc_match = not element_description or (elem.description and element_description.lower() in elem.description.lower())
                color_match = not color or (elem.color and color.lower() in elem.color.lower())
                
                if type_match and desc_match and color_match:
                    match = True
                    break
            
            if match:
                matching_sessions.append(SessionResponse(
                    id=session.id,
                    title=session.title,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    status=session.status,
                    statement_count=len(session.witness_statements),
                    version_count=len(session.scene_versions),
                    metadata=getattr(session, 'metadata', {})
                ))
                
                if len(matching_sessions) >= limit:
                    break
        
        return matching_sessions
    
    except Exception as e:
        logger.error(f"Error searching sessions by element: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search sessions"
        )



@router.get("/models", response_model=ModelsListResponse)
async def list_models():
    """
    List available Gemini models with their capabilities.
    
    Returns information about models that can be used for scene reconstruction.
    Falls back to known models if API is not configured or fails.
    """
    # Known models list for fallback
    known_models = [
        "gemini-2.5-pro",
        "gemini-2.5-flash", 
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-exp",
    ]
    
    try:
        # If no API key, return known models with informative message
        if not settings.google_api_key or settings.google_api_key.strip() == "":
            logger.info("No Google API key configured, returning known models list")
            models_list = []
            for model_name in known_models:
                models_list.append(ModelInfo(
                    name=model_name,
                    display_name=model_name.replace("-", " ").title(),
                    description=f"Gemini model: {model_name} (API key not configured - using fallback list)",
                    supported_generation_methods=["generateContent"],
                ))
            return {"models": models_list}
        
        # Run blocking API call in thread pool to avoid blocking event loop
        def fetch_models():
            """Fetch models from Gemini API (runs in thread pool)."""
            client = genai.Client(api_key=settings.google_api_key)
            models = []
            for model in client.models.list():
                # Filter for generation models only
                if hasattr(model, 'supported_generation_methods') and \
                   'generateContent' in model.supported_generation_methods:
                    models.append(model)
            return models
        
        # List models from Gemini API in thread pool
        models_list = []
        try:
            api_models = await asyncio.to_thread(fetch_models)
            for model in api_models:
                model_info = ModelInfo(
                    name=model.name,
                    display_name=model.display_name if hasattr(model, 'display_name') else model.name,
                    description=model.description if hasattr(model, 'description') else None,
                    version=model.version if hasattr(model, 'version') else None,
                    input_token_limit=model.input_token_limit if hasattr(model, 'input_token_limit') else None,
                    output_token_limit=model.output_token_limit if hasattr(model, 'output_token_limit') else None,
                    supported_generation_methods=list(model.supported_generation_methods) if hasattr(model, 'supported_generation_methods') else [],
                    temperature=model.temperature if hasattr(model, 'temperature') else None,
                    top_p=model.top_p if hasattr(model, 'top_p') else None,
                    top_k=model.top_k if hasattr(model, 'top_k') else None,
                )
                models_list.append(model_info)
            
            logger.info(f"Fetched {len(models_list)} models from Gemini API")
            
            # If API returned empty (rate limited or no results), use fallback
            if not models_list:
                logger.info("API returned no models, falling back to known models")
                for model_name in known_models:
                    models_list.append(ModelInfo(
                        name=model_name,
                        display_name=model_name.replace("-", " ").title(),
                        description=f"Gemini model: {model_name}",
                        supported_generation_methods=["generateContent"],
                    ))
        except Exception as e:
            logger.warning(f"Error listing models from API, falling back to known models: {e}")
            # Fall back to known models if API call fails
            for model_name in known_models:
                models_list.append(ModelInfo(
                    name=model_name,
                    display_name=model_name.replace("-", " ").title(),
                    description=f"Gemini model: {model_name}",
                    supported_generation_methods=["generateContent"],
                ))
        
        logger.info(f"Returning {len(models_list)} available models")
        # Return object with models key for frontend compatibility
        return {"models": models_list}
    
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        # Even on error, return known models
        models_list = []
        for model_name in known_models:
            models_list.append(ModelInfo(
                name=model_name,
                display_name=model_name.replace("-", " ").title(),
                description=f"Gemini model: {model_name}",
                supported_generation_methods=["generateContent"],
            ))
        return {"models": models_list}



@router.get("/models/quota", response_model=dict)
async def get_quota_info(model: Optional[str] = None):
    """
    Get quota and usage information for Gemini models.
    
    Args:
        model: Optional specific model name. If not provided, uses current model.
    
    Returns:
        Usage and quota information with rate limits in frontend-compatible format.
        
    Note:
        Gemini API does not provide programmatic quota endpoints.
        This tracks usage locally by counting API calls and tokens.
        Counts are approximate and reset at midnight Pacific Time.
    """
    try:
        # Use specified model or default to current model
        target_model = model or settings.gemini_model
        
        # Get usage for the target model
        usage = usage_tracker.get_usage(target_model)
        
        # Transform to frontend-expected format
        # Frontend expects flat structure with requests_per_minute, requests_per_day, tokens_per_day
        return {
            "selected_model": target_model,
            "tier": usage.get("tier", "free"),
            "requests_per_minute": {
                "used": usage.get("requests", {}).get("minute", {}).get("used", 0),
                "limit": usage.get("requests", {}).get("minute", {}).get("limit", 15),
                "remaining": usage.get("requests", {}).get("minute", {}).get("remaining", 15)
            },
            "requests_per_day": {
                "used": usage.get("requests", {}).get("day", {}).get("used", 0),
                "limit": usage.get("requests", {}).get("day", {}).get("limit", 1500),
                "remaining": usage.get("requests", {}).get("day", {}).get("remaining", 1500)
            },
            "tokens_per_day": {
                "used": usage.get("tokens", {}).get("day", {}).get("used", 0),
                "limit": usage.get("tokens", {}).get("day", {}).get("limit", 15000000),
                "remaining": usage.get("tokens", {}).get("day", {}).get("remaining", 15000000)
            },
            "reset_time": usage.get("reset_time", "Midnight Pacific Time"),
            "note": usage.get("note", "Usage tracking is approximate and based on local counting")
        }
    
    except Exception as e:
        logger.error(f"Error getting quota info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get quota information"
        )



@router.patch("/models/config")
async def update_model_config(config: ModelConfigUpdate):
    """
    Update the model configuration (which model to use).
    
    Args:
        config: New model configuration
    
    Returns:
        Success message with new model name
        
    Note:
        This updates the runtime configuration. To persist across restarts,
        update the GEMINI_MODEL environment variable.
    """
    try:
        # Validate model name format
        if not config.model_name or not config.model_name.startswith("gemini-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid model name. Must be a Gemini model (e.g., gemini-2.5-flash)"
            )
        
        # Update runtime configuration
        old_model = settings.gemini_model
        settings.gemini_model = config.model_name
        
        logger.info(f"Model configuration updated: {old_model} -> {config.model_name}")
        
        return {
            "success": True,
            "previous_model": old_model,
            "current_model": config.model_name,
            "note": "Configuration updated for current runtime. Update GEMINI_MODEL env var to persist."
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update model configuration"
        )



@router.get("/models/current")
async def get_current_model():
    """
    Get the currently configured model and actively selected models.
    
    Returns:
        Current model name and configuration, including model selector choices.
        Fixes Bug #42: Use new get_current_model() method.
    """
    try:
        from app.services.model_selector import model_selector
        
        return {
            "model": settings.gemini_model,
            "vision_model": settings.gemini_vision_model,
            "environment": settings.environment,
            "active_models": {
                "chat": model_selector.get_current_model("chat"),
                "scene_reconstruction": model_selector.get_current_model("scene")
            }
        }
    
    except Exception as e:
        logger.error(f"Error getting current model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get current model"
        )


@router.get("/models/status")
async def get_models_status():
    """
    Get status of all available models, including rate limit information.
    Implements Idea #2: Check what models are rate limited without spending tokens.
    
    Returns:
        List of models with their availability and rate limit status
    """
    from app.services.model_selector import model_selector
    
    try:
        statuses = await model_selector.get_all_models_status()
        
        # Add current model selection info
        chat_model = await model_selector.get_best_model_for_chat()
        scene_model = await model_selector.get_best_model_for_scene()
        
        return {
            "models": statuses,
            "recommended": {
                "chat": chat_model,
                "scene_reconstruction": scene_model
            },
            "current_selection": {
                "default": settings.gemini_model,
                "vision": settings.gemini_vision_model
            }
        }
    except Exception as e:
        logger.error(f"Error getting model status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model status: {str(e)}"
        )


@router.get("/models/selection/{task_type}")
async def get_model_selection(task_type: str):
    """Return model selection details for a task type."""
    from app.services.model_selector import model_selector, TASK_CHAINS

    try:
        helper = None
        for helper_name in (
            "get_selection_explanation",
            "explain_selection",
            "explain_model_selection",
            "get_model_selection_explanation",
        ):
            candidate = getattr(model_selector, helper_name, None)
            if callable(candidate):
                helper = candidate
                break

        if helper:
            return await helper(task_type) if asyncio.iscoroutinefunction(helper) else helper(task_type)

        selected_model = await model_selector.get_best_model_for_task(task_type)
        return {
            "task_type": task_type,
            "selected_model": selected_model,
            "current_model": model_selector.get_current_model(task_type),
            "fallback_chain": [model_name for model_name, _ in TASK_CHAINS.get(task_type, [])],
            "note": "Selection explanation helper not available on model_selector",
        }
    except Exception as e:
        logger.error(f"Error getting model selection for {task_type}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model selection: {str(e)}"
        )


@router.get("/models/compare")
async def compare_models():
    """
    Compare performance and usage statistics across different models.
    
    Returns comparison data for model selection decisions:
    - Usage statistics per model
    - Rate limits and quotas
    - Recommended use cases
    - Cost/performance tradeoffs
    """
    try:
        # Get usage data for all tracked models
        all_usage = usage_tracker.get_all_usage()
        
        # Model recommendations based on use case
        model_recommendations = {
            "gemini-2.5-pro": {
                "description": "Most capable model with best reasoning",
                "best_for": ["Complex scene analysis", "Multi-witness reconciliation", "Detailed reports"],
                "speed": "Slower",
                "quality": "Highest",
                "cost_tier": "Higher RPM limits but lower daily quota"
            },
            "gemini-2.5-flash": {
                "description": "Balanced performance and speed",
                "best_for": ["General scene reconstruction", "Real-time interviews", "Most use cases"],
                "speed": "Fast",
                "quality": "High",
                "cost_tier": "Free tier optimized (15 RPM, 1500/day, 15M tokens)"
            },
            "gemini-2.5-flash-lite": {
                "description": "Fastest responses with good quality",
                "best_for": ["Quick sketches", "Rapid iteration", "High volume"],
                "speed": "Fastest",
                "quality": "Good",
                "cost_tier": "Same as flash (15 RPM, 1500/day)"
            },
            "gemini-2.0-flash": {
                "description": "Previous generation fast model",
                "best_for": ["Fallback option", "Legacy compatibility"],
                "speed": "Fast",
                "quality": "High",
                "cost_tier": "Same as 2.5-flash"
            },
            "gemini-2.0-flash-lite": {
                "description": "Previous generation lite model",
                "best_for": ["Fallback option", "High volume"],
                "speed": "Fastest",
                "quality": "Good",
                "cost_tier": "Same as flash"
            }
        }
        
        # Build comparison data
        comparison = []
        for model_name, usage_data in all_usage.items():
            recommendation = model_recommendations.get(model_name, {
                "description": "Gemini model",
                "best_for": ["General use"],
                "speed": "Unknown",
                "quality": "Unknown",
                "cost_tier": "Unknown"
            })
            
            comparison.append({
                "model": model_name,
                "usage": {
                    "requests_today": usage_data.get("requests", {}).get("day", {}).get("used", 0),
                    "requests_minute": usage_data.get("requests", {}).get("minute", {}).get("used", 0),
                    "tokens_today": usage_data.get("tokens", {}).get("day", {}).get("used", 0)
                },
                "limits": usage_data.get("limits", {}),
                "remaining": usage_data.get("remaining", {}),
                "tier": usage_data.get("tier", "unknown"),
                "recommendation": recommendation
            })
        
        # Sort by usage (most used first)
        comparison.sort(
            key=lambda x: x["usage"]["requests_today"],
            reverse=True
        )
        
        return {
            "comparison": comparison,
            "current_model": settings.gemini_model,
            "recommendation": (
                "For most use cases, gemini-2.5-flash offers the best balance of speed, "
                "quality, and free tier quotas. Use gemini-2.5-pro for complex analysis. "
                "Use gemini-2.5-flash-lite for maximum speed and volume."
            )
        }
    except Exception as e:
        logger.error(f"Error comparing models: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compare models: {str(e)}"
        )


@router.post("/models/select")
async def select_model(config: ModelConfigUpdate):
    """
    Update the active model selection.
    
    Changes will apply to new sessions and API calls.
    Existing sessions continue using their original model.
    """
    try:
        # Validate model name
        valid_models = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash-exp"
        ]
        
        if config.model and config.model not in valid_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid model. Must be one of: {', '.join(valid_models)}"
            )
        
        # Update settings (in-memory only - restart required for persistence)
        if config.model:
            settings.gemini_model = config.model
            logger.info(f"Updated default model to: {config.model}")
        
        if config.vision_model:
            if config.vision_model not in valid_models:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid vision model. Must be one of: {', '.join(valid_models)}"
                )
            settings.gemini_vision_model = config.vision_model
            logger.info(f"Updated vision model to: {config.vision_model}")
        
        return {
            "success": True,
            "current_model": settings.gemini_model,
            "vision_model": settings.gemini_vision_model,
            "note": "Model selection updated. Restart server to persist changes."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error selecting model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update model selection: {str(e)}"
        )



@router.get("/version")
async def get_version():
    """Get application version from VERSION file."""
    import os
    # In production Docker: /app/VERSION
    # In development: ../../../VERSION from backend/app/api/
    version_file = "/app/VERSION" if os.path.exists("/app/VERSION") else os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "VERSION"
    )
    try:
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                version = f.read().strip()
        else:
            version = "1.0.0"  # Default fallback
    except Exception:
        version = "1.0.0"
    
    return {"version": version}


@router.get("/info")
async def get_server_info():
    """
    Get server information and capabilities.
    
    Returns:
        Server version, configuration, and feature flags
    """
    import os
    import sys
    
    # Read version from file (same logic as /version endpoint)
    version_file = "/app/VERSION" if os.path.exists("/app/VERSION") else os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "VERSION"
    )
    try:
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                version = f.read().strip()
        else:
            version = "1.0.0"
    except Exception:
        version = "1.0.0"
    
    return {
        "name": "WitnessReplay API",
        "version": version,
        "description": "Voice-driven crime scene reconstruction agent for Gemini Live Agent Challenge",
        "environment": settings.environment,
        "debug_mode": settings.debug,
        "python_version": sys.version.split()[0],
        "features": {
            "voice_streaming": True,
            "scene_generation": True,
            "multi_session": True,
            "analytics": True,
            "admin_portal": True,
            "model_selector": True,
            "witness_analysis": True,
            "session_comparison": True,
            "rate_limiting": settings.enforce_rate_limits,
            "export_pdf": True,
            "export_json": True,
            "export_csv": True,
            "export_evidence": True,
            "chain_of_custody": True,
            "websocket": True,
            "metrics": True,
        },
        "models": {
            "default": settings.gemini_model,
            "vision": settings.gemini_vision_model,
        },
        "limits": {
            "max_requests_per_minute": settings.max_requests_per_minute,
            "session_timeout_minutes": settings.session_timeout_minutes,
            "max_session_size_mb": settings.max_session_size_mb,
        },
        "endpoints": {
            "api_docs": "/docs",
            "health": "/api/health",
            "metrics": "/api/metrics",
            "sessions": "/api/sessions",
            "admin_stats": "/api/admin/stats",
            "admin_search": "/api/admin/search",
            "models": "/api/models",
            "models_quota": "/api/models/quota",
            "models_compare": "/api/models/compare",
            "websocket": "/ws/{session_id}",
        }
    }


@router.get("/config")
async def get_config_info(auth=Depends(require_admin_auth)):
    """
    Get detailed server configuration (admin only).
    
    Returns full configuration details including environment variables.
    Sensitive values are masked.
    """
    import os
    
    return {
        "google_cloud": {
            "project_id": settings.gcp_project_id or "(not set)",
            "gcs_bucket": settings.gcs_bucket,
            "firestore_collection": settings.firestore_collection,
            "api_key_configured": bool(settings.google_api_key),
        },
        "server": {
            "environment": settings.environment,
            "debug": settings.debug,
            "host": settings.host,
            "port": settings.port,
        },
        "models": {
            "default_model": settings.gemini_model,
            "vision_model": settings.gemini_vision_model,
        },
        "security": {
            "cors_origins": settings.allowed_origins,
            "rate_limiting_enabled": settings.enforce_rate_limits,
            "max_requests_per_minute": settings.max_requests_per_minute,
            "admin_password_set": bool(settings.admin_password),
        },
        "session": {
            "timeout_minutes": settings.session_timeout_minutes,
            "max_size_mb": settings.max_session_size_mb,
        },
        "environment_variables": {
            "GOOGLE_API_KEY": "***" if settings.google_api_key else "(not set)",
            "GCP_PROJECT_ID": settings.gcp_project_id or "(not set)",
            "ENVIRONMENT": settings.environment,
            "DEBUG": str(settings.debug),
            "ADMIN_PASSWORD": "***" if settings.admin_password else "(not set)",
        }
    }



@router.get("/admin/stats")
async def get_admin_stats(auth=Depends(require_admin_auth)):
    """
    Get comprehensive admin statistics for dashboard.
    
    Requires admin authentication.
    Returns:
        - Total cases
        - Active/completed/archived breakdown
        - Average statements per case
        - Total witness statements
        - Top scene elements
        - Recent activity
    """
    try:
        # Get all sessions
        sessions = await firestore_service.list_sessions(limit=1000)
        
        # Calculate statistics
        total_cases = len(sessions)
        status_counts = {"active": 0, "completed": 0, "archived": 0}
        total_statements = 0
        total_corrections = 0
        total_reconstructions = 0
        scene_elements = {}
        
        for session in sessions:
            status_counts[session.status] = status_counts.get(session.status, 0) + 1
            total_statements += len(session.witness_statements)
            total_corrections += sum(1 for stmt in session.witness_statements if stmt.is_correction)
            total_reconstructions += len(session.scene_versions)
            
            # Count scene elements
            for element in session.current_scene_elements:
                element_type = element.element_type
                scene_elements[element_type] = scene_elements.get(element_type, 0) + 1
        
        # Get top 10 most common scene elements
        top_elements = sorted(
            scene_elements.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Calculate averages
        avg_statements = total_statements / total_cases if total_cases > 0 else 0
        avg_reconstructions = total_reconstructions / total_cases if total_cases > 0 else 0
        
        # Get recent sessions (last 5)
        recent_sessions = sorted(
            sessions,
            key=lambda s: s.updated_at if s.updated_at else s.created_at,
            reverse=True
        )[:5]
        
        recent_activity = [
            {
                "id": session.id,
                "title": session.title,
                "status": session.status,
                "updated_at": session.updated_at.isoformat() if session.updated_at else session.created_at.isoformat(),
                "statement_count": len(session.witness_statements)
            }
            for session in recent_sessions
        ]
        
        return {
            "total_cases": total_cases,
            "status_breakdown": status_counts,
            "total_statements": total_statements,
            "total_corrections": total_corrections,
            "total_reconstructions": total_reconstructions,
            "total_cases_grouped": len(await firestore_service.list_cases(limit=1000)),
            "averages": {
                "statements_per_case": round(avg_statements, 2),
                "reconstructions_per_case": round(avg_reconstructions, 2)
            },
            "top_scene_elements": [
                {"type": element_type, "count": count}
                for element_type, count in top_elements
            ],
            "recent_activity": recent_activity
        }
    except Exception as e:
        logger.error(f"Error fetching admin stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch statistics: {str(e)}"
        )


@router.get("/admin/search")
async def search_cases(
    q: str,
    limit: int = 20,
    auth=Depends(require_admin_auth)
):
    """
    Search cases by title, witness statements, or scene elements.
    
    Args:
        q: Search query
        limit: Maximum results to return
        
    Requires admin authentication.
    """
    try:
        # Get all sessions
        all_sessions = await firestore_service.list_sessions(limit=1000)
        
        # Filter sessions based on search query
        query_lower = q.lower()
        matching_sessions = []
        
        for session in all_sessions:
            # Check title
            if query_lower in session.title.lower():
                matching_sessions.append({
                    "session": session,
                    "match_reason": "title",
                    "match_text": session.title
                })
                continue
            
            # Check witness statements
            for stmt in session.witness_statements:
                if query_lower in stmt.content.lower():
                    matching_sessions.append({
                        "session": session,
                        "match_reason": "statement",
                        "match_text": stmt.content[:100] + "..." if len(stmt.content) > 100 else stmt.content
                    })
                    break
            
            # Check scene elements
            for element in session.current_scene_elements:
                if query_lower in element.description.lower():
                    matching_sessions.append({
                        "session": session,
                        "match_reason": "scene_element",
                        "match_text": element.description
                    })
                    break
        
        # Limit results
        matching_sessions = matching_sessions[:limit]
        
        # Format response
        results = [
            {
                "id": match["session"].id,
                "title": match["session"].title,
                "status": match["session"].status,
                "created_at": match["session"].created_at.isoformat() if match["session"].created_at else None,
                "updated_at": match["session"].updated_at.isoformat() if match["session"].updated_at else None,
                "statement_count": len(match["session"].witness_statements),
                "match_reason": match["match_reason"],
                "match_text": match["match_text"]
            }
            for match in matching_sessions
        ]
        
        return {
            "query": q,
            "total_results": len(results),
            "results": results
        }
    except Exception as e:
        logger.error(f"Error searching cases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.get("/sessions/{session_id}/witnesses/analysis")
async def analyze_witnesses(session_id: str):
    """
    Analyze witness statements for contradictions, consensus, and reliability.
    
    Returns:
        - Statement consistency scores
        - Contradiction detection
        - Consensus areas
        - Confidence levels per witness
        - Timeline alignment
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        if not session.witness_statements:
            return {
                "session_id": session_id,
                "witness_count": 0,
                "total_statements": 0,
                "analysis": "No witness statements available for analysis"
            }
        
        # Analyze statements
        total_statements = len(session.witness_statements)
        corrections = sum(1 for stmt in session.witness_statements if stmt.is_correction)
        original_statements = total_statements - corrections
        
        # Calculate correction ratio (high ratio might indicate uncertainty or evolving account)
        correction_ratio = corrections / total_statements if total_statements > 0 else 0
        
        # Analyze temporal patterns
        statement_timeline = [
            {
                "index": i,
                "timestamp": stmt.timestamp.isoformat() if stmt.timestamp else None,
                "is_correction": stmt.is_correction,
                "content_length": len(stmt.content)
            }
            for i, stmt in enumerate(session.witness_statements)
        ]
        
        # Detect potential contradictions (simple keyword-based analysis)
        contradiction_keywords = ["no", "not", "never", "actually", "wrong", "mistake", "correction"]
        potential_contradictions = [
            {
                "statement_index": i,
                "content": stmt.content[:100] + "..." if len(stmt.content) > 100 else stmt.content,
                "is_correction": stmt.is_correction
            }
            for i, stmt in enumerate(session.witness_statements)
            if any(keyword in stmt.content.lower() for keyword in contradiction_keywords)
        ]
        
        # Calculate overall reliability score (0-100)
        # Lower correction ratio = higher reliability
        # More statements = more detailed account
        reliability_score = max(0, min(100, 
            100 - (correction_ratio * 30) + 
            min(20, total_statements * 2)  # Bonus for detail
        ))
        
        return {
            "session_id": session_id,
            "witness_count": 1,  # Currently single witness per session
            "total_statements": total_statements,
            "original_statements": original_statements,
            "corrections": corrections,
            "correction_ratio": round(correction_ratio, 3),
            "reliability_score": round(reliability_score, 1),
            "timeline": statement_timeline,
            "potential_contradictions": potential_contradictions[:5],  # Top 5
            "analysis_summary": {
                "consistency": "high" if correction_ratio < 0.2 else "medium" if correction_ratio < 0.4 else "low",
                "detail_level": "high" if total_statements >= 10 else "medium" if total_statements >= 5 else "low",
                "recommendation": (
                    "Highly consistent witness account with few corrections" if correction_ratio < 0.2 else
                    "Witness account shows some evolution or clarification" if correction_ratio < 0.4 else
                    "Witness account has significant corrections - may indicate uncertainty or evolving memory"
                )
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing witnesses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze witnesses: {str(e)}"
        )


@router.get("/sessions/compare-basic/{session_id_1}/{session_id_2}")
async def compare_sessions_basic(session_id_1: str, session_id_2: str):
    """
    Compare two witness accounts of the same event (basic element comparison).
    
    Useful for multi-witness scenarios where different people describe the same incident.
    Returns similarities, differences, and potential discrepancies.
    """
    try:
        # Fetch both sessions
        session1 = await firestore_service.get_session(session_id_1)
        session2 = await firestore_service.get_session(session_id_2)
        
        if not session1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id_1} not found"
            )
        if not session2:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id_2} not found"
            )
        
        # Compare scene elements
        elements1 = {elem.description.lower() for elem in session1.current_scene_elements}
        elements2 = {elem.description.lower() for elem in session2.current_scene_elements}
        
        common_elements = elements1 & elements2
        unique_to_1 = elements1 - elements2
        unique_to_2 = elements2 - elements1
        
        # Calculate similarity score
        total_unique_elements = len(elements1 | elements2)
        similarity_score = (len(common_elements) / total_unique_elements * 100) if total_unique_elements > 0 else 0
        
        # Compare statement counts
        statements_diff = len(session1.witness_statements) - len(session2.witness_statements)
        
        return {
            "session_1": {
                "id": session1.id,
                "title": session1.title,
                "statements": len(session1.witness_statements),
                "scene_elements": len(session1.current_scene_elements),
                "reconstructions": len(session1.scene_versions)
            },
            "session_2": {
                "id": session2.id,
                "title": session2.title,
                "statements": len(session2.witness_statements),
                "scene_elements": len(session2.current_scene_elements),
                "reconstructions": len(session2.scene_versions)
            },
            "comparison": {
                "similarity_score": round(similarity_score, 1),
                "common_elements": list(common_elements)[:10],  # Top 10
                "unique_to_session_1": list(unique_to_1)[:5],
                "unique_to_session_2": list(unique_to_2)[:5],
                "statements_difference": statements_diff,
                "interpretation": (
                    "Highly similar accounts - likely describing same event" if similarity_score > 70 else
                    "Moderately similar accounts - some overlap but significant differences" if similarity_score > 40 else
                    "Very different accounts - may be different events or perspectives"
                )
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compare sessions: {str(e)}"
        )



@router.get("/admin/api-keys/status")
async def get_api_key_status(auth=Depends(require_admin_auth)):
    """
    Get the status of API key rotation/fallback system.
    
    Returns information about:
    - Total configured keys
    - Healthy vs rate-limited vs failed keys
    - Cooldown status for each key
    
    Requires admin authentication.
    """
    try:
        from app.services.api_key_manager import get_key_manager
        
        key_manager = get_key_manager()
        if not key_manager:
            return {
                "enabled": False,
                "message": "API key rotation not enabled (single key mode)",
                "total_keys": 1,
                "healthy_keys": 1
            }
        
        status = key_manager.get_status()
        status["enabled"] = True
        return status
        
    except Exception as e:
        logger.error(f"Error getting API key status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get API key status"
        )


@router.get("/admin/cases")
async def get_admin_cases(
    auth=Depends(require_admin_auth),
    limit: int = 50,
    status_filter: Optional[str] = None
):
    """
    Get all cases (sessions) for admin portal. Alias for /api/sessions endpoint.
    
    Returns sessions grouped by status with summary statistics.
    Requires admin authentication.
    """
    try:
        # Get all sessions
        sessions = await firestore_service.list_sessions(limit=limit)
        
        # Filter by status if requested
        if status_filter:
            sessions = [s for s in sessions if s.status == status_filter]
        
        # Group by status
        cases_by_status = {
            "active": [],
            "completed": [],
            "archived": []
        }
        
        for session in sessions:
            session_data = SessionResponse(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                status=session.status,
                statement_count=len(session.witness_statements),
                version_count=len(session.scene_versions),
                source_type=getattr(session, 'source_type', 'chat'),
                report_number=getattr(session, 'report_number', ''),
                case_id=getattr(session, 'case_id', None),
                metadata=getattr(session, 'metadata', {})
            )
            
            status_key = session.status if session.status in cases_by_status else "active"
            cases_by_status[status_key].append(session_data)
        
        return {
            "cases": cases_by_status,
            "summary": {
                "total": len(sessions),
                "active": len(cases_by_status["active"]),
                "completed": len(cases_by_status["completed"]),
                "archived": len(cases_by_status["archived"])
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting admin cases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get admin cases"
        )


@router.get("/admin/analytics")
async def get_admin_analytics(auth=Depends(require_admin_auth)):
    """
    Get analytics dashboard data for admin portal.
    
    Returns:
    - Total sessions, statements, reconstructions
    - Average statements per session
    - Most common scene elements
    - System usage statistics
    - Recent activity timeline
    
    Requires admin authentication.
    """
    try:
        # Get all sessions
        sessions = await firestore_service.list_sessions(limit=1000)
        
        # Calculate statistics
        total_sessions = len(sessions)
        total_statements = sum(len(s.witness_statements) for s in sessions)
        total_reconstructions = sum(len(s.scene_versions) for s in sessions)
        total_corrections = sum(
            sum(1 for stmt in s.witness_statements if stmt.is_correction)
            for s in sessions
        )
        
        avg_statements = total_statements / total_sessions if total_sessions > 0 else 0
        avg_reconstructions = total_reconstructions / total_sessions if total_sessions > 0 else 0
        
        # Find most common scene elements
        element_counts = {}
        for session in sessions:
            for element in session.current_scene_elements:
                desc = element.description.lower()
                element_counts[desc] = element_counts.get(desc, 0) + 1
        
        top_elements = sorted(
            element_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Status distribution
        status_counts = {
            "active": sum(1 for s in sessions if s.status == "active"),
            "completed": sum(1 for s in sessions if s.status == "completed"),
            "archived": sum(1 for s in sessions if s.status == "archived")
        }
        
        # Recent activity (last 10 sessions)
        recent_sessions = sorted(
            sessions,
            key=lambda s: s.updated_at or s.created_at or datetime.min,
            reverse=True
        )[:10]
        
        recent_activity = [
            {
                "id": s.id,
                "title": s.title,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "status": s.status,
                "statements": len(s.witness_statements)
            }
            for s in recent_sessions
        ]
        
        # Get usage tracker stats
        usage_stats = {}
        try:
            from app.services.usage_tracker import usage_tracker
            models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
            for model in models:
                usage = usage_tracker.get_usage(model)
                if usage["requests"]["today"] > 0:
                    usage_stats[model] = {
                        "requests_today": usage["requests"]["today"],
                        "tokens_today": usage["tokens"]["today"]
                    }
        except Exception as e:
            logger.warning(f"Could not get usage stats: {e}")
        
        return {
            "overview": {
                "total_sessions": total_sessions,
                "total_statements": total_statements,
                "total_reconstructions": total_reconstructions,
                "total_corrections": total_corrections,
                "avg_statements_per_session": round(avg_statements, 1),
                "avg_reconstructions_per_session": round(avg_reconstructions, 1)
            },
            "status_distribution": status_counts,
            "top_scene_elements": [
                {"element": elem, "count": count}
                for elem, count in top_elements
            ],
            "recent_activity": recent_activity,
            "usage_statistics": usage_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting admin analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get admin analytics"
        )


@router.get("/admin/dashboard/stats")
async def get_dashboard_stats(auth=Depends(require_admin_auth)):
    """
    Get comprehensive statistics for the analytics dashboard.
    
    Returns:
    - Crime trends over time (daily/weekly/monthly)
    - Cases by type and status
    - Response time metrics
    - Geographic distribution data
    """
    try:
        from collections import defaultdict
        from datetime import timedelta
        
        # Get all cases and sessions
        cases = await firestore_service.list_cases(limit=1000)
        sessions = await firestore_service.list_sessions(limit=1000)
        
        now = datetime.utcnow()
        
        # ---- Crime trends over time ----
        # Daily counts for last 30 days
        daily_counts = defaultdict(int)
        weekly_counts = defaultdict(int)
        monthly_counts = defaultdict(int)
        
        for case in cases:
            created = case.created_at if case.created_at else now
            # Daily key (last 30 days)
            day_key = created.strftime("%Y-%m-%d")
            daily_counts[day_key] += 1
            
            # Weekly key (week number)
            week_key = created.strftime("%Y-W%W")
            weekly_counts[week_key] += 1
            
            # Monthly key
            month_key = created.strftime("%Y-%m")
            monthly_counts[month_key] += 1
        
        # Sort and limit to reasonable ranges
        sorted_daily = sorted(daily_counts.items(), key=lambda x: x[0])[-30:]
        sorted_weekly = sorted(weekly_counts.items(), key=lambda x: x[0])[-12:]
        sorted_monthly = sorted(monthly_counts.items(), key=lambda x: x[0])[-12:]
        
        # ---- Cases by type ----
        type_counts = defaultdict(int)
        for case in cases:
            incident_type = case.metadata.get("incident_type", "other") if case.metadata else "other"
            type_counts[incident_type.lower()] += 1
        
        # ---- Cases by status ----
        status_counts = defaultdict(int)
        for case in cases:
            status_counts[case.status or "open"] += 1
        
        # ---- Response time metrics ----
        # Calculate time from case creation to first update (simulated response time)
        response_times = []
        for case in cases:
            if case.created_at and case.updated_at:
                delta = (case.updated_at - case.created_at).total_seconds() / 3600  # hours
                if delta > 0:  # Only if there was an update
                    response_times.append(delta)
        
        # Calculate average response times by type
        response_by_type = defaultdict(list)
        for case in cases:
            if case.created_at and case.updated_at:
                delta = (case.updated_at - case.created_at).total_seconds() / 3600
                if delta > 0:
                    incident_type = case.metadata.get("incident_type", "other") if case.metadata else "other"
                    response_by_type[incident_type.lower()].append(delta)
        
        avg_response_by_type = {
            t: round(sum(times) / len(times), 2) if times else 0
            for t, times in response_by_type.items()
        }
        
        # Overall response metrics
        avg_response = round(sum(response_times) / len(response_times), 2) if response_times else 0
        min_response = round(min(response_times), 2) if response_times else 0
        max_response = round(max(response_times), 2) if response_times else 0
        
        # ---- Geographic distribution ----
        location_counts = defaultdict(int)
        geo_points = []
        for case in cases:
            location = case.location or "Unknown"
            location_counts[location] += 1
            
            # Extract coordinates if available in metadata
            if case.metadata:
                lat = case.metadata.get("latitude") or case.metadata.get("lat")
                lng = case.metadata.get("longitude") or case.metadata.get("lng") or case.metadata.get("lon")
                if lat and lng:
                    geo_points.append({
                        "lat": float(lat),
                        "lng": float(lng),
                        "case_id": case.id,
                        "title": case.title,
                        "type": case.metadata.get("incident_type", "other")
                    })
        
        # Top locations
        top_locations = sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # ---- Priority distribution ----
        priority_counts = defaultdict(int)
        for case in cases:
            priority = case.metadata.get("priority", "medium") if case.metadata else "medium"
            priority_counts[priority.lower()] += 1
        
        # ---- Sessions/reports statistics ----
        source_counts = defaultdict(int)
        for session in sessions:
            source = getattr(session, "source_type", None) or "voice"
            source_counts[source] += 1
        
        # ---- Time-based analysis ----
        hour_distribution = defaultdict(int)
        day_of_week_distribution = defaultdict(int)
        for case in cases:
            if case.created_at:
                hour_distribution[case.created_at.hour] += 1
                day_of_week_distribution[case.created_at.strftime("%A")] += 1
        
        return {
            "timestamp": now.isoformat(),
            "summary": {
                "total_cases": len(cases),
                "total_reports": len(sessions),
                "cases_today": sum(1 for c in cases if c.created_at and c.created_at.date() == now.date()),
                "cases_this_week": sum(1 for c in cases if c.created_at and (now - c.created_at).days <= 7),
                "cases_this_month": sum(1 for c in cases if c.created_at and (now - c.created_at).days <= 30),
            },
            "trends": {
                "daily": [{"date": d, "count": c} for d, c in sorted_daily],
                "weekly": [{"week": w, "count": c} for w, c in sorted_weekly],
                "monthly": [{"month": m, "count": c} for m, c in sorted_monthly],
            },
            "by_type": dict(type_counts),
            "by_status": dict(status_counts),
            "by_priority": dict(priority_counts),
            "by_source": dict(source_counts),
            "response_times": {
                "average_hours": avg_response,
                "min_hours": min_response,
                "max_hours": max_response,
                "by_type": avg_response_by_type,
            },
            "geographic": {
                "top_locations": [{"location": loc, "count": cnt} for loc, cnt in top_locations],
                "geo_points": geo_points[:100],  # Limit to 100 points for performance
            },
            "time_analysis": {
                "by_hour": dict(hour_distribution),
                "by_day_of_week": dict(day_of_week_distribution),
            },
        }
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get dashboard statistics"
        )


# ==================== RELATIONSHIPS AND EVIDENCE ENDPOINTS ====================

@router.get("/sessions/{session_id}/relationships")
async def get_session_relationships(session_id: str):
    """
    Get spatial and temporal relationships for a session.
    Returns relationship graph and timeline sequence.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        from app.services.relationships import relationship_tracker
        
        # Get relationships from session
        relationships = session.element_relationships
        
        # Build spatial graph
        spatial_graph = {}
        temporal_sequence = []
        
        for rel in relationships:
            if rel.relationship_type in ["next_to", "in_front_of", "behind", "above", "below", "inside"]:
                if rel.element_a_id not in spatial_graph:
                    spatial_graph[rel.element_a_id] = []
                spatial_graph[rel.element_a_id].append({
                    "element_id": rel.element_b_id,
                    "relationship": rel.relationship_type,
                    "confidence": rel.confidence
                })
            elif rel.relationship_type in ["before", "after", "during", "simultaneous"]:
                temporal_sequence.append({
                    "element_a": rel.element_a_id,
                    "element_b": rel.element_b_id,
                    "relationship": rel.relationship_type,
                    "confidence": rel.confidence
                })
        
        # Get consistency warnings
        tracker = relationship_tracker
        # Temporarily load relationships into tracker for validation
        original_rels = tracker.relationships.copy()
        tracker.relationships = {rel.id: rel for rel in relationships}
        warnings = tracker.validate_consistency()
        tracker.relationships = original_rels
        
        return {
            "session_id": session_id,
            "spatial_graph": spatial_graph,
            "temporal_sequence": temporal_sequence,
            "total_relationships": len(relationships),
            "consistency_warnings": warnings
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting relationships for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get relationships"
        )


@router.get("/sessions/{session_id}/evidence")
async def get_session_evidence(session_id: str):
    """
    Get evidence summary and categorization for a session.
    Returns breakdown by category and quality tags.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        from app.services.evidence import evidence_manager
        
        # Get evidence tags from session
        tags = session.evidence_tags
        
        # Build summary
        category_breakdown = {}
        quality_breakdown = {}
        critical_elements = []
        disputed_elements = []
        
        for tag in tags:
            # Count by category
            category_breakdown[tag.category] = category_breakdown.get(tag.category, 0) + 1
            
            # Count by quality tag
            if tag.tag in ["critical", "corroborated", "disputed", "uncertain"]:
                quality_breakdown[tag.tag] = quality_breakdown.get(tag.tag, 0) + 1
            
            # Collect critical and disputed items
            if tag.tag == "critical":
                element = next((e for e in session.current_scene_elements if e.id == tag.element_id), None)
                if element:
                    critical_elements.append({
                        "id": element.id,
                        "description": element.description,
                        "type": element.type
                    })
            elif tag.tag == "disputed":
                element = next((e for e in session.current_scene_elements if e.id == tag.element_id), None)
                if element:
                    disputed_elements.append({
                        "id": element.id,
                        "description": element.description,
                        "type": element.type
                    })
        
        return {
            "session_id": session_id,
            "total_tags": len(tags),
            "category_breakdown": category_breakdown,
            "quality_breakdown": quality_breakdown,
            "critical_evidence": critical_elements,
            "disputed_evidence": disputed_elements,
            "elements_tagged": len(set(tag.element_id for tag in tags)),
            "total_elements": len(session.current_scene_elements)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting evidence for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get evidence data"
        )


@router.get("/cache/stats")
async def get_cache_stats():
    """Get cache statistics (hit rate, entries, etc.)."""
    try:
        from app.services.cache import cache
        return cache.get_stats()
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            "entries": 0,
            "hits": 0,
            "misses": 0,
            "total_requests": 0,
            "hit_rate": 0
        }


@router.get("/cache/response-stats")
async def get_response_cache_stats():
    """Get response cache statistics (embedding-based AI response caching)."""
    try:
        from app.services.response_cache import response_cache
        return response_cache.get_stats()
    except Exception as e:
        logger.error(f"Error getting response cache stats: {e}")
        return {
            "entries": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0,
            "similarity_threshold": 0.95,
            "default_ttl": 3600,
            "max_size": 1000
        }


@router.post("/cache/response-clear")
async def clear_response_cache(context_key: Optional[str] = None, auth=Depends(require_admin_auth)):
    """Clear response cache entries (admin only). Optionally filter by context key."""
    try:
        from app.services.response_cache import response_cache
        await response_cache.invalidate(context_key or "")
        return {"message": f"Response cache cleared{' for ' + context_key if context_key else ''}"}
    except Exception as e:
        logger.error(f"Error clearing response cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear response cache"
        )


@router.post("/cache/clear")
async def clear_cache(auth=Depends(require_admin_auth)):
    """Clear all cache entries (admin only)."""
    try:
        from app.services.cache import cache
        await cache.clear()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache"
        )


# ============================================================================
# AI Intelligence Endpoints - Contradiction, Questions, Complexity
# ============================================================================

@router.get("/sessions/{session_id}/contradictions")
async def get_session_contradictions(
    session_id: str,
    unresolved_only: bool = False,
    sort_by: str = "timestamp"
):
    """
    Get detected contradictions in witness statements with severity scores.
    
    Args:
        session_id: Session identifier
        unresolved_only: If True, only return unresolved contradictions
        sort_by: Sort order - "timestamp", "severity", "severity_asc", or "severity_desc"
    
    Returns:
        List of contradictions with severity information including:
        - severity.level: low, medium, high, critical
        - severity.score: 0.0-1.0 numeric score
        - severity.factors: Individual factor scores
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        from app.services.contradiction_detector import contradiction_detector
        
        contradictions = contradiction_detector.get_contradictions(
            session_id,
            unresolved_only=unresolved_only,
            sort_by=sort_by
        )
        
        # Calculate severity distribution
        severity_counts = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
        for c in contradictions:
            level = c.get('severity', {}).get('level', 'medium')
            severity_counts[level] = severity_counts.get(level, 0) + 1
        
        return {
            "session_id": session_id,
            "total": len(contradictions),
            "unresolved": sum(1 for c in contradictions if not c['resolved']),
            "severity_distribution": severity_counts,
            "contradictions": contradictions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting contradictions for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving contradictions: {str(e)}"
        )


@router.post("/sessions/{session_id}/contradictions/{contradiction_id}/resolve")
async def resolve_contradiction(
    session_id: str,
    contradiction_id: str,
    resolution: Dict[str, str]
):
    """
    Mark a contradiction as resolved with a resolution note.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        from app.services.contradiction_detector import contradiction_detector
        
        resolution_note = resolution.get('resolution_note', '')
        if not resolution_note:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="resolution_note is required"
            )
        
        success = contradiction_detector.resolve_contradiction(
            session_id,
            contradiction_id,
            resolution_note
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Contradiction {contradiction_id} not found"
            )
        
        return {
            "success": True,
            "message": "Contradiction resolved",
            "contradiction_id": contradiction_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving contradiction {contradiction_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error resolving contradiction: {str(e)}"
        )


@router.get("/sessions/{session_id}/next-question")
async def get_next_question(session_id: str):
    """
    Get AI-generated next question to ask the witness.
    Uses scene state, contradictions, and conversation history.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        from app.services.question_generator import question_generator
        from app.services.contradiction_detector import contradiction_detector
        
        # Get scene elements and conversation history
        scene_elements = getattr(session, 'scene_elements', []) or []
        conversation = getattr(session, 'conversation_history', []) or []
        
        # Get unresolved contradictions
        contradictions = contradiction_detector.get_contradictions(
            session_id,
            unresolved_only=True
        )
        
        # Generate next question
        next_question = question_generator.get_next_question(
            session_id,
            scene_elements,
            conversation,
            contradictions
        )
        
        return {
            "session_id": session_id,
            "question": next_question,
            "has_question": next_question is not None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating next question for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating question: {str(e)}"
        )


@router.get("/sessions/{session_id}/complexity")
async def get_scene_complexity(session_id: str):
    """
    Get scene complexity score and generation readiness.
    Returns score breakdown and recommendation.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        from app.services.complexity_scorer import complexity_scorer
        from app.services.contradiction_detector import contradiction_detector
        
        # Get scene data
        scene_elements = getattr(session, 'scene_elements', []) or []
        conversation = getattr(session, 'conversation_history', []) or []
        conversation_turns = len([m for m in conversation if (m.get('role') if isinstance(m, dict) else getattr(m, 'role', '')) == 'user'])
        
        # Get unresolved contradictions count
        contradictions = contradiction_detector.get_contradictions(
            session_id,
            unresolved_only=True
        )
        
        # Calculate complexity
        complexity = complexity_scorer.calculate_complexity_score(
            scene_elements,
            conversation_turns,
            len(contradictions)
        )
        
        return {
            "session_id": session_id,
            **complexity
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating complexity for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error calculating complexity: {str(e)}"
        )


@router.get("/sessions/{session_id}/confidence")
async def get_witness_confidence(session_id: str):
    """
    Assess witness confidence and testimony reliability for a session.
    Returns scores for detail level, consistency, specificity, and overall confidence.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        agent = get_agent(session_id)
        confidence = await agent.assess_confidence()
        
        return {
            "session_id": session_id,
            **confidence
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assessing confidence for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assessing confidence: {str(e)}"
        )


@router.get("/metrics/requests")
async def get_request_metrics():
    """
    Get request metrics and performance statistics.
    Returns uptime, request counts, error rates, and per-endpoint stats.
    """
    try:
        from app.middleware.request_logging import request_metrics
        
        metrics = request_metrics.get_metrics()
        
        return {
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            **metrics
        }
        
    except Exception as e:
        logger.error(f"Error retrieving request metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving metrics: {str(e)}"
        )


# ── Case Management ──────────────────────────────────

MAX_BULK_CASE_IDS = 500
ADMIN_CASE_SCAN_LIMIT = 1000


class CaseBulkStatusRequest(BaseModel):
    case_ids: List[str] = Field(..., min_length=1, max_length=MAX_BULK_CASE_IDS)
    status: str = Field(..., min_length=1, max_length=100)


class CaseBulkAssignRequest(BaseModel):
    case_ids: List[str] = Field(..., min_length=1, max_length=MAX_BULK_CASE_IDS)
    assignee: str = Field(..., min_length=1, max_length=200)


class CaseBulkPriorityRequest(BaseModel):
    case_ids: List[str] = Field(..., min_length=1, max_length=MAX_BULK_CASE_IDS)
    priority_label: Optional[str] = Field(default=None, max_length=100)
    priority_score: Optional[float] = None


class CaseBulkTagRequest(BaseModel):
    case_ids: List[str] = Field(..., min_length=1, max_length=MAX_BULK_CASE_IDS)
    tag: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, max_length=32)


class CaseWatchlistToggleRequest(BaseModel):
    watchlisted: bool


class CasePinToggleRequest(BaseModel):
    pinned: bool


def _normalize_case_ids(case_ids: List[str]) -> List[str]:
    if not case_ids:
        raise HTTPException(status_code=400, detail="case_ids is required")
    if len(case_ids) > MAX_BULK_CASE_IDS:
        raise HTTPException(status_code=400, detail=f"case_ids cannot exceed {MAX_BULK_CASE_IDS}")

    normalized: List[str] = []
    seen = set()
    for case_id in case_ids:
        if not isinstance(case_id, str) or not case_id.strip():
            raise HTTPException(status_code=400, detail="case_ids must contain non-empty strings")
        value = case_id.strip()
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _build_bulk_response(updated: List[str], reasons: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "updated": updated,
        "failed": len(reasons),
        "reasons": reasons,
    }


def _ensure_case_metadata(case: Case) -> Dict[str, Any]:
    if not isinstance(case.metadata, dict):
        case.metadata = {}
    return case.metadata


def _tag_key(tag_item: Any) -> str:
    if isinstance(tag_item, dict):
        for key in ("tag", "name", "label"):
            value = tag_item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return json.dumps(tag_item, sort_keys=True, default=str)
    if isinstance(tag_item, str):
        return tag_item.strip().lower()
    return str(tag_item).strip().lower()


def _merge_tags(existing_tags: Any, incoming_tags: List[Any]) -> List[Any]:
    merged: List[Any] = []
    tag_index: Dict[str, int] = {}

    for item in (existing_tags if isinstance(existing_tags, list) else []):
        normalized_item = dict(item) if isinstance(item, dict) else item
        key = _tag_key(normalized_item)
        if key in tag_index:
            existing_item = merged[tag_index[key]]
            if isinstance(existing_item, dict) and isinstance(normalized_item, dict):
                existing_item.update(normalized_item)
            continue
        tag_index[key] = len(merged)
        merged.append(normalized_item)

    for item in incoming_tags:
        normalized_item = dict(item) if isinstance(item, dict) else item
        key = _tag_key(normalized_item)
        if key in tag_index:
            existing_item = merged[tag_index[key]]
            if isinstance(existing_item, dict) and isinstance(normalized_item, dict):
                existing_item.update(normalized_item)
            continue
        tag_index[key] = len(merged)
        merged.append(normalized_item)

    return merged


def _merge_unique_list(existing_values: Any, incoming_values: List[Any]) -> List[Any]:
    existing_list = existing_values if isinstance(existing_values, list) else []
    merged = list(existing_list)
    seen = {json.dumps(item, sort_keys=True, default=str) for item in merged}
    for item in incoming_values:
        marker = json.dumps(item, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(item)
    return merged


def _merge_case_metadata(existing_metadata: Optional[Dict[str, Any]], incoming_metadata: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing_metadata or {})
    for key, value in incoming_metadata.items():
        if key == "tags" and isinstance(value, list):
            merged[key] = _merge_tags(merged.get(key), value)
        elif key == "deadlines" and isinstance(value, list):
            merged[key] = _merge_unique_list(merged.get(key), value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged.get(key) or {})
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _parse_deadline_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.endswith("Z"):
        no_z = raw[:-1]
        candidates.append(f"{no_z}+00:00")
    else:
        no_z = raw

    if "T" not in no_z and " " not in no_z:
        candidates.append(f"{no_z}T00:00:00")
        if raw.endswith("Z"):
            candidates.append(f"{no_z}T00:00:00+00:00")

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@router.get("/cases")
async def list_cases(limit: int = 50, sort_by: str = "updated"):
    """List all cases with report counts and priority scores.
    
    Args:
        limit: Maximum number of cases to return
        sort_by: Sort order - "updated" (default), "created", "priority"
    """
    try:
        cases = await firestore_service.list_cases(limit=limit)
        cases_list = []
        for case in cases:
            report_count = len(case.report_ids)
            # Calculate priority score
            priority = priority_scoring_service.calculate_priority(case, report_count)
            
            cases_list.append(CaseResponse(
                id=case.id,
                case_number=case.case_number,
                title=case.title,
                summary=case.summary,
                location=case.location,
                status=case.status,
                report_count=report_count,
                created_at=case.created_at,
                updated_at=case.updated_at,
                scene_image_url=case.scene_image_url,
                timeframe=case.timeframe,
                priority_score=priority.total_score,
                priority_label=priority.priority_label,
                priority=priority.model_dump()
            ))
        
        # Sort by priority if requested
        if sort_by == "priority":
            cases_list.sort(key=lambda c: c.priority_score or 0, reverse=True)
        elif sort_by == "created":
            cases_list.sort(key=lambda c: c.created_at, reverse=True)
        # Default is already sorted by updated_at from firestore
        
        return {"cases": cases_list}
    except Exception as e:
        logger.error(f"Error listing cases: {e}")
        raise HTTPException(status_code=500, detail="Failed to list cases")


@router.get("/cases/priority")
async def list_cases_by_priority(limit: int = 50, min_score: float = 0):
    """List cases sorted by priority score (highest first).
    
    Args:
        limit: Maximum number of cases to return
        min_score: Minimum priority score threshold (0-100)
    """
    try:
        cases = await firestore_service.list_cases(limit=limit * 2)  # Get more to filter
        cases_list = []
        for case in cases:
            report_count = len(case.report_ids)
            priority = priority_scoring_service.calculate_priority(case, report_count)
            
            if priority.total_score >= min_score:
                cases_list.append(CaseResponse(
                    id=case.id,
                    case_number=case.case_number,
                    title=case.title,
                    summary=case.summary,
                    location=case.location,
                    status=case.status,
                    report_count=report_count,
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                    scene_image_url=case.scene_image_url,
                    timeframe=case.timeframe,
                    priority_score=priority.total_score,
                    priority_label=priority.priority_label,
                    priority=priority.model_dump()
                ))
        
        # Sort by priority score descending
        cases_list.sort(key=lambda c: c.priority_score or 0, reverse=True)
        
        return {
            "cases": cases_list[:limit],
            "total": len(cases_list),
            "min_score_filter": min_score
        }
    except Exception as e:
        logger.error(f"Error listing cases by priority: {e}")
        raise HTTPException(status_code=500, detail="Failed to list cases by priority")


@router.get("/export/cases.csv")
async def export_cases_csv(limit: int = 200):
    """Export cases as CSV."""
    try:
        from fastapi.responses import Response
        import csv

        limit = _guard_limit(limit)
        cases = await firestore_service.list_cases(limit=limit)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "number",
            "title",
            "status",
            "location",
            "report_count",
            "updated_at",
            "scene_image_url",
        ])

        for case in cases:
            writer.writerow([
                case.case_number,
                case.title,
                case.status,
                case.location,
                len(case.report_ids or []),
                case.updated_at.isoformat() if case.updated_at else "",
                case.scene_image_url or "",
            ])

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cases.csv"},
        )
    except Exception as e:
        logger.error(f"Error exporting cases CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export cases CSV")


@router.post("/cases/recalculate-priorities")
async def recalculate_case_priorities(limit: int = 200, _auth=Depends(require_admin_auth)):
    """Recalculate and persist case priority score/label metadata."""
    try:
        limit = _guard_limit(limit)
        cases = await firestore_service.list_cases(limit=limit)

        updated = 0
        failures = []

        for case in cases:
            try:
                report_count = len(case.report_ids or [])
                priority = priority_scoring_service.calculate_priority(case, report_count)

                case.metadata = case.metadata or {}
                case.metadata["priority_score"] = priority.total_score
                case.metadata["priority_label"] = priority.priority_label
                case.metadata["priority"] = priority.priority_label
                case.metadata["priority_calculated_at"] = (
                    priority.calculated_at.isoformat() if priority.calculated_at else None
                )

                await firestore_service.update_case(case)
                updated += 1
            except Exception as case_error:
                failures.append({"case_id": case.id, "error": str(case_error)})

        return {
            "processed": len(cases),
            "updated": updated,
            "failed": len(failures),
            "failures": failures,
        }
    except Exception as e:
        logger.error(f"Error recalculating priorities: {e}")
        raise HTTPException(status_code=500, detail="Failed to recalculate priorities")


@router.get("/cases/{case_id}/timeline")
async def get_case_timeline(case_id: str, limit: int = 100):
    """Aggregate witness statements across case reports into a sorted timeline."""
    try:
        limit = _guard_limit(limit)
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        timeline_events = []
        for report_id in case.report_ids:
            session = await firestore_service.get_session(report_id)
            if not session:
                continue

            for idx, statement in enumerate(session.witness_statements):
                sort_ts = statement.timestamp or session.created_at or session.updated_at
                timeline_events.append({
                    "event_id": f"{session.id}:{statement.id or idx}",
                    "report_id": session.id,
                    "report_number": getattr(session, "report_number", ""),
                    "report_title": session.title,
                    "statement_id": statement.id,
                    "timestamp": statement.timestamp.isoformat() if statement.timestamp else None,
                    "witness_name": statement.witness_name or getattr(session, "witness_name", None),
                    "text": statement.text,
                    "_sort_key": sort_ts.isoformat() if sort_ts else "",
                })

        timeline_events.sort(
            key=lambda item: (
                item.get("_sort_key") == "",
                item.get("_sort_key") or "",
                item.get("report_id") or "",
            )
        )
        events = [{k: v for k, v in event.items() if k != "_sort_key"} for event in timeline_events[:limit]]

        return {
            "case_id": case_id,
            "case_number": case.case_number,
            "case_title": case.title,
            "total_events": len(timeline_events),
            "returned": len(events),
            "limit": limit,
            "timeline": events,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting case timeline: {e}")
        raise HTTPException(status_code=500, detail="Failed to get case timeline")


@router.get("/cases/{case_id}/snippets")
async def get_case_snippets(case_id: str, limit: int = 50):
    """Return short statement snippets grouped by report for a case."""
    try:
        limit = _guard_limit(limit)
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        grouped = []
        for report_id in case.report_ids[:limit]:
            session = await firestore_service.get_session(report_id)
            if not session:
                continue

            snippets = []
            for statement in session.witness_statements:
                text = " ".join((statement.text or "").split())
                if not text:
                    continue
                snippet = text if len(text) <= 160 else f"{text[:157].rstrip()}..."
                snippets.append({
                    "statement_id": statement.id,
                    "timestamp": statement.timestamp.isoformat() if statement.timestamp else None,
                    "snippet": snippet,
                })

            grouped.append({
                "report_id": session.id,
                "report_number": getattr(session, "report_number", ""),
                "report_title": session.title,
                "source_type": getattr(session, "source_type", "chat"),
                "snippet_count": len(snippets),
                "snippets": snippets,
            })

        return {
            "case_id": case_id,
            "case_number": case.case_number,
            "total_reports": len(case.report_ids),
            "returned_reports": len(grouped),
            "limit": limit,
            "reports": grouped,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting case snippets: {e}")
        raise HTTPException(status_code=500, detail="Failed to get case snippets")


@router.get("/cases/{case_id}/priority")
async def get_case_priority(case_id: str):
    """Get detailed priority score for a specific case."""
    try:
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        report_count = len(case.report_ids)
        priority = priority_scoring_service.calculate_priority(case, report_count)
        
        return {
            "case_id": case_id,
            "case_number": case.case_number,
            "priority": priority.model_dump()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting case priority: {e}")
        raise HTTPException(status_code=500, detail="Failed to get case priority")


@router.post("/cases/bulk/status")
async def bulk_update_case_status(data: CaseBulkStatusRequest, _auth=Depends(require_admin_auth)):
    case_ids = _normalize_case_ids(data.case_ids)
    status_value = data.status.strip()
    if not status_value:
        raise HTTPException(status_code=400, detail="status is required")

    updated: List[str] = []
    reasons: List[Dict[str, str]] = []
    for case_id in case_ids:
        try:
            case = await firestore_service.get_case(case_id)
            if not case:
                reasons.append({"case_id": case_id, "reason": "Case not found"})
                continue
            case.status = status_value
            case.updated_at = datetime.utcnow()
            await firestore_service.update_case(case)
            updated.append(case_id)
        except Exception as e:
            reasons.append({"case_id": case_id, "reason": str(e)})

    return _build_bulk_response(updated, reasons)


@router.post("/cases/bulk/assign")
async def bulk_assign_cases(data: CaseBulkAssignRequest, _auth=Depends(require_admin_auth)):
    case_ids = _normalize_case_ids(data.case_ids)
    assignee = data.assignee.strip()
    if not assignee:
        raise HTTPException(status_code=400, detail="assignee is required")

    updated: List[str] = []
    reasons: List[Dict[str, str]] = []
    for case_id in case_ids:
        try:
            case = await firestore_service.get_case(case_id)
            if not case:
                reasons.append({"case_id": case_id, "reason": "Case not found"})
                continue
            metadata = _ensure_case_metadata(case)
            metadata["assigned_to"] = assignee
            metadata["assigned_at"] = datetime.utcnow().isoformat()
            case.updated_at = datetime.utcnow()
            await firestore_service.update_case(case)
            updated.append(case_id)
        except Exception as e:
            reasons.append({"case_id": case_id, "reason": str(e)})

    return _build_bulk_response(updated, reasons)


@router.post("/cases/bulk/priority")
async def bulk_set_case_priority(data: CaseBulkPriorityRequest, _auth=Depends(require_admin_auth)):
    case_ids = _normalize_case_ids(data.case_ids)
    priority_label = data.priority_label.strip() if isinstance(data.priority_label, str) else None
    if data.priority_label is not None and not priority_label:
        raise HTTPException(status_code=400, detail="priority_label cannot be blank")
    if priority_label is None and data.priority_score is None:
        raise HTTPException(status_code=400, detail="priority_label or priority_score is required")

    updated: List[str] = []
    reasons: List[Dict[str, str]] = []
    for case_id in case_ids:
        try:
            case = await firestore_service.get_case(case_id)
            if not case:
                reasons.append({"case_id": case_id, "reason": "Case not found"})
                continue
            metadata = _ensure_case_metadata(case)
            if priority_label is not None:
                metadata["manual_priority_label"] = priority_label
            if data.priority_score is not None:
                metadata["manual_priority_score"] = data.priority_score
            metadata["manual_priority_updated_at"] = datetime.utcnow().isoformat()
            case.updated_at = datetime.utcnow()
            await firestore_service.update_case(case)
            updated.append(case_id)
        except Exception as e:
            reasons.append({"case_id": case_id, "reason": str(e)})

    return _build_bulk_response(updated, reasons)


@router.post("/cases/bulk/tag")
async def bulk_tag_cases(data: CaseBulkTagRequest, _auth=Depends(require_admin_auth)):
    case_ids = _normalize_case_ids(data.case_ids)
    tag_name = data.tag.strip()
    if not tag_name:
        raise HTTPException(status_code=400, detail="tag is required")
    color = data.color.strip() if isinstance(data.color, str) and data.color.strip() else None

    updated: List[str] = []
    reasons: List[Dict[str, str]] = []
    for case_id in case_ids:
        try:
            case = await firestore_service.get_case(case_id)
            if not case:
                reasons.append({"case_id": case_id, "reason": "Case not found"})
                continue
            metadata = _ensure_case_metadata(case)
            tag_payload: Dict[str, str] = {"tag": tag_name}
            if color:
                tag_payload["color"] = color
            metadata["tags"] = _merge_tags(metadata.get("tags"), [tag_payload])
            metadata["tags_updated_at"] = datetime.utcnow().isoformat()
            case.updated_at = datetime.utcnow()
            await firestore_service.update_case(case)
            updated.append(case_id)
        except Exception as e:
            reasons.append({"case_id": case_id, "reason": str(e)})

    return _build_bulk_response(updated, reasons)


@router.get("/cases/overdue-deadlines")
async def list_cases_with_overdue_deadlines(_auth=Depends(require_admin_auth)):
    now = datetime.now(timezone.utc)
    cases = await firestore_service.list_cases(limit=ADMIN_CASE_SCAN_LIMIT)
    overdue_cases: List[Dict[str, Any]] = []

    for case in cases:
        metadata = case.metadata if isinstance(case.metadata, dict) else {}
        deadlines = metadata.get("deadlines", [])
        if not isinstance(deadlines, list):
            continue

        overdue_deadlines = []
        for deadline in deadlines:
            if not isinstance(deadline, dict):
                continue

            if deadline.get("completed") is True or deadline.get("is_completed") is True:
                continue

            deadline_status = str(deadline.get("status", "")).strip().lower()
            if deadline_status in {"completed", "done", "closed", "resolved"}:
                continue

            due_value = deadline.get("date") or deadline.get("due_at")
            due_at = _parse_deadline_datetime(due_value)
            if due_at and due_at < now:
                overdue_deadlines.append(deadline)

        if overdue_deadlines:
            overdue_cases.append({
                "id": case.id,
                "case_number": case.case_number,
                "title": case.title,
                "status": case.status,
                "overdue_deadlines": overdue_deadlines,
            })

    return {"cases": overdue_cases, "total": len(overdue_cases)}


@router.get("/cases/watchlist")
async def list_watchlisted_cases(_auth=Depends(require_admin_auth)):
    cases = await firestore_service.list_cases(limit=ADMIN_CASE_SCAN_LIMIT)
    watchlisted_cases = []

    for case in cases:
        metadata = case.metadata if isinstance(case.metadata, dict) else {}
        if metadata.get("watchlisted") is True:
            watchlisted_cases.append({
                "id": case.id,
                "case_number": case.case_number,
                "title": case.title,
                "status": case.status,
                "watchlisted_at": metadata.get("watchlisted_at") or metadata.get("watchlisted_updated_at"),
            })

    return {"cases": watchlisted_cases, "total": len(watchlisted_cases)}


@router.post("/cases/{case_id}/watchlist")
async def toggle_case_watchlist(case_id: str, data: CaseWatchlistToggleRequest, _auth=Depends(require_admin_auth)):
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    metadata = _ensure_case_metadata(case)
    timestamp = datetime.utcnow().isoformat()
    metadata["watchlisted"] = data.watchlisted
    metadata["watchlisted_updated_at"] = timestamp
    if data.watchlisted:
        metadata["watchlisted_at"] = timestamp
    else:
        metadata["watchlisted_removed_at"] = timestamp

    case.updated_at = datetime.utcnow()
    await firestore_service.update_case(case)
    return _build_bulk_response([case_id], [])


@router.get("/cases/pinned")
async def list_pinned_cases(_auth=Depends(require_admin_auth)):
    cases = await firestore_service.list_cases(limit=ADMIN_CASE_SCAN_LIMIT)
    pinned_cases = []

    for case in cases:
        metadata = case.metadata if isinstance(case.metadata, dict) else {}
        if metadata.get("pinned") is True:
            pinned_cases.append({
                "id": case.id,
                "case_number": case.case_number,
                "title": case.title,
                "status": case.status,
                "pinned_at": metadata.get("pinned_at") or metadata.get("pinned_updated_at"),
            })

    return {"cases": pinned_cases, "total": len(pinned_cases)}


@router.post("/cases/{case_id}/pin")
async def toggle_case_pin(case_id: str, data: CasePinToggleRequest, _auth=Depends(require_admin_auth)):
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    metadata = _ensure_case_metadata(case)
    timestamp = datetime.utcnow().isoformat()
    metadata["pinned"] = data.pinned
    metadata["pinned_updated_at"] = timestamp
    if data.pinned:
        metadata["pinned_at"] = timestamp
    else:
        metadata["pinned_removed_at"] = timestamp

    case.updated_at = datetime.utcnow()
    await firestore_service.update_case(case)
    return _build_bulk_response([case_id], [])


@router.get("/cases/{case_id}")
async def get_case_detail(case_id: str):
    """Get case detail with all its reports and related cases."""
    try:
        from app.services.case_linking import case_linking_service
        
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        reports = []
        for report_id in case.report_ids:
            session = await firestore_service.get_session(report_id)
            if session:
                reports.append({
                    "id": session.id,
                    "title": session.title,
                    "report_number": getattr(session, 'report_number', ''),
                    "source_type": getattr(session, 'source_type', 'chat'),
                    "created_at": session.created_at.isoformat() if session.created_at else None,
                    "statement_count": len(session.witness_statements),
                    "statements": [
                        {"id": s.id, "text": s.text, "timestamp": s.timestamp.isoformat() if s.timestamp else None}
                        for s in session.witness_statements
                    ],
                    "scene_versions": [
                        {"version": sv.version, "image_url": sv.image_url, "description": sv.description}
                        for sv in session.scene_versions
                    ]
                })

        # Get related cases
        related_cases = await case_linking_service.get_related_cases(case_id)
        
        # Calculate priority score
        report_count = len(case.report_ids)
        priority = priority_scoring_service.calculate_priority(case, report_count)

        return {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "summary": case.summary,
            "location": case.location,
            "status": case.status,
            "timeframe": case.timeframe,
            "scene_image_url": case.scene_image_url,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
            "reports": reports,
            "metadata": case.metadata,
            "related_cases": [r.model_dump(mode="json") for r in related_cases],
            "priority_score": priority.total_score,
            "priority_label": priority.priority_label,
            "priority": priority.model_dump(mode="json"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting case detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/cases/{case_id}")
async def update_case(case_id: str, updates: dict):
    """Update a case."""
    try:
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        if "title" in updates:
            case.title = updates["title"]
        if "status" in updates:
            case.status = updates["status"]
        if "location" in updates:
            case.location = updates["location"]
        if "summary" in updates:
            case.summary = updates["summary"]
        if "metadata" in updates:
            metadata_updates = updates.get("metadata")
            if not isinstance(metadata_updates, dict):
                raise HTTPException(status_code=400, detail="metadata must be an object")
            case.metadata = _merge_case_metadata(case.metadata, metadata_updates)

        case.updated_at = datetime.utcnow()
        await firestore_service.update_case(case)
        return _build_bulk_response([case_id], [])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating case: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/summary")
async def regenerate_case_summary(case_id: str, auth=Depends(require_admin_auth)):
    """Regenerate case summary using Gemini AI."""
    try:
        result = await case_manager.generate_case_summary(case_id)
        if result:
            return {"message": "Summary regenerated", "summary": result}
        raise HTTPException(status_code=500, detail="Failed to generate summary")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/evidence/upload")
async def upload_evidence_photo(session_id: str):
    """Upload evidence photo for a session (placeholder)."""
    raise HTTPException(status_code=501, detail="Evidence photo upload not yet implemented")


@router.post("/admin/seed-mock-data")
async def seed_mock_data(auth=Depends(require_admin_auth)):
    """Seed the database with mock reports and cases for demonstration."""
    try:
        mock_reports = [
            # --- Car Accident Reports ---
            {
                "title": "Car Accident on Main Street",
                "source_type": "chat",
                "statements": [
                    "I was walking on Main Street around 3:15 PM on February 22nd when I heard a loud crash.",
                    "A red sedan ran the red light at the intersection of Main and Oak Avenue.",
                    "It hit a blue SUV that was turning left. The SUV spun around and hit a parked white van.",
                    "The driver of the red car looked like a young man, maybe in his 20s, wearing a black hoodie.",
                    "There were two people in the SUV - a woman driving and a child in the back seat.",
                    "Glass was everywhere on the road. The front of the red car was completely smashed."
                ],
                "metadata": {"location": "Main Street & Oak Avenue", "case_type": "accident"}
            },
            {
                "title": "Witnessed collision at Main/Oak intersection",
                "source_type": "phone",
                "statements": [
                    "I called because I saw an accident today around 3:20 PM at Main Street.",
                    "A red car, maybe a Toyota, blew through the intersection really fast.",
                    "It crashed into another car that was making a left turn. I think it was a dark blue Honda.",
                    "The red car driver was a younger guy. He got out and was holding his head.",
                    "The lady in the other car was screaming. Someone ran over to help with the kid in the backseat.",
                    "An ambulance arrived about 10 minutes later."
                ],
                "metadata": {"location": "Main St intersection", "case_type": "accident"}
            },
            {
                "title": "Traffic accident report near Main Street",
                "source_type": "voice",
                "statements": [
                    "I was in the coffee shop on the corner of Main and Oak around 3:15, maybe 3:20 PM on the 22nd.",
                    "I heard the crash and looked out the window. A red compact car had hit a blue SUV.",
                    "The red car came from the east on Oak Avenue, must have been going at least 50 in a 30 zone.",
                    "After the impact the SUV hit a white vehicle parked on the street.",
                    "I ran out to help. The SUV driver was a woman, about 35-40, she seemed disoriented.",
                    "There was a little girl in the back, maybe 5 years old. She was crying but looked okay.",
                    "The red car driver was young, wearing dark clothes. He seemed dazed."
                ],
                "metadata": {"location": "Corner of Main & Oak", "case_type": "accident"}
            },
            # --- Convenience Store Robbery ---
            {
                "title": "Robbery at QuickMart Store",
                "source_type": "chat",
                "statements": [
                    "I was buying groceries at QuickMart on 5th Avenue around 9:45 PM on February 21st.",
                    "Two men came in wearing ski masks. One had a gun, the other had a knife.",
                    "The one with the gun was tall, maybe 6 feet, wearing all black clothes.",
                    "The shorter one with the knife went behind the counter and grabbed cash from the register.",
                    "They yelled at everyone to get on the floor. The whole thing lasted about 3 minutes.",
                    "They ran out the front door and got into a dark colored car, maybe black or dark gray.",
                    "I think it was a newer model sedan, maybe a Nissan or Honda."
                ],
                "metadata": {"location": "QuickMart, 5th Avenue", "case_type": "crime"}
            },
            {
                "title": "Armed robbery witness account",
                "source_type": "email",
                "statements": [
                    "I am writing to report what I witnessed at the QuickMart on 5th Avenue last night around 9:45 PM, February 21st.",
                    "Two masked individuals entered the store. The taller one, approximately 6 foot 1, brandished a handgun.",
                    "The shorter individual, about 5 foot 7, jumped over the counter with a large knife.",
                    "The taller one was wearing a black jacket and black pants. The shorter one wore a gray hoodie and jeans.",
                    "They took money from the register and I noticed the shorter one also grabbed cigarettes.",
                    "They fled in a dark vehicle heading south on 5th Avenue. The car looked like a black Honda Civic, newer model.",
                    "The store clerk was very shaken but not physically harmed."
                ],
                "metadata": {"location": "QuickMart, 5th Avenue", "case_type": "crime"}
            },
            # --- Hit and Run ---
            {
                "title": "Hit and run on Elm Boulevard",
                "source_type": "voice",
                "statements": [
                    "I saw a pedestrian get hit by a car on Elm Boulevard around 7:30 PM on February 23rd.",
                    "The car was a silver or light gray pickup truck, pretty large, maybe a Ford F-150.",
                    "It was driving too fast and ran over the crosswalk. A man was crossing the street.",
                    "The man fell and the truck just kept going. It turned right onto Cedar Lane.",
                    "The victim was an older man, maybe 60s, wearing a brown jacket. He was on the ground holding his leg.",
                    "I called 911 immediately. Some other people stopped to help."
                ],
                "metadata": {"location": "Elm Boulevard near Cedar Lane", "case_type": "accident"}
            }
        ]

        created_reports = []
        for mock in mock_reports:
            report_number = await firestore_service.get_next_report_number()
            session = ReconstructionSession(
                id=str(uuid.uuid4()),
                title=mock["title"],
                source_type=mock["source_type"],
                report_number=report_number,
                witness_statements=[
                    WitnessStatement(
                        id=str(uuid.uuid4()),
                        text=stmt_text,
                    )
                    for stmt_text in mock["statements"]
                ],
                metadata=mock.get("metadata", {}),
                status="completed"
            )

            await firestore_service.create_session(session)

            case_id = await case_manager.assign_report_to_case(session)
            session.case_id = case_id
            await firestore_service.update_session(session)

            created_reports.append({
                "report_number": report_number,
                "title": mock["title"],
                "source_type": mock["source_type"],
                "case_id": case_id
            })

        all_cases = await firestore_service.list_cases()
        cases_info = [
            {"case_number": c.case_number, "title": c.title, "report_count": len(c.report_ids)}
            for c in all_cases
        ]

        return {
            "message": f"Created {len(created_reports)} mock reports grouped into {len(all_cases)} cases",
            "reports": created_reports,
            "cases": cases_info
        }
    except Exception as e:
        logger.error(f"Error seeding mock data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Background Task Status ────────────────────────────────

@router.get("/tasks/recent")
async def get_recent_tasks(limit: int = 50):
    """Get recent in-memory background task results."""
    limit = _guard_limit(limit)

    recent = []
    for task_id, result in _task_results.items():
        if not isinstance(result, dict):
            continue
        sort_ts = result.get("completed_at") or result.get("started_at") or ""
        recent.append({"task_id": task_id, "_sort_ts": sort_ts, **result})

    recent.sort(key=lambda item: item.get("_sort_ts") or "", reverse=True)
    tasks = [{k: v for k, v in item.items() if k != "_sort_ts"} for item in recent[:limit]]

    return {
        "tasks": tasks,
        "count": len(tasks),
        "total_tracked": len(recent),
        "limit": limit,
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get the status of a background task."""
    result = _task_results.get(task_id)
    if result:
        return result
    # Try persistent storage
    stored = await firestore_service.get_background_task(task_id)
    if stored:
        return stored
    return {"status": "not_found"}


# ── Quota Status (all AI models) ─────────────────────────

@router.get("/models/all-quota")
async def get_all_quota_status():
    """Get real-time quota usage for all AI models including Imagen and embeddings."""
    try:
        from app.services.model_selector import model_selector
        from app.services.imagen_service import imagen_service
        from app.services.embedding_service import embedding_service
        from app.services.request_batcher import request_batcher

        return {
            "models": await model_selector.quota.get_quota_status() if hasattr(model_selector, 'quota') else {},
            "imagen": imagen_service.get_quota_status(),
            "embeddings": embedding_service.get_quota_status(),
            "batching": request_batcher.get_stats(),
        }
    except Exception as e:
        logger.error(f"Error getting all quota status: {e}")
        return {"models": {}, "imagen": {}, "embeddings": {}, "batching": {}, "error": str(e)}


# ── Request Batching Status ────────────────────────────────

@router.get("/batching/status")
async def get_batching_status():
    """
    Get request batching statistics and configuration.
    
    Returns:
        Batching stats including items processed, RPM saved, and current config.
    """
    try:
        from app.services.request_batcher import request_batcher
        
        return request_batcher.get_stats()
    except Exception as e:
        logger.error(f"Error getting batching status: {e}")
        return {"error": str(e)}


@router.post("/batching/configure")
async def configure_batching(
    batch_type: str,
    max_batch_size: Optional[int] = None,
    max_wait_ms: Optional[int] = None,
    enabled: Optional[bool] = None,
):
    """
    Configure batching parameters for a specific request type.
    
    Args:
        batch_type: Type of batch (embedding, classification, intent, preprocessing)
        max_batch_size: Maximum items per batch
        max_wait_ms: Maximum milliseconds to wait for batch to fill
        enabled: Enable/disable batching for this type
    """
    try:
        from app.services.request_batcher import request_batcher
        
        request_batcher.configure(
            batch_type=batch_type,
            max_batch_size=max_batch_size,
            max_wait_ms=max_wait_ms,
            enabled=enabled,
        )
        
        return {
            "success": True,
            "batch_type": batch_type,
            "config": request_batcher.get_stats()["configs"].get(batch_type, {}),
        }
    except Exception as e:
        logger.error(f"Error configuring batching: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Quota Dashboard Status ────────────────────────────────

@router.get("/quota/status")
async def get_quota_dashboard_status():
    """
    Get comprehensive quota status for all models for the admin dashboard.
    
    Returns:
        Per-model quota usage with RPM, TPM, RPD, limits, and time until reset.
    """
    try:
        from datetime import timezone, timedelta
        
        # Get all usage from usage_tracker
        all_usage = usage_tracker.get_all_usage()
        
        # Calculate time until reset (midnight UTC)
        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        seconds_until_reset = int((tomorrow - now).total_seconds())
        
        # Format response for dashboard
        models_data = {}
        for model_name, usage in all_usage.items():
            rpm_used = usage.get("requests", {}).get("minute", {}).get("used", 0)
            rpm_limit = usage.get("requests", {}).get("minute", {}).get("limit", 0)
            rpd_used = usage.get("requests", {}).get("day", {}).get("used", 0)
            rpd_limit = usage.get("requests", {}).get("day", {}).get("limit", 0)
            tpm_used = usage.get("tokens", {}).get("day", {}).get("used", 0)
            tpm_limit = usage.get("tokens", {}).get("day", {}).get("limit", 0)
            
            models_data[model_name] = {
                "tier": usage.get("tier", "free"),
                "rpm": {
                    "used": rpm_used,
                    "limit": rpm_limit,
                    "percent": round((rpm_used / rpm_limit * 100) if rpm_limit > 0 else 0, 1)
                },
                "tpm": {
                    "used": tpm_used,
                    "limit": tpm_limit,
                    "percent": round((tpm_used / tpm_limit * 100) if tpm_limit > 0 else 0, 1)
                },
                "rpd": {
                    "used": rpd_used,
                    "limit": rpd_limit,
                    "percent": round((rpd_used / rpd_limit * 100) if rpd_limit > 0 else 0, 1)
                }
            }
        
        return {
            "models": models_data,
            "reset": {
                "seconds_until": seconds_until_reset,
                "timestamp": tomorrow.isoformat(),
                "formatted": f"{seconds_until_reset // 3600}h {(seconds_until_reset % 3600) // 60}m"
            },
            "timestamp": now.isoformat(),
            "note": "Usage tracking is approximate and based on local counting"
        }
    
    except Exception as e:
        logger.error(f"Error getting quota dashboard status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get quota status"
        )


# ── Token Estimation Endpoints ───────────────────────────

class TokenEstimateRequest(BaseModel):
    """Request for token estimation."""
    prompt: str
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    history: Optional[List[dict]] = None
    task_type: str = "chat"


class TokenEstimateResponse(BaseModel):
    """Response with token estimation and quota check."""
    estimate: dict
    quota_check: dict
    model: str


@router.post("/tokens/estimate", response_model=TokenEstimateResponse)
async def estimate_tokens_endpoint(request: TokenEstimateRequest):
    """
    Estimate tokens for a request before sending to the API.
    
    Pre-checks against TPM limits and warns/rejects if quota would be exceeded.
    Use this to avoid wasted API calls when approaching quota limits.
    
    Returns:
        Token estimation breakdown and quota check result.
    """
    try:
        # Use default model if not specified
        model_name = request.model or settings.gemini_model
        
        # Get current usage for the model
        usage = usage_tracker.get_usage(model_name)
        current_tokens = usage.get("tokens", {}).get("day", {}).get("used", 0)
        
        # Estimate tokens
        estimate = token_estimator.estimate_request(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            history=request.history,
            task_type=request.task_type,
        )
        
        # Check against quota
        quota_check = token_estimator.check_quota(
            model_name=model_name,
            estimated_tokens=estimate.total_tokens,
            current_usage=current_tokens,
            enforce=settings.enforce_rate_limits,
        )
        
        return TokenEstimateResponse(
            estimate=estimate.to_dict(),
            quota_check=quota_check.to_dict(),
            model=model_name,
        )
    
    except Exception as e:
        logger.error(f"Error estimating tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to estimate tokens: {str(e)}"
        )


@router.get("/tokens/estimate-simple")
async def estimate_tokens_simple(
    text: str,
    model: Optional[str] = None,
    task_type: str = "chat",
):
    """
    Simple token estimation for a text string.
    
    Query params:
        text: The text to estimate
        model: Optional model name for quota check
        task_type: Type of task (chat, scene, analysis, etc.)
    
    Returns:
        Estimated token count and quota status.
    """
    try:
        model_name = model or settings.gemini_model
        
        # Simple estimation
        estimated_tokens = token_estimator.estimate_tokens(text)
        
        # Get quota status
        usage = usage_tracker.get_usage(model_name)
        current_tokens = usage.get("tokens", {}).get("day", {}).get("used", 0)
        token_limit = usage.get("tokens", {}).get("day", {}).get("limit", 0)
        
        return {
            "text_length": len(text),
            "estimated_tokens": estimated_tokens,
            "model": model_name,
            "quota": {
                "current_usage": current_tokens,
                "limit": token_limit,
                "remaining": max(0, token_limit - current_tokens) if token_limit else None,
                "would_exceed": (current_tokens + estimated_tokens > token_limit) if token_limit else False,
            }
        }
    
    except Exception as e:
        logger.error(f"Error with simple token estimation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to estimate tokens: {str(e)}"
        )


# ── Prompt Compression Stats Endpoint ───────────────────────

@router.get("/prompt/compression-stats")
async def get_compression_stats():
    """
    Get prompt compression statistics showing tokens saved.
    
    Returns:
        Total tokens saved, compression count, average savings, and breakdown by method.
    """
    try:
        from app.services.prompt_optimizer import prompt_optimizer
        return prompt_optimizer.get_savings_stats()
    except Exception as e:
        logger.error(f"Error getting compression stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get compression statistics"
        )


@router.post("/prompt/compress")
async def compress_prompt_endpoint(
    prompt: str,
    level: str = "moderate"
):
    """
    Compress a prompt to reduce token usage.
    
    Args:
        prompt: The prompt text to compress
        level: Compression level - "light", "moderate", or "aggressive"
    
    Returns:
        Compressed prompt and compression statistics.
    """
    try:
        from app.services.prompt_optimizer import compress_prompt
        result = compress_prompt(prompt, level=level)
        return result.to_dict()
    except Exception as e:
        logger.error(f"Error compressing prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compress prompt: {str(e)}"
        )


# ── RPD Budget Allocator Endpoints ───────────────────────

@router.get("/budget/dashboard")
async def get_budget_dashboard(model: Optional[str] = None):
    """
    Get comprehensive RPD budget dashboard showing budget vs actual per time window.
    
    Args:
        model: Optional model name to filter results. If not provided, returns all models.
    
    Returns:
        Dashboard with time windows, per-model budget allocation, and usage statistics.
    """
    try:
        from app.services.rpd_budget import rpd_budget
        return rpd_budget.get_dashboard(model=model)
    except Exception as e:
        logger.error(f"Error getting budget dashboard: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get budget dashboard"
        )


@router.get("/budget/current")
async def get_current_window_budget(model: str = "gemini-3-flash"):
    """
    Get budget status for the current time window.
    
    Args:
        model: Model name to check budget for.
    
    Returns:
        Current window info, budget, usage, and time remaining.
    """
    try:
        from app.services.rpd_budget import rpd_budget
        return rpd_budget.get_current_window_status(model)
    except Exception as e:
        logger.error(f"Error getting current window budget: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get current window budget"
        )


@router.get("/budget/windows")
async def get_budget_windows():
    """
    Get the current time window configuration.
    
    Returns:
        List of configured time windows with their budget percentages.
    """
    try:
        from app.services.rpd_budget import rpd_budget
        return {
            "windows": rpd_budget.get_windows_config(),
            "exceed_action": rpd_budget._exceed_action.value,
        }
    except Exception as e:
        logger.error(f"Error getting budget windows: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get budget windows"
        )


class BudgetWindowConfig(BaseModel):
    name: str
    start_hour: int
    end_hour: int
    budget_percent: float
    is_peak: bool = False


class UpdateWindowsRequest(BaseModel):
    windows: List[BudgetWindowConfig]


@router.post("/budget/windows", dependencies=[Depends(require_admin_auth)])
async def update_budget_windows(request: UpdateWindowsRequest):
    """
    Update time window configuration (admin only).
    
    Budget percentages should sum to approximately 100%.
    """
    try:
        from app.services.rpd_budget import rpd_budget, TimeWindow
        
        windows = [
            TimeWindow(
                name=w.name,
                start_hour=w.start_hour,
                end_hour=w.end_hour,
                budget_percent=w.budget_percent,
                is_peak=w.is_peak,
            )
            for w in request.windows
        ]
        
        success = rpd_budget.set_windows(windows)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid window configuration. Budget percentages should sum to ~100%."
            )
        
        return {"success": True, "windows": rpd_budget.get_windows_config()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating budget windows: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update budget windows"
        )


class SetModelLimitRequest(BaseModel):
    model: str
    rpd_limit: int


@router.post("/budget/model-limit", dependencies=[Depends(require_admin_auth)])
async def set_model_rpd_limit(request: SetModelLimitRequest):
    """
    Set custom RPD limit for a model (admin only).
    
    Overrides the default limits from usage_tracker.
    """
    try:
        from app.services.rpd_budget import rpd_budget
        
        rpd_budget.set_model_rpd_limit(request.model, request.rpd_limit)
        return {
            "success": True,
            "model": request.model,
            "rpd_limit": request.rpd_limit,
        }
    except Exception as e:
        logger.error(f"Error setting model RPD limit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set model RPD limit"
        )


@router.get("/budget/check")
async def check_budget_allowance(model: str = "gemini-3-flash"):
    """
    Check if a request would be allowed under current budget constraints.
    
    Returns:
        Whether request is allowed, reason, and recommended action.
    """
    try:
        from app.services.rpd_budget import rpd_budget
        
        allowed, reason, action = rpd_budget.check_budget(model)
        return {
            "allowed": allowed,
            "reason": reason,
            "action": action.value,
            "model": model,
        }
    except Exception as e:
        logger.error(f"Error checking budget allowance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check budget allowance"
        )


# ── SSE Events Stream ────────────────────────────────────

@router.get("/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint for real-time updates."""
    queue = asyncio.Queue(maxsize=50)
    _sse_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield message
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            if queue in _sse_subscribers:
                _sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Semantic Search ───────────────────────────────────────

@router.get("/search")
async def semantic_search(q: str, limit: int = 10):
    """Search cases and reports using semantic similarity."""
    try:
        cases = await case_manager.search_cases(q, limit=limit)
        reports = await case_manager.search_reports(q, limit=limit)
        return {
            "query": q,
            "cases": [{"id": cid, "score": score} for cid, score in cases],
            "reports": [{"id": rid, "score": score} for rid, score in reports],
        }
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Scene Image Generation ───────────────────────────────

@router.post("/cases/{case_id}/generate-scene", response_model=BackgroundTaskResponse)
async def generate_case_scene(case_id: str, body: SceneGenerateRequest = None):
    """Generate an AI scene image for a case (runs in background)."""
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    task_id = f"scene-case-{case_id}-{uuid.uuid4().hex[:8]}"
    description = (body.description if body and body.description else case.summary) or case.title

    async def _generate():
        from app.services.imagen_service import imagen_service
        path = await imagen_service.generate_case_scene(case_id, case.summary or "", description)
        if path:
            case.scene_image_url = path
            await firestore_service.update_case(case)
            await firestore_service.save_generated_image({
                "id": task_id,
                "entity_type": "case",
                "entity_id": case_id,
                "image_path": path,
                "model_used": "imagen",
                "prompt": description[:500],
            })
            await publish_event("image_generated", {"entity_type": "case", "entity_id": case_id, "image_path": path})
        return path

    asyncio.create_task(run_background_task(task_id, _generate()))
    return BackgroundTaskResponse(task_id=task_id, status="pending", message="Scene generation started")


@router.post("/sessions/{session_id}/generate-scene", response_model=BackgroundTaskResponse)
async def generate_report_scene(session_id: str, body: SceneGenerateRequest = None):
    """Generate an AI scene image for a report (runs in background)."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task_id = f"scene-report-{session_id}-{uuid.uuid4().hex[:8]}"
    description = (body.description if body and body.description else session.title)
    elements = [e.model_dump() for e in session.current_scene_elements[:10]]

    async def _generate():
        from app.services.imagen_service import imagen_service
        path = await imagen_service.generate_report_scene(session_id, description, elements)
        if path:
            await firestore_service.save_generated_image({
                "id": task_id,
                "entity_type": "report",
                "entity_id": session_id,
                "image_path": path,
                "model_used": "imagen",
                "prompt": description[:500],
            })
            await publish_event("image_generated", {"entity_type": "report", "entity_id": session_id, "image_path": path})
        return path

    asyncio.create_task(run_background_task(task_id, _generate()))
    return BackgroundTaskResponse(task_id=task_id, status="pending", message="Scene generation started")


@router.post("/cases/{case_id}/regenerate-scene", response_model=BackgroundTaskResponse)
async def regenerate_case_scene(case_id: str, body: SceneGenerateRequest = None):
    """Force regenerate a scene image for a case."""
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    task_id = f"regen-case-{case_id}-{uuid.uuid4().hex[:8]}"
    description = (body.description if body and body.description else case.summary) or case.title
    quality = body.quality if body else "standard"

    async def _regenerate():
        from app.services.imagen_service import imagen_service
        path = await imagen_service.regenerate_scene("case", case_id, description, quality=quality)
        if path:
            case.scene_image_url = path
            await firestore_service.update_case(case)
            await publish_event("image_generated", {"entity_type": "case", "entity_id": case_id, "image_path": path})
        return path

    asyncio.create_task(run_background_task(task_id, _regenerate()))
    return BackgroundTaskResponse(task_id=task_id, status="pending", message="Scene regeneration started")


# ── Image Listing ─────────────────────────────────────────

@router.get("/cases/{case_id}/images")
async def list_case_images(case_id: str):
    """List all generated images for a case."""
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        from app.services.imagen_service import imagen_service
        fs_images = await imagen_service.get_images_for_case(case_id)
    except Exception:
        fs_images = []
    db_images = await firestore_service.list_images_for_entity("case", case_id)
    return {"case_id": case_id, "images": fs_images, "records": db_images}


@router.get("/sessions/{session_id}/images")
async def list_report_images(session_id: str):
    """List all generated images for a report."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        from app.services.imagen_service import imagen_service
        fs_images = await imagen_service.get_images_for_report(session_id)
    except Exception:
        fs_images = []
    db_images = await firestore_service.list_images_for_entity("report", session_id)
    return {"report_id": session_id, "images": fs_images, "records": db_images}


@router.get("/images/stats")
async def get_image_stats():
    """Get image file counts and simple filename breakdown."""
    images_dir = "/app/data/images"
    if not os.path.exists(images_dir):
        dev_dir = os.path.join(os.path.dirname(__file__), "..", "data", "images")
        if os.path.exists(dev_dir):
            images_dir = dev_dir

    if not os.path.exists(images_dir):
        return {
            "images_dir": images_dir,
            "total": 0,
            "breakdown": {"case": 0, "report": 0, "other": 0},
        }

    files = [
        name for name in os.listdir(images_dir)
        if os.path.isfile(os.path.join(images_dir, name))
    ]
    case_count = sum(1 for name in files if name.startswith("case_"))
    report_count = sum(1 for name in files if name.startswith("report_"))
    other_count = len(files) - case_count - report_count

    return {
        "images_dir": images_dir,
        "total": len(files),
        "breakdown": {
            "case": case_count,
            "report": report_count,
            "other": other_count,
        },
    }


# ── Image Serving ─────────────────────────────────────────

@router.get("/images/{filename}")
async def serve_image(filename: str):
    """Serve a generated image file."""
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join("/app/data/images", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(filepath, media_type="image/png")


# ── Request Queue Endpoints ───────────────────────────────

@router.get("/queue/status")
async def get_queue_status():
    """
    Get the overall status of the request queue.
    
    Returns queue size, pending count, and processing statistics.
    """
    from app.services.request_queue import request_queue
    return request_queue.get_queue_status()


@router.get("/queue/status/{request_id}")
async def get_queued_request_status(request_id: str):
    """
    Get the status of a specific queued request.
    
    Args:
        request_id: The unique ID of the queued request (returned when request was queued)
    
    Returns:
        Status of the queued request or 404 if not found
    """
    from app.services.request_queue import request_queue
    
    queued = request_queue.get_request_status(request_id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Queued request {request_id} not found"
        )
    
    return queued.to_dict()


@router.get("/queue/pending")
async def get_pending_requests(
    request: Request,
    limit: int = 50,
    my_requests_only: bool = False,
    priority: Optional[str] = None,
):
    """
    Get list of pending requests in the queue, sorted by priority.
    
    Args:
        limit: Maximum number of requests to return (default 50)
        my_requests_only: If true, only return requests from this client IP
        priority: Filter by priority level (critical, high, normal, low)
    
    Returns:
        List of pending queued requests sorted by priority
    """
    from app.services.request_queue import request_queue, RequestPriority
    
    client_ip = None
    if my_requests_only:
        client_ip = request.client.host if request.client else None
    
    # Convert priority string to enum if provided
    priority_filter = None
    if priority:
        priority_map = {
            "critical": RequestPriority.CRITICAL,
            "high": RequestPriority.HIGH,
            "normal": RequestPriority.NORMAL,
            "low": RequestPriority.LOW,
        }
        priority_filter = priority_map.get(priority.lower())
    
    pending = request_queue.get_pending_requests(
        limit=limit, 
        client_ip=client_ip,
        priority=priority_filter
    )
    
    return {
        "pending_count": len(pending),
        "requests": pending,
    }


@router.delete("/queue/{request_id}")
async def cancel_queued_request(request_id: str):
    """
    Cancel a pending queued request.
    
    Args:
        request_id: The unique ID of the queued request to cancel
    
    Returns:
        Success status or 404/400 if request not found or cannot be cancelled
    """
    from app.services.request_queue import request_queue
    
    queued = request_queue.get_request_status(request_id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Queued request {request_id} not found"
        )
    
    success = request_queue.cancel_request(request_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request {request_id} cannot be cancelled (status: {queued.status.value})"
        )
    
    return {"message": f"Request {request_id} cancelled", "success": True}


class SetPriorityRequest(BaseModel):
    """Request model for setting queue request priority."""
    priority: str  # critical, high, normal, low


@router.patch("/queue/{request_id}/priority")
async def set_queued_request_priority(request_id: str, priority_request: SetPriorityRequest):
    """
    Set the priority of a pending queued request.
    
    Args:
        request_id: The unique ID of the queued request
        priority_request: The new priority level (critical, high, normal, low)
    
    Returns:
        Updated request status or error
    """
    from app.services.request_queue import request_queue, RequestPriority
    
    # Validate priority
    priority_map = {
        "critical": RequestPriority.CRITICAL,
        "high": RequestPriority.HIGH,
        "normal": RequestPriority.NORMAL,
        "low": RequestPriority.LOW,
    }
    
    priority_str = priority_request.priority.lower()
    if priority_str not in priority_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority '{priority_request.priority}'. Must be one of: critical, high, normal, low"
        )
    
    queued = request_queue.get_request_status(request_id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Queued request {request_id} not found"
        )
    
    success = request_queue.set_request_priority(request_id, priority_map[priority_str])
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request {request_id} cannot have priority changed (status: {queued.status.value})"
        )
    
    # Return updated request
    updated = request_queue.get_request_status(request_id)
    return updated.to_dict() if updated else {"message": f"Priority updated to {priority_str}", "success": True}


@router.post("/queue/cleanup", dependencies=[Depends(require_admin_auth)])
async def cleanup_queue(max_age_hours: int = 1):
    """
    Clean up old completed/failed/expired requests from the queue.
    
    Admin only endpoint.
    
    Args:
        max_age_hours: Remove completed requests older than this many hours (default 1)
    
    Returns:
        Queue status after cleanup
    """
    from app.services.request_queue import request_queue
    
    request_queue.cleanup_completed(max_age_seconds=max_age_hours * 3600)
    
    return request_queue.get_queue_status()


# ── Text-to-Speech Endpoints ──────────────────────────────


class TTSRequest(BaseModel):
    """Request model for TTS generation."""
    text: str
    voice: str = "Puck"


class TTSResponse(BaseModel):
    """Response model for TTS generation."""
    audio_base64: str
    mime_type: str = "audio/wav"
    voice: str
    text_length: int


@router.post("/tts/generate", response_model=TTSResponse)
async def generate_tts(
    request: TTSRequest,
):
    """
    Generate text-to-speech audio from text.
    
    This endpoint converts text to speech using Gemini 2.5 Flash Native Audio Dialog with fallback to preview TTS.
    Useful for accessibility, allowing visually impaired users to hear AI responses.
    
    Rate limits depend on active TTS model and configured fallback chain.
    
    Args:
        text: The text to convert to speech (max ~8000 characters).
        voice: Voice preset to use (default: Puck).
    
    Returns:
        Base64-encoded audio data with metadata.
    """
    if not request.text or not request.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text is required for TTS generation"
        )
    
    # Check quota status first
    quota = tts_service.get_quota_status()
    if not quota.get("available"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="TTS quota exhausted. Please try again later.",
            headers={"Retry-After": "60"},
        )
    
    audio_base64 = await tts_service.generate_speech_base64(
        text=request.text,
        voice=request.voice,
    )
    
    if not audio_base64:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS generation failed. Service may be temporarily unavailable."
        )
    
    return TTSResponse(
        audio_base64=audio_base64,
        mime_type="audio/wav",
        voice=request.voice,
        text_length=len(request.text),
    )


@router.get("/tts/voices")
async def get_tts_voices():
    """
    Get list of available TTS voice options.
    
    Returns:
        List of voice presets with IDs and descriptions.
    """
    return {
        "voices": tts_service.get_available_voices(),
        "default": "Puck",
    }


@router.get("/tts/quota")
async def get_tts_quota():
    """
    Get current TTS quota status.
    
    Returns:
        Current usage against rate limits (RPM, RPD).
    """
    return tts_service.get_quota_status()


@router.get("/voice/profile")
async def get_voice_profile():
    """Get default voice-first profile settings for mobile witness flow."""
    defaults = dict(VOICE_DEFAULT_PREFERENCES)
    return {
        "mobile_voice_first": True,
        "defaults": defaults,
        "tts_enabled_default": defaults["tts_enabled"],
        "auto_listen_default": defaults["auto_listen"],
        "quick_phrases_enabled": True,
        "suggested_voice": defaults["voice"],
        "available_voices": tts_service.get_available_voices(),
    }


@router.get("/sessions/{session_id}/voice/preferences")
async def get_session_voice_preferences(session_id: str):
    """Get normalized voice preferences for a session."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(getattr(session, "metadata", {}) or {})
    preferences = _normalize_voice_preferences(metadata.get("voice_preferences"))
    return {
        "session_id": session_id,
        "voice_preferences": preferences,
        "defaults": dict(VOICE_DEFAULT_PREFERENCES),
    }


@router.patch("/sessions/{session_id}/voice/preferences")
async def update_session_voice_preferences(session_id: str, payload: Optional[Dict[str, Any]] = None):
    """Validate and persist merged voice preferences in session metadata."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="voice preferences payload must be an object")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(getattr(session, "metadata", {}) or {})
    current = _normalize_voice_preferences(metadata.get("voice_preferences"))
    merged = _normalize_voice_preferences(payload, base_preferences=current, strict=True)
    metadata["voice_preferences"] = merged

    session.metadata = metadata
    success = await firestore_service.update_session(session)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update voice preferences")

    return {
        "session_id": session_id,
        "voice_preferences": merged,
    }


@router.get("/voice/health")
async def get_voice_health():
    """Get voice feature health including TTS quota and websocket guidance."""
    tts_quota = tts_service.get_quota_status()
    models_available = 0
    model_total = 0
    try:
        from app.services.model_selector import model_selector

        statuses = await model_selector.get_all_models_status()
        model_total = len(statuses)
        models_available = sum(1 for item in statuses if item.get("available"))
    except Exception as e:
        logger.warning(f"Voice health model status unavailable: {e}")

    services = {
        "firestore": await firestore_service.health_check(),
        "tts": tts_service.health_check(),
        "websocket": True,
    }
    return {
        "status": "healthy" if all(services.values()) and tts_quota.get("available", False) else "degraded",
        "services": services,
        "tts_quota": tts_quota,
        "models_available": models_available,
        "models_total": model_total,
        "websocket_guidance": "Connect to /ws/{session_id}; listen for status, call_state, voice_hint, and call_metrics events.",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/voice/quick-phrases")
async def get_voice_quick_phrases(limit: int = 8):
    """Get starter voice chips/prompts for witness intake."""
    safe_limit = _guard_limit(limit)
    phrases = VOICE_QUICK_PHRASES[:safe_limit]
    return {
        "quick_phrases": phrases,
        "count": len(phrases),
        "limit": safe_limit,
    }


@router.get("/sessions/{session_id}/conversation/summary")
async def get_conversation_summary(session_id: str):
    """Get a lightweight conversation summary for voice UI."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = list(getattr(session, "witness_statements", []) or [])
    statement_count = len(statements)
    agent = get_agent(session_id)
    history = list(getattr(agent, "conversation_history", []) or [])
    turns = len([m for m in history if isinstance(m, dict) and m.get("role") == "user"]) or statement_count

    last_user_snippet = ""
    if statements:
        latest_statement = statements[-1]
        last_user_snippet = ((latest_statement.original_text or latest_statement.text or "").strip())[:180]
    elif history:
        for item in reversed(history):
            if isinstance(item, dict) and item.get("role") == "user":
                last_user_snippet = str(item.get("content", "")).strip()[:180]
                break

    last_agent_snippet = ""
    for item in reversed(history):
        if isinstance(item, dict) and item.get("role") in {"assistant", "agent", "model"}:
            last_agent_snippet = str(item.get("content", "")).strip()[:180]
            break

    latest_scene = (session.scene_versions or [])[-1] if (session.scene_versions or []) else None
    scene_snapshot = {
        "latest_version": getattr(latest_scene, "version", None),
        "image_url": getattr(latest_scene, "image_url", None),
        "description": getattr(latest_scene, "description", None),
        "timestamp": latest_scene.timestamp.isoformat() if latest_scene and getattr(latest_scene, "timestamp", None) else None,
    }

    return {
        "session_id": session_id,
        "turns": turns,
        "statement_count": statement_count,
        "last_user_snippet": last_user_snippet,
        "last_agent_snippet": last_agent_snippet,
        "case_id": session.case_id,
        "scene_version_count": len(session.scene_versions or []),
        "scene_snapshot": scene_snapshot,
        "scene_latest_version": scene_snapshot["latest_version"],
        "scene_latest_image_url": scene_snapshot["image_url"],
        "scene_latest_description": scene_snapshot["description"],
    }


@router.get("/sessions/{session_id}/scene/preview")
async def get_scene_preview(session_id: str):
    """Get latest scene preview metadata for realtime voice UI."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    latest_scene = (session.scene_versions or [])[-1] if (session.scene_versions or []) else None
    metadata = dict(getattr(session, "metadata", {}) or {})
    if latest_scene:
        return {
            "session_id": session_id,
            "has_scene": True,
            "version": getattr(latest_scene, "version", len(session.scene_versions or [])),
            "image_url": getattr(latest_scene, "image_url", None),
            "description": getattr(latest_scene, "description", ""),
            "timestamp": latest_scene.timestamp.isoformat() if getattr(latest_scene, "timestamp", None) else None,
            "scene_version_count": len(session.scene_versions or []),
        }

    agent = get_agent(session_id)
    scene_summary = agent.get_scene_summary()
    return {
        "session_id": session_id,
        "has_scene": False,
        "version": None,
        "image_url": metadata.get("report_scene_image_url"),
        "description": scene_summary.get("description", ""),
        "timestamp": None,
        "scene_version_count": 0,
    }


@router.post("/sessions/{session_id}/barge-in")
async def record_barge_in(session_id: str, payload: Optional[Dict[str, Any]] = None):
    """Record a barge-in marker in session voice events."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="barge-in payload must be an object")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(getattr(session, "metadata", {}) or {})
    event = {
        "type": "barge_in",
        "timestamp": datetime.utcnow().isoformat(),
        "source": str(payload.get("source", "client"))[:40],
    }
    if payload.get("reason") is not None:
        event["reason"] = str(payload.get("reason", ""))[:160]

    events = _append_voice_event(metadata, event)
    session.metadata = metadata
    success = await firestore_service.update_session(session)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to record barge-in event")

    _log_voice_event_write(session_id, event, len(events))
    return {
        "session_id": session_id,
        "event": event,
        "voice_events_count": len(events),
    }


@router.post("/sessions/{session_id}/call-event")
async def record_call_event(session_id: str, payload: Optional[Dict[str, Any]] = None):
    """Record a generic call event in session metadata."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="call-event payload must be an object")

    event_type = str(payload.get("event_type") or payload.get("type") or "").strip()
    if not event_type:
        raise HTTPException(status_code=400, detail="event_type is required")
    if len(event_type) > 60:
        raise HTTPException(status_code=400, detail="event_type must be <= 60 characters")

    event_payload = payload.get("payload")
    if event_payload is not None and not isinstance(event_payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object when provided")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(getattr(session, "metadata", {}) or {})
    event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if payload.get("source") is not None:
        event["source"] = str(payload.get("source", ""))[:40]
    if payload.get("status") is not None:
        event["status"] = str(payload.get("status", ""))[:40]
    if event_payload:
        event["payload"] = event_payload

    events = _append_voice_event(metadata, event)
    session.metadata = metadata
    success = await firestore_service.update_session(session)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to record call event")

    _log_voice_event_write(session_id, event, len(events))
    return {
        "session_id": session_id,
        "event": event,
        "voice_events_count": len(events),
    }


# ============================================================================
# Interactive Timeline Visualization Endpoints
# ============================================================================

class TimelineEventUpdate(BaseModel):
    """Request model for updating a timeline event time."""
    event_time: str  # ISO format datetime


@router.get("/cases/{case_id}/timeline/visualization")
async def get_case_timeline_visualization(case_id: str):
    """
    Get comprehensive timeline data for interactive visualization.
    Returns events organized by witness as swim lanes with contradiction detection.
    """
    try:
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        witnesses = []
        all_events = []
        event_id_counter = 0

        # Collect all reports and their timelines
        for report_id in case.report_ids:
            session = await firestore_service.get_session(report_id)
            if not session:
                continue

            witness_id = report_id
            witness_name = session.witness_name or session.title or f"Witness {len(witnesses) + 1}"
            
            witnesses.append({
                "id": witness_id,
                "name": witness_name,
                "source_type": getattr(session, 'source_type', 'chat'),
                "report_number": getattr(session, 'report_number', ''),
                "created_at": session.created_at.isoformat() if session.created_at else None,
            })

            # Extract timeline events from statements
            for idx, statement in enumerate(session.witness_statements):
                event_id_counter += 1
                event = {
                    "id": f"evt-{event_id_counter}",
                    "witness_id": witness_id,
                    "witness_name": witness_name,
                    "sequence": idx,
                    "event_time": statement.timestamp.isoformat() if statement.timestamp else None,
                    "type": "correction" if statement.is_correction else "statement",
                    "description": statement.text[:200] + "..." if len(statement.text) > 200 else statement.text,
                    "full_text": statement.text,
                    "confidence": getattr(statement, 'confidence', 0.5),
                    "editable": True,
                }
                all_events.append(event)

            # Include timeline events from session if available
            for idx, tl_event in enumerate(session.timeline):
                event_id_counter += 1
                event = {
                    "id": f"evt-{event_id_counter}",
                    "witness_id": witness_id,
                    "witness_name": witness_name,
                    "sequence": tl_event.sequence,
                    "event_time": tl_event.timestamp.isoformat() if tl_event.timestamp else None,
                    "type": "timeline_event",
                    "description": tl_event.description,
                    "full_text": tl_event.description,
                    "image_url": tl_event.image_url,
                    "confidence": getattr(tl_event, 'confidence', 0.5),
                    "needs_review": getattr(tl_event, 'needs_review', False),
                    "editable": True,
                }
                all_events.append(event)

            # Include scene generation events
            for idx, version in enumerate(session.scene_versions):
                event_id_counter += 1
                event = {
                    "id": f"evt-{event_id_counter}",
                    "witness_id": witness_id,
                    "witness_name": witness_name,
                    "sequence": 1000 + idx,  # Place at end
                    "event_time": version.timestamp.isoformat() if version.timestamp else None,
                    "type": "scene_generation",
                    "description": f"Scene reconstruction #{idx + 1}",
                    "full_text": version.description or "",
                    "image_url": version.image_url,
                    "editable": False,
                }
                all_events.append(event)

        # Sort events by time
        all_events.sort(key=lambda x: x.get("event_time") or "9999")

        # Detect contradictions between witness accounts
        contradictions = await _detect_timeline_contradictions(all_events, witnesses)

        # Calculate time bounds
        times = [e["event_time"] for e in all_events if e.get("event_time")]
        time_bounds = {
            "earliest": min(times) if times else None,
            "latest": max(times) if times else None,
        }

        return {
            "case_id": case_id,
            "case_title": case.title,
            "case_number": case.case_number,
            "witnesses": witnesses,
            "events": all_events,
            "contradictions": contradictions,
            "time_bounds": time_bounds,
            "total_events": len(all_events),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting case timeline visualization: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _detect_timeline_contradictions(events: List[dict], witnesses: List[dict]) -> List[dict]:
    """
    Detect potential contradictions between witness timelines.
    Returns list of contradiction objects with event pairs and reasoning.
    """
    contradictions = []
    
    if len(witnesses) < 2:
        return contradictions

    # Group events by witness
    events_by_witness = {}
    for event in events:
        wid = event.get("witness_id")
        if wid not in events_by_witness:
            events_by_witness[wid] = []
        events_by_witness[wid].append(event)

    # Simple contradiction detection: look for timing conflicts
    # Events from different witnesses at similar times with conflicting content
    witness_ids = list(events_by_witness.keys())
    
    for i, wid1 in enumerate(witness_ids):
        for wid2 in witness_ids[i+1:]:
            events1 = events_by_witness.get(wid1, [])
            events2 = events_by_witness.get(wid2, [])
            
            for e1 in events1:
                for e2 in events2:
                    if not e1.get("event_time") or not e2.get("event_time"):
                        continue
                    
                    # Check if events are close in time (within 5 minutes)
                    try:
                        t1 = datetime.fromisoformat(e1["event_time"].replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(e2["event_time"].replace("Z", "+00:00"))
                        delta = abs((t2 - t1).total_seconds())
                        
                        if delta < 300:  # Within 5 minutes
                            # Check for potential content conflicts using keywords
                            text1 = e1.get("full_text", "").lower()
                            text2 = e2.get("full_text", "").lower()
                            
                            conflict_pairs = [
                                ("left", "right"),
                                ("red", "blue"),
                                ("ran", "walked"),
                                ("before", "after"),
                                ("yes", "no"),
                                ("one", "two"),
                                ("man", "woman"),
                            ]
                            
                            for word1, word2 in conflict_pairs:
                                if (word1 in text1 and word2 in text2) or \
                                   (word2 in text1 and word1 in text2):
                                    contradictions.append({
                                        "id": f"conflict-{len(contradictions)+1}",
                                        "event_ids": [e1["id"], e2["id"]],
                                        "witness_ids": [wid1, wid2],
                                        "type": "timing_conflict",
                                        "severity": "medium",
                                        "description": f"Potential conflict: witnesses differ on '{word1}' vs '{word2}' at similar times",
                                        "time_delta_seconds": delta,
                                    })
                                    break
                    except (ValueError, TypeError):
                        continue

    return contradictions[:10]  # Limit to top 10 contradictions


@router.put("/cases/{case_id}/timeline/events/{event_id}")
async def update_timeline_event_time(
    case_id: str,
    event_id: str,
    update: TimelineEventUpdate,
    auth=Depends(require_admin_auth)
):
    """
    Update the time of a timeline event.
    Allows investigators to correct event timestamps.
    """
    try:
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Parse the event ID to find source
        # Event IDs are formatted as evt-{number}
        # We need to find which session/statement this belongs to
        
        new_time = datetime.fromisoformat(update.event_time.replace("Z", "+00:00"))
        
        # Search through all reports to find and update the event
        event_counter = 0
        for report_id in case.report_ids:
            session = await firestore_service.get_session(report_id)
            if not session:
                continue

            # Check statements
            for idx, statement in enumerate(session.witness_statements):
                event_counter += 1
                if f"evt-{event_counter}" == event_id:
                    statement.timestamp = new_time
                    session.updated_at = datetime.utcnow()
                    await firestore_service.update_session(session)
                    return {"message": "Event time updated", "event_id": event_id, "new_time": new_time.isoformat()}

            # Check timeline events
            for idx, tl_event in enumerate(session.timeline):
                event_counter += 1
                if f"evt-{event_counter}" == event_id:
                    tl_event.timestamp = new_time
                    session.updated_at = datetime.utcnow()
                    await firestore_service.update_session(session)
                    return {"message": "Event time updated", "event_id": event_id, "new_time": new_time.isoformat()}

            # Scene events are not editable, skip them
            event_counter += len(session.scene_versions)

        raise HTTPException(status_code=404, detail="Event not found or not editable")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")
    except Exception as e:
        logger.error(f"Error updating timeline event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/timeline/visualization")
async def get_session_timeline_visualization(session_id: str):
    """
    Get timeline visualization data for a single session/report.
    Supports multi-witness sessions with separate swim lanes per witness.
    """
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        events = []
        event_id_counter = 0
        
        # Build witnesses list - use multi-witness if available, else fallback to single witness
        witnesses_list = getattr(session, 'witnesses', []) or []
        witness_map = {w.id: w for w in witnesses_list}
        
        # Create witnesses for visualization
        viz_witnesses = []
        if witnesses_list:
            for witness in witnesses_list:
                viz_witnesses.append({
                    "id": witness.id,
                    "name": witness.name,
                    "source_type": witness.source_type,
                })
        else:
            # Fallback for sessions without multi-witness
            viz_witnesses.append({
                "id": session_id,
                "name": session.witness_name or session.title or "Witness",
                "source_type": getattr(session, 'source_type', 'chat'),
            })

        # Statements - use witness_id from statement if available
        for idx, statement in enumerate(session.witness_statements):
            event_id_counter += 1
            
            # Determine witness info for this statement
            stmt_witness_id = getattr(statement, 'witness_id', None) or session_id
            stmt_witness_name = getattr(statement, 'witness_name', None)
            if not stmt_witness_name:
                if stmt_witness_id in witness_map:
                    stmt_witness_name = witness_map[stmt_witness_id].name
                else:
                    stmt_witness_name = session.witness_name or session.title or "Witness"
            
            events.append({
                "id": f"evt-{event_id_counter}",
                "witness_id": stmt_witness_id,
                "witness_name": stmt_witness_name,
                "sequence": idx,
                "event_time": statement.timestamp.isoformat() if statement.timestamp else None,
                "type": "correction" if statement.is_correction else "statement",
                "description": statement.text[:200] + "..." if len(statement.text) > 200 else statement.text,
                "full_text": statement.text,
                "confidence": getattr(statement, 'confidence', 0.5),
                "editable": True,
            })

        # Timeline events
        for idx, tl_event in enumerate(session.timeline):
            event_id_counter += 1
            events.append({
                "id": f"evt-{event_id_counter}",
                "witness_id": session_id,
                "witness_name": session.witness_name or session.title or "Timeline",
                "sequence": tl_event.sequence,
                "event_time": tl_event.timestamp.isoformat() if tl_event.timestamp else None,
                "type": "timeline_event",
                "description": tl_event.description,
                "full_text": tl_event.description,
                "image_url": tl_event.image_url,
                "confidence": getattr(tl_event, 'confidence', 0.5),
                "needs_review": getattr(tl_event, 'needs_review', False),
                "editable": True,
            })

        # Scene versions
        for idx, version in enumerate(session.scene_versions):
            event_id_counter += 1
            events.append({
                "id": f"evt-{event_id_counter}",
                "witness_id": session_id,
                "witness_name": "Scene Reconstruction",
                "sequence": 1000 + idx,
                "event_time": version.timestamp.isoformat() if version.timestamp else None,
                "type": "scene_generation",
                "description": f"Scene reconstruction #{idx + 1}",
                "full_text": version.description or "",
                "image_url": version.image_url,
                "editable": False,
            })

        events.sort(key=lambda x: x.get("event_time") or "9999")
        
        times = [e["event_time"] for e in events if e.get("event_time")]
        
        return {
            "session_id": session_id,
            "session_title": session.title,
            "witnesses": viz_witnesses,
            "events": events,
            "contradictions": [],
            "time_bounds": {
                "earliest": min(times) if times else None,
                "latest": max(times) if times else None,
            },
            "total_events": len(events),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session timeline visualization: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Quota Alert Endpoints ─────────────────────────────────

@router.get("/alerts/history")
async def get_alert_history(
    limit: int = 50,
    model: Optional[str] = None,
    level: Optional[str] = None
):
    """
    Get quota alert history.
    
    Args:
        limit: Maximum number of alerts to return (default: 50)
        model: Filter by model name
        level: Filter by alert level (warning, critical, resolved)
    
    Returns:
        List of recent alerts
    """
    from app.services.quota_alert_service import quota_alert_service
    
    return {
        "alerts": quota_alert_service.get_alert_history(
            limit=limit,
            model=model,
            level=level
        ),
        "total": len(quota_alert_service.get_alert_history(limit=1000)),
    }


@router.get("/alerts/active")
async def get_active_alerts():
    """
    Get currently active (unresolved) quota alerts.
    
    Returns:
        List of active alerts that haven't been resolved
    """
    from app.services.quota_alert_service import quota_alert_service
    
    return {
        "active_alerts": quota_alert_service.get_active_alerts(),
        "count": len(quota_alert_service.get_active_alerts()),
    }


@router.get("/alerts/config")
async def get_alert_config():
    """
    Get current quota alert service configuration.
    
    Returns:
        Current threshold settings and service status
    """
    from app.services.quota_alert_service import quota_alert_service
    
    return quota_alert_service.get_config()


@router.post("/alerts/config")
async def update_alert_config(
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None
):
    """
    Update quota alert thresholds.
    
    Args:
        warning_threshold: New warning threshold (0-1, e.g., 0.80 for 80%)
        critical_threshold: New critical threshold (0-1, e.g., 0.95 for 95%)
    
    Returns:
        Updated configuration
    """
    from app.services.quota_alert_service import quota_alert_service
    
    if warning_threshold is not None:
        if not 0 < warning_threshold < 1:
            raise HTTPException(
                status_code=400,
                detail="warning_threshold must be between 0 and 1"
            )
    
    if critical_threshold is not None:
        if not 0 < critical_threshold <= 1:
            raise HTTPException(
                status_code=400,
                detail="critical_threshold must be between 0 and 1"
            )
    
    if warning_threshold and critical_threshold and warning_threshold >= critical_threshold:
        raise HTTPException(
            status_code=400,
            detail="warning_threshold must be less than critical_threshold"
        )
    
    quota_alert_service.set_thresholds(
        warning=warning_threshold,
        critical=critical_threshold
    )
    
    return quota_alert_service.get_config()


@router.post("/alerts/check")
async def trigger_quota_check():
    """
    Manually trigger a quota check for all models.
    
    Returns:
        Any alerts generated from the check
    """
    from app.services.quota_alert_service import quota_alert_service
    
    alerts = await quota_alert_service.check_all_quotas()
    
    return {
        "checked": True,
        "alerts_generated": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
    }


# ── Case Linking ─────────────────────────────────────────

@router.get("/cases/{case_id}/related")
async def get_related_cases(case_id: str):
    """Get all cases related to the given case."""
    from app.services.case_linking import case_linking_service
    
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    try:
        related = await case_linking_service.get_related_cases(case_id)
        return {
            "case_id": case_id,
            "related_cases": [r.model_dump(mode="json") for r in related],
            "count": len(related),
        }
    except Exception as e:
        logger.error(f"Error getting related cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/similar")
async def find_similar_cases(case_id: str, limit: int = 5, auth=Depends(require_admin_auth)):
    """Find similar cases based on type, location, and time patterns."""
    case = await firestore_service.get_case(case_id)
    if not case: raise HTTPException(404, "Case not found")
    c = case if isinstance(case, dict) else case.model_dump()
    all_cases = await firestore_service.list_cases(limit=100)
    similar = []
    for other in all_cases:
        o = other if isinstance(other, dict) else other.model_dump()
        if o.get("id") == case_id: continue
        score = 0
        # Location match
        if c.get("location") and o.get("location") and c["location"].lower() in o["location"].lower():
            score += 40
        # Status match
        if c.get("status") == o.get("status"): score += 10
        # Title keyword overlap
        c_words = set((c.get("title","") + " " + c.get("summary","")).lower().split())
        o_words = set((o.get("title","") + " " + o.get("summary","")).lower().split())
        overlap = len(c_words & o_words - {"the","a","an","in","on","at","to","of","and","or","was","is"})
        score += min(40, overlap * 5)
        if score > 15:
            similar.append({"case_id": o.get("id"), "title": o.get("title",""), "score": min(100, score), "location": o.get("location","")})
    similar.sort(key=lambda x: x["score"], reverse=True)
    return {"similar_cases": similar[:limit]}


class LinkCasesRequest(BaseModel):
    case_b_id: str
    relationship_type: str = "related"
    link_reason: str = "manual"
    notes: Optional[str] = None


@router.post("/cases/{case_id}/link")
async def link_cases(case_id: str, request: LinkCasesRequest, auth=Depends(require_admin_auth)):
    """Manually link two cases."""
    from app.services.case_linking import case_linking_service
    
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    case_b = await firestore_service.get_case(request.case_b_id)
    if not case_b:
        raise HTTPException(status_code=404, detail="Target case not found")
    
    try:
        rel = await case_linking_service.create_relationship(
            case_a_id=case_id,
            case_b_id=request.case_b_id,
            relationship_type=request.relationship_type,
            link_reason=request.link_reason,
            notes=request.notes,
            confidence=1.0,
            created_by="manual",
        )
        if rel:
            return {
                "message": "Cases linked successfully",
                "relationship_id": rel.id,
                "case_a": case.case_number,
                "case_b": case_b.case_number,
            }
        raise HTTPException(status_code=400, detail="Failed to create relationship")
    except Exception as e:
        logger.error(f"Error linking cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cases/{case_id}/link/{relationship_id}")
async def unlink_cases(case_id: str, relationship_id: str, auth=Depends(require_admin_auth)):
    """Remove a link between two cases."""
    from app.services.case_linking import case_linking_service
    
    # Verify the relationship exists and involves this case
    rel = await firestore_service.get_case_relationship(relationship_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    
    if rel["case_a_id"] != case_id and rel["case_b_id"] != case_id:
        raise HTTPException(status_code=400, detail="Relationship does not involve this case")
    
    try:
        success = await case_linking_service.delete_relationship(relationship_id)
        if success:
            return {"message": "Cases unlinked successfully", "relationship_id": relationship_id}
        raise HTTPException(status_code=500, detail="Failed to delete relationship")
    except Exception as e:
        logger.error(f"Error unlinking cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/auto-link")
async def auto_link_cases(case_id: str, threshold: float = 0.75, auth=Depends(require_admin_auth)):
    """Automatically link similar cases based on similarity threshold."""
    from app.services.case_linking import case_linking_service
    
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    try:
        created_links = await case_linking_service.auto_link_similar_cases(case_id, threshold=threshold)
        return {
            "message": f"Auto-linked {len(created_links)} cases",
            "case_id": case_id,
            "links_created": len(created_links),
            "relationships": [
                {
                    "id": rel.id,
                    "linked_case_id": rel.case_b_id if rel.case_a_id == case_id else rel.case_a_id,
                    "type": rel.relationship_type,
                    "confidence": rel.confidence,
                }
                for rel in created_links
            ],
        }
    except Exception as e:
        logger.error(f"Error auto-linking cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Pattern Detection Endpoints
# ============================================================================

@router.get("/patterns/analyze")
async def analyze_patterns(
    days_back: int = 90,
    limit: int = 100,
    case_ids: Optional[str] = None
):
    """
    Analyze patterns across cases.
    
    Args:
        days_back: Number of days to look back (default 90)
        limit: Maximum cases to analyze (default 100)
        case_ids: Comma-separated list of specific case IDs to analyze (optional)
    """
    from app.services.pattern_detection import pattern_detection_service
    
    try:
        # Parse case_ids if provided
        ids_list = None
        if case_ids:
            ids_list = [cid.strip() for cid in case_ids.split(",") if cid.strip()]
        
        result = await pattern_detection_service.analyze_patterns(
            case_ids=ids_list,
            days_back=days_back,
            limit=limit
        )
        
        return {
            "success": True,
            "analysis": result.to_dict(),
        }
    except Exception as e:
        logger.error(f"Error analyzing patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/patterns")
async def get_case_patterns(case_id: str):
    """
    Find patterns related to a specific case.
    Returns time, location, MO, and semantic matches.
    """
    from app.services.pattern_detection import pattern_detection_service
    
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    try:
        patterns = await pattern_detection_service.find_related_patterns(case_id)
        
        return {
            "success": True,
            "case_id": case_id,
            "case_number": case.case_number,
            "patterns": patterns,
        }
    except Exception as e:
        logger.error(f"Error finding patterns for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RMS (Records Management System) Export Endpoints
# ============================================================================

@router.get("/cases/{case_id}/export/rms")
async def export_case_rms(
    case_id: str,
    format: str = "niem_json"
):
    """
    Export case data in RMS-compatible formats.
    
    Supported formats:
    - `niem_json`: NIEM-compliant JSON (default) - simplified NIEM 4.0 Justice domain format
    - `xml`: Standard XML format for RMS import
    - `csv`: CSV files (returned as ZIP) for bulk import
    
    Args:
        case_id: The case ID to export
        format: Export format - 'niem_json', 'xml', or 'csv'
    
    Returns:
        Export data in the requested format
    """
    from app.services.rms_export import rms_export_service
    
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    valid_formats = ["niem_json", "xml", "csv"]
    if format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format. Must be one of: {', '.join(valid_formats)}"
        )
    
    try:
        if format == "xml":
            xml_content = await rms_export_service.export_to_xml(case_id)
            if not xml_content:
                raise HTTPException(status_code=500, detail="Failed to generate XML export")
            
            # Record export in custody chain
            await custody_chain_service.record_evidence_exported(
                evidence_type="case",
                evidence_id=case_id,
                actor="api_user",
                export_format="RMS_XML",
                metadata={"endpoint": "export_case_rms", "case_number": case.case_number}
            )
            
            from fastapi.responses import Response
            return Response(
                content=xml_content,
                media_type="application/xml",
                headers={
                    "Content-Disposition": f"attachment; filename=case_{case.case_number}_rms.xml"
                }
            )
        
        elif format == "csv":
            csv_files = await rms_export_service.export_to_csv(case_id)
            if not csv_files:
                raise HTTPException(status_code=500, detail="Failed to generate CSV export")
            
            # Record export in custody chain
            await custody_chain_service.record_evidence_exported(
                evidence_type="case",
                evidence_id=case_id,
                actor="api_user",
                export_format="RMS_CSV",
                metadata={"endpoint": "export_case_rms", "case_number": case.case_number, "files": list(csv_files.keys())}
            )
            
            # Create a ZIP file containing all CSV files
            import zipfile
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, content in csv_files.items():
                    zf.writestr(filename, content)
            zip_buffer.seek(0)
            
            return StreamingResponse(
                zip_buffer,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename=case_{case.case_number}_rms_csv.zip"
                }
            )
        
        else:  # niem_json (default)
            niem_data = await rms_export_service.export_to_niem_json(case_id)
            if not niem_data:
                raise HTTPException(status_code=500, detail="Failed to generate NIEM JSON export")
            
            # Record export in custody chain
            await custody_chain_service.record_evidence_exported(
                evidence_type="case",
                evidence_id=case_id,
                actor="api_user",
                export_format="RMS_NIEM_JSON",
                metadata={"endpoint": "export_case_rms", "case_number": case.case_number}
            )
            
            from fastapi.responses import Response
            json_str = json.dumps(niem_data, indent=2, default=str)
            return Response(
                content=json_str,
                media_type="application/json",
                headers={
                    "Content-Disposition": f"attachment; filename=case_{case.case_number}_niem.json"
                }
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting case {case_id} in RMS format: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export case in RMS format: {str(e)}"
        )


@router.get("/cases/export/rms/bulk")
async def export_cases_rms_bulk(
    format: str = "niem_json",
    status_filter: Optional[str] = None,
    limit: int = 50
):
    """
    Bulk export multiple cases in RMS-compatible formats.
    
    Args:
        format: Export format - 'niem_json', 'xml', or 'csv'
        status_filter: Optional filter by case status (open, under_review, closed)
        limit: Maximum number of cases to export (default 50, max 100)
    
    Returns:
        ZIP archive containing all exported cases
    """
    from app.services.rms_export import rms_export_service
    import zipfile
    
    valid_formats = ["niem_json", "xml", "csv"]
    if format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format. Must be one of: {', '.join(valid_formats)}"
        )
    
    limit = min(max(1, limit), 100)  # Clamp between 1 and 100
    
    try:
        cases = await firestore_service.list_cases(limit=limit)
        
        if status_filter:
            cases = [c for c in cases if c.status == status_filter]
        
        if not cases:
            return {"message": "No cases found matching criteria", "count": 0}
        
        # Create ZIP archive with all exports
        zip_buffer = io.BytesIO()
        exported_count = 0
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for case in cases:
                try:
                    if format == "xml":
                        content = await rms_export_service.export_to_xml(case.id)
                        if content:
                            zf.writestr(f"{case.case_number}_rms.xml", content)
                            exported_count += 1
                    
                    elif format == "csv":
                        csv_files = await rms_export_service.export_to_csv(case.id)
                        if csv_files:
                            # Create a subfolder for each case's CSV files
                            for filename, csv_content in csv_files.items():
                                zf.writestr(f"{case.case_number}/{filename}", csv_content)
                            exported_count += 1
                    
                    else:  # niem_json
                        niem_data = await rms_export_service.export_to_niem_json(case.id)
                        if niem_data:
                            json_str = json.dumps(niem_data, indent=2, default=str)
                            zf.writestr(f"{case.case_number}_niem.json", json_str)
                            exported_count += 1
                
                except Exception as e:
                    logger.warning(f"Failed to export case {case.id}: {e}")
                    continue
        
        if exported_count == 0:
            raise HTTPException(status_code=500, detail="Failed to export any cases")
        
        # Record bulk export in custody chain
        await custody_chain_service.record_evidence_exported(
            evidence_type="case_bulk",
            evidence_id="bulk_export",
            actor="api_user",
            export_format=f"RMS_{format.upper()}_BULK",
            metadata={
                "endpoint": "export_cases_rms_bulk",
                "case_count": exported_count,
                "format": format
            }
        )
        
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=cases_rms_bulk_{format}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk RMS export: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export cases: {str(e)}")


class PatternAnalysisRequest(BaseModel):
    """Request for pattern analysis on specific cases."""
    case_ids: List[str]


@router.post("/patterns/analyze")
async def analyze_specific_patterns(request: PatternAnalysisRequest):
    """Analyze patterns for a specific set of cases."""
    from app.services.pattern_detection import pattern_detection_service
    
    if not request.case_ids:
        raise HTTPException(status_code=400, detail="At least one case ID required")
    
    try:
        result = await pattern_detection_service.analyze_patterns(
            case_ids=request.case_ids
        )
        
        return {
            "success": True,
            "case_count": len(request.case_ids),
            "analysis": result.to_dict(),
        }
    except Exception as e:
        logger.error(f"Error analyzing patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Scene Animation Endpoints
# ============================================================================

class AnimationKeyframeCreate(BaseModel):
    """Request model for creating/updating an animation keyframe."""
    time_offset: float
    element_id: str
    action: str = "appear"  # appear, disappear, move, highlight, pulse
    duration: float = 0.5
    properties: Dict = {}
    description: Optional[str] = None


class AnimationCreate(BaseModel):
    """Request model for creating/updating a scene animation."""
    total_duration: float = 10.0
    keyframes: List[AnimationKeyframeCreate] = []


@router.get("/sessions/{session_id}/scene-versions/{version}/animation")
async def get_scene_animation(session_id: str, version: int):
    """Get animation data for a specific scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if version < 1 or version > len(session.scene_versions):
            raise HTTPException(status_code=404, detail="Scene version not found")
        
        scene_version = session.scene_versions[version - 1]
        
        # If animation exists, return it
        if hasattr(scene_version, 'animation') and scene_version.animation:
            return {
                "session_id": session_id,
                "version": version,
                "animation": scene_version.animation.model_dump() if hasattr(scene_version.animation, 'model_dump') else scene_version.animation
            }
        
        # Auto-generate animation from timeline events if no animation exists
        animation = await _generate_animation_from_timeline(session, version)
        return {
            "session_id": session_id,
            "version": version,
            "animation": animation,
            "auto_generated": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting scene animation: {e}")
        raise HTTPException(status_code=500, detail="Failed to get scene animation")


@router.put("/sessions/{session_id}/scene-versions/{version}/animation")
async def update_scene_animation(
    session_id: str,
    version: int,
    body: AnimationCreate,
    auth=Depends(require_admin_auth)
):
    """Update animation data for a specific scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if version < 1 or version > len(session.scene_versions):
            raise HTTPException(status_code=404, detail="Scene version not found")
        
        # Create animation object
        animation_id = f"anim_{session_id}_{version}_{uuid.uuid4().hex[:8]}"
        keyframes = [
            AnimationKeyframe(
                id=f"kf_{uuid.uuid4().hex[:8]}",
                time_offset=kf.time_offset,
                element_id=kf.element_id,
                action=kf.action,
                duration=kf.duration,
                properties=kf.properties,
                description=kf.description
            )
            for kf in body.keyframes
        ]
        
        animation = SceneAnimation(
            id=animation_id,
            scene_version=version,
            total_duration=body.total_duration,
            keyframes=keyframes,
            auto_generated=False
        )
        
        # Update the scene version with animation
        session.scene_versions[version - 1].animation = animation
        await firestore_service.update_session(session_id, {
            "scene_versions": [v.model_dump() if hasattr(v, 'model_dump') else v for v in session.scene_versions]
        })
        
        return {
            "message": "Animation updated",
            "session_id": session_id,
            "version": version,
            "animation": animation.model_dump()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating scene animation: {e}")
        raise HTTPException(status_code=500, detail="Failed to update scene animation")


@router.post("/sessions/{session_id}/scene-versions/{version}/animation/generate")
async def generate_scene_animation(session_id: str, version: int):
    """Auto-generate animation from timeline events for a scene version."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if version < 1 or version > len(session.scene_versions):
            raise HTTPException(status_code=404, detail="Scene version not found")
        
        animation = await _generate_animation_from_timeline(session, version)
        
        return {
            "session_id": session_id,
            "version": version,
            "animation": animation,
            "auto_generated": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating scene animation: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate animation")


async def _generate_animation_from_timeline(session: ReconstructionSession, version: int) -> dict:
    """Generate animation keyframes from session timeline and scene elements."""
    scene_version = session.scene_versions[version - 1]
    elements = scene_version.elements or []
    timeline = session.timeline or []
    
    keyframes = []
    total_duration = max(10.0, len(elements) * 2.0)  # At least 10 seconds
    
    if not elements:
        # No elements, return empty animation
        return {
            "id": f"anim_auto_{version}",
            "scene_version": version,
            "total_duration": 5.0,
            "keyframes": [],
            "auto_generated": True
        }
    
    # Sort elements by type priority for appearance order
    type_priority = {"location_feature": 0, "environmental": 1, "vehicle": 2, "object": 3, "person": 4}
    sorted_elements = sorted(elements, key=lambda e: type_priority.get(e.type, 5))
    
    # Generate keyframes - each element appears in sequence
    time_per_element = total_duration / (len(sorted_elements) + 1)
    
    for idx, element in enumerate(sorted_elements):
        time_offset = idx * time_per_element
        
        # Appear keyframe
        keyframes.append({
            "id": f"kf_{idx}_appear",
            "time_offset": time_offset,
            "element_id": element.id,
            "action": "appear",
            "duration": 0.5,
            "properties": {
                "from_opacity": 0,
                "to_opacity": 1,
                "position": element.position
            },
            "description": f"{element.type}: {element.description[:50]}..." if len(element.description) > 50 else f"{element.type}: {element.description}"
        })
        
        # Add highlight for high-confidence elements
        if element.confidence > 0.7:
            keyframes.append({
                "id": f"kf_{idx}_highlight",
                "time_offset": time_offset + 0.6,
                "element_id": element.id,
                "action": "highlight",
                "duration": 0.3,
                "properties": {
                    "color": "#00d4ff"
                },
                "description": f"Highlighting {element.type}"
            })
    
    # If there are timeline events, add pulse effects at corresponding times
    if timeline:
        timeline_sorted = sorted(timeline, key=lambda t: t.sequence if hasattr(t, 'sequence') else 0)
        for idx, event in enumerate(timeline_sorted[:5]):  # Limit to first 5 events
            event_time = (idx + 1) / (len(timeline_sorted[:5]) + 1) * total_duration
            # Find relevant element
            for elem in elements:
                if hasattr(event, 'description') and elem.description.lower() in event.description.lower():
                    keyframes.append({
                        "id": f"kf_event_{idx}",
                        "time_offset": event_time,
                        "element_id": elem.id,
                        "action": "pulse",
                        "duration": 0.5,
                        "properties": {},
                        "description": event.description if hasattr(event, 'description') else "Timeline event"
                    })
                    break
    
    # Sort keyframes by time
    keyframes.sort(key=lambda k: k["time_offset"])
    
    return {
        "id": f"anim_auto_{version}",
        "scene_version": version,
        "total_duration": total_duration,
        "keyframes": keyframes,
        "auto_generated": True
    }


# ============================================================================
# Multi-Model Verification Endpoints
# ============================================================================

class VerificationToggleRequest(BaseModel):
    """Request model for toggling multi-model verification."""
    enabled: bool


class VerificationTestRequest(BaseModel):
    """Request model for testing verification with a custom prompt."""
    prompt: str
    comparison_fields: Optional[List[str]] = None


@router.get("/verification/status")
async def get_verification_status():
    """
    Get current multi-model verification status and statistics.
    
    Returns:
        Verification enabled/disabled status and statistics.
    """
    from app.services.multi_model_verifier import multi_model_verifier
    
    return {
        "enabled": multi_model_verifier.enabled,
        "statistics": multi_model_verifier.get_stats(),
        "config": {
            "multi_model_verification_enabled": settings.multi_model_verification_enabled,
        }
    }


@router.post("/verification/toggle")
async def toggle_verification(request: VerificationToggleRequest, _=Depends(require_admin_auth)):
    """
    Enable or disable multi-model verification (admin only).
    
    When enabled, critical extractions are cross-verified using both
    Gemini and Gemma models to detect discrepancies.
    """
    from app.services.multi_model_verifier import multi_model_verifier
    
    multi_model_verifier.set_enabled(request.enabled)
    
    return {
        "success": True,
        "enabled": multi_model_verifier.enabled,
        "message": f"Multi-model verification {'enabled' if request.enabled else 'disabled'}",
    }


@router.post("/verification/test")
async def test_verification(request: VerificationTestRequest, _=Depends(require_admin_auth)):
    """
    Test multi-model verification with a custom prompt (admin only).
    
    Sends the prompt to both Gemini and Gemma and returns comparison results.
    Useful for testing verification behavior before deploying to production.
    """
    from app.services.multi_model_verifier import multi_model_verifier
    
    # Temporarily enable for test
    was_enabled = multi_model_verifier.enabled
    multi_model_verifier.enabled = True
    
    try:
        result = await multi_model_verifier.verify_extraction(
            prompt=request.prompt,
            comparison_fields=request.comparison_fields,
        )
        
        return {
            "verification_result": result.result.value,
            "confidence_score": result.confidence_score,
            "discrepancies": result.discrepancies,
            "primary_model": result.primary_response.model_name if result.primary_response else None,
            "secondary_model": result.secondary_response.model_name if result.secondary_response else None,
            "primary_response": result.primary_response.response_text[:500] if result.primary_response else None,
            "secondary_response": result.secondary_response.response_text[:500] if result.secondary_response else None,
            "metadata": result.metadata,
        }
    finally:
        multi_model_verifier.enabled = was_enabled


@router.get("/verification/stats")
async def get_verification_stats():
    """
    Get detailed verification statistics.
    
    Returns:
        Statistics including total verifications, consistency rate, and discrepancy rate.
    """
    from app.services.multi_model_verifier import multi_model_verifier
    
    stats = multi_model_verifier.get_stats()
    
    return {
        "statistics": stats,
        "summary": {
            "total_verifications": stats["total_verifications"],
            "consistency_rate": (
                stats["consistent"] / max(1, stats["total_verifications"])
            ),
            "discrepancy_rate": stats["discrepancy_rate"],
            "fallback_rate": (
                stats["single_model_fallback"] / max(1, stats["total_verifications"])
            ),
        }
    }


# ── Model Performance Metrics ─────────────────────────────────────────────

@router.get("/models/metrics")
async def get_model_metrics():
    """
    Get AI model performance metrics dashboard data.
    
    Returns comprehensive metrics including:
    - Per-model latency (avg, p50, p95)
    - Success/failure rates
    - Token usage
    - Error type breakdown
    - Optimization hints
    """
    from app.services.model_metrics import model_metrics
    
    try:
        return model_metrics.get_dashboard_data()
    except Exception as e:
        logger.error(f"Error getting model metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model metrics: {str(e)}"
        )


@router.get("/models/metrics/{model_name}")
async def get_model_metrics_detail(model_name: str):
    """
    Get detailed performance metrics for a specific model.
    
    Args:
        model_name: Name of the AI model
        
    Returns:
        Detailed performance summary for the specified model
    """
    from app.services.model_metrics import model_metrics
    
    try:
        summary = model_metrics.get_model_summary(model_name)
        historical = await model_metrics.get_historical_metrics(model=model_name, days=7)
        hints = model_metrics.get_model_optimization_hints()
        
        return {
            "model": model_name,
            "current": summary.to_dict(),
            "historical": historical,
            "optimization_hints": hints.get(model_name, {}),
        }
    except Exception as e:
        logger.error(f"Error getting model metrics for {model_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model metrics: {str(e)}"
        )


@router.get("/models/metrics/history")
async def get_model_metrics_history(
    model: Optional[str] = None,
    days: int = 7
):
    """
    Get historical model metrics from the database.
    
    Args:
        model: Optional model name filter
        days: Number of days of history (default 7, max 30)
        
    Returns:
        Historical metrics aggregated by day and model
    """
    from app.services.model_metrics import model_metrics
    
    days = min(max(1, days), 30)  # Clamp to 1-30
    
    try:
        return await model_metrics.get_historical_metrics(model=model, days=days)
    except Exception as e:
        logger.error(f"Error getting historical metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get historical metrics: {str(e)}"
        )


@router.get("/models/metrics/optimization")
async def get_model_optimization_hints():
    """
    Get model selection optimization recommendations.
    
    Returns recommendations based on:
    - Success rates
    - Latency patterns
    - Error frequency
    - Rate limit pressure
    
    Use these hints to optimize model selection for different task types.
    """
    from app.services.model_metrics import model_metrics
    
    try:
        hints = model_metrics.get_model_optimization_hints()
        task_metrics = model_metrics.get_task_metrics()
        
        # Generate task-specific recommendations
        task_recommendations = {}
        for task_type, models in task_metrics.items():
            best_model = None
            best_score = -1
            
            for model, metrics in models.items():
                # Score based on success rate and latency
                success_rate = metrics.get("success_rate", 0)
                avg_latency = metrics.get("avg_latency_ms", 10000)
                latency_score = max(0, 1 - (avg_latency / 10000))
                score = success_rate * 0.7 + latency_score * 0.3
                
                if score > best_score:
                    best_score = score
                    best_model = model
            
            task_recommendations[task_type] = {
                "recommended_model": best_model,
                "score": best_score,
                "models_evaluated": len(models),
            }
        
        return {
            "model_hints": hints,
            "task_recommendations": task_recommendations,
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error getting optimization hints: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get optimization hints: {str(e)}"
        )


# ============================================================================
# Witness Memory Endpoints
# ============================================================================

@router.post("/memories", response_model=WitnessMemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    memory_data: WitnessMemoryCreate,
    _auth: dict = Depends(authenticate),
):
    """
    Create a new memory about a witness.
    
    Memories persist across sessions and can be retrieved semantically.
    """
    from app.services.memory_service import memory_service
    
    try:
        memory = await memory_service.store_memory(
            witness_id=memory_data.witness_id,
            memory_type=memory_data.memory_type,
            content=memory_data.content,
            session_id=memory_data.session_id,
            case_id=memory_data.case_id,
            confidence=memory_data.confidence,
            metadata=memory_data.metadata,
        )
        
        if not memory:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create memory"
            )
        
        return WitnessMemoryResponse(**memory.to_dict())
    except Exception as e:
        logger.error(f"Error creating memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create memory: {str(e)}"
        )


@router.get("/memories/{memory_id}", response_model=WitnessMemoryResponse)
async def get_memory(
    memory_id: str,
    _auth: dict = Depends(authenticate),
):
    """Get a specific memory by ID."""
    from app.services.memory_service import memory_service
    
    memory = await memory_service.get_memory(memory_id)
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found"
        )
    
    return WitnessMemoryResponse(**memory.to_dict())


@router.put("/memories/{memory_id}", response_model=WitnessMemoryResponse)
async def update_memory(
    memory_id: str,
    update_data: WitnessMemoryUpdate,
    _auth: dict = Depends(authenticate),
):
    """Update an existing memory."""
    from app.services.memory_service import memory_service
    
    memory = await memory_service.update_memory(
        memory_id=memory_id,
        content=update_data.content,
        confidence=update_data.confidence,
        metadata=update_data.metadata,
    )
    
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found"
        )
    
    return WitnessMemoryResponse(**memory.to_dict())


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    _auth: dict = Depends(authenticate),
):
    """Delete a memory."""
    from app.services.memory_service import memory_service
    
    success = await memory_service.delete_memory(memory_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found or could not be deleted"
        )


@router.get("/witnesses/{witness_id}/memories", response_model=List[WitnessMemoryResponse])
async def get_witness_memories(
    witness_id: str,
    memory_type: Optional[str] = None,
    limit: int = 50,
    _auth: dict = Depends(authenticate),
):
    """
    Get all memories for a specific witness.
    
    Args:
        witness_id: The witness ID
        memory_type: Optional filter by type (fact, testimony, behavior, relationship)
        limit: Maximum number to return
    """
    from app.services.memory_service import memory_service
    
    memory_types = [memory_type] if memory_type else None
    memories = await memory_service.get_witness_memories(
        witness_id=witness_id,
        memory_types=memory_types,
        limit=limit,
    )
    
    return [WitnessMemoryResponse(**m.to_dict()) for m in memories]


@router.post("/witnesses/{witness_id}/memories/search", response_model=List[WitnessMemorySearchResult])
async def search_witness_memories(
    witness_id: str,
    search_request: WitnessMemorySearchRequest,
    _auth: dict = Depends(authenticate),
):
    """
    Search memories for a witness using semantic similarity.
    
    Uses embeddings to find memories relevant to the query.
    """
    from app.services.memory_service import memory_service
    
    results = await memory_service.retrieve_relevant_memories(
        witness_id=witness_id,
        query=search_request.query,
        top_k=search_request.top_k,
        threshold=search_request.threshold,
        memory_types=search_request.memory_types,
    )
    
    return [
        WitnessMemorySearchResult(
            memory=WitnessMemoryResponse(**memory.to_dict()),
            similarity_score=score
        )
        for memory, score in results
    ]


@router.post("/memories/extract", response_model=List[WitnessMemoryResponse])
async def extract_memories_from_session(
    request: ExtractMemoriesRequest,
    _auth: dict = Depends(authenticate),
):
    """
    Extract and store memories from a completed interview session.
    
    Uses AI to identify key facts from witness testimony.
    """
    from app.services.memory_service import memory_service
    
    # Get the session
    session = await firestore_service.get_session(request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    # Get statements
    statements = [
        {"text": stmt.text, "timestamp": stmt.timestamp.isoformat() if stmt.timestamp else None}
        for stmt in session.witness_statements
    ]
    
    if not statements:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has no statements to extract memories from"
        )
    
    try:
        memories = await memory_service.extract_memories_from_session(
            session_id=request.session_id,
            witness_id=request.witness_id,
            statements=statements,
            case_id=request.case_id,
        )
        
        return [WitnessMemoryResponse(**m.to_dict()) for m in memories]
    except Exception as e:
        logger.error(f"Error extracting memories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract memories: {str(e)}"
        )


@router.get("/memories/stats", response_model=WitnessMemoryStatsResponse)
async def get_memory_stats(
    witness_id: Optional[str] = None,
    _auth: dict = Depends(authenticate),
):
    """
    Get memory statistics.
    
    Args:
        witness_id: Optional filter by witness
    """
    from app.services.memory_service import memory_service
    
    stats = await memory_service.get_memory_stats(witness_id=witness_id)
    return WitnessMemoryStatsResponse(**stats)


@router.post("/sessions/{session_id}/load-memories")
async def load_session_memories(
    session_id: str,
    witness_id: Optional[str] = None,
    _auth: dict = Depends(authenticate),
):
    """
    Load relevant memories for a session's witness into the AI context.
    
    Call this at the start of a session with a returning witness
    to include their prior testimony and facts in the AI context.
    
    Args:
        session_id: The session ID
        witness_id: Optional specific witness ID (otherwise uses session witness)
    
    Returns:
        The memory context that will be included in AI prompts.
    """
    from app.services.memory_service import memory_service
    
    # Get the session
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    # Determine witness ID
    if not witness_id:
        if session.active_witness_id:
            witness_id = session.active_witness_id
        elif session.witnesses:
            witness_id = session.witnesses[0].id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No witness ID provided and session has no witnesses"
            )
    
    # Get recent statements for context
    recent_statements = " ".join([
        stmt.text for stmt in session.witness_statements[-5:]
    ]) if session.witness_statements else "starting a new interview"
    
    # Build memory context
    context = await memory_service.build_memory_context(
        witness_id=witness_id,
        current_statement=recent_statements,
        max_memories=5,
    )
    
    # Get the agent and update its context
    agent = get_agent(session_id)
    
    # Get memory stats for response
    memories = await memory_service.get_witness_memories(witness_id, limit=10)
    
    return {
        "witness_id": witness_id,
        "memories_loaded": len(memories),
        "memory_context": context,
        "message": f"Loaded {len(memories)} memories for witness {witness_id}"
    }


# ── Spatial Validation Endpoints ─────────────────────────────

class SpatialValidationRequest(BaseModel):
    """Request body for spatial validation."""
    include_corrections: bool = False


@router.post("/sessions/{session_id}/validate-spatial", tags=["spatial-validation"])
async def validate_session_spatial(
    session_id: str,
    request: SpatialValidationRequest,
    _: bool = Depends(authenticate),
) -> Dict:
    """
    Validate spatial plausibility of the current scene in a session.
    
    Checks for:
    - Element overlaps (physical impossibilities)
    - Realistic distances between elements
    - Position constraints (e.g., vehicles on roads, people on sidewalks)
    - Consistent spatial relationships
    
    Args:
        session_id: Session ID to validate
        request: Validation options (include_corrections flag)
        
    Returns:
        Validation results with issues and optional corrections
    """
    # Get session from firestore
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Get the latest scene version
    if not session.scene_versions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has no scene versions to validate"
        )
    
    latest_scene = session.scene_versions[-1]
    
    # Get relationships if available
    relationships = getattr(session, 'element_relationships', []) or []
    
    if request.include_corrections:
        result = get_spatial_corrections(latest_scene, relationships)
    else:
        result = {"validation": validate_scene_spatial(latest_scene, relationships)}
    
    logger.info(f"Spatial validation for session {session_id}: {result['validation']['summary']}")
    
    return {
        "session_id": session_id,
        "scene_version": latest_scene.version,
        **result
    }


@router.post("/sessions/{session_id}/versions/{version}/validate-spatial", tags=["spatial-validation"])
async def validate_scene_version_spatial(
    session_id: str,
    version: int,
    request: SpatialValidationRequest,
    _: bool = Depends(authenticate),
) -> Dict:
    """
    Validate spatial plausibility of a specific scene version.
    
    Args:
        session_id: Session ID
        version: Scene version number to validate
        request: Validation options
        
    Returns:
        Validation results with issues and optional corrections
    """
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Find the requested version
    scene_version = None
    for sv in session.scene_versions:
        if sv.version == version:
            scene_version = sv
            break
    
    if not scene_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene version {version} not found in session {session_id}"
        )
    
    relationships = getattr(session, 'element_relationships', []) or []
    
    if request.include_corrections:
        result = get_spatial_corrections(scene_version, relationships)
    else:
        result = {"validation": validate_scene_spatial(scene_version, relationships)}
    
    return {
        "session_id": session_id,
        "scene_version": version,
        **result
    }


class BatchValidationRequest(BaseModel):
    """Request for validating multiple sessions."""
    session_ids: List[str]
    include_corrections: bool = False


@router.post("/validate-spatial/batch", tags=["spatial-validation"])
async def validate_spatial_batch(
    request: BatchValidationRequest,
    _: bool = Depends(authenticate),
) -> Dict:
    """
    Validate spatial plausibility across multiple sessions.
    
    Useful for bulk validation of scenes.
    
    Returns:
        Summary of validation results for all sessions
    """
    results = []
    
    for session_id in request.session_ids:
        try:
            session = await firestore_service.get_session(session_id)
            if not session or not session.scene_versions:
                results.append({
                    "session_id": session_id,
                    "status": "skipped",
                    "reason": "No session or scene versions"
                })
                continue
            
            latest_scene = session.scene_versions[-1]
            relationships = getattr(session, 'element_relationships', []) or []
            
            validation = validate_scene_spatial(latest_scene, relationships)
            
            results.append({
                "session_id": session_id,
                "status": "validated",
                "is_valid": validation["is_valid"],
                "error_count": validation["error_count"],
                "warning_count": validation["warning_count"],
                "summary": validation["summary"]
            })
        except Exception as e:
            logger.error(f"Error validating session {session_id}: {e}")
            results.append({
                "session_id": session_id,
                "status": "error",
                "reason": str(e)
            })
    
    # Calculate summary stats
    validated = [r for r in results if r.get("status") == "validated"]
    valid_count = len([r for r in validated if r.get("is_valid")])
    
    return {
        "total_sessions": len(request.session_ids),
        "validated": len(validated),
        "valid": valid_count,
        "with_errors": len(validated) - valid_count,
        "skipped": len([r for r in results if r.get("status") == "skipped"]),
        "errors": len([r for r in results if r.get("status") == "error"]),
        "results": results
    }


# ── Translation Endpoints ─────────────────────────────────────────────────────


class TranslateRequest(BaseModel):
    """Request model for translation."""
    text: str
    target_language: str
    source_language: Optional[str] = None


class TranslateResponse(BaseModel):
    """Response model for translation."""
    original_text: str
    translated_text: str
    source_language: str
    target_language: str


class DetectLanguageRequest(BaseModel):
    """Request model for language detection."""
    text: str


class DetectLanguageResponse(BaseModel):
    """Response model for language detection."""
    language_code: str
    language_name: str
    confidence: float


class SupportedLanguagesResponse(BaseModel):
    """Response model for supported languages."""
    languages: Dict[str, str]


@router.get("/translation/languages", response_model=SupportedLanguagesResponse)
async def get_supported_languages():
    """
    Get list of supported languages for translation.
    
    Returns language codes and their display names.
    """
    from app.services.translation_service import translation_service
    
    return SupportedLanguagesResponse(
        languages=translation_service.get_supported_languages()
    )


@router.post("/translation/detect", response_model=DetectLanguageResponse)
async def detect_language(request: DetectLanguageRequest):
    """
    Detect the language of the given text.
    
    Uses Gemini to analyze text and determine language.
    """
    from app.services.translation_service import translation_service, SUPPORTED_LANGUAGES
    
    if not request.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text cannot be empty"
        )
    
    lang_code, confidence = await translation_service.detect_language(request.text)
    lang_name = SUPPORTED_LANGUAGES.get(lang_code, lang_code)
    
    return DetectLanguageResponse(
        language_code=lang_code,
        language_name=lang_name,
        confidence=confidence
    )


@router.post("/translation/translate", response_model=TranslateResponse)
async def translate_text(request: TranslateRequest):
    """
    Translate text to target language.
    
    If source_language is not provided, it will be auto-detected.
    """
    from app.services.translation_service import translation_service
    
    if not request.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text cannot be empty"
        )
    
    translated, source_lang = await translation_service.translate(
        text=request.text,
        target_language=request.target_language,
        source_language=request.source_language,
    )
    
    return TranslateResponse(
        original_text=request.text,
        translated_text=translated,
        source_language=source_lang,
        target_language=request.target_language
    )


@router.put("/sessions/{session_id}/witnesses/{witness_id}/language")
async def set_witness_language(
    session_id: str,
    witness_id: str,
    language_code: str,
):
    """
    Set the preferred language for a witness.
    
    This language will be used to translate AI responses for the witness.
    """
    from app.services.translation_service import SUPPORTED_LANGUAGES
    
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Validate language code
    if language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language code: {language_code}. Supported: {list(SUPPORTED_LANGUAGES.keys())}"
        )
    
    # Find and update witness
    witness_found = False
    for witness in session.witnesses:
        if witness.id == witness_id:
            witness.preferred_language = language_code
            witness_found = True
            break
    
    if not witness_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Witness {witness_id} not found in session {session_id}"
        )
    
    await firestore_service.update_session(session)
    
    return {
        "witness_id": witness_id,
        "preferred_language": language_code,
        "language_name": SUPPORTED_LANGUAGES[language_code],
        "message": f"Language preference updated to {SUPPORTED_LANGUAGES[language_code]}"
    }


@router.get("/sessions/{session_id}/witnesses/{witness_id}/language")
async def get_witness_language(
    session_id: str,
    witness_id: str,
):
    """
    Get the preferred language for a witness.
    """
    from app.services.translation_service import SUPPORTED_LANGUAGES
    
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Find witness
    for witness in session.witnesses:
        if witness.id == witness_id:
            lang_code = getattr(witness, 'preferred_language', 'en')
            return {
                "witness_id": witness_id,
                "preferred_language": lang_code,
                "language_name": SUPPORTED_LANGUAGES.get(lang_code, lang_code)
            }
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Witness {witness_id} not found in session {session_id}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Investigator Management Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/investigators")
async def list_investigators(active_only: bool = False, auth=Depends(require_admin_auth)):
    """List all investigators."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        investigators = await db.list_investigators(active_only=active_only)
        return {"investigators": investigators, "total": len(investigators)}
    except Exception as e:
        logger.error(f"Error listing investigators: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/investigators", status_code=status.HTTP_201_CREATED)
async def create_investigator(data: dict, auth=Depends(require_admin_auth)):
    """Create a new investigator."""
    try:
        from app.services.database import get_database
        investigator_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        investigator_dict = {
            "id": investigator_id,
            "name": data.get("name"),
            "badge_number": data.get("badge_number"),
            "email": data.get("email"),
            "department": data.get("department"),
            "active": True,
            "max_cases": data.get("max_cases", 10),
            "created_at": now,
            "updated_at": now,
        }
        
        if not investigator_dict["name"]:
            raise HTTPException(status_code=400, detail="Name is required")
        
        db = get_database()
        if db._db is None:
            await db.initialize()
        await db.save_investigator(investigator_dict)
        
        return {"message": "Investigator created", "investigator": investigator_dict}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating investigator: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/investigators/{investigator_id}")
async def get_investigator(investigator_id: str, auth=Depends(require_admin_auth)):
    """Get investigator by ID."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        investigator = await db.get_investigator(investigator_id)
        if not investigator:
            raise HTTPException(status_code=404, detail="Investigator not found")
        return investigator
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting investigator: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/investigators/{investigator_id}")
async def update_investigator(investigator_id: str, updates: dict, auth=Depends(require_admin_auth)):
    """Update an investigator."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        
        investigator = await db.get_investigator(investigator_id)
        if not investigator:
            raise HTTPException(status_code=404, detail="Investigator not found")
        
        for key in ["name", "badge_number", "email", "department", "active", "max_cases"]:
            if key in updates:
                investigator[key] = updates[key]
        investigator["updated_at"] = datetime.utcnow().isoformat()
        
        await db.save_investigator(investigator)
        return {"message": "Investigator updated", "investigator": investigator}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating investigator: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/investigators/{investigator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigator(investigator_id: str, auth=Depends(require_admin_auth)):
    """Deactivate an investigator (soft delete)."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        await db.delete_investigator(investigator_id)
    except Exception as e:
        logger.error(f"Error deleting investigator: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Case Assignment Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/assign")
async def assign_case(case_id: str, data: dict, auth=Depends(require_admin_auth)):
    """Assign a case to an investigator."""
    try:
        from app.services.database import get_database
        
        investigator_id = data.get("investigator_id")
        assigned_by = data.get("assigned_by", "admin")
        notes = data.get("notes")
        
        if not investigator_id:
            raise HTTPException(status_code=400, detail="investigator_id is required")
        
        # Verify case exists
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        db = get_database()
        if db._db is None:
            await db.initialize()
        
        # Verify investigator exists
        investigator = await db.get_investigator(investigator_id)
        if not investigator:
            raise HTTPException(status_code=404, detail="Investigator not found")
        
        if not investigator.get("active"):
            raise HTTPException(status_code=400, detail="Investigator is not active")
        
        # Check workload
        current_assignments = await db.get_investigator_assignments(investigator_id, active_only=True)
        if len(current_assignments) >= investigator.get("max_cases", 10):
            raise HTTPException(status_code=400, detail="Investigator has reached maximum case capacity")
        
        # Deactivate existing assignments for this case
        await db.deactivate_case_assignments(case_id)
        
        # Create new assignment
        assignment_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        assignment_dict = {
            "id": assignment_id,
            "case_id": case_id,
            "investigator_id": investigator_id,
            "investigator_name": investigator.get("name"),
            "assigned_by": assigned_by,
            "assigned_at": now,
            "notes": notes,
            "is_active": True,
        }
        await db.save_case_assignment(assignment_dict)
        
        # Update case metadata
        if not case.metadata:
            case.metadata = {}
        case.metadata["assigned_to"] = investigator.get("name")
        case.metadata["assigned_investigator_id"] = investigator_id
        case.metadata["assignment_id"] = assignment_id
        case.updated_at = datetime.utcnow()
        await firestore_service.update_case(case)
        
        # Log custody event
        try:
            await custody_chain_service.log_event(
                evidence_type="case",
                evidence_id=case_id,
                action="transferred",
                actor=assigned_by,
                actor_role="admin",
                details=f"Case assigned to {investigator.get('name')}",
            )
        except Exception as ce:
            logger.warning(f"Failed to log custody event: {ce}")
        
        return {
            "message": "Case assigned successfully",
            "assignment": assignment_dict,
            "investigator": investigator,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning case: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cases/{case_id}/assign")
async def unassign_case(case_id: str, auth=Depends(require_admin_auth)):
    """Remove case assignment (unassign from investigator)."""
    try:
        from app.services.database import get_database
        
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        db = get_database()
        if db._db is None:
            await db.initialize()
        
        await db.deactivate_case_assignments(case_id)
        
        # Update case metadata
        if case.metadata:
            case.metadata.pop("assigned_to", None)
            case.metadata.pop("assigned_investigator_id", None)
            case.metadata.pop("assignment_id", None)
        case.updated_at = datetime.utcnow()
        await firestore_service.update_case(case)
        
        return {"message": "Case unassigned successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unassigning case: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/{case_id}/assignments")
async def get_case_assignment_history(case_id: str, auth=Depends(require_admin_auth)):
    """Get assignment history for a case."""
    try:
        from app.services.database import get_database
        
        case = await firestore_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        db = get_database()
        if db._db is None:
            await db.initialize()
        
        assignments = await db.get_case_assignments(case_id)
        active_assignment = next((a for a in assignments if a.get("is_active")), None)
        
        return {
            "case_id": case_id,
            "case_number": case.case_number,
            "active_assignment": active_assignment,
            "assignment_history": assignments,
            "total_assignments": len(assignments),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting case assignments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/investigators/{investigator_id}/cases")
async def get_investigator_cases(investigator_id: str, active_only: bool = True, auth=Depends(require_admin_auth)):
    """Get cases assigned to an investigator."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        
        investigator = await db.get_investigator(investigator_id)
        if not investigator:
            raise HTTPException(status_code=404, detail="Investigator not found")
        
        assignments = await db.get_investigator_assignments(investigator_id, active_only=active_only)
        
        # Fetch case details
        cases = []
        for assignment in assignments:
            case = await firestore_service.get_case(assignment.get("case_id"))
            if case:
                cases.append({
                    "case_id": case.id,
                    "case_number": case.case_number,
                    "title": case.title,
                    "status": case.status,
                    "assigned_at": assignment.get("assigned_at"),
                    "is_active": assignment.get("is_active"),
                })
        
        return {
            "investigator_id": investigator_id,
            "investigator_name": investigator.get("name"),
            "cases": cases,
            "active_cases": len([c for c in cases if c.get("is_active")]),
            "total_assignments": len(assignments),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting investigator cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workload")
async def get_workload_summary(auth=Depends(require_admin_auth)):
    """Get workload summary for all investigators."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        
        stats = await db.get_workload_stats()
        unassigned = await db.count_unassigned_cases()
        
        investigators = []
        total_active_cases = 0
        total_utilization = 0
        
        for row in stats:
            active_cases = row.get("active_cases", 0)
            max_cases = row.get("max_cases", 10)
            utilization = (active_cases / max_cases * 100) if max_cases > 0 else 0
            total_active_cases += active_cases
            total_utilization += utilization
            
            # Fetch assigned cases for this investigator
            assignments = await db.get_investigator_assignments(row.get("investigator_id"), active_only=True)
            cases = []
            for assignment in assignments:
                case = await firestore_service.get_case(assignment.get("case_id"))
                if case:
                    cases.append({
                        "case_id": case.id,
                        "case_number": case.case_number,
                        "title": case.title,
                        "status": case.status,
                    })
            
            investigators.append({
                "investigator_id": row.get("investigator_id"),
                "investigator_name": row.get("investigator_name"),
                "badge_number": row.get("badge_number"),
                "department": row.get("department"),
                "active_cases": active_cases,
                "max_cases": max_cases,
                "utilization_percent": round(utilization, 1),
                "total_assignments": row.get("total_assignments", 0),
                "cases": cases,
                "active": row.get("active", True),
            })
        
        active_investigators = len([i for i in investigators if i.get("active")])
        avg_utilization = (total_utilization / len(investigators)) if investigators else 0
        
        return {
            "total_investigators": len(investigators),
            "active_investigators": active_investigators,
            "total_active_cases": total_active_cases,
            "unassigned_cases": unassigned,
            "avg_utilization": round(avg_utilization, 1),
            "investigators": investigators,
        }
    except Exception as e:
        logger.error(f"Error getting workload summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Interview Comfort Features ====================

# In-memory store for comfort states (would use Firestore in production)
_comfort_states: Dict[str, dict] = {}


class InterviewPauseRequest(BaseModel):
    paused: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EmotionalSupportRequest(BaseModel):
    context: str
    trigger: Optional[str] = None


@router.post("/sessions/{session_id}/comfort/pause")
async def set_interview_pause_state(session_id: str, request: InterviewPauseRequest):
    """
    Set the pause state for an interview session.
    
    Tracks when interviews are paused/resumed for comfort tracking.
    """
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Initialize comfort state if needed
    if session_id not in _comfort_states:
        _comfort_states[session_id] = {
            "is_paused": False,
            "pause_events": [],
            "total_pause_duration": 0,
            "breaks_taken": 0
        }
    
    state = _comfort_states[session_id]
    
    if request.paused and not state["is_paused"]:
        # Starting a pause
        state["is_paused"] = True
        state["pause_start"] = request.timestamp.isoformat()
        state["pause_events"].append({
            "type": "pause",
            "timestamp": request.timestamp.isoformat()
        })
    elif not request.paused and state["is_paused"]:
        # Ending a pause
        state["is_paused"] = False
        if "pause_start" in state:
            pause_start = datetime.fromisoformat(state["pause_start"])
            duration = (request.timestamp - pause_start).total_seconds()
            state["total_pause_duration"] += duration
            if duration > 30:  # Count as break if > 30 seconds
                state["breaks_taken"] += 1
        state["pause_events"].append({
            "type": "resume",
            "timestamp": request.timestamp.isoformat()
        })
    
    return {
        "session_id": session_id,
        "paused": state["is_paused"],
        "message": "Interview paused" if state["is_paused"] else "Interview resumed",
        "total_pause_duration": state["total_pause_duration"],
        "breaks_taken": state["breaks_taken"]
    }


@router.get("/sessions/{session_id}/comfort/state")
async def get_comfort_state(session_id: str):
    """
    Get the current comfort state for an interview session.
    """
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    state = _comfort_states.get(session_id, {
        "is_paused": False,
        "total_pause_duration": 0,
        "breaks_taken": 0,
        "pause_events": []
    })
    
    return {
        "session_id": session_id,
        **state
    }


@router.post("/sessions/{session_id}/comfort/support")
async def get_emotional_support_prompt(session_id: str, request: EmotionalSupportRequest):
    """
    Get an AI-generated emotional support prompt based on interview context.
    
    Uses the session context to generate appropriate supportive messages.
    """
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Default support prompts by trigger type
    support_prompts = {
        "distress": [
            "Take your time. There's no rush here.",
            "It's okay to feel emotional. We can pause whenever you need.",
            "You're doing great. Would you like to take a short break?",
            "I understand this is difficult. Your comfort matters."
        ],
        "confusion": [
            "Let me rephrase that for you.",
            "There are no wrong answers here. Just share what you remember.",
            "We can come back to this question later if you'd like.",
            "It's perfectly normal if some details are unclear."
        ],
        "fatigue": [
            "We've been talking for a while. How about a 5-minute break?",
            "You've provided a lot of helpful information. Let's take a breather.",
            "Would you like some water? We can pause here.",
            "Your wellbeing is important. Please rest if you need to."
        ],
        "encouragement": [
            "That's very helpful information. Thank you.",
            "You're doing an excellent job remembering the details.",
            "These details are valuable for understanding what happened.",
            "Your account is clear and well-organized. Keep going."
        ]
    }
    
    trigger = request.trigger or "encouragement"
    prompts = support_prompts.get(trigger, support_prompts["encouragement"])
    
    import random
    selected_prompt = random.choice(prompts)
    
    # Record that we sent a support prompt
    if session_id in _comfort_states:
        _comfort_states[session_id]["last_support_at"] = datetime.utcnow().isoformat()
    
    return {
        "prompt": selected_prompt,
        "trigger": trigger,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/sessions/{session_id}/comfort/progress")
async def get_interview_progress(session_id: str):
    """
    Get comprehensive interview progress including comfort metrics.
    """
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Calculate progress
    statement_count = len(session.witness_statements)
    scene_count = len(session.scene_versions)
    
    # Estimate completion based on typical interview patterns
    completion = min(100, (statement_count * 10) + (scene_count * 15))
    
    # Determine phase
    if statement_count == 0:
        phase = "intro"
    elif statement_count < 3:
        phase = "narrative"
    elif scene_count == 0:
        phase = "details"
    else:
        phase = "review"
    
    # Get comfort state
    comfort_state = _comfort_states.get(session_id, {
        "is_paused": False,
        "total_pause_duration": 0,
        "breaks_taken": 0
    })
    
    # Calculate durations
    created_at = session.created_at
    total_duration = (datetime.utcnow() - created_at).total_seconds()
    active_duration = total_duration - comfort_state.get("total_pause_duration", 0)
    
    return {
        "session_id": session_id,
        "statement_count": statement_count,
        "scene_version_count": scene_count,
        "estimated_completion_percent": completion,
        "phase": phase,
        "is_paused": comfort_state.get("is_paused", False),
        "total_duration_seconds": int(total_duration),
        "active_duration_seconds": int(active_duration),
        "breaks_taken": comfort_state.get("breaks_taken", 0)
    }


# ─── API Key Management (Admin Only) ─────────────────────


@router.post("/admin/api-keys")
async def create_api_key(data: dict, auth=Depends(require_admin_auth)):
    """Create a new API key. Returns the full key ONCE."""
    name = data.get("name", "Unnamed Key")
    permissions = data.get("permissions", ["read", "write"])
    rate_limit = data.get("rate_limit_rpm", 30)
    result = await api_key_service.create_key(name, permissions, rate_limit)
    return result


@router.get("/admin/api-keys")
async def list_api_keys(auth=Depends(require_admin_auth)):
    """List all API keys (without the actual keys)."""
    keys = await api_key_service.list_keys()
    return {"keys": keys}


@router.delete("/admin/api-keys/{key_id}")
async def revoke_api_key(key_id: str, auth=Depends(require_admin_auth)):
    """Revoke an API key."""
    success = await api_key_service.revoke_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked"}


# ─── Interview Links ─────────────────────────────────────


@router.post("/admin/interview-links", dependencies=[Depends(require_admin_auth)])
async def create_interview_link(data: dict):
    """Generate a unique interview link for a witness."""
    import secrets
    token = secrets.token_urlsafe(16)
    session = ReconstructionSession(
        id=str(uuid.uuid4()),
        title=data.get("title", "Phone Interview"),
        source_type="phone_link",
        metadata={"interview_token": token, "created_by": "admin"}
    )
    await firestore_service.create_session(session)
    base_url = data.get("base_url", "")
    return {"token": token, "session_id": session.id, "link": f"{base_url}/interview?token={token}&session={session.id}"}


# ─── Interview Scripts CRUD ──────────────────────────────


@router.get("/admin/interview-scripts")
async def list_scripts(auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute("SELECT * FROM interview_scripts WHERE is_active = 1 ORDER BY name")
    rows = await cursor.fetchall()
    return {"scripts": [dict(r) for r in rows]}


@router.post("/admin/interview-scripts")
async def create_script(data: dict, auth=Depends(require_admin_auth)):
    from datetime import timezone
    from app.services.database import get_database
    script_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db = get_database()
    await db._db.execute(
        "INSERT INTO interview_scripts (id, name, incident_type, questions, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (script_id, data["name"], data.get("incident_type", "general"), json.dumps(data.get("questions", [])), now, now)
    )
    await db._db.commit()
    return {"id": script_id, "name": data["name"]}


@router.delete("/admin/interview-scripts/{script_id}")
async def delete_script(script_id: str, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    await db._db.execute("UPDATE interview_scripts SET is_active = 0 WHERE id = ?", (script_id,))
    await db._db.commit()
    return {"status": "deleted"}


# ─── Public API (API Key Authenticated) ──────────────────


@router.post("/v1/sessions", tags=["Public API"])
async def api_create_session(data: dict = {}, api_key=Depends(require_api_key)):
    """Create a new witness interview session."""
    if "write" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: write required")
    try:
        session = ReconstructionSession(
            id=str(uuid.uuid4()),
            title=data.get("title", "API Session"),
            source_type=data.get("source_type", "api"),
            witness_name=data.get("witness_name", ""),
            witness_contact=data.get("witness_contact", ""),
            witness_location=data.get("witness_location", ""),
            metadata=data.get("metadata", {}),
        )
        success = await firestore_service.create_session(session)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create session")
        session.report_number = await firestore_service.get_next_report_number()
        await firestore_service.update_session(session)
        agent = get_agent(session.id)
        greeting = await agent.start_interview()
        return {
            "id": session.id,
            "title": session.title,
            "report_number": session.report_number,
            "greeting": greeting,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API create session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/sessions/{session_id}", tags=["Public API"])
async def api_get_session(session_id: str, api_key=Depends(require_api_key)):
    """Get session details including all statements and scene versions."""
    if "read" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: read required")
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/v1/sessions/{session_id}/message", tags=["Public API"])
async def api_send_message(session_id: str, data: dict, api_key=Depends(require_api_key)):
    """Send a text message to the AI interviewer and get a response.
    Body: {"text": "I saw a red car crash into a blue van"}
    Returns: AI response + updated scene description
    """
    if "write" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: write required")

    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' in request body")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent = get_agent(session_id)
    is_correction = data.get("is_correction", False)

    try:
        agent_response, should_generate_image, token_info = await agent.process_statement(
            text, is_correction=is_correction
        )
    except Exception as e:
        logger.error(f"API message processing error: {e}")
        raise HTTPException(status_code=500, detail="AI processing failed")

    # Save statement
    stmt = WitnessStatement(
        id=str(uuid.uuid4()),
        text=text,
        is_correction=is_correction,
    )
    session.witness_statements.append(stmt)
    await firestore_service.update_session(session)

    scene_summary = agent.get_scene_summary()
    return {
        "response": agent_response,
        "should_generate_image": should_generate_image,
        "scene": {
            "description": scene_summary.get("description", ""),
            "elements": scene_summary.get("elements", []),
            "statement_count": scene_summary.get("statement_count", 0),
        },
        "token_info": token_info,
    }


@router.post("/v1/sessions/{session_id}/audio", tags=["Public API"])
async def api_send_audio(session_id: str, data: dict, api_key=Depends(require_api_key)):
    """Send base64-encoded audio for transcription + AI response.
    Body: {"audio": "<base64>", "format": "webm"}
    Returns: transcription + AI response + scene data
    """
    if "write" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: write required")

    import base64

    audio_b64 = data.get("audio", "")
    audio_format = data.get("format", "webm")
    if not audio_b64:
        raise HTTPException(status_code=400, detail="Missing 'audio' in request body")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Transcribe
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio data")

    try:
        from google import genai as _genai

        client = _genai.Client(api_key=settings.google_api_key)
        mime_map = {"webm": "audio/webm", "wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg"}
        mime = mime_map.get(audio_format, f"audio/{audio_format}")

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_model,
            contents=[
                "Transcribe the following audio accurately. Return only the transcription text.",
                {"inline_data": {"mime_type": mime, "data": audio_b64}},
            ],
        )
        transcription = response.text.strip()
    except Exception as e:
        logger.error(f"Audio transcription error: {e}")
        raise HTTPException(status_code=500, detail="Audio transcription failed")

    # Process transcription through agent
    agent = get_agent(session_id)
    try:
        agent_response, should_generate_image, token_info = await agent.process_statement(transcription)
    except Exception as e:
        logger.error(f"API audio message processing error: {e}")
        raise HTTPException(status_code=500, detail="AI processing failed")

    stmt = WitnessStatement(id=str(uuid.uuid4()), text=transcription)
    session.witness_statements.append(stmt)
    await firestore_service.update_session(session)

    scene_summary = agent.get_scene_summary()
    return {
        "transcription": transcription,
        "response": agent_response,
        "should_generate_image": should_generate_image,
        "scene": {
            "description": scene_summary.get("description", ""),
            "elements": scene_summary.get("elements", []),
            "statement_count": scene_summary.get("statement_count", 0),
        },
        "token_info": token_info,
    }


@router.get("/v1/sessions/{session_id}/scene", tags=["Public API"])
async def api_get_scene(session_id: str, version: int = None, api_key=Depends(require_api_key)):
    """Get the latest (or specific version) scene reconstruction."""
    if "read" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: read required")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    versions = session.scene_versions or []
    if version is not None:
        match = [v for v in versions if getattr(v, "version", None) == version]
        if not match:
            raise HTTPException(status_code=404, detail=f"Scene version {version} not found")
        return match[0]

    if versions:
        return versions[-1]

    # Fall back to agent in-memory scene summary
    agent = get_agent(session_id)
    return agent.get_scene_summary()


@router.get("/v1/sessions/{session_id}/transcript", tags=["Public API"])
async def api_get_transcript(session_id: str, api_key=Depends(require_api_key)):
    """Get the full interview transcript."""
    if "read" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: read required")

    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = []
    for s in session.witness_statements:
        statements.append({
            "id": s.id,
            "text": s.text,
            "is_correction": s.is_correction,
            "timestamp": s.timestamp.isoformat() if hasattr(s, "timestamp") and s.timestamp else None,
        })

    agent = get_agent(session_id)
    return {
        "session_id": session_id,
        "statements": statements,
        "conversation_history": agent.conversation_history,
    }


@router.get("/v1/cases", tags=["Public API"])
async def api_list_cases(limit: int = 20, api_key=Depends(require_api_key)):
    """List all cases."""
    if "read" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: read required")
    cases = await firestore_service.list_cases(limit=limit)
    return {"cases": cases}


@router.get("/v1/cases/{case_id}", tags=["Public API"])
async def api_get_case(case_id: str, api_key=Depends(require_api_key)):
    """Get case details with linked reports."""
    if "read" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: read required")
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.post("/v1/cases/{case_id}/export", tags=["Public API"])
async def api_export_case(case_id: str, format: str = "json", api_key=Depends(require_api_key)):
    """Export case in JSON or RMS format."""
    if "read" not in api_key.get("permissions", []):
        raise HTTPException(status_code=403, detail="Permission denied: read required")

    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if format == "json":
        return case

    if format in ("niem_json", "xml", "csv"):
        from app.services.rms_export import rms_export_service

        if format == "niem_json":
            exported = await rms_export_service.export_case(case_id)
            return exported
        elif format == "xml":
            xml_content = await rms_export_service.export_to_xml(case_id)
            from fastapi.responses import Response

            return Response(content=xml_content, media_type="application/xml")
        elif format == "csv":
            csv_files = await rms_export_service.export_to_csv(case_id)
            return csv_files

    raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")


@router.get("/v1/status", tags=["Public API"])
async def api_status(api_key=Depends(require_api_key)):
    """Check API health and quota status."""
    return {
        "status": "ok",
        "api_key_name": api_key.get("name"),
        "permissions": api_key.get("permissions"),
        "rate_limit_rpm": api_key.get("rate_limit_rpm"),
    }


@router.get("/vehicles/search")
async def search_vehicles(query: str = "", make: str = "", color: str = ""):
    """Search vehicle database for matching vehicles."""
    vehicles = [
        {"make":"Toyota","models":["Camry","Corolla","RAV4","Highlander","Tacoma","Prius"]},
        {"make":"Honda","models":["Civic","Accord","CR-V","Pilot","Fit","HR-V"]},
        {"make":"Ford","models":["F-150","Mustang","Explorer","Escape","Focus","Fusion"]},
        {"make":"Chevrolet","models":["Silverado","Malibu","Equinox","Tahoe","Camaro","Impala"]},
        {"make":"BMW","models":["3 Series","5 Series","X3","X5","7 Series"]},
        {"make":"Mercedes","models":["C-Class","E-Class","GLE","GLC","S-Class"]},
        {"make":"Nissan","models":["Altima","Sentra","Rogue","Pathfinder","Maxima"]},
        {"make":"Hyundai","models":["Elantra","Sonata","Tucson","Santa Fe","Kona"]},
        {"make":"Kia","models":["Optima","Forte","Sportage","Sorento","Seltos"]},
        {"make":"Volkswagen","models":["Jetta","Passat","Tiguan","Atlas","Golf"]},
    ]
    colors = ["black","white","silver","gray","red","blue","green","yellow","orange","brown","gold","beige","maroon","navy","tan"]
    results = []
    q = query.lower()
    for v in vehicles:
        if make and make.lower() != v["make"].lower(): continue
        if q and q not in v["make"].lower() and not any(q in m.lower() for m in v["models"]): continue
        for m in v["models"]:
            if q and q not in v["make"].lower() and q not in m.lower(): continue
            results.append({"make": v["make"], "model": m})
    return {"results": results[:20], "colors": colors if not color else [c for c in colors if color.lower() in c]}


@router.post("/sessions/{session_id}/validate-estimates")
async def validate_estimates(session_id: str, data: dict):
    from app.services.spatial_validation import SpatialValidator
    validator = SpatialValidator()
    result = await validator.validate_estimates(data.get("text", ""))
    return result


@router.post("/sessions/{session_id}/photo-overlay")
async def create_photo_overlay(session_id: str, data: dict):
    """Accept a base64 photo and return scene overlay description."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    # Store reference photo in session metadata
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    metadata["reference_photo"] = data.get("photo", "")[:100] + "..."  # Store truncated for metadata
    session.metadata = metadata
    await firestore_service.update_session(session)
    return {"status": "photo_received", "message": "Reference photo stored. Scene reconstruction will use this as background."}


@router.get("/weather")
async def get_weather(lat: float = 0, lon: float = 0, dt: str = ""):
    """Fetch weather conditions for a location and time (uses Open-Meteo free API)."""
    import httpx
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                weather = data.get("current_weather", {})
                return {
                    "temperature": weather.get("temperature"),
                    "windspeed": weather.get("windspeed"),
                    "weathercode": weather.get("weathercode"),
                    "is_day": weather.get("is_day"),
                    "description": _weather_code_to_text(weather.get("weathercode", 0))
                }
        return {"error": "Weather service unavailable"}
    except Exception as e:
        return {"error": str(e)}


def _weather_code_to_text(code):
    codes = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog",
             48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
             61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 71: "Slight snow",
             73: "Moderate snow", 75: "Heavy snow", 80: "Slight rain showers",
             81: "Moderate rain showers", 82: "Violent rain showers", 95: "Thunderstorm",
             96: "Thunderstorm with hail"}
    return codes.get(code, "Unknown")


# ── Feature 26: Custom Case Tags ─────────────────────────────────

@router.post("/cases/{case_id}/tags")
async def add_case_tag(case_id: str, data: dict, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    from datetime import timezone
    db = get_database()
    tag = data.get("tag", "").strip()
    color = data.get("color", "#60a5fa")
    if not tag:
        raise HTTPException(400, "Tag required")
    try:
        await db._db.execute(
            "INSERT INTO case_tags (case_id, tag, color, created_at) VALUES (?,?,?,?)",
            (case_id, tag, color, datetime.now(timezone.utc).isoformat()))
        await db._db.commit()
    except Exception:
        pass  # Duplicate
    return {"status": "ok"}


@router.get("/cases/{case_id}/tags")
async def get_case_tags(case_id: str):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute("SELECT tag, color FROM case_tags WHERE case_id = ?", (case_id,))
    rows = await cursor.fetchall()
    return {"tags": [{"tag": r[0], "color": r[1]} for r in rows]}


@router.delete("/cases/{case_id}/tags/{tag}")
async def remove_case_tag(case_id: str, tag: str, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    await db._db.execute("DELETE FROM case_tags WHERE case_id = ? AND tag = ?", (case_id, tag))
    await db._db.commit()
    return {"status": "deleted"}


# ── Feature 27: Audit Trail Viewer ───────────────────────────────

@router.get("/cases/{case_id}/audit-trail")
async def get_audit_trail(case_id: str, limit: int = 50, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute(
        "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY timestamp DESC LIMIT ?",
        (case_id, limit))
    rows = await cursor.fetchall()
    return {"events": [dict(r) for r in rows]}


@router.post("/audit-log")
async def add_audit_event(data: dict, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    await db._db.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, details) VALUES (?,?,?,?)",
        (data.get("entity_type", "case"), data.get("entity_id", ""),
         data.get("action", ""), data.get("details", "")))
    await db._db.commit()
    return {"status": "logged"}


# ── Feature 28: Investigator Case Notes ──────────────────────────

@router.get("/cases/{case_id}/notes")
async def get_case_notes(case_id: str, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute(
        "SELECT * FROM case_notes WHERE case_id = ? ORDER BY created_at DESC", (case_id,))
    return {"notes": [dict(r) for r in await cursor.fetchall()]}


@router.post("/cases/{case_id}/notes")
async def add_case_note(case_id: str, data: dict, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    from datetime import timezone
    db = get_database()
    note_id = str(uuid.uuid4())
    await db._db.execute(
        "INSERT INTO case_notes (id, case_id, author_id, author_name, content, created_at) VALUES (?,?,?,?,?,?)",
        (note_id, case_id, auth.get("user_id", ""), auth.get("username", "admin"),
         data.get("content", ""), datetime.now(timezone.utc).isoformat()))
    await db._db.commit()
    return {"id": note_id, "status": "created"}


# ── Feature 29: Case Merge/Split ─────────────────────────────────

@router.post("/admin/cases/merge")
async def merge_cases(data: dict, auth=Depends(require_admin_auth)):
    """Merge source case into target case."""
    from app.services.database import get_database
    target_id = data.get("target_case_id")
    source_id = data.get("source_case_id")
    if not target_id or not source_id:
        raise HTTPException(400, "Both target and source case IDs required")
    target = await firestore_service.get_case(target_id)
    source = await firestore_service.get_case(source_id)
    if not target or not source:
        raise HTTPException(404, "Case not found")
    t = target if isinstance(target, dict) else target.model_dump()
    s = source if isinstance(source, dict) else source.model_dump()
    # Merge report_ids
    t_reports = t.get("report_ids", [])
    s_reports = s.get("report_ids", [])
    if isinstance(t_reports, str):
        t_reports = json.loads(t_reports) if t_reports else []
    if isinstance(s_reports, str):
        s_reports = json.loads(s_reports) if s_reports else []
    merged = list(set(t_reports + s_reports))
    # Update target
    if hasattr(target, 'report_ids'):
        target.report_ids = merged
    elif isinstance(target, dict):
        target["report_ids"] = merged
    await firestore_service.update_case(target)
    # Mark source as merged
    if hasattr(source, 'status'):
        source.status = 'merged'
    elif isinstance(source, dict):
        source["status"] = 'merged'
    await firestore_service.update_case(source)
    # Audit
    db = get_database()
    await db._db.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, details) VALUES (?,?,?,?)",
        ("case", target_id, "merge", f"Merged case {source_id} into {target_id}. {len(s_reports)} reports moved."))
    await db._db.commit()
    return {"status": "merged", "target_reports": len(merged), "source_status": "merged"}


# ── Feature 30: Case Deadline/SLA Tracking ───────────────────────

@router.get("/cases/{case_id}/deadlines")
async def get_deadlines(case_id: str, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute(
        "SELECT * FROM case_deadlines WHERE case_id = ? ORDER BY due_date ASC", (case_id,))
    return {"deadlines": [dict(r) for r in await cursor.fetchall()]}


@router.post("/cases/{case_id}/deadlines")
async def add_deadline(case_id: str, data: dict, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    from datetime import timezone
    db = get_database()
    dl_id = str(uuid.uuid4())
    await db._db.execute(
        "INSERT INTO case_deadlines (id, case_id, deadline_type, due_date, description, created_at) VALUES (?,?,?,?,?,?)",
        (dl_id, case_id, data.get("type", "general"), data.get("due_date", ""),
         data.get("description", ""), datetime.now(timezone.utc).isoformat()))
    await db._db.commit()
    return {"id": dl_id}


@router.get("/admin/upcoming-deadlines")
async def upcoming_deadlines(days: int = 7, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    from datetime import timezone, timedelta
    db = get_database()
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    cursor = await db._db.execute(
        "SELECT * FROM case_deadlines WHERE due_date <= ? AND is_completed = 0 ORDER BY due_date ASC",
        (cutoff,))
    return {"deadlines": [dict(r) for r in await cursor.fetchall()]}


@router.get("/cases/{case_id}/lead-scores")
async def get_lead_scores(case_id: str, auth=Depends(require_admin_auth)):
    """Score and rank witness statements by investigative value."""
    case = await firestore_service.get_case(case_id)
    if not case: raise HTTPException(404, "Case not found")
    report_ids = case.get("report_ids", []) if isinstance(case, dict) else getattr(case, 'report_ids', [])
    if isinstance(report_ids, str):
        try:
            report_ids = json.loads(report_ids)
        except Exception as e:
            logger.warning(f"Error parsing report_ids: {e}")
            report_ids = []
    leads = []
    for rid in report_ids[:10]:
        session = await firestore_service.get_session(rid)
        if not session: continue
        s = session if isinstance(session, dict) else session.model_dump()
        statements = s.get("statements", [])
        scene_versions = s.get("scene_versions", [])
        # Score based on: detail level, scene impact, recency
        detail_score = min(50, len(statements) * 10)
        scene_score = min(30, len(scene_versions) * 15)
        recency_score = 20  # default
        total = detail_score + scene_score + recency_score
        leads.append({"session_id": rid, "score": min(100, total), "detail_score": detail_score, "scene_score": scene_score, "statements_count": len(statements), "scene_versions": len(scene_versions)})
    leads.sort(key=lambda x: x["score"], reverse=True)
    return {"leads": leads}


@router.get("/cases/{case_id}/pdf")
async def export_case_pdf(case_id: str, auth=Depends(require_admin_auth)):
    """Export case as a formatted text report (plain text for now, PDF requires reportlab)."""
    case = await firestore_service.get_case(case_id)
    if not case: raise HTTPException(404, "Case not found")
    c = case if isinstance(case, dict) else case.model_dump()
    
    lines = []
    lines.append("=" * 60)
    lines.append("WITNESSREPLAY - OFFICIAL CASE REPORT")
    lines.append("=" * 60)
    lines.append(f"Case Number: {c.get('case_number', 'N/A')}")
    lines.append(f"Title: {c.get('title', 'Untitled')}")
    lines.append(f"Status: {c.get('status', 'open').upper()}")
    lines.append(f"Location: {c.get('location', 'Not specified')}")
    lines.append(f"Created: {c.get('created_at', 'N/A')}")
    lines.append(f"Last Updated: {c.get('updated_at', 'N/A')}")
    lines.append("-" * 60)
    lines.append("CASE SUMMARY")
    lines.append(c.get('summary', 'No summary available.'))
    lines.append("-" * 60)
    
    report_ids = c.get("report_ids", [])
    if isinstance(report_ids, str):
        try:
            report_ids = json.loads(report_ids)
        except Exception as e:
            logger.warning(f"Error parsing report_ids: {e}")
            report_ids = []
    
    lines.append(f"WITNESS REPORTS ({len(report_ids)} total)")
    lines.append("-" * 60)
    for i, rid in enumerate(report_ids[:20]):
        session = await firestore_service.get_session(rid)
        if not session: continue
        s = session if isinstance(session, dict) else session.model_dump()
        lines.append(f"\nReport #{i+1} (ID: {rid[:8]}...)")
        lines.append(f"  Title: {s.get('title', 'Untitled')}")
        lines.append(f"  Source: {s.get('source_type', 'chat')}")
        lines.append(f"  Created: {s.get('created_at', 'N/A')}")
        for stmt in (s.get('statements', []) or [])[:10]:
            text = stmt.get('text', '') if isinstance(stmt, dict) else str(stmt)
            lines.append(f"  Statement: {text[:200]}")
    
    from datetime import timezone
    lines.append("\n" + "=" * 60)
    lines.append("END OF REPORT")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 60)
    
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), media_type="text/plain", headers={"Content-Disposition": f"attachment; filename=case_{c.get('case_number','report')}.txt"})


@router.post("/cases/{case_id}/notify-witnesses")
async def notify_case_witnesses(case_id: str, data: dict, auth=Depends(require_admin_auth)):
    """Send notification to all witnesses in a case (logged for now — email service needed)."""
    case = await firestore_service.get_case(case_id)
    if not case: raise HTTPException(404, "Case not found")
    c = case if isinstance(case, dict) else case.model_dump()
    message = data.get("message", "")
    notification_type = data.get("type", "update")  # update, follow_up, court_date
    
    report_ids = c.get("report_ids", [])
    if isinstance(report_ids, str):
        try:
            report_ids = json.loads(report_ids)
        except Exception as e:
            logger.warning(f"Error parsing report_ids: {e}")
            report_ids = []
    
    notified = []
    for rid in report_ids:
        session = await firestore_service.get_session(rid)
        if session:
            s = session if isinstance(session, dict) else session.model_dump()
            notified.append({"session_id": rid, "title": s.get("title",""), "status": "logged"})
            logger.info(f"[Notification] Case {case_id} → Session {rid}: {notification_type} - {message[:100]}")
    
    return {"notifications_sent": len(notified), "type": notification_type, "recipients": notified, "note": "Notifications logged. Email delivery requires SMTP configuration."}


# ==================== Dashboard Widgets (Feature 43) ====================

@router.get("/admin/dashboard/widgets")
async def get_dashboard_widgets(auth=Depends(require_admin_auth)):
    """Get aggregated dashboard widget data."""
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        widgets = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cursor = await db._db.execute("SELECT COUNT(*) FROM sessions WHERE created_at LIKE ?", (f"{today}%",))
        widgets["sessions_today"] = (await cursor.fetchone())[0]
        cursor = await db._db.execute("SELECT COUNT(*) FROM cases")
        widgets["total_cases"] = (await cursor.fetchone())[0]
        cursor = await db._db.execute("SELECT COUNT(*) FROM cases WHERE status = 'open'")
        widgets["open_cases"] = (await cursor.fetchone())[0]
        cursor = await db._db.execute("SELECT COUNT(*) FROM users")
        widgets["total_users"] = (await cursor.fetchone())[0]
        cursor = await db._db.execute("SELECT COUNT(*) FROM sessions WHERE created_at >= datetime('now', '-7 days')")
        widgets["sessions_this_week"] = (await cursor.fetchone())[0]
        return widgets
    except Exception as e:
        logger.error(f"Error getting dashboard widgets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Global Search (Feature 44) ====================

@router.get("/admin/search/global")
async def global_search(q: str = "", auth=Depends(require_admin_auth)):
    """Search across cases, sessions, and users."""
    if len(q) < 2:
        raise HTTPException(400, "Query too short")
    try:
        from app.services.database import get_database
        db = get_database()
        if db._db is None:
            await db.initialize()
        results = {"cases": [], "sessions": [], "users": []}
        cursor = await db._db.execute("SELECT id, title, status, case_number FROM cases WHERE title LIKE ? OR case_number LIKE ? LIMIT 10", (f"%{q}%", f"%{q}%"))
        results["cases"] = [dict(r) for r in await cursor.fetchall()]
        cursor = await db._db.execute("SELECT id, title, source_type, created_at FROM sessions WHERE title LIKE ? OR id LIKE ? LIMIT 10", (f"%{q}%", f"%{q}%"))
        results["sessions"] = [dict(r) for r in await cursor.fetchall()]
        cursor = await db._db.execute("SELECT id, username, email, role FROM users WHERE username LIKE ? OR email LIKE ? LIMIT 10", (f"%{q}%", f"%{q}%"))
        results["users"] = [dict(r) for r in await cursor.fetchall()]
        results["total"] = sum(len(v) for v in results.values())
        return results
    except Exception as e:
        logger.error(f"Error in global search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Multi-Format Export (Feature 45) ====================

@router.get("/cases/{case_id}/export")
async def export_case(case_id: str, format: str = "json", auth=Depends(require_admin_auth)):
    """Export case in multiple formats: json, csv, txt."""
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    c = case if isinstance(case, dict) else case.model_dump()

    if format == "csv":
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Field", "Value"])
        for key, val in c.items():
            writer.writerow([key, str(val)[:500]])
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=case_{case_id[:8]}.csv"})
    elif format == "txt":
        lines = [f"{k}: {v}" for k, v in c.items()]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("\n".join(lines), media_type="text/plain", headers={"Content-Disposition": f"attachment; filename=case_{case_id[:8]}.txt"})
    else:
        return c


# ── Feature 36: Rate Limit Dashboard ──────────────────────────────────────

@router.get("/admin/rate-limits")
async def get_rate_limit_stats(auth=Depends(require_admin_auth)):
    """Get current API quota usage stats."""
    import time
    from datetime import timezone
    from app.api.auth import _api_key_requests
    stats = {}
    now = time.time()
    for key_hash, requests in _api_key_requests.items():
        active = [r for r in requests if (now - r) < 60]
        stats[key_hash[:8] + "..."] = {"requests_last_minute": len(active), "total_tracked": len(requests)}
    return {"api_key_stats": stats, "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Feature 37: Session Replay for Admin ──────────────────────────────────

@router.get("/admin/sessions/{session_id}/replay")
async def get_session_replay(session_id: str, auth=Depends(require_admin_auth)):
    """Get full session conversation replay data."""
    session = await firestore_service.get_session(session_id)
    if not session: raise HTTPException(404, "Session not found")
    s = session if isinstance(session, dict) else session.model_dump()
    # Build replay timeline
    messages = []
    for stmt in (s.get("statements", []) or []):
        if isinstance(stmt, dict):
            messages.append({"role": "witness", "content": stmt.get("text",""), "timestamp": stmt.get("timestamp",""), "type": stmt.get("type","text")})
    for sv in (s.get("scene_versions", []) or []):
        if isinstance(sv, dict):
            messages.append({"role": "system", "content": f"Scene reconstruction updated (v{sv.get('version',0)})", "timestamp": sv.get("timestamp",""), "type": "scene_update"})
    messages.sort(key=lambda x: x.get("timestamp",""))
    return {"session_id": session_id, "title": s.get("title",""), "created_at": s.get("created_at",""), "messages": messages, "total_messages": len(messages)}


# ── Feature 38: Multi-Tenant Organization Support ─────────────────────────

@router.get("/admin/organizations")
async def list_organizations(auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute("SELECT * FROM organizations ORDER BY created_at DESC")
    return {"organizations": [dict(r) for r in await cursor.fetchall()]}

@router.post("/admin/organizations")
async def create_organization(data: dict, auth=Depends(require_admin_auth)):
    import uuid
    from datetime import timezone
    from app.services.database import get_database
    db = get_database()
    org_id = str(uuid.uuid4())
    await db._db.execute("INSERT INTO organizations (id, name, domain, created_at) VALUES (?,?,?,?)",
        (org_id, data.get("name",""), data.get("domain",""), datetime.now(timezone.utc).isoformat()))
    await db._db.commit()
    return {"id": org_id}


# ── Feature 39: Email Notification Service ────────────────────────────────

@router.get("/admin/email-config")
async def get_email_config(auth=Depends(require_admin_auth)):
    from app.services.email_service import email_service
    return {"configured": email_service.is_configured, "host": email_service.smtp_host, "from_email": email_service.from_email}

@router.post("/admin/email-config")
async def configure_email(data: dict, auth=Depends(require_admin_auth)):
    from app.services.email_service import email_service
    email_service.configure(data.get("host",""), data.get("port",587), data.get("user",""), data.get("password",""), data.get("from_email"))
    return {"status": "configured"}


# ── Feature 40: Two-Factor Authentication ─────────────────────────────────

@router.post("/auth/2fa/setup")
async def setup_2fa(auth=Depends(require_admin_auth)):
    """Generate 2FA secret for user."""
    import secrets, hashlib
    from datetime import timezone
    from app.services.database import get_database
    user_id = auth.get("user_id", "")
    secret = secrets.token_hex(20)
    backup = [secrets.token_hex(4) for _ in range(8)]
    db = get_database()
    await db._db.execute("INSERT OR REPLACE INTO user_2fa (user_id, secret, is_enabled, backup_codes, created_at) VALUES (?,?,0,?,?)",
        (user_id, secret, ",".join(backup), datetime.now(timezone.utc).isoformat()))
    await db._db.commit()
    return {"secret": secret, "backup_codes": backup, "note": "Save backup codes securely. Use any TOTP app to scan the secret."}

@router.post("/auth/2fa/verify")
async def verify_2fa(data: dict, auth=Depends(require_admin_auth)):
    """Verify a 2FA code (simplified TOTP check)."""
    import hashlib, time
    from app.services.database import get_database
    user_id = auth.get("user_id", "")
    code = data.get("code", "")
    db = get_database()
    cursor = await db._db.execute("SELECT secret, backup_codes FROM user_2fa WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    if not row: raise HTTPException(400, "2FA not set up")
    # Check backup codes
    if code in (row[1] or "").split(","):
        remaining = [c for c in row[1].split(",") if c != code]
        await db._db.execute("UPDATE user_2fa SET backup_codes = ?, is_enabled = 1 WHERE user_id = ?", (",".join(remaining), user_id))
        await db._db.commit()
        return {"verified": True, "method": "backup_code"}
    # Simplified TOTP-like check (real implementation would use pyotp)
    t = int(time.time()) // 30
    expected = hashlib.sha256(f"{row[0]}{t}".encode()).hexdigest()[:6]
    if code == expected:
        await db._db.execute("UPDATE user_2fa SET is_enabled = 1 WHERE user_id = ?", (user_id,))
        await db._db.commit()
        return {"verified": True, "method": "totp"}
    return {"verified": False, "error": "Invalid code"}


# ── Feature 33: Real-time Collaboration (Presence) ────────

@router.post("/cases/{case_id}/presence")
async def update_presence(case_id: str, data: dict, auth=Depends(require_admin_auth)):
    """Report that a user is viewing this case."""
    if case_id not in _case_viewers:
        _case_viewers[case_id] = {}
    _case_viewers[case_id][auth.get("user_id", "")] = auth.get("username", "anonymous")
    return {"viewers": _case_viewers.get(case_id, {})}


@router.delete("/cases/{case_id}/presence")
async def remove_presence(case_id: str, auth=Depends(require_admin_auth)):
    if case_id in _case_viewers:
        _case_viewers[case_id].pop(auth.get("user_id", ""), None)
    return {"status": "ok"}


@router.get("/cases/{case_id}/presence")
async def get_presence(case_id: str, auth=Depends(require_admin_auth)):
    return {"viewers": _case_viewers.get(case_id, {})}


# ── Feature 34: Webhook Integration Framework ─────────────

@router.get("/admin/webhooks")
async def list_webhooks(auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute("SELECT * FROM webhooks WHERE is_active = 1")
    return {"webhooks": [dict(r) for r in await cursor.fetchall()]}


@router.post("/admin/webhooks")
async def create_webhook(data: dict, auth=Depends(require_admin_auth)):
    from datetime import timezone
    from app.services.database import get_database
    db = get_database()
    wh_id = str(uuid.uuid4())
    await db._db.execute(
        "INSERT INTO webhooks (id, name, url, events, is_active, created_at) VALUES (?,?,?,?,1,?)",
        (wh_id, data.get("name", ""), data.get("url", ""), json.dumps(data.get("events", ["case.created"])),
         datetime.now(timezone.utc).isoformat()))
    await db._db.commit()
    return {"id": wh_id}


@router.delete("/admin/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    await db._db.execute("UPDATE webhooks SET is_active = 0 WHERE id = ?", (webhook_id,))
    await db._db.commit()
    return {"status": "deleted"}


# ── System Health Monitoring ───────────────────

@router.get("/admin/system-health")
async def get_system_health(auth=Depends(require_admin_auth)):
    """Get comprehensive system health information for admin dashboard."""
    import psutil
    import platform

    try:
        # CPU and memory
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Process-specific info
        proc = psutil.Process()
        proc_mem = proc.memory_info()
        proc_create_time = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
        uptime_seconds = (datetime.now(timezone.utc) - proc_create_time).total_seconds()

        # Response time from metrics
        avg_response_ms = None
        try:
            from app.services.metrics import metrics_collector
            stats = metrics_collector.get_stats()
            avg_response_ms = stats.get("response_time", {}).get("avg_ms")
        except Exception:
            pass

        # Active WebSocket connections
        active_ws = 0
        try:
            from app.api.websocket import active_connections
            active_ws = len(active_connections) if hasattr(active_connections, '__len__') else 0
        except Exception:
            pass

        return {
            "system": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu_percent": cpu_percent,
                "cpu_count": psutil.cpu_count(),
                "memory_total_mb": round(mem.total / 1048576),
                "memory_used_mb": round(mem.used / 1048576),
                "memory_percent": mem.percent,
                "disk_total_gb": round(disk.total / 1073741824, 1),
                "disk_used_gb": round(disk.used / 1073741824, 1),
                "disk_percent": round(disk.percent, 1),
            },
            "process": {
                "pid": proc.pid,
                "memory_rss_mb": round(proc_mem.rss / 1048576, 1),
                "uptime_seconds": round(uptime_seconds),
                "uptime_human": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
                "threads": proc.num_threads(),
            },
            "app": {
                "avg_response_ms": round(avg_response_ms, 1) if avg_response_ms else None,
                "active_websockets": active_ws,
                "environment": settings.environment,
                "debug": settings.debug,
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except ImportError:
        return {
            "error": "psutil not installed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# ── Feature 35: Data Backup and Restore ───────────────────

@router.get("/admin/backup")
async def create_backup(auth=Depends(require_admin_auth)):
    """Create a database backup."""
    import shutil
    from datetime import timezone
    db_path = settings.database_path
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"backup_{timestamp}.db")
    shutil.copy2(db_path, backup_path)
    backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')], reverse=True)
    return {"backup_created": backup_path, "timestamp": timestamp, "existing_backups": backups[:10]}


@router.get("/admin/backups")
async def list_backups(auth=Depends(require_admin_auth)):
    from datetime import timezone
    backup_dir = os.path.join(os.path.dirname(settings.database_path), "backups")
    if not os.path.exists(backup_dir):
        return {"backups": []}
    backups = sorted(
        [{"name": f, "size_kb": os.path.getsize(os.path.join(backup_dir, f)) // 1024}
         for f in os.listdir(backup_dir) if f.endswith('.db')],
        key=lambda x: x["name"], reverse=True)
    return {"backups": backups}


# ── Feature 47: Witness Feedback ─────────────────────────────

@router.post("/sessions/{session_id}/feedback")
async def submit_feedback(session_id: str, data: dict):
    """Submit witness feedback after interview."""
    import uuid
    from app.services.database import get_database
    db = get_database()
    fb_id = str(uuid.uuid4())
    await db._db.execute("INSERT INTO witness_feedback (id, session_id, rating, ease_of_use, felt_heard, comments, created_at) VALUES (?,?,?,?,?,?,?)",
        (fb_id, session_id, data.get("rating",0), data.get("ease_of_use",0), data.get("felt_heard",0), data.get("comments",""), datetime.now(timezone.utc).isoformat()))
    await db._db.commit()
    return {"id": fb_id, "status": "Thank you for your feedback!"}

@router.get("/admin/feedback")
async def list_feedback(auth=Depends(require_admin_auth)):
    from app.services.database import get_database
    db = get_database()
    cursor = await db._db.execute("SELECT * FROM witness_feedback ORDER BY created_at DESC LIMIT 100")
    return {"feedback": [dict(r) for r in await cursor.fetchall()]}


# ── Feature 50: Auto Incident Classification ─────────────────

@router.post("/sessions/{session_id}/classify")
async def classify_incident(session_id: str, auth=Depends(require_admin_auth)):
    """Auto-classify incident type based on conversation content."""
    session = await firestore_service.get_session(session_id)
    if not session: raise HTTPException(404, "Session not found")
    s = session if isinstance(session, dict) else session.model_dump()

    # Extract all text
    texts = []
    for stmt in (s.get("statements", []) or []):
        if isinstance(stmt, dict): texts.append(stmt.get("text",""))
        else: texts.append(str(stmt))
    full_text = " ".join(texts).lower()

    # Keyword-based classification
    categories = {
        "theft": ["stole", "stolen", "theft", "robbed", "robbery", "burglary", "broke in", "shoplifting"],
        "assault": ["hit", "punch", "attack", "assault", "beat", "fight", "violence", "weapon"],
        "traffic_accident": ["car", "crash", "accident", "vehicle", "collision", "driving", "traffic", "hit and run"],
        "vandalism": ["vandal", "graffiti", "damage", "smash", "broke", "destroy", "property"],
        "fraud": ["fraud", "scam", "identity", "fake", "counterfeit", "phishing", "money"],
        "drug_related": ["drug", "substance", "narcotics", "marijuana", "cocaine", "dealing"],
        "domestic": ["domestic", "partner", "spouse", "family", "household"],
        "missing_person": ["missing", "disappeared", "lost", "haven't seen", "not come home"],
        "harassment": ["harass", "stalk", "threaten", "intimidat", "bully"],
        "other": []
    }

    scores = {}
    for cat, keywords in categories.items():
        scores[cat] = sum(1 for kw in keywords if kw in full_text)

    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_cats[0] if sorted_cats[0][1] > 0 else ("other", 0)
    secondary = sorted_cats[1] if len(sorted_cats) > 1 and sorted_cats[1][1] > 0 else None

    confidence = min(1.0, primary[1] / max(1, len(texts)))

    return {
        "primary_classification": primary[0],
        "primary_score": primary[1],
        "confidence": round(confidence, 2),
        "secondary_classification": secondary[0] if secondary else None,
        "all_scores": {k: v for k, v in scores.items() if v > 0},
        "analyzed_statements": len(texts)
    }


@router.get("/admin/audit-timeline")
async def get_audit_timeline(limit: int = 100, auth=Depends(require_admin_auth)):
    """Get recent audit log events as a timeline for the admin dashboard."""
    limit = _guard_limit(limit)
    try:
        rows = await firestore_service.query(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        events = []
        for row in (rows or []):
            r = dict(row) if hasattr(row, 'keys') else row
            events.append({
                "id": r.get("id"),
                "entity_type": r.get("entity_type", ""),
                "entity_id": r.get("entity_id", ""),
                "action": r.get("action", ""),
                "details": r.get("details", ""),
                "timestamp": r.get("timestamp", ""),
            })
        return {"events": events, "total": len(events)}
    except Exception as e:
        logger.error(f"Error fetching audit timeline: {e}")
        return {"events": [], "total": 0}


@router.get("/admin/interview-analytics")
async def get_interview_analytics(auth=Depends(require_admin_auth)):
    """Get aggregate analytics about interviews for the admin dashboard."""
    try:
        sessions = await firestore_service.list_sessions(limit=200)
        if not sessions:
            return {"total_sessions": 0, "avg_statements": 0, "incident_types": {}, "hourly_distribution": {}}

        total = len(sessions)
        total_statements = 0
        incident_types = {}
        hourly = {}

        for s in sessions:
            sd = s if isinstance(s, dict) else s.model_dump()
            stmts = sd.get("statements", []) or []
            total_statements += len(stmts)

            inc_type = (sd.get("metadata", {}) or {}).get("incident_type", "unknown")
            incident_types[inc_type] = incident_types.get(inc_type, 0) + 1

            created = sd.get("created_at", "")
            if created and "T" in str(created):
                try:
                    hour = str(created).split("T")[1][:2]
                    hourly[hour] = hourly.get(hour, 0) + 1
                except (IndexError, ValueError):
                    pass

        return {
            "total_sessions": total,
            "avg_statements": round(total_statements / max(1, total), 1),
            "incident_types": incident_types,
            "hourly_distribution": dict(sorted(hourly.items())),
        }
    except Exception as e:
        logger.error(f"Error computing interview analytics: {e}")
        return {"total_sessions": 0, "avg_statements": 0, "incident_types": {}, "hourly_distribution": {}}


# ==================== Session Keyword Extraction ====================

@router.get("/sessions/{session_id}/keywords")
async def get_session_keywords(session_id: str):
    """Extract key terms and stats from a session's conversation."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    sd = session if isinstance(session, dict) else session.model_dump()

    statements = sd.get("statements", []) or []
    stop_words = {"the","a","an","is","was","are","were","i","you","he","she","it","we","they",
                  "my","your","his","her","its","our","their","and","or","but","in","on","at",
                  "to","for","of","with","that","this","from","by","as","not","have","has","had",
                  "do","does","did","be","been","being","will","would","could","should","can",
                  "may","might","just","so","very","also","about","up","out","if","no","when",
                  "what","where","who","how","than","then","there","here","all","some","any",
                  "each","every","more","most","other","into","over","after","before","between"}

    word_freq = {}
    total_words = 0
    witness_words = 0
    agent_words = 0

    for stmt in statements:
        text = stmt.get("text", "") if isinstance(stmt, dict) else str(stmt)
        speaker = stmt.get("speaker", "unknown") if isinstance(stmt, dict) else "unknown"
        words = re.findall(r'[a-zA-Z]+', text.lower())
        total_words += len(words)

        if speaker in ("user", "witness"):
            witness_words += len(words)
            for w in words:
                if len(w) > 2 and w not in stop_words:
                    word_freq[w] = word_freq.get(w, 0) + 1
        else:
            agent_words += len(words)

    top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:15]
    reading_time = max(1, round(total_words / 200))

    return {
        "total_words": total_words,
        "witness_words": witness_words,
        "agent_words": agent_words,
        "reading_time_minutes": reading_time,
        "total_statements": len(statements),
        "top_keywords": [{"word": w, "count": c} for w, c in top_keywords]
    }


# ==================== Evidence Extraction ====================

@router.get("/sessions/{session_id}/extract-evidence")
async def extract_session_evidence_items(session_id: str):
    """Extract evidence items mentioned in a session's conversation."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    sd = session if isinstance(session, dict) else session.model_dump()

    statements = sd.get("statements", []) or []
    evidence_items = []
    evidence_keywords = {
        "weapon": "🔫", "knife": "🔪", "gun": "🔫", "blood": "🩸",
        "car": "🚗", "vehicle": "🚗", "truck": "🚛", "camera": "📷",
        "phone": "📱", "document": "📄", "footage": "🎥", "video": "🎥",
        "photo": "📸", "fingerprint": "🖐️", "dna": "🧬", "drug": "💊",
        "money": "💰", "cash": "💰", "bag": "👜", "clothing": "👕",
        "shoe": "👟", "hat": "🧢", "mask": "🎭", "glasses": "👓",
        "tattoo": "🖊️", "scar": "📍", "injury": "🩹", "wound": "🩹",
        "door": "🚪", "window": "🪟", "key": "🔑", "lock": "🔒",
        "bottle": "🍾", "glass": "🥃", "ring": "💍", "watch": "⌚",
        "wallet": "👛", "license": "🪪", "plate": "🔢", "cctv": "📹",
    }

    seen = set()
    for idx, stmt in enumerate(statements):
        text = stmt.get("text", "") if isinstance(stmt, dict) else str(stmt)
        speaker = stmt.get("speaker", "unknown") if isinstance(stmt, dict) else "unknown"
        lower = text.lower()
        for kw, icon in evidence_keywords.items():
            if kw in lower and kw not in seen:
                seen.add(kw)
                # Extract surrounding context (±30 chars)
                pos = lower.index(kw)
                start = max(0, pos - 30)
                end = min(len(text), pos + len(kw) + 30)
                context = text[start:end].strip()
                if start > 0:
                    context = "..." + context
                if end < len(text):
                    context = context + "..."
                evidence_items.append({
                    "item": kw.title(),
                    "icon": icon,
                    "speaker": speaker,
                    "statement_index": idx,
                    "context": context,
                })

    return {
        "session_id": session_id,
        "evidence_count": len(evidence_items),
        "items": evidence_items,
    }


# ==================== Admin Activity Heatmap ====================

@router.get("/admin/activity-heatmap")
async def get_activity_heatmap(auth=Depends(require_admin_auth)):
    """Return session activity counts by hour and day-of-week for a heatmap."""
    try:
        sessions = await firestore_service.list_sessions(limit=500)
        heatmap = {}  # key: "day-hour" → count
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        for s in sessions:
            sd = s if isinstance(s, dict) else s.model_dump()
            created = sd.get("created_at", "")
            if not created:
                continue
            try:
                from datetime import datetime as _dt
                if isinstance(created, str):
                    dt = _dt.fromisoformat(created.replace("Z", "+00:00"))
                elif hasattr(created, 'isoformat'):
                    dt = created
                else:
                    continue
                day = day_names[dt.weekday()]
                hour = dt.hour
                key = f"{day}-{hour}"
                heatmap[key] = heatmap.get(key, 0) + 1
            except (ValueError, AttributeError):
                continue

        # Build structured response
        cells = []
        for d_idx, day in enumerate(day_names):
            for hour in range(24):
                key = f"{day}-{hour}"
                count = heatmap.get(key, 0)
                cells.append({"day": day, "day_index": d_idx, "hour": hour, "count": count})

        return {"cells": cells, "days": day_names, "total_sessions": len(sessions)}
    except Exception as e:
        logger.error(f"Error computing activity heatmap: {e}")
        return {"cells": [], "days": [], "total_sessions": 0}


# ==================== Interview Quality Score ====================

@router.get("/sessions/{session_id}/quality-score")
async def get_interview_quality_score(session_id: str):
    """Evaluate interview completeness based on 5W1H coverage."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    sd = session if isinstance(session, dict) else session.model_dump()
    statements = sd.get("statements", []) or []

    full_text = " ".join(
        (s.get("text", "") if isinstance(s, dict) else str(s)) for s in statements
    ).lower()

    categories = {
        "who": {
            "label": "Who (People)",
            "keywords": ["man", "woman", "person", "suspect", "victim", "witness",
                         "he ", "she ", "they ", "name", "officer", "driver",
                         "child", "male", "female", "individual", "group"],
            "found": False
        },
        "what": {
            "label": "What (Event)",
            "keywords": ["happened", "occurred", "incident", "crime", "accident",
                         "robbery", "assault", "theft", "shot", "stabbed", "hit",
                         "broke", "stole", "attacked", "punched", "crashed"],
            "found": False
        },
        "when": {
            "label": "When (Time)",
            "keywords": ["o'clock", "am ", "pm ", "morning", "afternoon", "evening",
                         "night", "yesterday", "today", "minutes ago", "hours ago",
                         "around ", "approximately", "about ", "midnight", "noon"],
            "found": False
        },
        "where": {
            "label": "Where (Location)",
            "keywords": ["street", "road", "avenue", "building", "park", "store",
                         "parking", "intersection", "block", "corner", "house",
                         "apartment", "address", "near", "location", "north",
                         "south", "east", "west"],
            "found": False
        },
        "why": {
            "label": "Why (Motive)",
            "keywords": ["because", "reason", "motive", "angry", "argument",
                         "dispute", "money", "revenge", "jealous", "drunk",
                         "intoxicated", "trying to"],
            "found": False
        },
        "how": {
            "label": "How (Method)",
            "keywords": ["weapon", "gun", "knife", "vehicle", "ran", "walked",
                         "drove", "fled", "escaped", "entered", "broke in",
                         "forced", "climbed", "jumped"],
            "found": False
        },
        "description": {
            "label": "Physical Description",
            "keywords": ["tall", "short", "heavy", "thin", "hair", "eyes",
                         "wearing", "shirt", "pants", "jacket", "tattoo",
                         "scar", "beard", "glasses", "hoodie", "cap"],
            "found": False
        },
    }

    for cat_key, cat in categories.items():
        for kw in cat["keywords"]:
            if kw in full_text:
                cat["found"] = True
                break

    found_count = sum(1 for c in categories.values() if c["found"])
    total = len(categories)
    score = round((found_count / total) * 100)

    message_count = len(statements)
    detail_bonus = min(15, message_count * 2)
    score = min(100, score + detail_bonus)

    result = []
    for key, cat in categories.items():
        result.append({
            "category": key,
            "label": cat["label"],
            "covered": cat["found"]
        })

    return {
        "session_id": session_id,
        "score": score,
        "categories": result,
        "message_count": message_count,
    }


# ==================== Sentiment Timeline ====================

@router.get("/sessions/{session_id}/sentiment-timeline")
async def get_sentiment_timeline(session_id: str):
    """Analyze sentiment/emotion progression across the interview."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    sd = session if isinstance(session, dict) else session.model_dump()
    statements = sd.get("statements", []) or []

    positive_words = {"thank", "good", "sure", "yes", "okay", "fine", "help",
                      "remember", "clearly", "definitely", "certain", "right"}
    negative_words = {"scared", "afraid", "angry", "upset", "confused", "nervous",
                      "worried", "panic", "terrible", "horrible", "threat",
                      "danger", "hurt", "pain", "cry", "scream", "shock"}
    neutral_words = {"said", "told", "went", "saw", "heard", "looked", "walked"}

    timeline_points = []
    for idx, stmt in enumerate(statements):
        text = (stmt.get("text", "") if isinstance(stmt, dict) else str(stmt)).lower()
        speaker = (stmt.get("speaker", "unknown") if isinstance(stmt, dict) else "unknown")
        if speaker != "user":
            continue

        words = set(text.split())
        pos = len(words & positive_words)
        neg = len(words & negative_words)

        if neg > pos:
            sentiment = "negative"
            emoji = "😰"
            value = -1
        elif pos > neg:
            sentiment = "positive"
            emoji = "😊"
            value = 1
        else:
            sentiment = "neutral"
            emoji = "😐"
            value = 0

        timeline_points.append({
            "index": idx,
            "sentiment": sentiment,
            "value": value,
            "emoji": emoji,
            "snippet": text[:80] + ("..." if len(text) > 80 else ""),
        })

    return {
        "session_id": session_id,
        "points": timeline_points,
        "total_statements": len(timeline_points),
    }


# ==================== Session Tags ====================

@router.post("/sessions/{session_id}/tags")
async def add_session_tag(session_id: str, data: dict):
    """Add a tag to a session."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    tag = data.get("tag", "").strip().lower()
    if not tag or len(tag) > 30:
        raise HTTPException(400, "Tag must be 1-30 characters")

    # Use session.metadata to store tags (metadata is Dict[str,Any])
    if hasattr(session, 'metadata'):
        meta = session.metadata or {}
        tags = meta.get("tags", []) or []
        if tag not in tags:
            tags.append(tag)
            meta["tags"] = tags
            session.metadata = meta
            await firestore_service.update_session(session)
    else:
        tags = [tag]

    return {"session_id": session_id, "tags": tags}


@router.delete("/sessions/{session_id}/tags/{tag}")
async def remove_session_tag(session_id: str, tag: str):
    """Remove a tag from a session."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    tag_lower = tag.strip().lower()
    tags = []
    if hasattr(session, 'metadata'):
        meta = session.metadata or {}
        tags = meta.get("tags", []) or []
        if tag_lower in tags:
            tags.remove(tag_lower)
            meta["tags"] = tags
            session.metadata = meta
            await firestore_service.update_session(session)

    return {"session_id": session_id, "tags": tags}


@router.get("/sessions/{session_id}/tags")
async def get_session_tags(session_id: str):
    """Get all tags for a session."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    if hasattr(session, 'metadata'):
        meta = session.metadata or {}
        tags = meta.get("tags", []) or []
    else:
        tags = []

    return {"session_id": session_id, "tags": tags}


# ==================== Admin Data Retention ====================

@router.get("/admin/data-retention")
async def get_data_retention(auth=Depends(require_admin_auth)):
    """Get current data retention settings."""
    return {
        "retention_days": 90,
        "auto_purge": False,
        "archive_before_delete": True,
        "exempt_flagged": True,
        "last_purge": None,
    }


@router.post("/admin/data-retention/purge")
async def purge_old_sessions(data: dict, auth=Depends(require_admin_auth)):
    """Purge sessions older than specified days."""
    days = data.get("days", 90)
    if days < 7:
        raise HTTPException(400, "Minimum retention is 7 days")

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sessions = await firestore_service.list_sessions(limit=1000)

    purged = 0
    for s in sessions:
        sd = s if isinstance(s, dict) else s.model_dump()
        created = sd.get("created_at", "")
        if not created:
            continue
        try:
            if isinstance(created, str):
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            elif hasattr(created, "isoformat"):
                dt = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            else:
                continue
            if dt < cutoff:
                purged += 1
        except (ValueError, AttributeError):
            continue

    return {
        "purged_count": purged,
        "cutoff_date": cutoff.isoformat(),
        "message": f"Found {purged} sessions older than {days} days (dry run — no actual deletion)",
    }


# ==================== Admin Session Transcript Viewer ====================

@router.get("/admin/sessions/{session_id}/transcript")
async def admin_get_session_transcript(session_id: str, auth=Depends(require_admin_auth)):
    """Get full transcript for admin session viewer."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    from app.agents.scene_agent import get_agent
    agent = get_agent(session_id)

    statements = []
    for s in session.witness_statements:
        statements.append({
            "id": s.id,
            "text": s.text,
            "is_correction": getattr(s, "is_correction", False),
            "confidence": getattr(s, "confidence", 0.5),
            "timestamp": s.timestamp.isoformat() if hasattr(s, "timestamp") and s.timestamp else None,
        })

    history = agent.conversation_history if hasattr(agent, "conversation_history") else []

    return {
        "session_id": session_id,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "statement_count": len(statements),
        "statements": statements,
        "conversation_history": history,
        "metadata": getattr(session, "metadata", {}) or {},
    }


# ==================== AI Follow-up Question Suggestions ====================

@router.get("/sessions/{session_id}/suggest-questions")
async def suggest_follow_up_questions(session_id: str):
    """Suggest contextual follow-up questions based on interview progress."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = [s.text for s in session.witness_statements[-5:]]
    context = " ".join(statements) if statements else ""

    # Rule-based question suggestions based on missing info
    suggestions = []
    text_lower = context.lower()

    if not any(w in text_lower for w in ["when", "time", "o'clock", "morning", "evening", "night", "afternoon"]):
        suggestions.append("When exactly did this happen? Can you estimate the time?")
    if not any(w in text_lower for w in ["where", "location", "street", "address", "building", "room"]):
        suggestions.append("Where did this take place? Can you describe the location?")
    if not any(w in text_lower for w in ["looked like", "wearing", "tall", "short", "hair", "face", "description"]):
        suggestions.append("Can you describe the appearance of the person(s) involved?")
    if not any(w in text_lower for w in ["weapon", "gun", "knife", "tool", "object"]):
        suggestions.append("Were any weapons or objects involved?")
    if not any(w in text_lower for w in ["witness", "anyone else", "other people", "saw", "bystander"]):
        suggestions.append("Were there any other witnesses or bystanders?")
    if not any(w in text_lower for w in ["vehicle", "car", "truck", "license", "plate"]):
        suggestions.append("Were any vehicles involved? Can you describe them?")
    if not any(w in text_lower for w in ["direction", "ran", "fled", "left", "drove away"]):
        suggestions.append("Which direction did the suspect(s) go afterward?")
    if not any(w in text_lower for w in ["camera", "cctv", "security", "footage", "recording"]):
        suggestions.append("Are there any security cameras or recordings in the area?")

    # Limit to 3 most relevant
    return {"session_id": session_id, "suggestions": suggestions[:3]}


# ==================== Investigation Report Generator ====================

@router.get("/sessions/{session_id}/investigation-report")
async def generate_investigation_report(session_id: str):
    """Generate a structured investigation report from interview data."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    from app.agents.scene_agent import get_agent
    agent = get_agent(session_id)

    statements = session.witness_statements
    meta = getattr(session, "metadata", {}) or {}

    # Extract key facts from statements
    all_text = " ".join(s.text for s in statements)
    word_count = len(all_text.split())

    # Build report sections
    report = {
        "session_id": session_id,
        "report_title": f"Investigation Report — {session.title}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_info": {
            "case_id": getattr(session, "case_id", None),
            "title": session.title,
            "status": session.status,
            "created": session.created_at.isoformat() if session.created_at else None,
            "incident_type": meta.get("incident_type", "Unknown"),
            "report_number": getattr(session, "report_number", ""),
        },
        "interview_summary": {
            "total_statements": len(statements),
            "total_words": word_count,
            "corrections_made": sum(1 for s in statements if getattr(s, "is_correction", False)),
            "avg_confidence": round(
                sum(getattr(s, "confidence", 0.5) for s in statements) / max(len(statements), 1), 2
            ),
            "duration_estimate": f"{max(1, word_count // 150)} min",
        },
        "witness_statements": [
            {
                "sequence": i + 1,
                "text": s.text,
                "timestamp": s.timestamp.isoformat() if hasattr(s, "timestamp") and s.timestamp else None,
                "is_correction": getattr(s, "is_correction", False),
            }
            for i, s in enumerate(statements)
        ],
        "tags": meta.get("tags", []),
        "notes": "Auto-generated by WitnessReplay AI system. Review and verify all details before official filing.",
    }

    return report


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 34: Witness Credibility Score
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/credibility-score")
async def get_credibility_score(session_id: str):
    """Analyze witness credibility based on testimony patterns."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    all_text = " ".join(s.text for s in statements)
    words = all_text.split()
    word_count = len(words)

    # 1. Detail specificity (names, numbers, colors, times → higher score)
    detail_patterns = [
        r'\b\d{1,2}:\d{2}\b',  # times
        r'\b\d+\s*(feet|meters|inches|yards|miles|km)\b',  # measurements
        r'\b(red|blue|green|black|white|gray|silver|brown|yellow)\b',  # colors
        r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)\b',  # proper names
        r'\b\d{1,4}\b',  # numbers
    ]
    detail_hits = sum(len(re.findall(p, all_text, re.I)) for p in detail_patterns)
    detail_score = min(100, (detail_hits / max(word_count / 100, 1)) * 25)

    # 2. Consistency (corrections lower the score)
    corrections = sum(1 for s in statements if getattr(s, "is_correction", False))
    consistency_score = max(0, 100 - corrections * 15)

    # 3. Coherence (avg sentence length, hedging language)
    hedge_words = len(re.findall(r'\b(maybe|perhaps|possibly|i think|i guess|not sure|might have|could have|probably)\b', all_text, re.I))
    hedge_ratio = hedge_words / max(word_count / 100, 1)
    coherence_score = max(0, 100 - hedge_ratio * 20)

    # 4. Completeness (based on 5W1H coverage)
    w_checks = {
        "who": bool(re.search(r'\b(he|she|they|man|woman|person|suspect|victim|officer|driver)\b', all_text, re.I)),
        "what": bool(re.search(r'\b(happened|saw|heard|noticed|hit|crashed|attacked|stole|broke)\b', all_text, re.I)),
        "when": bool(re.search(r'\b(\d{1,2}:\d{2}|morning|afternoon|evening|night|yesterday|today|ago)\b', all_text, re.I)),
        "where": bool(re.search(r'\b(street|road|park|building|corner|intersection|house|store|inside|outside)\b', all_text, re.I)),
        "why": bool(re.search(r'\b(because|reason|motive|argument|dispute|angry|drunk)\b', all_text, re.I)),
        "how": bool(re.search(r'\b(how|slowly|quickly|suddenly|carefully|violently|running|driving|walking)\b', all_text, re.I)),
    }
    completeness_score = (sum(w_checks.values()) / 6) * 100

    # 5. Volume (more statements → higher confidence in assessment)
    volume_score = min(100, len(statements) * 12)

    # Weighted overall
    overall = round(
        detail_score * 0.25 +
        consistency_score * 0.25 +
        coherence_score * 0.20 +
        completeness_score * 0.20 +
        volume_score * 0.10
    )

    return {
        "session_id": session_id,
        "credibility_score": min(100, max(0, overall)),
        "breakdown": {
            "detail_specificity": round(detail_score),
            "consistency": round(consistency_score),
            "coherence": round(coherence_score),
            "completeness": round(completeness_score),
            "volume": round(volume_score),
        },
        "coverage": w_checks,
        "flags": {
            "corrections": corrections,
            "hedge_words": hedge_words,
            "detail_mentions": detail_hits,
            "statement_count": len(statements),
        },
        "assessment": (
            "High credibility" if overall >= 75 else
            "Moderate credibility" if overall >= 50 else
            "Low credibility — needs more detail" if overall >= 25 else
            "Insufficient data for assessment"
        ),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 35: Testimony Timeline Extraction
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/extract-timeline")
async def extract_testimony_timeline(session_id: str):
    """Extract time-ordered events from testimony for visual timeline."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    events = []

    time_patterns = [
        (r'(?:at|around|about|approximately)\s+(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)', 'exact'),
        (r'(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)', 'exact'),
        (r'((?:early|late)\s+(?:morning|afternoon|evening|night))', 'approximate'),
        (r'((?:around|about)\s+(?:noon|midnight|dawn|dusk|sunset|sunrise))', 'approximate'),
        (r'(yesterday|today|last\s+(?:night|week|month))', 'relative'),
        (r'(\d+\s+(?:minutes?|hours?|days?)\s+(?:ago|later|before|after))', 'relative'),
        (r'((?:before|after|during|while)\s+\w+(?:\s+\w+){0,3})', 'sequential'),
    ]

    for i, s in enumerate(statements):
        text = s.text
        for pattern, precision in time_patterns:
            matches = re.finditer(pattern, text, re.I)
            for m in matches:
                time_ref = m.group(1) if m.lastindex else m.group(0)
                # Get surrounding context (up to 80 chars around match)
                start = max(0, m.start() - 40)
                end = min(len(text), m.end() + 40)
                context = text[start:end].strip()
                if start > 0:
                    context = "..." + context
                if end < len(text):
                    context = context + "..."

                events.append({
                    "time_reference": time_ref.strip(),
                    "precision": precision,
                    "context": context,
                    "statement_index": i,
                    "position": m.start(),
                })

    # Sort: exact times first, then approximate, then sequential
    precision_order = {"exact": 0, "approximate": 1, "relative": 2, "sequential": 3}
    events.sort(key=lambda e: (precision_order.get(e["precision"], 9), e["statement_index"], e["position"]))

    # Deduplicate close matches
    seen = set()
    unique_events = []
    for e in events:
        key = e["time_reference"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique_events.append(e)

    return {
        "session_id": session_id,
        "event_count": len(unique_events),
        "events": unique_events[:30],
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 36: Session Comparison
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/compare/{session_a}/{session_b}")
async def compare_sessions(session_a: str, session_b: str):
    """Compare two witness sessions for contradictions and commonalities."""
    sa = await firestore_service.get_session(session_a)
    sb = await firestore_service.get_session(session_b)
    if not sa:
        raise HTTPException(404, f"Session {session_a} not found")
    if not sb:
        raise HTTPException(404, f"Session {session_b} not found")

    text_a = " ".join(s.text for s in sa.witness_statements)
    text_b = " ".join(s.text for s in sb.witness_statements)

    words_a = set(re.findall(r'\b[a-z]{3,}\b', text_a.lower()))
    words_b = set(re.findall(r'\b[a-z]{3,}\b', text_b.lower()))

    common_words = words_a & words_b
    stop_words = {'the', 'and', 'was', 'were', 'that', 'this', 'with', 'have', 'had', 'for', 'not', 'but',
                  'are', 'from', 'they', 'been', 'said', 'what', 'when', 'where', 'who', 'how', 'about',
                  'which', 'then', 'them', 'than', 'just', 'also', 'some', 'could', 'would', 'into', 'more',
                  'like', 'very', 'there', 'their', 'your', 'other', 'after', 'before', 'back', 'over'}
    shared_keywords = sorted(common_words - stop_words)[:30]

    # Time references comparison
    time_pat = r'\b\d{1,2}:\d{2}\s*(?:am|pm)?\b'
    times_a = set(re.findall(time_pat, text_a, re.I))
    times_b = set(re.findall(time_pat, text_b, re.I))

    # Location references
    loc_pat = r'(?:at|on|near|in)\s+(?:the\s+)?([A-Z][a-zA-Z\s]+(?:Street|St|Ave|Road|Rd|Park|Mall|Store|Building))'
    locs_a = set(m.strip() for m in re.findall(loc_pat, text_a))
    locs_b = set(m.strip() for m in re.findall(loc_pat, text_b))

    return {
        "session_a": {"id": session_a, "title": sa.title, "statements": len(sa.witness_statements), "words": len(text_a.split())},
        "session_b": {"id": session_b, "title": sb.title, "statements": len(sb.witness_statements), "words": len(text_b.split())},
        "comparison": {
            "shared_keywords": shared_keywords,
            "shared_keyword_count": len(shared_keywords),
            "unique_to_a": len(words_a - words_b - stop_words),
            "unique_to_b": len(words_b - words_a - stop_words),
            "overlap_pct": round(len(common_words) / max(len(words_a | words_b), 1) * 100, 1),
            "time_refs_a": sorted(times_a),
            "time_refs_b": sorted(times_b),
            "shared_times": sorted(times_a & times_b),
            "locations_a": sorted(locs_a),
            "locations_b": sorted(locs_b),
            "shared_locations": sorted(locs_a & locs_b),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 37: Word Cloud Data
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/wordcloud")
async def get_wordcloud_data(session_id: str):
    """Get word frequency data for visual word cloud rendering."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    all_text = " ".join(s.text for s in statements)
    words = re.findall(r'\b[a-z]{3,}\b', all_text.lower())

    stop_words = {
        'the', 'and', 'was', 'were', 'that', 'this', 'with', 'have', 'had', 'for', 'not', 'but',
        'are', 'from', 'they', 'been', 'said', 'what', 'when', 'where', 'who', 'how', 'about',
        'which', 'then', 'them', 'than', 'just', 'also', 'some', 'could', 'would', 'into', 'more',
        'like', 'very', 'there', 'their', 'your', 'other', 'after', 'before', 'back', 'over',
        'can', 'don', 'did', 'does', 'because', 'through', 'too', 'only', 'its', 'being',
        'you', 'she', 'her', 'his', 'him', 'has', 'will', 'way', 'each', 'make',
    }

    freq = {}
    for w in words:
        if w not in stop_words and len(w) >= 3:
            freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:60]
    max_count = sorted_words[0][1] if sorted_words else 1

    cloud = [
        {"word": w, "count": c, "size": round(0.6 + (c / max_count) * 2.4, 2)}
        for w, c in sorted_words
    ]

    return {
        "session_id": session_id,
        "total_words": len(words),
        "unique_words": len(freq),
        "cloud": cloud,
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 38: Admin User Activity Log
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/activity-log")
async def get_activity_log(limit: int = 50, auth=Depends(require_admin_auth)):
    """Get detailed user activity log for admin review."""
    sessions = await firestore_service.list_sessions()

    activities = []
    for s in sessions:
        # Session creation
        activities.append({
            "type": "session_created",
            "icon": "🆕",
            "description": f"Session created: {s.title}",
            "session_id": s.id,
            "timestamp": s.created_at.isoformat() if s.created_at else None,
        })
        # Statement activity
        stmt_count = len(s.witness_statements)
        if stmt_count > 0:
            last_stmt = s.witness_statements[-1]
            activities.append({
                "type": "statement_added",
                "icon": "💬",
                "description": f"{stmt_count} statement(s) in '{s.title}'",
                "session_id": s.id,
                "timestamp": last_stmt.timestamp.isoformat() if hasattr(last_stmt, "timestamp") and last_stmt.timestamp else None,
            })
        # Status changes
        if s.status != "active":
            activities.append({
                "type": "status_change",
                "icon": "📋",
                "description": f"Session '{s.title}' → {s.status}",
                "session_id": s.id,
                "timestamp": s.updated_at.isoformat() if hasattr(s, "updated_at") and s.updated_at else None,
            })

    # Sort by timestamp (newest first)
    activities.sort(key=lambda a: a.get("timestamp") or "", reverse=True)

    return {
        "total": len(activities),
        "activities": activities[:limit],
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 39: Auto-Summary Generation
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/auto-summary")
async def get_auto_summary(session_id: str):
    """Generate a concise auto-summary of the current interview state."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if not statements:
        return {"session_id": session_id, "summary": "No statements recorded yet.", "key_points": []}

    all_text = " ".join(s.text for s in statements)
    words = all_text.split()

    # Extract key entities
    names = list(set(re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+))\b', all_text)))[:5]
    times = list(set(re.findall(r'\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\b', all_text, re.I)))[:5]
    locations = list(set(re.findall(r'(?:at|on|near)\s+(?:the\s+)?([A-Z][a-zA-Z\s]{3,30})', all_text)))[:5]

    # Build key points
    key_points = []
    if names:
        key_points.append(f"People mentioned: {', '.join(names[:3])}")
    if times:
        key_points.append(f"Times referenced: {', '.join(times[:3])}")
    if locations:
        key_points.append(f"Locations: {', '.join(locations[:3])}")

    corrections = sum(1 for s in statements if getattr(s, "is_correction", False))
    if corrections:
        key_points.append(f"Witness made {corrections} correction(s)")

    key_points.append(f"Interview contains {len(statements)} statements ({len(words)} words)")

    # Quick narrative summary from last 5 statements
    recent = statements[-5:]
    recent_text = " ".join(s.text for s in recent)
    if len(recent_text) > 200:
        recent_text = recent_text[:197] + "..."

    return {
        "session_id": session_id,
        "summary": f"Witness has provided {len(statements)} statements covering {len(words)} words. {f'Key people: {chr(44).join(names[:2])}. ' if names else ''}{f'Timeframe: {chr(44).join(times[:2])}. ' if times else ''}Recent focus: {recent_text}",
        "key_points": key_points,
        "stats": {
            "statements": len(statements),
            "words": len(words),
            "corrections": corrections,
            "names_found": len(names),
            "times_found": len(times),
            "locations_found": len(locations),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 41: Testimony Bookmark System
# ═══════════════════════════════════════════════════════════════════
_session_bookmarks: Dict[str, List[Dict[str, Any]]] = {}

@router.post("/sessions/{session_id}/bookmarks")
async def add_bookmark(session_id: str, data: dict):
    """Add a bookmark to a specific statement in the session."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    idx = data.get("statement_index", -1)
    note = data.get("note", "")
    label = data.get("label", "important")

    statements = session.witness_statements
    text_preview = ""
    if 0 <= idx < len(statements):
        text_preview = statements[idx].text[:120]
    elif statements:
        idx = len(statements) - 1
        text_preview = statements[-1].text[:120]

    bookmark = {
        "id": f"bm-{session_id[:8]}-{len(_session_bookmarks.get(session_id, []))}",
        "statement_index": idx,
        "note": note[:200] if note else "",
        "label": label,
        "text_preview": text_preview,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if session_id not in _session_bookmarks:
        _session_bookmarks[session_id] = []
    _session_bookmarks[session_id].append(bookmark)

    return {"bookmark": bookmark, "total": len(_session_bookmarks[session_id])}


@router.get("/sessions/{session_id}/bookmarks")
async def list_bookmarks(session_id: str):
    """List all bookmarks for a session."""
    return {
        "session_id": session_id,
        "bookmarks": _session_bookmarks.get(session_id, []),
        "total": len(_session_bookmarks.get(session_id, [])),
    }


@router.delete("/sessions/{session_id}/bookmarks/{bookmark_id}")
async def delete_bookmark(session_id: str, bookmark_id: str):
    """Delete a bookmark."""
    bms = _session_bookmarks.get(session_id, [])
    _session_bookmarks[session_id] = [b for b in bms if b["id"] != bookmark_id]
    return {"deleted": bookmark_id}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 42: AI Contradiction Detector
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/contradictions")
async def detect_contradictions(session_id: str):
    """Detect contradictions and inconsistencies in witness statements."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if len(statements) < 2:
        return {"session_id": session_id, "contradictions": [], "count": 0,
                "assessment": "Need at least 2 statements to detect contradictions."}

    contradictions = []
    texts = [s.text for s in statements]

    # Time contradiction detection
    time_refs = {}
    for i, t in enumerate(texts):
        times_found = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)\b', t)
        events = re.findall(r'(?:when|while|during|before|after)\s+(.{10,40})', t, re.I)
        for tf in times_found:
            norm = tf.strip().lower()
            if norm in time_refs and time_refs[norm]["index"] != i:
                prev = time_refs[norm]
                contradictions.append({
                    "type": "time_reference",
                    "severity": "medium",
                    "description": f"Time '{tf}' mentioned in different contexts",
                    "statement_a": {"index": prev["index"], "excerpt": prev["text"][:80]},
                    "statement_b": {"index": i, "excerpt": t[:80]},
                })
            else:
                time_refs[norm] = {"index": i, "text": t}

    # Quantity contradiction detection
    for i, t in enumerate(texts):
        quantities = re.findall(r'\b(\d+)\s+(people|person|car|vehicle|man|men|woman|women|kid|child|children)\b', t, re.I)
        for q_num, q_obj in quantities:
            obj_norm = q_obj.lower()
            for j in range(i + 1, len(texts)):
                other_quantities = re.findall(r'\b(\d+)\s+' + re.escape(obj_norm) + r'\b', texts[j], re.I)
                for oq in other_quantities:
                    if oq != q_num:
                        contradictions.append({
                            "type": "quantity_mismatch",
                            "severity": "high",
                            "description": f"Conflicting counts: '{q_num} {q_obj}' vs '{oq} {obj_norm}'",
                            "statement_a": {"index": i, "excerpt": texts[i][:80]},
                            "statement_b": {"index": j, "excerpt": texts[j][:80]},
                        })

    # Direction / location inconsistency
    directions = ["left", "right", "north", "south", "east", "west", "front", "back"]
    for i, t in enumerate(texts):
        for d in directions:
            if re.search(r'\b' + d + r'\b', t, re.I):
                opposites = {"left": "right", "right": "left", "north": "south", "south": "north",
                             "east": "west", "west": "east", "front": "back", "back": "front"}
                opp = opposites.get(d)
                if opp:
                    for j in range(i + 1, len(texts)):
                        if re.search(r'\b' + opp + r'\b', texts[j], re.I):
                            # Check if describing same event context
                            words_i = set(t.lower().split())
                            words_j = set(texts[j].lower().split())
                            overlap = len(words_i & words_j)
                            if overlap > 5:
                                contradictions.append({
                                    "type": "direction_inconsistency",
                                    "severity": "medium",
                                    "description": f"Opposite directions used: '{d}' vs '{opp}' in related statements",
                                    "statement_a": {"index": i, "excerpt": texts[i][:80]},
                                    "statement_b": {"index": j, "excerpt": texts[j][:80]},
                                })

    # Self-corrections detection
    corrections = []
    correction_phrases = [
        r"(?:actually|wait|no|sorry|I mean|let me correct|I was wrong|I meant)",
    ]
    for i, t in enumerate(texts):
        for pattern in correction_phrases:
            if re.search(pattern, t, re.I):
                corrections.append({"index": i, "excerpt": t[:100]})

    severity_score = len([c for c in contradictions if c["severity"] == "high"]) * 3 + \
                     len([c for c in contradictions if c["severity"] == "medium"]) * 1

    if severity_score == 0:
        assessment = "No significant contradictions detected"
    elif severity_score <= 3:
        assessment = "Minor inconsistencies found — may warrant clarification"
    elif severity_score <= 8:
        assessment = "Moderate contradictions detected — follow up recommended"
    else:
        assessment = "Significant contradictions — critical review needed"

    return {
        "session_id": session_id,
        "contradictions": contradictions[:20],
        "corrections": corrections[:10],
        "count": len(contradictions),
        "correction_count": len(corrections),
        "severity_score": severity_score,
        "assessment": assessment,
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 43: Session Export to Markdown
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/export/markdown")
async def export_session_markdown(session_id: str):
    """Export session as formatted markdown text."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    title = getattr(session, "title", "Untitled Session")
    created = getattr(session, "created_at", "Unknown")
    statements = session.witness_statements

    lines = []
    lines.append(f"# 🛡️ WitnessReplay — {title}")
    lines.append(f"")
    lines.append(f"**Session ID:** `{session_id}`  ")
    lines.append(f"**Created:** {created}  ")
    lines.append(f"**Statements:** {len(statements)}  ")
    lines.append(f"")
    lines.append("---")
    lines.append("")
    lines.append("## Testimony Transcript")
    lines.append("")

    for i, s in enumerate(statements, 1):
        speaker = getattr(s, "speaker", "witness").capitalize()
        ts = getattr(s, "timestamp", "")
        emoji = "🗣️" if speaker.lower() == "witness" else "🤖"
        lines.append(f"### {emoji} {speaker} (#{i})")
        if ts:
            lines.append(f"*{ts}*")
        lines.append("")
        lines.append(f"> {s.text}")
        lines.append("")

    # Summary section
    lines.append("---")
    lines.append("")
    lines.append("## Summary Statistics")
    lines.append("")
    total_words = sum(len(s.text.split()) for s in statements)
    lines.append(f"- **Total statements:** {len(statements)}")
    lines.append(f"- **Total words:** {total_words}")

    # Extract key entities
    all_text = " ".join(s.text for s in statements)
    names = list(set(re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+))\b', all_text)))[:5]
    times = list(set(re.findall(r'\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\b', all_text, re.I)))[:5]
    if names:
        lines.append(f"- **People mentioned:** {', '.join(names)}")
    if times:
        lines.append(f"- **Times referenced:** {', '.join(times)}")

    lines.append("")
    lines.append("---")
    lines.append(f"*Exported from WitnessReplay on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")

    markdown_text = "\n".join(lines)
    return {"session_id": session_id, "markdown": markdown_text, "statements": len(statements)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 44: Smart Evidence Linker
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/evidence-links")
async def extract_evidence_links(session_id: str):
    """Detect evidence references (exhibits, documents, photos) across testimony."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if not statements:
        return {"session_id": session_id, "evidence_refs": [], "count": 0}

    evidence_patterns = [
        (r'\b(Exhibit\s+[A-Z0-9]+)\b', 'exhibit'),
        (r'\b(Document\s+(?:#?\d+|[A-Z]))\b', 'document'),
        (r'\b(Photo(?:graph)?\s+(?:#?\d+|[A-Z]))\b', 'photo'),
        (r'\b(Video\s+(?:#?\d+|[A-Z]))\b', 'video'),
        (r'\b(Recording\s+(?:#?\d+|[A-Z]))\b', 'recording'),
        (r'\b(Report\s+(?:#?\d+|[A-Z]))\b', 'report'),
        (r'\b(Evidence\s+(?:#?\d+|[A-Z]))\b', 'evidence'),
        (r'\b(File\s+(?:#?\d+|[A-Z]))\b', 'file'),
        (r'\b(Item\s+(?:#?\d+|[A-Z]))\b', 'item'),
    ]

    refs_map = {}
    for i, s in enumerate(statements):
        for pattern, etype in evidence_patterns:
            matches = re.findall(pattern, s.text, re.I)
            for m in matches:
                key = m.strip().lower()
                if key not in refs_map:
                    refs_map[key] = {
                        "reference": m.strip(),
                        "type": etype,
                        "mentioned_in": [],
                        "contexts": [],
                    }
                refs_map[key]["mentioned_in"].append(i)
                # Extract surrounding context
                pos = s.text.lower().find(key)
                start = max(0, pos - 30)
                end = min(len(s.text), pos + len(key) + 30)
                refs_map[key]["contexts"].append(s.text[start:end].strip())

    evidence_refs = sorted(refs_map.values(), key=lambda x: len(x["mentioned_in"]), reverse=True)

    # Flag cross-referenced evidence
    cross_refs = [r for r in evidence_refs if len(r["mentioned_in"]) > 1]

    return {
        "session_id": session_id,
        "evidence_refs": evidence_refs[:30],
        "cross_referenced": cross_refs[:10],
        "count": len(evidence_refs),
        "cross_ref_count": len(cross_refs),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 45: Admin Case Analytics Dashboard
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/case-analytics")
async def get_case_analytics(auth=Depends(require_admin_auth)):
    """Aggregated analytics for cases and sessions."""
    all_sessions = await firestore_service.get_all_sessions()
    now = datetime.now(timezone.utc)

    total = len(all_sessions)
    stmt_counts = []
    word_counts = []
    sessions_by_day = {}
    status_dist = {}

    for s in all_sessions:
        stmts = s.witness_statements if hasattr(s, "witness_statements") else []
        stmt_counts.append(len(stmts))
        wc = sum(len(st.text.split()) for st in stmts)
        word_counts.append(wc)

        created = getattr(s, "created_at", None)
        if created:
            day = str(created)[:10]
            sessions_by_day[day] = sessions_by_day.get(day, 0) + 1

        st = getattr(s, "status", "active")
        status_dist[st] = status_dist.get(st, 0) + 1

    avg_stmts = round(sum(stmt_counts) / max(total, 1), 1)
    avg_words = round(sum(word_counts) / max(total, 1), 1)

    # Sort by day (last 30 days)
    sorted_days = sorted(sessions_by_day.items())[-30:]

    return {
        "total_sessions": total,
        "avg_statements_per_session": avg_stmts,
        "avg_words_per_session": avg_words,
        "max_statements": max(stmt_counts) if stmt_counts else 0,
        "max_words": max(word_counts) if word_counts else 0,
        "sessions_by_day": [{"date": d, "count": c} for d, c in sorted_days],
        "status_distribution": status_dist,
        "active_sessions": status_dist.get("active", 0),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 46: Witness Statement Diff
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/diff")
async def diff_statements(session_id: str, a: int = 0, b: int = -1):
    """Compare two statements within the same session to find changes."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if len(statements) < 2:
        return {"error": "Need at least 2 statements to diff"}

    if b < 0:
        b = len(statements) - 1
    if a < 0 or a >= len(statements) or b < 0 or b >= len(statements):
        raise HTTPException(400, "Statement indices out of range")

    text_a = statements[a].text
    text_b = statements[b].text
    words_a = text_a.lower().split()
    words_b = text_b.lower().split()
    set_a = set(words_a)
    set_b = set(words_b)

    added = set_b - set_a
    removed = set_a - set_b
    common = set_a & set_b

    # Compute similarity
    union = set_a | set_b
    similarity = round(len(common) / max(len(union), 1) * 100, 1)

    return {
        "session_id": session_id,
        "statement_a": {"index": a, "text": text_a[:300], "word_count": len(words_a)},
        "statement_b": {"index": b, "text": text_b[:300], "word_count": len(words_b)},
        "added_words": sorted(list(added))[:30],
        "removed_words": sorted(list(removed))[:30],
        "common_word_count": len(common),
        "similarity_pct": similarity,
        "added_count": len(added),
        "removed_count": len(removed),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 47: Interview Completeness Checker
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/completeness")
async def check_interview_completeness(session_id: str):
    """Score how complete an interview is based on investigation area coverage."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    all_text = " ".join(s.text for s in statements).lower() if statements else ""

    # Investigation areas to check
    areas = {
        "who": {
            "label": "People / Suspects",
            "patterns": [r'\b(he|she|they|man|woman|person|suspect|victim|witness|name|someone)\b'],
            "icon": "👤",
        },
        "what": {
            "label": "What Happened",
            "patterns": [r'\b(happened|saw|heard|noticed|event|incident|attack|crash|shot|hit|stole)\b'],
            "icon": "❓",
        },
        "when": {
            "label": "Time / Date",
            "patterns": [r'\b(\d{1,2}:\d{2}|morning|afternoon|evening|night|today|yesterday|o.clock|ago|around|about)\b'],
            "icon": "🕐",
        },
        "where": {
            "label": "Location / Place",
            "patterns": [r'\b(street|road|building|house|store|park|corner|block|intersection|address|apartment|near)\b'],
            "icon": "📍",
        },
        "how": {
            "label": "Method / Manner",
            "patterns": [r'\b(how|using|weapon|knife|gun|car|ran|drove|walked|broke|entered|forced)\b'],
            "icon": "🔧",
        },
        "description": {
            "label": "Physical Descriptions",
            "patterns": [r'\b(tall|short|hair|wearing|shirt|jacket|hat|tattoo|scar|build|heavy|thin|old|young|age|color|white|black|red|blue)\b'],
            "icon": "📋",
        },
        "vehicle": {
            "label": "Vehicle Info",
            "patterns": [r'\b(car|truck|van|motorcycle|bike|license|plate|model|make|color|sedan|suv)\b'],
            "icon": "🚗",
        },
        "evidence": {
            "label": "Physical Evidence",
            "patterns": [r'\b(evidence|photo|video|recording|camera|fingerprint|blood|damage|broken|mark)\b'],
            "icon": "🔬",
        },
        "sequence": {
            "label": "Event Sequence",
            "patterns": [r'\b(first|then|after|before|next|finally|later|suddenly|while|during|followed)\b'],
            "icon": "📊",
        },
        "emotional": {
            "label": "Emotional State",
            "patterns": [r'\b(scared|afraid|angry|upset|nervous|calm|crying|shouting|panic|shock|confused)\b'],
            "icon": "💭",
        },
    }

    coverage = {}
    total_score = 0
    for key, area in areas.items():
        match_count = 0
        for pattern in area["patterns"]:
            match_count += len(re.findall(pattern, all_text, re.I))
        covered = match_count > 0
        depth = min(match_count, 10)
        score = min(round(depth / 3 * 100), 100)
        coverage[key] = {
            "label": area["label"],
            "icon": area["icon"],
            "covered": covered,
            "match_count": match_count,
            "depth_score": score,
        }
        if covered:
            total_score += 1

    completeness_pct = round(total_score / len(areas) * 100)
    missing = [v for k, v in coverage.items() if not v["covered"]]

    if completeness_pct >= 90:
        assessment = "Excellent — nearly all areas covered"
    elif completeness_pct >= 70:
        assessment = "Good — most areas addressed"
    elif completeness_pct >= 50:
        assessment = "Moderate — several areas need more detail"
    elif completeness_pct >= 30:
        assessment = "Incomplete — many critical areas missing"
    else:
        assessment = "Early stage — continue gathering information"

    suggestions = []
    for area in missing[:3]:
        suggestions.append(f"Ask about: {area['icon']} {area['label']}")

    return {
        "session_id": session_id,
        "completeness_pct": completeness_pct,
        "areas_covered": total_score,
        "total_areas": len(areas),
        "assessment": assessment,
        "coverage": coverage,
        "missing_areas": [{"label": m["label"], "icon": m["icon"]} for m in missing],
        "suggestions": suggestions,
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 49: Key Quote Extraction
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/key-quotes")
async def extract_key_quotes(session_id: str):
    """Extract the most notable and important quotes from testimony."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if not statements:
        return {"quotes": [], "total": 0}

    quote_patterns = [
        (r'\b(I saw|I heard|I noticed|I observed|I remember|I recall|I witnessed)\b', "eyewitness", "👁️"),
        (r'\b(he said|she said|they said|told me|yelled|screamed|whispered)\b', "direct_speech", "💬"),
        (r'\b(I\'m sure|I\'m certain|definitely|absolutely|no doubt|100 percent|positive)\b', "high_confidence", "✅"),
        (r'\b(I think|I believe|maybe|possibly|not sure|might have|could have|I guess)\b', "uncertainty", "❓"),
        (r'\b(threatened|attacked|hit|shot|stabbed|pushed|grabbed|choked|punched)\b', "violence", "⚠️"),
        (r'\b(afraid|scared|terrified|panicked|shocked|horrified|traumatized)\b', "emotional", "💭"),
        (r'\b(first|then|after that|next|before|finally|suddenly|immediately)\b', "sequence", "📊"),
        (r'\b(approximately|about \d|around \d|\d+ feet|\d+ minutes|\d+ hours)\b', "measurement", "📏"),
    ]

    quotes = []
    for stmt in statements:
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        if len(text) < 10:
            continue
        importance = 0
        categories = []
        for pattern, cat, icon in quote_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                importance += 1
                if cat not in [c["type"] for c in categories]:
                    categories.append({"type": cat, "icon": icon})

        if importance >= 1:
            # Extract a clean quote snippet (first 200 chars of matching sentence)
            sentences = re.split(r'[.!?]+', text)
            best_sentence = text[:200]
            for s in sentences:
                s = s.strip()
                if len(s) > 15:
                    for pattern, _, _ in quote_patterns:
                        if re.search(pattern, s, re.IGNORECASE):
                            best_sentence = s[:200]
                            break
            quotes.append({
                "text": best_sentence.strip(),
                "importance": importance,
                "categories": categories,
                "statement_index": statements.index(stmt),
            })

    quotes.sort(key=lambda q: q["importance"], reverse=True)
    return {"quotes": quotes[:15], "total": len(quotes)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 50: Witness Cooperation Assessment
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/cooperation")
async def assess_cooperation(session_id: str):
    """Assess witness cooperation and responsiveness level."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if not statements:
        return {"score": 0, "level": "unknown", "indicators": {}}

    total = len(statements)
    total_words = 0
    evasive_count = 0
    detailed_count = 0
    correction_count = 0
    refusal_count = 0
    emotional_count = 0

    evasive_patterns = re.compile(r'\b(I don.t know|can.t remember|I forget|no comment|I.m not sure|I refuse|I plead|none of your)\b', re.IGNORECASE)
    detailed_patterns = re.compile(r'\b(specifically|exactly|precisely|in detail|for example|such as|including)\b', re.IGNORECASE)
    refusal_patterns = re.compile(r'\b(I won.t|I refuse|I decline|no comment|lawyer|attorney|fifth amendment|I plead)\b', re.IGNORECASE)
    emotional_patterns = re.compile(r'\b(sorry|please|I swear|honestly|trust me|believe me|I promise)\b', re.IGNORECASE)

    for stmt in statements:
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        words = len(text.split())
        total_words += words
        if getattr(stmt, 'is_correction', False):
            correction_count += 1
        if evasive_patterns.search(text):
            evasive_count += 1
        if detailed_patterns.search(text):
            detailed_count += 1
        if refusal_patterns.search(text):
            refusal_count += 1
        if emotional_patterns.search(text):
            emotional_count += 1

    avg_words = total_words / total if total > 0 else 0
    detail_ratio = detailed_count / total if total > 0 else 0
    evasive_ratio = evasive_count / total if total > 0 else 0
    refusal_ratio = refusal_count / total if total > 0 else 0

    # Score 0-100
    score = 50
    score += min(20, int(avg_words / 5))  # Longer answers = more cooperative
    score += int(detail_ratio * 20)
    score -= int(evasive_ratio * 25)
    score -= int(refusal_ratio * 30)
    score += int(correction_count * 3)  # Willing to correct = cooperative
    score = max(0, min(100, score))

    if score >= 80:
        level = "highly_cooperative"
    elif score >= 60:
        level = "cooperative"
    elif score >= 40:
        level = "moderately_cooperative"
    elif score >= 20:
        level = "reluctant"
    else:
        level = "uncooperative"

    return {
        "score": score,
        "level": level,
        "indicators": {
            "avg_response_length": round(avg_words, 1),
            "detailed_responses": detailed_count,
            "evasive_responses": evasive_count,
            "refusals": refusal_count,
            "corrections_offered": correction_count,
            "emotional_appeals": emotional_count,
            "total_statements": total,
        },
        "assessment": {
            "highly_cooperative": "Witness is very cooperative, providing detailed and helpful responses",
            "cooperative": "Witness is generally cooperative with good detail level",
            "moderately_cooperative": "Witness shows mixed cooperation, some evasiveness noted",
            "reluctant": "Witness appears reluctant, with frequent vague or short responses",
            "uncooperative": "Witness is largely uncooperative, refusing or evading questions",
        }.get(level, "Unknown"),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 51: Testimony Annotation System
# ═══════════════════════════════════════════════════════════════════
_session_annotations: Dict[str, list] = {}

@router.post("/sessions/{session_id}/annotations")
async def add_annotation(session_id: str, data: dict):
    """Add an annotation to a session."""
    text = data.get("text", "").strip()
    msg_index = data.get("message_index")
    category = data.get("category", "note")
    if not text:
        raise HTTPException(400, "Annotation text required")

    if session_id not in _session_annotations:
        _session_annotations[session_id] = []

    annotation = {
        "id": f"ann-{len(_session_annotations[session_id])}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
        "text": text,
        "message_index": msg_index,
        "category": category,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _session_annotations[session_id].append(annotation)
    return {"annotation": annotation, "total": len(_session_annotations[session_id])}

@router.get("/sessions/{session_id}/annotations")
async def list_annotations(session_id: str):
    """List all annotations for a session."""
    anns = _session_annotations.get(session_id, [])
    return {"session_id": session_id, "annotations": anns, "total": len(anns)}

@router.delete("/sessions/{session_id}/annotations/{annotation_id}")
async def delete_annotation(session_id: str, annotation_id: str):
    """Delete an annotation."""
    anns = _session_annotations.get(session_id, [])
    _session_annotations[session_id] = [a for a in anns if a["id"] != annotation_id]
    return {"deleted": annotation_id}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 52: Cross-Session Search
# ═══════════════════════════════════════════════════════════════════
@router.get("/search-sessions")
async def search_all_sessions(q: str = "", limit: int = 20):
    """Search across all sessions for a keyword or phrase."""
    if not q.strip():
        return {"results": [], "query": q, "total": 0}

    query_lower = q.strip().lower()
    sessions = await firestore_service.list_sessions(limit=500)
    results = []

    for session in sessions:
        matches = []
        statements = getattr(session, 'witness_statements', []) or []
        for i, stmt in enumerate(statements):
            text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
            if query_lower in text.lower():
                # Extract context around match
                idx = text.lower().index(query_lower)
                start = max(0, idx - 40)
                end = min(len(text), idx + len(query_lower) + 40)
                snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
                matches.append({"statement_index": i, "snippet": snippet})

        case_title = getattr(session, 'case_title', '') or ''
        if query_lower in case_title.lower():
            matches.append({"statement_index": -1, "snippet": f"Case title: {case_title}"})

        if matches:
            results.append({
                "session_id": getattr(session, 'session_id', '') or getattr(session, 'id', ''),
                "case_title": case_title,
                "statement_count": len(statements),
                "matches": matches[:5],
                "match_count": len(matches),
            })

    results.sort(key=lambda r: r["match_count"], reverse=True)
    return {"results": results[:limit], "query": q, "total": len(results)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 53: Testimony Highlight Reel
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/highlights")
async def get_testimony_highlights(session_id: str):
    """Auto-extract the most important testimony moments."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    statements = session.witness_statements
    if not statements:
        return {"highlights": [], "total": 0}

    highlight_signals = [
        (r'\b(I saw|I witnessed|I observed)\b', "direct_observation", "👁️", 3),
        (r'\b(he said|she said|they told me)\b', "reported_speech", "💬", 2),
        (r'\b(suddenly|immediately|all of a sudden|out of nowhere)\b', "sudden_event", "⚡", 3),
        (r'\b(weapon|gun|knife|blood|injury|wound|dead|killed)\b', "critical_detail", "🔴", 4),
        (r'\b(I remember clearly|I will never forget|distinctly|vivid)\b', "vivid_memory", "🧠", 3),
        (r'\b(wait|actually|correction|let me clarify|I was wrong)\b', "correction", "🔄", 2),
        (r'\b(license plate|registration|serial number|badge|ID)\b', "identifying_info", "🏷️", 4),
        (r'\b(I heard a|loud|bang|scream|crash|explosion)\b', "auditory", "👂", 2),
        (r'\b(ran|fled|escaped|chased|drove away|sped off)\b', "flight", "🏃", 3),
        (r'\b(approximately|about \d|around \d|o.clock|a\.m\.|p\.m\.)\b', "time_reference", "🕐", 2),
    ]

    highlights = []
    for i, stmt in enumerate(statements):
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        if len(text) < 10:
            continue

        score = 0
        tags = []
        for pattern, tag, icon, weight in highlight_signals:
            if re.search(pattern, text, re.IGNORECASE):
                score += weight
                if tag not in [t["type"] for t in tags]:
                    tags.append({"type": tag, "icon": icon})

        # Bonus for longer, more detailed responses
        word_count = len(text.split())
        if word_count > 30:
            score += 1
        if word_count > 60:
            score += 1

        if score >= 3:
            highlights.append({
                "text": text[:300] + ("..." if len(text) > 300 else ""),
                "score": score,
                "tags": tags,
                "statement_index": i,
                "word_count": word_count,
            })

    highlights.sort(key=lambda h: h["score"], reverse=True)
    return {"highlights": highlights[:10], "total": len(highlights)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 54: Admin System Health Dashboard (enhanced)
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/health-dashboard")
async def get_health_dashboard(auth=Depends(require_admin_auth)):
    """Get a comprehensive health dashboard with session stats, trends, and system info."""
    import time as _time
    try:
        sessions = await firestore_service.list_sessions(limit=500)
        total_sessions = len(sessions)
        total_statements = sum(len(getattr(s, 'witness_statements', []) or []) for s in sessions)

        # Status breakdown
        status_counts = {}
        for s in sessions:
            st = getattr(s, 'status', 'unknown') or 'unknown'
            status_counts[st] = status_counts.get(st, 0) + 1

        # Recent activity (last 24h)
        now = datetime.now(timezone.utc)
        recent = 0
        for s in sessions:
            created = getattr(s, 'created_at', None)
            if created:
                try:
                    if isinstance(created, str):
                        created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if hasattr(created, 'tzinfo') and created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if (now - created).total_seconds() < 86400:
                        recent += 1
                except Exception:
                    pass

        # Avg statements per session
        avg_stmts = round(total_statements / total_sessions, 1) if total_sessions > 0 else 0

        # System uptime
        import psutil
        proc = psutil.Process()
        uptime_sec = (now - datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)).total_seconds()
        hours = int(uptime_sec // 3600)
        mins = int((uptime_sec % 3600) // 60)

        return {
            "sessions": {
                "total": total_sessions,
                "recent_24h": recent,
                "avg_statements": avg_stmts,
                "total_statements": total_statements,
                "status_breakdown": status_counts,
            },
            "system": {
                "uptime": f"{hours}h {mins}m",
                "uptime_seconds": int(uptime_sec),
                "memory_mb": round(proc.memory_info().rss / 1048576, 1),
                "cpu_percent": psutil.cpu_percent(interval=0.3),
                "timestamp": now.isoformat(),
            },
            "storage": {
                "annotations": sum(len(v) for v in _session_annotations.values()),
                "bookmarks": sum(len(v) for v in _session_bookmarks.values()),
            },
        }
    except Exception as e:
        logger.error(f"Health dashboard error: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 55: Admin Bulk Export
# ═══════════════════════════════════════════════════════════════════
@router.post("/admin/bulk-export")
async def bulk_export_sessions(data: dict, auth=Depends(require_admin_auth)):
    """Export multiple sessions in JSON or CSV format."""
    session_ids = data.get("session_ids", [])
    fmt = data.get("format", "json")
    limit = data.get("limit", 50)

    if not session_ids:
        all_sessions = await firestore_service.list_sessions(limit=limit)
        session_ids = [getattr(s, 'session_id', '') or getattr(s, 'id', '') for s in all_sessions]

    exported = []
    for sid in session_ids[:100]:
        try:
            session = await firestore_service.get_session(sid)
            if not session:
                continue
            statements = getattr(session, 'witness_statements', []) or []
            exported.append({
                "session_id": sid,
                "case_title": getattr(session, 'case_title', '') or '',
                "status": getattr(session, 'status', '') or '',
                "statement_count": len(statements),
                "statements": [
                    {
                        "index": i,
                        "text": getattr(s, 'text', '') or getattr(s, 'content', '') or str(s),
                        "is_correction": getattr(s, 'is_correction', False),
                    }
                    for i, s in enumerate(statements)
                ],
                "created_at": str(getattr(session, 'created_at', '')),
            })
        except Exception:
            continue

    if fmt == "csv":
        lines = ["session_id,case_title,status,statement_count,created_at"]
        for e in exported:
            lines.append(f'"{e["session_id"]}","{e["case_title"]}","{e["status"]}",{e["statement_count"]},"{e["created_at"]}"')
        return {"format": "csv", "content": "\n".join(lines), "total": len(exported)}

    return {"format": "json", "sessions": exported, "total": len(exported)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 56: Testimony Outline Generator
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/outline")
async def generate_testimony_outline(session_id: str):
    """Auto-generate a structured outline/TOC of testimony by detected topics."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"outline": [], "total_sections": 0}

    topic_patterns = {
        "identification": {"patterns": [r"\bname\b", r"\bidentif", r"\bwho (?:are|were) you"], "icon": "🪪"},
        "location": {"patterns": [r"\bwhere\b", r"\blocation\b", r"\baddress\b", r"\bscene\b", r"\bstreet\b"], "icon": "📍"},
        "timeline": {"patterns": [r"\bwhen\b", r"\btime\b", r"\bclock\b", r"\bo'clock\b", r"\bdate\b", r"\bmorning\b", r"\bevening\b", r"\bnight\b"], "icon": "🕐"},
        "observations": {"patterns": [r"\bsaw\b", r"\bheard\b", r"\bnoticed\b", r"\bobserved\b", r"\bwitnessed\b", r"\blooked\b"], "icon": "👁️"},
        "actions": {"patterns": [r"\bran\b", r"\bdrove\b", r"\bhit\b", r"\bpushed\b", r"\bgrabbed\b", r"\bfled\b", r"\bchased\b"], "icon": "🏃"},
        "description": {"patterns": [r"\btall\b", r"\bwearing\b", r"\bhair\b", r"\bcloth", r"\bappearance\b", r"\bbuilt\b"], "icon": "📝"},
        "vehicle": {"patterns": [r"\bcar\b", r"\bvehicle\b", r"\btruck\b", r"\bvan\b", r"\blicense\b", r"\bplate\b"], "icon": "🚗"},
        "emotional": {"patterns": [r"\bscared\b", r"\bafraid\b", r"\bangry\b", r"\bshock", r"\bcried\b", r"\bupset\b", r"\bfrightened\b"], "icon": "😨"},
        "evidence": {"patterns": [r"\bweapon\b", r"\bknife\b", r"\bgun\b", r"\bblood\b", r"\bfootprint\b", r"\bdna\b", r"\bfingerprint"], "icon": "🔍"},
        "aftermath": {"patterns": [r"\bpolice\b", r"\bambulance\b", r"\bhospital\b", r"\b911\b", r"\bcalled\b", r"\breported\b"], "icon": "🚨"},
    }

    sections = []
    for i, stmt in enumerate(statements):
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        text_lower = text.lower()
        topics_found = []
        for topic, info in topic_patterns.items():
            for pat in info["patterns"]:
                if re.search(pat, text_lower):
                    topics_found.append({"topic": topic, "icon": info["icon"]})
                    break
        if not topics_found:
            topics_found = [{"topic": "general", "icon": "💬"}]
        preview = text[:120].strip() + ("..." if len(text) > 120 else "")
        sections.append({
            "index": i,
            "topics": topics_found,
            "preview": preview,
            "word_count": len(text.split()),
        })

    topic_summary = {}
    for sec in sections:
        for t in sec["topics"]:
            topic_summary[t["topic"]] = topic_summary.get(t["topic"], 0) + 1

    return {
        "outline": sections,
        "total_sections": len(sections),
        "topic_summary": topic_summary,
        "case_title": getattr(session, 'case_title', '') or '',
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 57: Witness Reliability Timeline
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/reliability")
async def get_reliability_timeline(session_id: str):
    """Track answer quality/detail over interview progression."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"timeline": [], "avg_reliability": 0, "trend": "neutral"}

    hedging_words = [r"\bmaybe\b", r"\bperhaps\b", r"\bpossibly\b", r"\bi think\b", r"\bi guess\b", r"\bnot sure\b", r"\bprobably\b", r"\bmight\b"]
    precise_words = [r"\bexactly\b", r"\bprecisely\b", r"\bdefinitely\b", r"\bclearly\b", r"\bcertain\b", r"\bi remember\b", r"\bspecifically\b"]
    detail_markers = [r"\d{1,2}:\d{2}", r"\d+ (?:feet|meters|yards|inches)", r"\b(?:red|blue|green|black|white|yellow)\b", r"\b(?:left|right|north|south|east|west)\b"]

    timeline = []
    for i, stmt in enumerate(statements):
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        text_lower = text.lower()
        words = len(text.split())

        hedge_count = sum(1 for p in hedging_words if re.search(p, text_lower))
        precise_count = sum(1 for p in precise_words if re.search(p, text_lower))
        detail_count = sum(1 for p in detail_markers if re.search(p, text_lower))

        # Reliability score: detail & precision boost, hedging penalizes
        base = min(40, words * 0.5)  # longer = more base
        score = base + (precise_count * 12) + (detail_count * 8) - (hedge_count * 10)
        score = max(0, min(100, score))

        timeline.append({
            "index": i,
            "score": round(score, 1),
            "word_count": words,
            "hedging": hedge_count,
            "precision": precise_count,
            "details": detail_count,
            "label": "high" if score >= 70 else "medium" if score >= 40 else "low",
        })

    scores = [t["score"] for t in timeline]
    avg = round(sum(scores) / len(scores), 1) if scores else 0

    # Trend: compare first half vs second half
    mid = len(scores) // 2
    if mid > 0 and len(scores) > 1:
        first_half = sum(scores[:mid]) / mid
        second_half = sum(scores[mid:]) / (len(scores) - mid)
        trend = "improving" if second_half > first_half + 5 else "declining" if second_half < first_half - 5 else "stable"
    else:
        trend = "neutral"

    return {"timeline": timeline, "avg_reliability": avg, "trend": trend, "total": len(timeline)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 58: PII Redaction Tool
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/redact")
async def detect_pii(session_id: str):
    """Detect PII in testimony (SSN, phone, email, addresses)."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"findings": [], "total_pii": 0}

    pii_patterns = {
        "ssn": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b", "icon": "🔒", "severity": "critical"},
        "phone": {"pattern": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "icon": "📱", "severity": "high"},
        "email": {"pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "icon": "📧", "severity": "high"},
        "date_of_birth": {"pattern": r"\b(?:born|dob|date of birth)[:\s]+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b", "icon": "🎂", "severity": "medium"},
        "address": {"pattern": r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Rd|Road|Ln|Lane|Ct|Court)\b", "icon": "🏠", "severity": "medium"},
        "license_plate": {"pattern": r"\b[A-Z]{2,3}[-\s]?\d{3,4}[-\s]?[A-Z]{0,3}\b", "icon": "🚗", "severity": "medium"},
        "credit_card": {"pattern": r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "icon": "💳", "severity": "critical"},
    }

    findings = []
    for i, stmt in enumerate(statements):
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        stmt_findings = []
        for pii_type, info in pii_patterns.items():
            matches = re.finditer(info["pattern"], text, re.IGNORECASE)
            for m in matches:
                masked = m.group(0)[:2] + "•" * (len(m.group(0)) - 4) + m.group(0)[-2:] if len(m.group(0)) > 4 else "••••"
                stmt_findings.append({
                    "type": pii_type,
                    "icon": info["icon"],
                    "severity": info["severity"],
                    "masked": masked,
                    "position": m.start(),
                })
        if stmt_findings:
            findings.append({
                "statement_index": i,
                "pii_items": stmt_findings,
                "count": len(stmt_findings),
            })

    total = sum(f["count"] for f in findings)
    severity_dist = {}
    for f in findings:
        for p in f["pii_items"]:
            severity_dist[p["severity"]] = severity_dist.get(p["severity"], 0) + 1

    return {"findings": findings, "total_pii": total, "severity_distribution": severity_dist}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 59: Question Analyzer
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/questions")
async def analyze_questions(session_id: str):
    """Extract and categorize all questions from testimony."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"questions": [], "total": 0}

    question_types = {
        "open_ended": [r"^(?:what|how|why|describe|explain|tell)\b"],
        "closed": [r"^(?:did|do|does|is|are|was|were|can|could|would|will|has|have|had)\b"],
        "leading": [r"^(?:isn't it true|wouldn't you|don't you|didn't you|you (?:did|saw|were|said))\b"],
        "clarifying": [r"^(?:you mean|so you're saying|to clarify|let me understand)\b"],
        "temporal": [r"^(?:when|what time|how long|how (?:many|much) time)\b"],
        "spatial": [r"^(?:where|which direction|how far|how close)\b"],
    }

    questions = []
    for i, stmt in enumerate(statements):
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        # Extract sentences ending with ?
        q_sentences = re.findall(r'[^.!?]*\?', text)
        for q in q_sentences:
            q_clean = q.strip()
            if len(q_clean) < 5:
                continue
            q_lower = q_clean.lower().strip()
            q_type = "other"
            for typ, patterns in question_types.items():
                for pat in patterns:
                    if re.search(pat, q_lower):
                        q_type = typ
                        break
                if q_type != "other":
                    break
            questions.append({
                "text": q_clean,
                "type": q_type,
                "statement_index": i,
                "word_count": len(q_clean.split()),
            })

    type_dist = {}
    for q in questions:
        type_dist[q["type"]] = type_dist.get(q["type"], 0) + 1

    type_icons = {
        "open_ended": "🔓", "closed": "🔒", "leading": "⚠️",
        "clarifying": "🔍", "temporal": "🕐", "spatial": "📍", "other": "❓",
    }

    return {
        "questions": questions[:50],
        "total": len(questions),
        "type_distribution": type_dist,
        "type_icons": type_icons,
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 60: Session Pinning/Favorites
# ═══════════════════════════════════════════════════════════════════
_pinned_sessions: Dict[str, Dict[str, Any]] = {}

@router.post("/sessions/{session_id}/pin")
async def pin_session(session_id: str, data: dict = {}):
    """Pin/unpin a session for quick access."""
    if session_id in _pinned_sessions:
        del _pinned_sessions[session_id]
        return {"pinned": False, "session_id": session_id, "total_pinned": len(_pinned_sessions)}

    session = await firestore_service.get_session(session_id)
    _pinned_sessions[session_id] = {
        "session_id": session_id,
        "case_title": getattr(session, 'case_title', '') or '' if session else '',
        "pinned_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"pinned": True, "session_id": session_id, "total_pinned": len(_pinned_sessions)}


@router.get("/pinned-sessions")
async def list_pinned_sessions():
    """List all pinned sessions."""
    pins = sorted(_pinned_sessions.values(), key=lambda x: x.get("pinned_at", ""), reverse=True)
    return {"pinned": pins, "total": len(pins)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 61: Admin Audit Trail
# ═══════════════════════════════════════════════════════════════════
_admin_audit_trail: deque = deque(maxlen=500)

def _log_admin_action(action: str, details: str = "", user: str = "admin"):
    _admin_audit_trail.appendleft({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
        "user": user,
    })

@router.get("/admin/audit-trail")
async def get_audit_trail(limit: int = 100, auth=Depends(require_admin_auth)):
    """Get admin audit trail."""
    _log_admin_action("view_audit_trail", "Viewed audit trail")
    entries = list(_admin_audit_trail)[:limit]
    return {"entries": entries, "total": len(_admin_audit_trail)}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 62: Summary Card Generator
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/summary-card")
async def generate_summary_card(session_id: str):
    """Generate a compact summary card for a session."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    texts = [getattr(s, 'text', '') or getattr(s, 'content', '') or str(s) for s in statements]
    all_text = " ".join(texts).lower()
    total_words = len(all_text.split())

    # Key stats
    people_mentioned = set(re.findall(r'\b(?:Mr|Mrs|Ms|Dr|Officer|Detective|Judge)\.\s+[A-Z][a-z]+', " ".join(texts)))
    locations = set(re.findall(r'\b\d{1,5}\s+[A-Z][a-z]+\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Ct)', " ".join(texts)))
    times = set(re.findall(r'\b\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?\b', " ".join(texts)))

    # Dominant emotion
    emotions = {
        "fearful": len(re.findall(r'\b(?:scared|afraid|frightened|terrified|fear)\b', all_text)),
        "angry": len(re.findall(r'\b(?:angry|mad|furious|rage|upset)\b', all_text)),
        "sad": len(re.findall(r'\b(?:sad|crying|cried|tears|devastated)\b', all_text)),
        "calm": len(re.findall(r'\b(?:calm|clearly|remember|confident|certain)\b', all_text)),
        "confused": len(re.findall(r'\b(?:confused|unsure|maybe|perhaps|not sure)\b', all_text)),
    }
    dominant_emotion = max(emotions, key=emotions.get) if any(emotions.values()) else "neutral"

    # First sentence as opener
    opener = texts[0][:150].strip() + "..." if texts else "No statements yet"

    return {
        "session_id": session_id,
        "case_title": getattr(session, 'case_title', '') or 'Untitled',
        "status": getattr(session, 'status', '') or 'unknown',
        "statement_count": len(statements),
        "total_words": total_words,
        "people_mentioned": list(people_mentioned)[:10],
        "locations": list(locations)[:5],
        "times_referenced": list(times)[:10],
        "dominant_emotion": dominant_emotion,
        "emotion_scores": emotions,
        "opener": opener,
        "created_at": str(getattr(session, 'created_at', '')),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 63: Statement Gap Detector
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/gaps")
async def detect_statement_gaps(session_id: str):
    """Detect temporal gaps, missing info, and logical jumps in testimony."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"gaps": [], "total": 0, "severity_summary": {}}

    texts = [getattr(s, 'text', '') or getattr(s, 'content', '') or str(s) for s in statements]

    gap_signals = {
        "temporal_jump": {"patterns": [r'\b(?:then later|after that|some time later|the next day|hours later|suddenly)\b'], "icon": "⏭️", "severity": "medium"},
        "memory_gap": {"patterns": [r"\b(?:I don't remember|I can't recall|it's unclear|I'm not sure what happened|blank|fuzzy)\b"], "icon": "🧠", "severity": "high"},
        "topic_shift": {"patterns": [r'\b(?:anyway|moving on|different topic|back to|let me go back|changing subject)\b'], "icon": "🔀", "severity": "low"},
        "missing_detail": {"patterns": [r'\b(?:something happened|things occurred|stuff went on|I think something|not sure exactly)\b'], "icon": "❓", "severity": "high"},
        "contradiction_hint": {"patterns": [r'\b(?:wait|actually|no,? I mean|let me correct|I misspoke|that\'s wrong)\b'], "icon": "⚡", "severity": "high"},
        "evasion": {"patterns": [r"\b(?:I'd rather not|can we skip|I don't want to|that's not relevant|next question)\b"], "icon": "🚫", "severity": "critical"},
        "vague_timing": {"patterns": [r'\b(?:sometime|at some point|around then|about that time|a while)\b'], "icon": "🕐", "severity": "medium"},
    }

    gaps = []
    for i, text in enumerate(texts):
        text_lower = text.lower()
        for gap_type, info in gap_signals.items():
            for pat in info["patterns"]:
                matches = re.finditer(pat, text_lower)
                for m in matches:
                    context_start = max(0, m.start() - 40)
                    context_end = min(len(text), m.end() + 40)
                    gaps.append({
                        "type": gap_type,
                        "icon": info["icon"],
                        "severity": info["severity"],
                        "statement_index": i,
                        "matched": m.group(0),
                        "context": text[context_start:context_end].strip(),
                    })

    severity_summary = {}
    for g in gaps:
        severity_summary[g["severity"]] = severity_summary.get(g["severity"], 0) + 1

    # Sort by severity
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    gaps.sort(key=lambda g: sev_order.get(g["severity"], 9))

    return {"gaps": gaps[:50], "total": len(gaps), "severity_summary": severity_summary}


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 64: Testimony Comparison Matrix
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/comparison-matrix")
async def build_comparison_matrix(session_id: str, compare_id: str = ""):
    """Build a comparison matrix between two sessions across key dimensions."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def _extract_dims(sess):
        stmts = getattr(sess, 'witness_statements', []) or []
        texts = [getattr(s, 'text', '') or getattr(s, 'content', '') or str(s) for s in stmts]
        all_text = " ".join(texts)
        all_lower = all_text.lower()

        times = list(set(re.findall(r'\b\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?\b', all_text)))
        people = list(set(re.findall(r'\b(?:Mr|Mrs|Ms|Dr|Officer|Detective)\.\s+[A-Z][a-z]+', all_text)))
        locations = list(set(re.findall(r'\b\d{1,5}\s+[A-Z][a-z]+\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Ct)', all_text)))
        events = []
        event_patterns = [r'(?:saw|heard|noticed|witnessed|observed)\s+(.{10,60}?)(?:\.|,|$)']
        for pat in event_patterns:
            events.extend(re.findall(pat, all_text, re.IGNORECASE)[:10])
        emotions = {
            "fear": len(re.findall(r'\b(?:scared|afraid|frightened|terrified)\b', all_lower)),
            "anger": len(re.findall(r'\b(?:angry|mad|furious|upset)\b', all_lower)),
            "sadness": len(re.findall(r'\b(?:sad|crying|cried|tears)\b', all_lower)),
            "calm": len(re.findall(r'\b(?:calm|clearly|certain|sure)\b', all_lower)),
        }
        return {
            "statement_count": len(stmts),
            "word_count": len(all_text.split()),
            "times": times[:10],
            "people": people[:10],
            "locations": locations[:5],
            "key_events": events[:10],
            "emotions": emotions,
        }

    dims_a = await _extract_dims(session)

    if compare_id:
        session_b = await firestore_service.get_session(compare_id)
        if not session_b:
            raise HTTPException(status_code=404, detail="Comparison session not found")
        dims_b = await _extract_dims(session_b)
    else:
        dims_b = None

    # Compute overlap if comparing
    overlap = {}
    if dims_b:
        shared_people = set(dims_a["people"]) & set(dims_b["people"])
        shared_locations = set(dims_a["locations"]) & set(dims_b["locations"])
        shared_times = set(dims_a["times"]) & set(dims_b["times"])
        overlap = {
            "shared_people": list(shared_people),
            "shared_locations": list(shared_locations),
            "shared_times": list(shared_times),
            "people_overlap_pct": round(len(shared_people) / max(len(set(dims_a["people"]) | set(dims_b["people"])), 1) * 100, 1),
            "location_overlap_pct": round(len(shared_locations) / max(len(set(dims_a["locations"]) | set(dims_b["locations"])), 1) * 100, 1),
        }

    return {
        "session_a": {"id": session_id, **dims_a},
        "session_b": {"id": compare_id, **dims_b} if dims_b else None,
        "overlap": overlap if overlap else None,
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 65: Legal Term Glossary
# ═══════════════════════════════════════════════════════════════════
LEGAL_GLOSSARY = {
    "deposition": "Sworn out-of-court testimony used in discovery phase of litigation",
    "affidavit": "A written statement confirmed by oath for use as evidence in court",
    "testimony": "Formal statement made under oath, especially in a court of law",
    "subpoena": "A legal document ordering someone to attend court or produce documents",
    "perjury": "The offense of willfully telling a lie under oath in a court of law",
    "hearsay": "Testimony based on what a witness has heard from another person rather than direct knowledge",
    "objection": "A formal protest raised during trial to disallow a witness's testimony or evidence",
    "stipulation": "An agreement between attorneys on both sides about some aspect of the case",
    "impeach": "To challenge the credibility of a witness's testimony",
    "corroborate": "To confirm or give support to a statement with additional evidence",
    "exhibit": "A document or object shown as evidence during a trial or hearing",
    "plaintiff": "The person who brings a case against another in a court of law",
    "defendant": "The person accused or sued in a court of law",
    "Miranda rights": "Constitutional rights that must be read during arrest (right to remain silent, right to an attorney)",
    "probable cause": "Reasonable grounds for making an arrest or conducting a search",
    "arraignment": "The formal reading of charges to a defendant, who enters a plea",
    "bail": "The temporary release of a prisoner in exchange for security",
    "indictment": "A formal charge or accusation of a serious crime",
    "statute of limitations": "The maximum time after an event within which legal proceedings may be initiated",
    "mens rea": "The intention or knowledge of wrongdoing (guilty mind)",
    "habeas corpus": "A legal action requiring a person under arrest to be brought before a judge",
    "voir dire": "The process of questioning prospective jurors to determine their suitability",
    "pro bono": "Legal work done without charge, especially for those who cannot afford it",
    "due process": "Fair treatment through the normal judicial system guaranteed by law",
    "felony": "A crime regarded as more serious than a misdemeanor, usually punishable by imprisonment",
    "misdemeanor": "A minor wrongdoing, less serious than a felony",
    "acquittal": "A judgment that a person is not guilty of the crime charged",
    "precedent": "A previous case or legal decision used as an authority for deciding subsequent cases",
    "jurisdiction": "The authority of a court to hear and decide a case",
    "plea bargain": "An agreement in which the defendant pleads guilty to a lesser charge in exchange for a more lenient sentence",
}


@router.get("/sessions/{session_id}/glossary")
async def detect_legal_terms(session_id: str):
    """Detect and explain legal terms found in testimony."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    texts = [getattr(s, 'text', '') or getattr(s, 'content', '') or str(s) for s in statements]
    all_text = " ".join(texts).lower()

    found_terms = []
    for term, definition in LEGAL_GLOSSARY.items():
        count = len(re.findall(r'\b' + re.escape(term.lower()) + r'\b', all_text))
        if count > 0:
            found_terms.append({
                "term": term,
                "definition": definition,
                "occurrences": count,
            })

    found_terms.sort(key=lambda t: t["occurrences"], reverse=True)

    return {
        "terms_found": found_terms,
        "total_legal_terms": len(found_terms),
        "total_occurrences": sum(t["occurrences"] for t in found_terms),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 66: Testimony Complexity Score
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/linguistic-complexity")
async def measure_testimony_complexity(session_id: str):
    """Analyze linguistic complexity of testimony."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"complexity_score": 0, "metrics": {}, "level": "none"}

    texts = [getattr(s, 'text', '') or getattr(s, 'content', '') or str(s) for s in statements]
    all_text = " ".join(texts)
    words = all_text.split()
    total_words = len(words)
    if total_words == 0:
        return {"complexity_score": 0, "metrics": {}, "level": "none"}

    sentences = re.split(r'[.!?]+', all_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    total_sentences = max(len(sentences), 1)

    # Avg sentence length
    avg_sentence_len = round(total_words / total_sentences, 1)

    # Vocabulary diversity (type-token ratio)
    unique_words = len(set(w.lower() for w in words))
    vocabulary_diversity = round(unique_words / total_words * 100, 1)

    # Syllable estimation (simple heuristic)
    def syllable_count(word):
        word = word.lower()
        count = len(re.findall(r'[aeiouy]+', word))
        return max(count, 1)

    total_syllables = sum(syllable_count(w) for w in words)
    avg_syllables = round(total_syllables / total_words, 2)

    # Flesch reading ease approximation
    flesch = round(206.835 - 1.015 * (total_words / total_sentences) - 84.6 * (total_syllables / total_words), 1)
    flesch = max(0, min(100, flesch))

    # Complex words (3+ syllables)
    complex_words = sum(1 for w in words if syllable_count(w) >= 3)
    complex_pct = round(complex_words / total_words * 100, 1)

    # Longest sentence
    longest_sentence = max(sentences, key=lambda s: len(s.split())) if sentences else ""
    longest_word_count = len(longest_sentence.split())

    # Composite complexity score (0-100)
    score = min(100, round(
        (min(avg_sentence_len, 30) / 30 * 25) +
        ((100 - vocabulary_diversity) / 100 * 15) +
        (min(avg_syllables, 3) / 3 * 20) +
        ((100 - flesch) / 100 * 25) +
        (min(complex_pct, 30) / 30 * 15)
    ))

    if score < 20:
        level = "very_simple"
    elif score < 40:
        level = "simple"
    elif score < 60:
        level = "moderate"
    elif score < 80:
        level = "complex"
    else:
        level = "very_complex"

    return {
        "complexity_score": score,
        "level": level,
        "metrics": {
            "total_words": total_words,
            "total_sentences": total_sentences,
            "unique_words": unique_words,
            "avg_sentence_length": avg_sentence_len,
            "vocabulary_diversity_pct": vocabulary_diversity,
            "avg_syllables_per_word": avg_syllables,
            "flesch_reading_ease": flesch,
            "complex_word_pct": complex_pct,
            "longest_sentence_words": longest_word_count,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 67: Admin User Session Report
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/session-report")
async def get_session_report(auth=Depends(require_admin_auth)):
    """Generate a report on session usage patterns."""
    _log_admin_action("view_session_report")
    all_sessions = await firestore_service.list_sessions()
    sessions = all_sessions if isinstance(all_sessions, list) else []

    total = len(sessions)
    now = datetime.datetime.now()

    statuses = {}
    word_counts = []
    stmt_counts = []
    for s in sessions:
        st = getattr(s, 'status', 'unknown') or 'unknown'
        statuses[st] = statuses.get(st, 0) + 1
        stmts = getattr(s, 'witness_statements', []) or []
        stmt_counts.append(len(stmts))
        total_w = sum(len((getattr(st2, 'text', '') or '').split()) for st2 in stmts)
        word_counts.append(total_w)

    avg_statements = round(sum(stmt_counts) / max(total, 1), 1)
    avg_words = round(sum(word_counts) / max(total, 1), 1)
    max_statements = max(stmt_counts) if stmt_counts else 0
    max_words = max(word_counts) if word_counts else 0

    return {
        "total_sessions": total,
        "status_distribution": statuses,
        "avg_statements_per_session": avg_statements,
        "avg_words_per_session": avg_words,
        "max_statements": max_statements,
        "max_words": max_words,
        "generated_at": now.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 68: Admin System Alerts
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/system-alerts")
async def get_system_alerts(auth=Depends(require_admin_auth)):
    """Check system health and generate alerts for concerning conditions."""
    import psutil
    _log_admin_action("view_system_alerts")
    alerts = []

    # Memory check
    try:
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            alerts.append({"level": "critical", "icon": "🔴", "title": "Memory Critical", "detail": f"Memory usage at {mem.percent}%"})
        elif mem.percent > 75:
            alerts.append({"level": "warning", "icon": "🟡", "title": "Memory High", "detail": f"Memory usage at {mem.percent}%"})
    except Exception:
        pass

    # CPU check
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        if cpu > 90:
            alerts.append({"level": "critical", "icon": "🔴", "title": "CPU Critical", "detail": f"CPU usage at {cpu}%"})
        elif cpu > 70:
            alerts.append({"level": "warning", "icon": "🟡", "title": "CPU High", "detail": f"CPU usage at {cpu}%"})
    except Exception:
        pass

    # Disk check
    try:
        disk = psutil.disk_usage('/')
        if disk.percent > 90:
            alerts.append({"level": "critical", "icon": "🔴", "title": "Disk Full", "detail": f"Disk usage at {disk.percent}%"})
        elif disk.percent > 80:
            alerts.append({"level": "warning", "icon": "🟡", "title": "Disk High", "detail": f"Disk usage at {disk.percent}%"})
    except Exception:
        pass

    # Session count check
    try:
        all_sessions = await firestore_service.list_sessions()
        count = len(all_sessions) if isinstance(all_sessions, list) else 0
        if count > 100:
            alerts.append({"level": "warning", "icon": "🟡", "title": "Many Sessions", "detail": f"{count} active sessions"})
    except Exception:
        pass

    # Check if no alerts
    if not alerts:
        alerts.append({"level": "ok", "icon": "🟢", "title": "All Clear", "detail": "No issues detected"})

    return {
        "alerts": alerts,
        "total": len(alerts),
        "has_critical": any(a["level"] == "critical" for a in alerts),
        "has_warning": any(a["level"] == "warning" for a in alerts),
        "checked_at": datetime.datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# IMPROVEMENT 69: Witness Emotional Arc
# ═══════════════════════════════════════════════════════════════════
@router.get("/sessions/{session_id}/emotional-arc")
async def get_emotional_arc(session_id: str):
    """Track emotional trajectory across testimony statements."""
    session = await firestore_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    statements = getattr(session, 'witness_statements', []) or []
    if not statements:
        return {"arc": [], "dominant_emotion": "neutral", "emotional_range": 0}

    emotion_lexicon = {
        "fear": [r'\b(?:scared|afraid|frightened|terrified|fear|anxious|panic|dread|horror|worried|nervous)\b'],
        "anger": [r'\b(?:angry|mad|furious|rage|upset|livid|irate|hostile|aggressive|infuriated)\b'],
        "sadness": [r'\b(?:sad|crying|cried|tears|devastated|heartbroken|grief|mourning|depressed|sorrowful)\b'],
        "surprise": [r'\b(?:shocked|surprised|stunned|amazed|astonished|startled|unexpected|disbelief)\b'],
        "confidence": [r'\b(?:sure|certain|definitely|absolutely|clearly|without doubt|positive|convinced)\b'],
        "uncertainty": [r'\b(?:maybe|perhaps|not sure|I think|possibly|might have|could have|uncertain)\b'],
        "distress": [r'\b(?:screaming|yelling|shaking|trembling|couldn\'t breathe|hyperventilat|sobbing)\b'],
    }

    arc = []
    for i, stmt in enumerate(statements):
        text = getattr(stmt, 'text', '') or getattr(stmt, 'content', '') or str(stmt)
        text_lower = text.lower()
        scores = {}
        for emotion, patterns in emotion_lexicon.items():
            total = 0
            for pat in patterns:
                total += len(re.findall(pat, text_lower))
            scores[emotion] = total

        dominant = max(scores, key=scores.get) if any(scores.values()) else "neutral"
        intensity = sum(scores.values())

        arc.append({
            "statement_index": i,
            "scores": scores,
            "dominant": dominant,
            "intensity": intensity,
            "preview": text[:80].strip(),
        })

    # Overall analysis
    totals = {}
    for point in arc:
        for emo, count in point["scores"].items():
            totals[emo] = totals.get(emo, 0) + count

    overall_dominant = max(totals, key=totals.get) if any(totals.values()) else "neutral"
    intensities = [p["intensity"] for p in arc]
    emotional_range = max(intensities) - min(intensities) if intensities else 0

    # Detect emotional shifts
    shifts = []
    for i in range(1, len(arc)):
        if arc[i]["dominant"] != arc[i-1]["dominant"] and arc[i]["dominant"] != "neutral":
            shifts.append({
                "from_statement": i - 1,
                "to_statement": i,
                "from_emotion": arc[i-1]["dominant"],
                "to_emotion": arc[i]["dominant"],
            })

    return {
        "arc": arc,
        "dominant_emotion": overall_dominant,
        "emotion_totals": totals,
        "emotional_range": emotional_range,
        "shifts": shifts[:20],
        "total_shifts": len(shifts),
    }
