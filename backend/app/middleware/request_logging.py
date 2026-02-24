"""Request logging middleware for comprehensive API monitoring."""

import logging
import time
from typing import Callable
from datetime import datetime
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses.
    Tracks request timing, status codes, and errors.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.request_count = 0
        self.error_count = 0
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process each request and log details."""
        # Increment counter
        self.request_count += 1
        request_id = f"req_{self.request_count}_{int(time.time() * 1000)}"
        
        # Start timing
        start_time = time.time()
        
        # Log request
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Client: {request.client.host if request.client else 'unknown'}"
        )
        
        # Add request ID to state for access in routes
        request.state.request_id = request_id
        
        # Process request
        response = None
        
        try:
            response = await call_next(request)
        except Exception as e:
            self.error_count += 1
            logger.error(
                f"[{request_id}] Error processing request: {str(e)}",
                exc_info=True
            )
            # Re-raise to let error handlers deal with it
            raise
        finally:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log response
            if response:
                status_code = response.status_code
                log_level = logging.INFO
                
                # Elevate log level for errors
                if status_code >= 500:
                    log_level = logging.ERROR
                    self.error_count += 1
                elif status_code >= 400:
                    log_level = logging.WARNING
                    
                logger.log(
                    log_level,
                    f"[{request_id}] {request.method} {request.url.path} - "
                    f"Status: {status_code} - Duration: {duration_ms:.2f}ms"
                )
                
                # Log slow requests (>2s)
                if duration_ms > 2000:
                    logger.warning(
                        f"[{request_id}] SLOW REQUEST: {duration_ms:.2f}ms - "
                        f"{request.method} {request.url.path}"
                    )
                    
        return response


class RequestMetrics:
    """Track request metrics across the application."""
    
    def __init__(self):
        self.total_requests = 0
        self.total_errors = 0
        self.endpoint_stats = {}
        self.start_time = datetime.utcnow()
        
    def get_metrics(self) -> dict:
        """Get current metrics."""
        uptime_seconds = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            'uptime_seconds': round(uptime_seconds, 2),
            'total_requests': self.total_requests,
            'total_errors': self.total_errors,
            'error_rate': round(self.total_errors / self.total_requests * 100, 2) if self.total_requests > 0 else 0,
            'requests_per_second': round(self.total_requests / uptime_seconds, 2) if uptime_seconds > 0 else 0,
        }


# Global metrics instance
request_metrics = RequestMetrics()
