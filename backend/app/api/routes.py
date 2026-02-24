import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
import io
import asyncio

from app.models.schemas import (
    ReconstructionSession,
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    HealthResponse,
    ModelInfo,
    UsageQuota,
    ModelConfigUpdate,
)
from app.services.firestore import firestore_service
from app.services.storage import storage_service
from app.services.image_gen import image_service
from app.services.usage_tracker import usage_tracker
from app.agents.scene_agent import get_agent, remove_agent
from app.config import settings
from app.api.auth import authenticate, require_admin_auth, revoke_session
from google import genai
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()


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
async def login(request: LoginRequest):
    """Admin login endpoint."""
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




@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(limit: int = 50):
    """List all reconstruction sessions."""
    try:
        sessions = await firestore_service.list_sessions(limit=limit)
        return [
            SessionResponse(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                status=session.status,
                statement_count=len(session.witness_statements),
                version_count=len(session.scene_versions)
            )
            for session in sessions
        ]
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
        session = ReconstructionSession(
            id=str(uuid.uuid4()),
            title=session_data.title or "Untitled Session",
            metadata=session_data.metadata or {}
        )
        
        success = await firestore_service.create_session(session)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create session"
            )
        
        # Initialize agent for this session
        agent = get_agent(session.id)
        greeting = await agent.start_interview()
        
        logger.info(f"Created session {session.id}")
        return session
    
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
        
        # Output PDF (fpdf2 returns bytearray, no need to encode)
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
                    version_count=len(session.scene_versions)
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



@router.get("/models", response_model=List[ModelInfo])
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
            return models_list
        
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
        return models_list
    
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
        return models_list



@router.get("/models/quota", response_model=dict)
async def get_quota_info(model: Optional[str] = None):
    """
    Get quota and usage information for Gemini models.
    
    Args:
        model: Optional specific model name. If not provided, returns all.
    
    Returns:
        Usage and quota information with rate limits.
        
    Note:
        Gemini API does not provide programmatic quota endpoints.
        This tracks usage locally by counting API calls and tokens.
        Counts are approximate and reset at midnight Pacific Time.
    """
    try:
        if model:
            # Get specific model usage
            usage = usage_tracker.get_usage(model)
            return usage
        else:
            # Get all models usage
            all_usage = usage_tracker.get_all_usage()
            return {
                "models": all_usage,
                "current_model": settings.gemini_model,
                "note": "Usage tracking is approximate and based on local counting"
            }
    
    except Exception as e:
        logger.error(f"Error getting quota info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get quota information"
        )



@router.post("/models/config")
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
            "rate_limiting": os.getenv("ENFORCE_RATE_LIMITS", "false").lower() == "true",
            "export_pdf": True,
            "export_json": True,
            "websocket": True,
        },
        "models": {
            "default": settings.gemini_model,
            "vision": settings.gemini_vision_model,
        },
        "endpoints": {
            "api_docs": "/docs",
            "health": "/api/health",
            "sessions": "/api/sessions",
            "websocket": "/ws/{session_id}",
        }
    }
