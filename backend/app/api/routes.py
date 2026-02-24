import logging
from typing import Dict, List, Optional
from datetime import datetime
from collections import deque
from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
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
)
from app.services.firestore import firestore_service
from app.services.storage import storage_service
from app.services.image_gen import image_service
from app.services.usage_tracker import usage_tracker
from app.services.token_estimator import token_estimator, TokenEstimate, QuotaCheckResult
from app.services.case_manager import case_manager
from app.services.interview_templates import get_all_templates, get_template, get_templates_by_category
from app.services.tts_service import tts_service
from app.agents.scene_agent import get_agent, remove_agent
from app.config import settings
from app.api.auth import authenticate, require_admin_auth, revoke_session, check_rate_limit
from google import genai
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Background task queue ─────────────────────────────────

_task_results: dict = {}

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


# Authentication schemas
class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    token: str
    expires_in: int = 86400  # 24 hours in seconds

class LogoutRequest(BaseModel):
    token: str


# Authentication endpoints
@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, raw_request: Request):
    """Admin login endpoint."""
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in 15 minutes."
        )
    token = authenticate(request.password)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid password"
        )
    return LoginResponse(token=token)


@router.post("/auth/logout")
async def logout(request: LogoutRequest):
    """Admin logout endpoint."""
    revoke_session(request.token)
    return {"message": "Logged out successfully"}


@router.get("/auth/verify")
async def verify_auth(auth=Depends(require_admin_auth)):
    """Verify admin authentication."""
    return {"authenticated": True}


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
                source_type=getattr(session, 'source_type', 'chat'),
                report_number=getattr(session, 'report_number', ''),
                case_id=getattr(session, 'case_id', None),
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
            },
            "notes": [
                "This report was generated using AI-assisted witness interview and scene reconstruction technology.",
                "All scene reconstructions are based on witness statements and should be verified with physical evidence.",
                "Confidence scores indicate the AI's certainty based on statement consistency and detail.",
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
        
        # Convert to JSON with proper datetime handling
        session_data = session.model_dump(mode='json')
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
            except:
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
        
        # Output PDF (fpdf2 returns bytearray, no need to encode)
        pdf_bytes = pdf.output()
        pdf_bytes = pdf.output()
        
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
            "recommendations": []
        }
        
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
async def get_witnesses(session_id: str):
    """Get all witnesses for a session."""
    try:
        session = await firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        witnesses_list = getattr(session, 'witnesses', []) or []
        
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
        
        # Validate file type
        content_type = getattr(image_file, 'content_type', 'image/png')
        if not content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Read image data
        image_data = await image_file.read()
        if len(image_data) > 10 * 1024 * 1024:  # 10MB limit
            raise HTTPException(status_code=400, detail="Image must be under 10MB")
        
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


@router.get("/sessions/compare/{session_id_1}/{session_id_2}")
async def compare_sessions(session_id_1: str, session_id_2: str):
    """
    Compare two witness accounts of the same event.
    
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
        scene_elements = session.get('scene_elements', [])
        conversation = session.get('conversation_history', [])
        
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
        scene_elements = session.get('scene_elements', [])
        conversation = session.get('conversation_history', [])
        conversation_turns = len([m for m in conversation if m.get('role') == 'user'])
        
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

@router.get("/cases")
async def list_cases(limit: int = 50):
    """List all cases with report counts."""
    try:
        cases = await firestore_service.list_cases(limit=limit)
        cases_list = [
            CaseResponse(
                id=case.id,
                case_number=case.case_number,
                title=case.title,
                summary=case.summary,
                location=case.location,
                status=case.status,
                report_count=len(case.report_ids),
                created_at=case.created_at,
                updated_at=case.updated_at,
                scene_image_url=case.scene_image_url,
                timeframe=case.timeframe
            )
            for case in cases
        ]
        return {"cases": cases_list}
    except Exception as e:
        logger.error(f"Error listing cases: {e}")
        raise HTTPException(status_code=500, detail="Failed to list cases")


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

        case.updated_at = datetime.utcnow()
        await firestore_service.update_case(case)
        return {"message": "Case updated", "case_id": case_id}
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

        return {
            "models": await model_selector.quota.get_quota_status() if hasattr(model_selector, 'quota') else {},
            "imagen": imagen_service.get_quota_status(),
            "embeddings": embedding_service.get_quota_status(),
        }
    except Exception as e:
        logger.error(f"Error getting all quota status: {e}")
        return {"models": {}, "imagen": {}, "embeddings": {}, "error": str(e)}


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
    raw_request: Request,
    _auth: dict = Depends(check_rate_limit),
):
    """
    Generate text-to-speech audio from text.
    
    This endpoint converts text to speech using Google Gemini 2.5 Flash TTS.
    Useful for accessibility, allowing visually impaired users to hear AI responses.
    
    Rate limits: 3 requests per minute, 10 requests per day.
    
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
async def get_similar_cases(case_id: str, limit: int = 5, exclude_linked: bool = True):
    """Find similar cases based on semantic similarity, location, time, and MO."""
    from app.services.case_linking import case_linking_service
    
    case = await firestore_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    try:
        similar = await case_linking_service.find_similar_cases(
            case_id, limit=limit, exclude_linked=exclude_linked
        )
        return {
            "case_id": case_id,
            "similar_cases": [s.model_dump(mode="json") for s in similar],
            "count": len(similar),
        }
    except Exception as e:
        logger.error(f"Error finding similar cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
