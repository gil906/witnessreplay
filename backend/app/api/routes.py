import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from fpdf import FPDF
import io

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
from google import genai
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    services = {
        "firestore": firestore_service.health_check(),
        "storage": storage_service.health_check(),
        "image_generation": image_service.health_check(),
    }
    
    return HealthResponse(
        status="healthy" if all(services.values()) else "degraded",
        services=services
    )


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


@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """Export a session as a PDF report."""
    try:
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
        pdf.cell(0, 10, f"Date: {session.created_at.strftime('%Y-%m-%d %H:%M')}", ln=True)
        pdf.ln(10)
        
        # Witness Statements
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Witness Statements:", ln=True)
        pdf.set_font("Arial", "", 11)
        for i, statement in enumerate(session.witness_statements, 1):
            pdf.multi_cell(0, 10, f"{i}. {statement.text}")
            pdf.ln(5)
        
        # Scene Versions
        if session.scene_versions:
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Scene Reconstructions:", ln=True)
            pdf.set_font("Arial", "", 11)
            for version in session.scene_versions:
                pdf.multi_cell(0, 10, f"Version {version.version}: {version.description}")
                if version.image_url:
                    pdf.cell(0, 10, f"Image: {version.image_url}", ln=True)
                pdf.ln(5)
        
        # Output PDF
        pdf_bytes = pdf.output(dest='S').encode('latin1')
        
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
        logger.error(f"Error exporting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export session"
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
                type_match = not element_type or elem.type.lower() == element_type.lower()
                desc_match = not element_description or element_description.lower() in elem.description.lower()
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


# ==================== Model Management Endpoints ====================

@router.get("/models", response_model=List[ModelInfo])
async def list_models():
    """
    List available Gemini models with their capabilities.
    
    Returns information about models that can be used for scene reconstruction.
    """
    try:
        if not settings.google_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google API key not configured"
            )
        
        client = genai.Client(api_key=settings.google_api_key)
        
        # List models from Gemini API
        models_list = []
        try:
            for model in client.models.list():
                # Filter for generation models only
                if hasattr(model, 'supported_generation_methods') and \
                   'generateContent' in model.supported_generation_methods:
                    
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
        except Exception as e:
            logger.warning(f"Error listing models from API: {e}")
            # Fall back to known models if API call fails
            known_models = [
                "gemini-2.5-pro",
                "gemini-2.5-flash", 
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash",
                "gemini-2.0-flash-lite",
                "gemini-2.0-flash-exp",
            ]
            for model_name in known_models:
                models_list.append(ModelInfo(
                    name=model_name,
                    display_name=model_name.replace("-", " ").title(),
                    description=f"Gemini model: {model_name}",
                    supported_generation_methods=["generateContent"],
                ))
        
        logger.info(f"Returning {len(models_list)} available models")
        return models_list
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list models"
        )


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
    Get the currently configured model.
    
    Returns:
        Current model name and configuration
    """
    try:
        return {
            "model": settings.gemini_model,
            "vision_model": settings.gemini_vision_model,
            "environment": settings.environment,
        }
    
    except Exception as e:
        logger.error(f"Error getting current model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get current model"
        )
