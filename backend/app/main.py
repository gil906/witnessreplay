import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os
import asyncio

from app.config import settings
from app.api.routes import router as api_router
from app.api.websocket import websocket_endpoint

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting WitnessReplay application")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Startup
    yield
    
    # Shutdown
    logger.info("Shutting down WitnessReplay application")


# Create FastAPI app
app = FastAPI(
    title="WitnessReplay API",
    description="Voice-driven crime scene reconstruction agent",
    version="1.0.0",
    lifespan=lifespan
)

# Global exception handler for better error responses
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to provide consistent error responses.
    Includes request ID for debugging and detailed error context in debug mode.
    """
    request_id = getattr(request.state, 'request_id', 'unknown')
    
    # Log the error
    logger.error(
        f"Unhandled exception in {request.method} {request.url.path} | "
        f"ID: {request_id} | Error: {str(exc)}",
        exc_info=True
    )
    
    # Build error response
    error_detail = {
        "detail": "Internal server error",
        "request_id": request_id,
        "path": str(request.url.path)
    }
    
    # In debug mode, include more details
    if settings.debug:
        error_detail["error_type"] = exc.__class__.__name__
        error_detail["error_message"] = str(exc)
    
    return JSONResponse(
        status_code=500,
        content=error_detail,
        headers={"X-Request-ID": request_id}
    )

# CORS middleware — allow all origins for hackathon demo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api", tags=["api"])

# WebSocket endpoint
@app.websocket("/ws/{session_id}")
async def websocket_handler(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time communication."""
    await websocket_endpoint(websocket, session_id)


# Serve static files (frontend)
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend")
# Also check Docker path where frontend is at /app/frontend
if not os.path.exists(frontend_path):
    frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if not os.path.exists(frontend_path):
    frontend_path = "/app/frontend"
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    
    @app.get("/")
    async def serve_frontend():
        """Serve the frontend HTML."""
        index_path = os.path.join(frontend_path, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "WitnessReplay API is running"}
    
    @app.get("/admin")
    @app.get("/admin.html")
    async def serve_admin_portal():
        """Serve the admin portal HTML."""
        admin_path = os.path.join(frontend_path, "admin.html")
        if os.path.exists(admin_path):
            return FileResponse(admin_path)
        return JSONResponse(
            status_code=404,
            content={"detail": "Admin portal not found"}
        )
else:
    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": "WitnessReplay API",
            "version": "1.0.0",
            "docs": "/docs"
        }


# Request timeout middleware - prevent indefinite hanging
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """Timeout protection for all requests."""
    try:
        # Set timeout to 60 seconds for all requests
        return await asyncio.wait_for(call_next(request), timeout=60.0)
    except asyncio.TimeoutError:
        logger.error(f"Request timeout: {request.method} {request.url}")
        return JSONResponse(
            status_code=504,
            content={
                "detail": "Request timeout - server took too long to respond",
                "path": str(request.url.path)
            }
        )


# Request ID middleware for debugging
@app.middleware("http")
async def add_request_id(request, call_next):
    """Add request ID for tracking."""
    import uuid
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Request logging middleware
@app.middleware("http")
async def log_requests(request, call_next):
    """Log all HTTP requests and responses."""
    import time
    
    # Start timer
    start_time = time.time()
    
    # Get request details
    request_id = getattr(request.state, 'request_id', 'unknown')
    method = request.method
    url = str(request.url)
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(f"Request started: {method} {url} | IP: {client_ip} | ID: {request_id}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = time.time() - start_time
    
    # Log response
    logger.info(
        f"Request completed: {method} {url} | "
        f"Status: {response.status_code} | "
        f"Duration: {duration:.3f}s | "
        f"ID: {request_id}"
    )
    
    # Add timing header
    response.headers["X-Process-Time"] = str(duration)
    
    return response


# Rate limiting middleware (optional - can be disabled via env var)
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Rate limiting middleware using usage tracker.
    Only enforces limits if ENFORCE_RATE_LIMITS=true in env.
    Adds rate limit headers to all API responses.
    """
    from app.services.usage_tracker import usage_tracker
    
    # Skip rate limiting for health checks and static files
    if request.url.path in ["/api/health", "/", "/docs", "/openapi.json"] or \
       request.url.path.startswith("/static"):
        return await call_next(request)
    
    # Get current model from settings
    current_model = settings.gemini_model
    
    # Get usage info for headers
    usage = usage_tracker.get_usage(current_model)
    
    # Check if enforcement is enabled
    enforce_limits = os.getenv("ENFORCE_RATE_LIMITS", "false").lower() == "true"
    
    if enforce_limits:
        # Check rate limit before processing request
        allowed, reason = usage_tracker.check_rate_limit(current_model)
        
        if not allowed:
            logger.warning(f"Rate limit exceeded for {current_model}: {reason}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": reason,
                    "model": current_model,
                    "retry_after": "60"  # Retry after 1 minute
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(usage["limits"]["requests_per_minute"]),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(usage.get("next_reset_timestamp", 0)))
                }
            )
    
    # Process request
    response = await call_next(request)
    
    # Add rate limit headers to response
    response.headers["X-RateLimit-Limit"] = str(usage["limits"]["requests_per_minute"])
    response.headers["X-RateLimit-Remaining"] = str(usage["remaining"]["requests_per_minute"])
    response.headers["X-RateLimit-Reset"] = str(int(usage.get("next_reset_timestamp", 0)))
    
    return response



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
