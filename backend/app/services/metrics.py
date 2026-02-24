"""
Simple metrics collection service for request tracking and monitoring.
Tracks request counts, response times, and error rates.
"""
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Lightweight metrics collector for monitoring API performance."""
    
    def __init__(self, max_recent_requests: int = 1000):
        self._lock = threading.Lock()
        self.max_recent_requests = max_recent_requests
        
        # Request counts by endpoint
        self.request_counts: Dict[str, int] = defaultdict(int)
        
        # Error counts by endpoint
        self.error_counts: Dict[str, int] = defaultdict(int)
        
        # Response times (keep recent N requests)
        self.response_times: deque = deque(maxlen=max_recent_requests)
        
        # Recent errors (keep last 100)
        self.recent_errors: deque = deque(maxlen=100)
        
        # Start time for uptime tracking
        self.start_time = datetime.now(timezone.utc)
        
        # Status code counts
        self.status_codes: Dict[int, int] = defaultdict(int)
    
    def record_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: float,
        error: str = None
    ):
        """
        Record a completed request.
        
        Args:
            endpoint: API endpoint path
            method: HTTP method
            status_code: Response status code
            duration_ms: Request duration in milliseconds
            error: Optional error message
        """
        with self._lock:
            # Track request count
            key = f"{method} {endpoint}"
            self.request_counts[key] += 1
            
            # Track status codes
            self.status_codes[status_code] += 1
            
            # Track errors
            if status_code >= 400:
                self.error_counts[key] += 1
                if error:
                    self.recent_errors.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "endpoint": endpoint,
                        "method": method,
                        "status_code": status_code,
                        "error": error
                    })
            
            # Track response time
            self.response_times.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "endpoint": endpoint,
                "method": method,
                "duration_ms": duration_ms,
                "status_code": status_code
            })
    
    def get_stats(self) -> Dict:
        """
        Get current metrics statistics.
        
        Returns:
            Dictionary with comprehensive metrics data
        """
        with self._lock:
            # Calculate uptime
            uptime_seconds = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            
            # Calculate total requests
            total_requests = sum(self.request_counts.values())
            total_errors = sum(self.error_counts.values())
            
            # Calculate average response time
            if self.response_times:
                response_time_list = [r["duration_ms"] for r in self.response_times]
                avg_response_time = sum(response_time_list) / len(response_time_list)
                min_response_time = min(response_time_list)
                max_response_time = max(response_time_list)
                
                # Calculate p95 response time
                sorted_times = sorted(response_time_list)
                p95_index = int(len(sorted_times) * 0.95)
                p95_response_time = sorted_times[p95_index] if sorted_times else 0
            else:
                avg_response_time = 0
                min_response_time = 0
                max_response_time = 0
                p95_response_time = 0
            
            # Error rate
            error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0
            
            # Top endpoints by request count
            top_endpoints = sorted(
                self.request_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            
            # Top endpoints by error count
            top_errors = sorted(
                self.error_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            return {
                "uptime_seconds": round(uptime_seconds, 1),
                "uptime_formatted": self._format_duration(uptime_seconds),
                "total_requests": total_requests,
                "total_errors": total_errors,
                "error_rate_percent": round(error_rate, 2),
                "response_times": {
                    "avg_ms": round(avg_response_time, 2),
                    "min_ms": round(min_response_time, 2),
                    "max_ms": round(max_response_time, 2),
                    "p95_ms": round(p95_response_time, 2)
                },
                "status_codes": dict(self.status_codes),
                "top_endpoints": [
                    {"endpoint": endpoint, "requests": count}
                    for endpoint, count in top_endpoints
                ],
                "top_errors": [
                    {"endpoint": endpoint, "errors": count}
                    for endpoint, count in top_errors
                ],
                "recent_errors": list(self.recent_errors)[-10:],  # Last 10
                "sample_size": len(self.response_times)
            }
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def reset_stats(self):
        """Reset all statistics (useful for testing or new deployment)."""
        with self._lock:
            self.request_counts.clear()
            self.error_counts.clear()
            self.response_times.clear()
            self.recent_errors.clear()
            self.status_codes.clear()
            self.start_time = datetime.now(timezone.utc)
            logger.info("Metrics statistics reset")


# Global instance
metrics_collector = MetricsCollector()
