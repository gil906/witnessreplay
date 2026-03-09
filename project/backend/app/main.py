import logging
from contextlib import asynccontextmanager
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import uuid as uuid_lib
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
import os
import asyncio
import time as time_module

from app.config import settings
from app.api.routes import router as api_router
from app.api.websocket import websocket_endpoint
from app.api.auth import cleanup_expired_sessions
from app.middleware.request_logging import RequestLoggingMiddleware, request_metrics

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ── Per-IP API rate limiter ───────────────────────────────

class APIRateLimiter:
    """Simple per-IP rate limiter for API endpoints."""

    def __init__(self, requests_per_minute: int = 60):
        self._requests: dict = defaultdict(list)
        self._rpm = requests_per_minute

    def check(self, client_ip: str) -> bool:
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=1)
        self._requests[client_ip] = [t for t in self._requests[client_ip] if t > cutoff]
        if len(self._requests[client_ip]) >= self._rpm:
            return False
        self._requests[client_ip].append(now)
        return True

api_rate_limiter = APIRateLimiter(requests_per_minute=60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting WitnessReplay application")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Validate configuration on startup
    settings.validate_config()
    
    # Initialize API key rotation if multiple keys configured
    if settings.google_api_keys:
        from app.services.api_key_manager import initialize_key_manager
        keys = [k.strip() for k in settings.google_api_keys.split(',') if k.strip()]
        if len(keys) > 1:
            initialize_key_manager(keys)
            logger.info(f"API key rotation enabled with {len(keys)} keys")
        else:
            logger.info("Single API key mode (no rotation)")
    else:
        logger.info("Single API key mode (no rotation)")
    
    # Initialize SQLite database
    from app.services.database import DatabaseService
    db = DatabaseService()
    await db.initialize()
    logger.info("SQLite database initialized")

    # Initialize API key service
    from app.services.api_key_service import api_key_service
    await api_key_service.initialize()
    logger.info("API key service initialized")

    # Initialize user service
    from app.services.user_service import user_service
    await user_service.initialize()
    logger.info("User service initialized")

    # Ensure images directory exists
    os.makedirs("/app/data/images", exist_ok=True)
    
    # Start cache cleanup background task
    from app.services.cache import cache
    from app.services.response_cache import response_cache
    
    # Load cached responses from database
    await response_cache.load_from_db()
    logger.info(f"Response cache loaded ({response_cache.get_stats()['entries']} entries)")
    
    async def cleanup_cache_periodically():
        while True:
            await asyncio.sleep(300)  # Run every 5 minutes
            await cache.cleanup_expired()
            await response_cache.cleanup_expired()
    
    cleanup_task = asyncio.create_task(cleanup_cache_periodically())
    logger.info("Started cache cleanup background task")
    
    async def _session_cleanup_loop():
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            await cleanup_expired_sessions()
    
    asyncio.create_task(_session_cleanup_loop())
    logger.info("Started session cleanup background task")
    
    # Start request queue processor
    from app.services.request_queue import request_queue
    await request_queue.start()
    logger.info("Started request queue processor")
    
    # Start quota alert service
    from app.services.quota_alert_service import quota_alert_service
    await quota_alert_service.start()
    logger.info("Started quota alert service")
    
    # Startup
    yield
    
    # Shutdown
    cleanup_task.cancel()
    await request_queue.stop()
    await quota_alert_service.stop()
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

# Custom 404 handler
@app.exception_handler(404)
async def custom_404(request, exc):
    # Return JSON for API routes
    if request.url.path.startswith('/api/') or request.url.path.startswith('/v1/') or request.url.path.startswith('/admin/'):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Not Found", "path": str(request.url.path)})
    # Return styled HTML for browser requests
    return HTMLResponse(status_code=404, content="""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>404 - Not Found</title><style>body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}.c{max-width:400px;padding:20px}.icon{font-size:4rem;margin-bottom:1rem}h1{font-size:2rem;margin:0 0 .5rem;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}p{color:#94a3b8;font-size:1rem;line-height:1.5}a{color:#60a5fa;text-decoration:none}a:hover{text-decoration:underline}.links{margin-top:1.5rem;display:flex;gap:16px;justify-content:center}</style></head><body><div class="c"><div class="icon">🔍</div><h1>Page Not Found</h1><p>The page you're looking for doesn't exist or has been moved.</p><div class="links"><a href="/">← Back to WitnessReplay</a><a href="/admin">Admin Portal</a></div></div></body></html>""")

# Security headers middleware with CSP (applied before CORS)
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' ws: wss: https://generativelanguage.googleapis.com https://maps.googleapis.com; "
            "media-src 'self' blob:; "
            "frame-src 'none'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Request size limit middleware
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB
        return JSONResponse(status_code=413, content={"detail": "Request too large"})
    return await call_next(request)

# Maintenance mode write guard
@app.middleware("http")
async def maintenance_mode_write_guard(request: Request, call_next):
    if (
        settings.maintenance_mode
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/health"
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
    ):
        return JSONResponse(
            status_code=503,
            content={"detail": "Service temporarily in maintenance mode"},
        )
    return await call_next(request)

# GZip compression for responses >= 500 bytes
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS middleware
is_wildcard = settings.allowed_origins == ["*"]
if is_wildcard and settings.environment == "production":
    import logging
    logging.getLogger("witnessreplay").warning(
        "⚠️ CORS is set to allow ALL origins (*) in production. "
        "Set ALLOWED_ORIGINS to specific domains for security."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=not is_wildcard,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
)

# Global rate limiting middleware (after CORS)
_request_counts = defaultdict(list)
_RATE_LIMIT = 100  # requests per minute
_RATE_WINDOW = 60  # seconds

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip rate limiting for static files and health checks
        path = request.url.path
        if path.startswith('/static') or path == '/api/health':
            return await call_next(request)
        
        client_ip = request.client.host if request.client else "unknown"
        now = time_module.time()
        
        # Clean old entries
        _request_counts[client_ip] = [t for t in _request_counts[client_ip] if now - t < _RATE_WINDOW]
        
        if len(_request_counts[client_ip]) >= _RATE_LIMIT:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later.", "retry_after": _RATE_WINDOW},
                headers={"Retry-After": str(_RATE_WINDOW)}
            )
        
        _request_counts[client_ip].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(_RATE_LIMIT - len(_request_counts[client_ip]))
        return response

app.add_middleware(RateLimitMiddleware)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Include API routes
app.include_router(api_router, prefix="/api", tags=["api"])

# API versioning: mount same router under /api/v1/ as alias
app.include_router(api_router, prefix="/api/v1", tags=["api-v1"])

# Lightweight health check alias for Docker HEALTHCHECK
@app.get("/api/health")
async def api_health_check():
    """Health check endpoint for Docker."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

# Serve robots.txt and security.txt
@app.get("/robots.txt")
async def robots_txt():
    path = os.path.join(os.path.dirname(__file__), "../../frontend/robots.txt")
    if os.path.exists(path):
        return FileResponse(path, media_type="text/plain")
    return PlainTextResponse("User-agent: *\nDisallow: /admin\nDisallow: /api/\n")

@app.get("/.well-known/security.txt")
async def security_txt():
    path = os.path.join(os.path.dirname(__file__), "../../frontend/security.txt")
    if os.path.exists(path):
        return FileResponse(path, media_type="text/plain")
    return PlainTextResponse("Contact: security@witnessreplay.com\n")

# Serve generated images from /data/images/
@app.get("/data/images/{filename}")
async def serve_data_image(filename: str):
    """Serve generated image files from the data directory."""
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse(status_code=400, content={"detail": "Invalid filename"})
    base_dir = os.path.realpath("/app/data/images")
    filepath = os.path.realpath(os.path.join(base_dir, filename))
    if not filepath.startswith(base_dir + os.sep):
        return JSONResponse(status_code=400, content={"detail": "Invalid filename"})
    if not os.path.exists(filepath):
        return JSONResponse(status_code=404, content={"detail": "Image not found"})
    return FileResponse(filepath, media_type="image/png")

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
    
    # Add convenience aliases for /css/ and /js/ paths
    css_path = os.path.join(frontend_path, "css")
    js_path = os.path.join(frontend_path, "js")
    if os.path.exists(css_path):
        app.mount("/css", StaticFiles(directory=css_path), name="css")
    if os.path.exists(js_path):
        app.mount("/js", StaticFiles(directory=js_path), name="js")
    
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


# Middleware are applied in REVERSE order of registration
# Execution order will be: rate_limit → log_requests → add_request_id → timeout → handler

# Rate limiting middleware (optional - can be disabled via env var)
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Rate limiting middleware using usage tracker.
    Only enforces limits if ENFORCE_RATE_LIMITS=true in env.
    Adds rate limit headers to all API responses.
    When QUEUE_RATE_LIMITED=true, queues requests instead of rejecting them.
    Also checks quotas after each request to trigger alerts.
    Integrates with RPD budget allocator for time-window based budget control.
    """
    from app.services.usage_tracker import usage_tracker
    from app.services.request_queue import request_queue
    from app.services.quota_alert_service import quota_alert_service
    from app.services.rpd_budget import rpd_budget, BudgetAction
    
    # Skip rate limiting for health checks and static files
    if request.url.path in ["/api/health", "/", "/docs", "/openapi.json"] or \
       request.url.path.startswith("/static") or \
       request.url.path.startswith("/api/queue") or \
       request.url.path.startswith("/api/alerts"):
        return await call_next(request)
    
    # Get current model from settings
    current_model = settings.gemini_model
    
    # Get usage info for headers
    usage = usage_tracker.get_usage(current_model)
    
    # Check if enforcement is enabled
    enforce_limits = os.getenv("ENFORCE_RATE_LIMITS", "false").lower() == "true"
    queue_rate_limited = os.getenv("QUEUE_RATE_LIMITED", "false").lower() == "true"
    enforce_budget = os.getenv("ENFORCE_RPD_BUDGET", "false").lower() == "true"
    
    if enforce_limits:
        # Check rate limit before processing request
        allowed, reason = usage_tracker.check_rate_limit(current_model)
        
        if not allowed:
            logger.warning(f"Rate limit exceeded for {current_model}: {reason}")
            
            # Try to queue the request if queuing is enabled
            if queue_rate_limited:
                client_ip = request.client.host if request.client else "unknown"
                success, queued = request_queue.queue_request(
                    endpoint=str(request.url.path),
                    method=request.method,
                    client_ip=client_ip,
                )
                
                if success and queued:
                    # Return 202 Accepted with queue info
                    return JSONResponse(
                        status_code=202,
                        content={
                            "detail": "Request queued due to rate limit",
                            "queue_id": queued.id,
                            "queue_status_url": f"/api/queue/status/{queued.id}",
                            "expires_at": queued.expires_at.isoformat(),
                            "reason": reason,
                        },
                        headers={
                            "X-Queue-ID": queued.id,
                            "Retry-After": "60",
                            "X-RateLimit-Limit": str(usage["limits"]["requests_per_minute"]),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(int(usage.get("next_reset_timestamp", 0)))
                        }
                    )
            
            # Queue full or not enabled - return 429
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
    
    # Check RPD budget allocation if enabled
    if enforce_budget:
        budget_allowed, budget_reason, budget_action = rpd_budget.check_budget(current_model)
        
        if not budget_allowed:
            logger.warning(f"Budget exceeded for {current_model}: {budget_reason}")
            
            if budget_action == BudgetAction.QUEUE:
                # Queue the request
                client_ip = request.client.host if request.client else "unknown"
                success, queued = request_queue.queue_request(
                    endpoint=str(request.url.path),
                    method=request.method,
                    client_ip=client_ip,
                )
                
                if success and queued:
                    rpd_budget.record_queued(current_model)
                    return JSONResponse(
                        status_code=202,
                        content={
                            "detail": "Request queued due to budget limit",
                            "queue_id": queued.id,
                            "queue_status_url": f"/api/queue/status/{queued.id}",
                            "expires_at": queued.expires_at.isoformat(),
                            "reason": budget_reason,
                        },
                        headers={
                            "X-Queue-ID": queued.id,
                            "Retry-After": "300",  # Try again after window changes
                            "X-Budget-Exceeded": "true",
                        }
                    )
            
            if budget_action == BudgetAction.REJECT:
                rpd_budget.record_rejected(current_model)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": budget_reason,
                        "model": current_model,
                        "budget_exceeded": True,
                        "retry_after": "300"
                    },
                    headers={
                        "Retry-After": "300",
                        "X-Budget-Exceeded": "true",
                    }
                )
            # BudgetAction.ALLOW - continue but track overage
    
    # Process request
    response = await call_next(request)
    
    # Record successful request to budget allocator
    rpd_budget.record_request(current_model)
    
    # Add rate limit headers to response
    response.headers["X-RateLimit-Limit"] = str(usage["limits"]["requests_per_minute"])
    response.headers["X-RateLimit-Remaining"] = str(usage["remaining"]["requests_per_minute"])
    response.headers["X-RateLimit-Reset"] = str(int(usage.get("next_reset_timestamp", 0)))
    
    # Add budget headers
    try:
        window_status = rpd_budget.get_current_window_status(current_model)
        if window_status.get("current_window"):
            window_usage = window_status.get("usage", {})
            response.headers["X-Budget-Window"] = window_status["current_window"]["name"]
            response.headers["X-Budget-Remaining"] = str(window_usage.get("remaining", 0))
    except Exception:
        pass
    
    # Check quotas after request to trigger alerts if approaching limits
    try:
        updated_usage = usage_tracker.get_usage(current_model)
        await quota_alert_service.check_quota(current_model, updated_usage)
    except Exception as e:
        logger.debug(f"Quota alert check failed: {e}")
    
    return response


# Per-IP API rate limiting middleware
@app.middleware("http")
async def api_ip_rate_limit(request: Request, call_next):
    """Per-IP rate limiting for all API endpoints."""
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        if not api_rate_limiter.check(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again shortly."},
                headers={"Retry-After": "60"},
            )
    return await call_next(request)


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
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(f"Request started: {method} {url} | IP: {client_ip} | ID: {request_id}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = time.time() - start_time
    duration_ms = duration * 1000
    
    # Log response
    logger.info(
        f"Request completed: {method} {url} | "
        f"Status: {response.status_code} | "
        f"Duration: {duration:.3f}s | "
        f"ID: {request_id}"
    )
    
    # Record metrics
    try:
        from app.services.metrics import metrics_collector
        error_msg = None
        if response.status_code >= 400:
            error_msg = f"HTTP {response.status_code}"
        metrics_collector.record_request(
            endpoint=path,
            method=method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            error=error_msg
        )
    except Exception as e:
        logger.warning(f"Failed to record metrics: {e}")
    
    # Add timing header
    response.headers["X-Process-Time"] = str(duration)
    
    return response


# Request ID middleware for debugging
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid_lib.uuid4())[:8])
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)


# Static asset caching and API cache-control headers
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path.startswith("/css/") or path.startswith("/js/"):
        if path.endswith(('.css', '.js', '.png', '.jpg', '.svg', '.ico')):
            response.headers["Cache-Control"] = "public, max-age=3600"  # 1 hour
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Vary"] = "Accept, Authorization"
    return response


# Request timeout middleware - prevent indefinite hanging
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """Timeout protection with endpoint-specific limits."""
    path = request.url.path
    # Longer timeouts for AI/streaming/image-generation endpoints
    if any(p in path for p in ['/ws', '/stream', '/generate', '/tts', '/scene', '/image', '/interview']):
        timeout_seconds = 180.0
    elif any(p in path for p in ['/health', '/status', '/ping']):
        timeout_seconds = 10.0
    else:
        timeout_seconds = 60.0
    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.error(f"Request timeout ({timeout_seconds}s): {request.method} {request.url}")
        return JSONResponse(
            status_code=504,
            content={
                "detail": "Request timeout - server took too long to respond",
                "path": str(request.url.path)
            }
        )


@app.middleware("http")
async def add_response_timing_headers(request: Request, call_next):
    start_time = time_module.perf_counter()
    response = await call_next(request)
    duration_ms = (time_module.perf_counter() - start_time) * 1000
    duration_value = f"{duration_ms:.2f}"
    response.headers["X-Response-Time-ms"] = duration_value
    response.headers["Server-Timing"] = f"app;dur={duration_value}"
    return response



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
