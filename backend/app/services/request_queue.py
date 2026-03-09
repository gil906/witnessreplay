"""
Request queuing service for handling rate-limited requests.
Buffers requests when rate limits are hit and processes them when quota refreshes.
Supports priority levels for processing critical requests (e.g., police emergencies) first.
"""
import logging
import asyncio
import uuid
import heapq
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Callable, Any, Tuple, List
from dataclasses import dataclass, field
from collections import deque
from enum import Enum, IntEnum
import threading

logger = logging.getLogger(__name__)


class RequestPriority(IntEnum):
    """Priority levels for queued requests. Lower values = higher priority."""
    CRITICAL = 0  # Police emergencies, highest priority
    HIGH = 1      # Important requests
    NORMAL = 2    # Default priority
    LOW = 3       # Background/batch requests


class QueuedRequestStatus(str, Enum):
    """Status of a queued request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(order=True)
class QueuedRequest:
    """Represents a queued request waiting for rate limit to refresh."""
    # Sort key for priority queue (priority, then timestamp)
    sort_key: Tuple[int, datetime] = field(init=False, repr=False)
    
    id: str = field(compare=False)
    endpoint: str = field(compare=False)
    method: str = field(compare=False)
    client_ip: str = field(compare=False)
    created_at: datetime = field(compare=False)
    ttl_seconds: int = field(compare=False)
    priority: RequestPriority = field(default=RequestPriority.NORMAL, compare=False)
    status: QueuedRequestStatus = field(default=QueuedRequestStatus.PENDING, compare=False)
    result: Optional[Any] = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    completed_at: Optional[datetime] = field(default=None, compare=False)
    session_id: Optional[str] = field(default=None, compare=False)  # Associated session for priority lookup
    # Callable to execute when processing (stored separately, not serialized)
    _callback: Optional[Callable] = field(default=None, repr=False, compare=False)
    
    def __post_init__(self):
        # Initialize sort key for heap ordering (lower priority value + earlier time = first)
        self.sort_key = (int(self.priority), self.created_at)
    
    @property
    def expires_at(self) -> datetime:
        """Calculate expiration time."""
        return self.created_at + timedelta(seconds=self.ttl_seconds)
    
    @property
    def is_expired(self) -> bool:
        """Check if request has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    def update_priority(self, new_priority: RequestPriority):
        """Update the priority and recalculate sort key."""
        self.priority = new_priority
        self.sort_key = (int(self.priority), self.created_at)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "endpoint": self.endpoint,
            "method": self.method,
            "client_ip": self.client_ip,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "priority": self.priority.name.lower(),
            "status": self.status.value,
            "error": self.error,
            "session_id": self.session_id,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class RequestQueue:
    """
    Request queue service that buffers rate-limited requests.
    
    Features:
    - Queue requests when rate limits are hit
    - Priority-based processing (critical > high > normal > low)
    - Background task processes queued requests when quota refreshes
    - Max queue size to prevent memory issues
    - TTL for queued requests to prevent stale requests
    - Status endpoint for checking pending requests
    """
    
    DEFAULT_MAX_QUEUE_SIZE = 100
    DEFAULT_TTL_SECONDS = 300  # 5 minutes
    DEFAULT_PROCESS_INTERVAL = 5  # seconds
    
    def __init__(
        self,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
        process_interval: float = DEFAULT_PROCESS_INTERVAL,
    ):
        self._lock = threading.Lock()
        self._priority_queue: List[QueuedRequest] = []  # Heap-based priority queue
        self._requests_by_id: Dict[str, QueuedRequest] = {}
        self._max_queue_size = max_queue_size
        self._default_ttl_seconds = default_ttl_seconds
        self._process_interval = process_interval
        self._processing_task: Optional[asyncio.Task] = None
        self._is_running = False
        
        # Statistics
        self._stats = {
            "total_queued": 0,
            "total_processed": 0,
            "total_expired": 0,
            "total_failed": 0,
            "total_rejected": 0,  # Rejected due to full queue
            "by_priority": {p.name.lower(): 0 for p in RequestPriority},
        }
    
    async def start(self):
        """Start the background queue processor."""
        if self._is_running:
            return
        
        self._is_running = True
        self._processing_task = asyncio.create_task(self._process_queue_loop())
        logger.info("Request queue processor started")
    
    async def stop(self):
        """Stop the background queue processor."""
        self._is_running = False
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        logger.info("Request queue processor stopped")
    
    def queue_request(
        self,
        endpoint: str,
        method: str,
        client_ip: str,
        callback: Optional[Callable] = None,
        ttl_seconds: Optional[int] = None,
        priority: RequestPriority = RequestPriority.NORMAL,
        session_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[QueuedRequest]]:
        """
        Queue a request for later processing.
        
        Args:
            endpoint: The API endpoint path
            method: HTTP method (GET, POST, etc.)
            client_ip: Client IP address
            callback: Async callable to execute when processing
            ttl_seconds: Time-to-live for this request
            priority: Request priority (critical, high, normal, low)
            session_id: Associated session ID for priority lookup
            
        Returns:
            Tuple of (success, queued_request or None if rejected)
        """
        with self._lock:
            # Check queue size limit
            if len(self._priority_queue) >= self._max_queue_size:
                self._stats["total_rejected"] += 1
                logger.warning(
                    f"Request queue full ({self._max_queue_size}), rejecting request to {endpoint}"
                )
                return False, None
            
            # Create queued request
            request = QueuedRequest(
                id=str(uuid.uuid4()),
                endpoint=endpoint,
                method=method,
                client_ip=client_ip,
                created_at=datetime.now(timezone.utc),
                ttl_seconds=ttl_seconds or self._default_ttl_seconds,
                priority=priority,
                session_id=session_id,
                _callback=callback,
            )
            
            # Add to priority queue (heap)
            heapq.heappush(self._priority_queue, request)
            self._requests_by_id[request.id] = request
            self._stats["total_queued"] += 1
            self._stats["by_priority"][priority.name.lower()] += 1
            
            logger.info(
                f"Queued request {request.id}: {method} {endpoint} "
                f"(priority: {priority.name}, queue size: {len(self._priority_queue)})"
            )
            
            return True, request
    
    def get_request_status(self, request_id: str) -> Optional[QueuedRequest]:
        """Get the status of a queued request."""
        with self._lock:
            return self._requests_by_id.get(request_id)
    
    def cancel_request(self, request_id: str) -> bool:
        """Cancel a pending queued request."""
        with self._lock:
            request = self._requests_by_id.get(request_id)
            if not request:
                return False
            
            if request.status == QueuedRequestStatus.PENDING:
                request.status = QueuedRequestStatus.CANCELLED
                # Remove from priority queue
                try:
                    self._priority_queue.remove(request)
                    heapq.heapify(self._priority_queue)
                except ValueError:
                    pass
                logger.info(f"Cancelled queued request {request_id}")
                return True
            
            return False
    
    def set_request_priority(self, request_id: str, priority: RequestPriority) -> bool:
        """
        Update the priority of a pending queued request.
        
        Args:
            request_id: The unique ID of the queued request
            priority: The new priority level
            
        Returns:
            True if priority was updated, False if request not found or not pending
        """
        with self._lock:
            request = self._requests_by_id.get(request_id)
            if not request:
                return False
            
            if request.status != QueuedRequestStatus.PENDING:
                return False
            
            old_priority = request.priority
            request.update_priority(priority)
            
            # Re-heapify to maintain heap property
            heapq.heapify(self._priority_queue)
            
            logger.info(
                f"Updated priority for request {request_id}: "
                f"{old_priority.name} -> {priority.name}"
            )
            return True
    
    def get_queue_status(self) -> Dict:
        """Get overall queue status and statistics."""
        with self._lock:
            pending_count = sum(
                1 for r in self._priority_queue 
                if r.status == QueuedRequestStatus.PENDING and not r.is_expired
            )
            
            # Group pending by endpoint
            pending_by_endpoint: Dict[str, int] = {}
            pending_by_priority: Dict[str, int] = {p.name.lower(): 0 for p in RequestPriority}
            
            for request in self._priority_queue:
                if request.status == QueuedRequestStatus.PENDING and not request.is_expired:
                    key = f"{request.method} {request.endpoint}"
                    pending_by_endpoint[key] = pending_by_endpoint.get(key, 0) + 1
                    pending_by_priority[request.priority.name.lower()] += 1
            
            return {
                "is_running": self._is_running,
                "queue_size": len(self._priority_queue),
                "pending_count": pending_count,
                "max_queue_size": self._max_queue_size,
                "default_ttl_seconds": self._default_ttl_seconds,
                "process_interval_seconds": self._process_interval,
                "pending_by_endpoint": pending_by_endpoint,
                "pending_by_priority": pending_by_priority,
                "statistics": dict(self._stats),
            }
    
    def get_pending_requests(
        self,
        limit: int = 50,
        client_ip: Optional[str] = None,
        priority: Optional[RequestPriority] = None,
    ) -> list[Dict]:
        """Get list of pending requests, sorted by priority."""
        with self._lock:
            results = []
            # Sort by priority for display (heap maintains partial order)
            sorted_requests = sorted(self._priority_queue)
            
            for request in sorted_requests:
                if request.status != QueuedRequestStatus.PENDING:
                    continue
                if request.is_expired:
                    continue
                if client_ip and request.client_ip != client_ip:
                    continue
                if priority is not None and request.priority != priority:
                    continue
                
                results.append(request.to_dict())
                if len(results) >= limit:
                    break
            
            return results
    
    async def _process_queue_loop(self):
        """Background loop that processes queued requests."""
        from app.services.usage_tracker import usage_tracker
        from app.config import settings
        
        logger.info("Queue processing loop started")
        
        while self._is_running:
            try:
                await asyncio.sleep(self._process_interval)
                await self._process_pending_requests(usage_tracker, settings)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue processing loop: {e}")
    
    async def _process_pending_requests(self, usage_tracker, settings):
        """Process pending requests by priority if rate limit allows."""
        # Get current model for rate limit check
        current_model = settings.gemini_model
        
        # Check if we have quota available
        allowed, reason = usage_tracker.check_rate_limit(current_model)
        
        if not allowed:
            logger.debug(f"Rate limit still exceeded, skipping queue processing: {reason}")
            return
        
        # Process requests while we have quota (in priority order)
        processed_count = 0
        max_batch = 5  # Process up to 5 requests per cycle
        
        with self._lock:
            requests_to_process = []
            expired_requests = []
            
            # Process in priority order using heap
            # Create a copy since we'll modify the heap
            temp_heap = self._priority_queue.copy()
            
            while temp_heap and len(requests_to_process) < max_batch:
                request = heapq.heappop(temp_heap)
                
                if request.status != QueuedRequestStatus.PENDING:
                    continue
                
                if request.is_expired:
                    request.status = QueuedRequestStatus.EXPIRED
                    expired_requests.append(request)
                    self._stats["total_expired"] += 1
                    continue
                
                request.status = QueuedRequestStatus.PROCESSING
                requests_to_process.append(request)
            
            # Remove expired requests from the priority queue
            for request in expired_requests:
                try:
                    self._priority_queue.remove(request)
                except ValueError:
                    pass
            if expired_requests:
                heapq.heapify(self._priority_queue)
        
        # Process requests outside the lock
        for request in requests_to_process:
            try:
                # Re-check rate limit before each request
                allowed, _ = usage_tracker.check_rate_limit(current_model)
                if not allowed:
                    # Put back to pending
                    with self._lock:
                        request.status = QueuedRequestStatus.PENDING
                    break
                
                if request._callback:
                    result = await request._callback()
                    request.result = result
                
                request.status = QueuedRequestStatus.COMPLETED
                request.completed_at = datetime.now(timezone.utc)
                processed_count += 1
                
                with self._lock:
                    self._stats["total_processed"] += 1
                    # Remove from priority queue
                    try:
                        self._priority_queue.remove(request)
                        heapq.heapify(self._priority_queue)
                    except ValueError:
                        pass
                
                logger.info(
                    f"Processed queued request {request.id}: {request.method} {request.endpoint} "
                    f"(priority: {request.priority.name})"
                )
                
            except Exception as e:
                logger.error(f"Error processing queued request {request.id}: {e}")
                request.status = QueuedRequestStatus.FAILED
                request.error = str(e)
                request.completed_at = datetime.now(timezone.utc)
                
                with self._lock:
                    self._stats["total_failed"] += 1
                    try:
                        self._priority_queue.remove(request)
                        heapq.heapify(self._priority_queue)
                    except ValueError:
                        pass
        
        if processed_count > 0:
            logger.info(f"Processed {processed_count} queued requests")
    
    def cleanup_completed(self, max_age_seconds: int = 3600):
        """Clean up completed/failed/expired requests older than max_age."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        
        with self._lock:
            to_remove = []
            for request_id, request in self._requests_by_id.items():
                if request.status in (
                    QueuedRequestStatus.COMPLETED,
                    QueuedRequestStatus.FAILED,
                    QueuedRequestStatus.EXPIRED,
                    QueuedRequestStatus.CANCELLED,
                ):
                    completed_time = request.completed_at or request.created_at
                    if completed_time < cutoff:
                        to_remove.append(request_id)
            
            for request_id in to_remove:
                del self._requests_by_id[request_id]
            
            if to_remove:
                logger.debug(f"Cleaned up {len(to_remove)} old queued requests")


# Global instance
request_queue = RequestQueue()
