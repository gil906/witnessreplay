"""
RPD (Requests Per Day) Budget Allocator Service.

Distributes daily RPD quota across configurable time windows (e.g., 6-hour blocks),
allowing for peak hour reservations and budget tracking per window.
"""
import logging
import json
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import os

logger = logging.getLogger(__name__)


class BudgetAction(str, Enum):
    """Action to take when budget is exceeded."""
    REJECT = "reject"
    QUEUE = "queue"
    ALLOW = "allow"  # Allow but track overage


@dataclass
class TimeWindow:
    """Represents a time window with its budget allocation."""
    name: str
    start_hour: int  # 0-23 UTC
    end_hour: int    # 0-23 UTC (exclusive, wraps at 24)
    budget_percent: float  # Percentage of daily RPD allocated to this window
    is_peak: bool = False
    
    def contains_hour(self, hour: int) -> bool:
        """Check if an hour falls within this window."""
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        else:
            # Wraps around midnight
            return hour >= self.start_hour or hour < self.end_hour
    
    def duration_hours(self) -> int:
        """Get duration in hours."""
        if self.start_hour <= self.end_hour:
            return self.end_hour - self.start_hour
        else:
            return (24 - self.start_hour) + self.end_hour
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "budget_percent": self.budget_percent,
            "is_peak": self.is_peak,
            "duration_hours": self.duration_hours(),
        }


@dataclass
class WindowUsage:
    """Tracks usage within a time window."""
    window_name: str
    date: str  # ISO date string
    budget: int  # Allocated requests for this window
    used: int = 0
    queued: int = 0
    rejected: int = 0
    
    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)
    
    @property
    def utilization_percent(self) -> float:
        if self.budget == 0:
            return 0.0
        return (self.used / self.budget) * 100
    
    def to_dict(self) -> Dict:
        return {
            "window_name": self.window_name,
            "date": self.date,
            "budget": self.budget,
            "used": self.used,
            "remaining": self.remaining,
            "queued": self.queued,
            "rejected": self.rejected,
            "utilization_percent": round(self.utilization_percent, 2),
        }


# Default time windows (6-hour blocks with peak hour reservation)
DEFAULT_WINDOWS = [
    TimeWindow("night", 0, 6, 15.0, is_peak=False),      # 00:00-06:00 UTC
    TimeWindow("morning", 6, 12, 25.0, is_peak=True),    # 06:00-12:00 UTC (peak)
    TimeWindow("afternoon", 12, 18, 35.0, is_peak=True), # 12:00-18:00 UTC (peak)
    TimeWindow("evening", 18, 24, 25.0, is_peak=False),  # 18:00-24:00 UTC
]


class RPDBudgetAllocator:
    """
    Manages daily RPD budget allocation across time windows.
    
    Features:
    - Configurable time windows with budget percentages
    - Peak hour reservations
    - Per-model budget tracking
    - Reject/queue requests exceeding window budget
    - Dashboard endpoint for budget vs actual
    """
    
    def __init__(
        self,
        persistence_file: Optional[str] = None,
        windows: Optional[List[TimeWindow]] = None,
        exceed_action: BudgetAction = BudgetAction.REJECT,
    ):
        self._lock = threading.Lock()
        self._windows = windows or DEFAULT_WINDOWS.copy()
        self._exceed_action = exceed_action
        
        # Model RPD limits (same as usage_tracker, but could be overridden)
        self._model_rpd_limits: Dict[str, int] = {}
        
        # Per-model, per-window usage tracking: {model: {window_name: WindowUsage}}
        self._window_usage: Dict[str, Dict[str, WindowUsage]] = defaultdict(dict)
        
        # Track the current date for reset logic
        self._current_date = datetime.now(timezone.utc).date()
        
        # Persistence
        if persistence_file:
            self._persistence_file = Path(persistence_file)
        else:
            data_dir = Path("/tmp/witnessreplay_data")
            data_dir.mkdir(exist_ok=True)
            self._persistence_file = data_dir / "rpd_budget.json"
        
        # Load configuration from environment
        self._load_config_from_env()
        self._load_from_disk()
    
    def _load_config_from_env(self):
        """Load budget configuration from environment variables."""
        # RPD_BUDGET_WINDOWS: JSON array of window configs
        windows_json = os.environ.get("RPD_BUDGET_WINDOWS")
        if windows_json:
            try:
                windows_data = json.loads(windows_json)
                self._windows = [
                    TimeWindow(
                        name=w["name"],
                        start_hour=w["start_hour"],
                        end_hour=w["end_hour"],
                        budget_percent=w["budget_percent"],
                        is_peak=w.get("is_peak", False),
                    )
                    for w in windows_data
                ]
                logger.info(f"Loaded {len(self._windows)} time windows from environment")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse RPD_BUDGET_WINDOWS: {e}, using defaults")
        
        # RPD_BUDGET_EXCEED_ACTION: reject, queue, or allow
        action = os.environ.get("RPD_BUDGET_EXCEED_ACTION", "reject").lower()
        try:
            self._exceed_action = BudgetAction(action)
        except ValueError:
            logger.warning(f"Invalid RPD_BUDGET_EXCEED_ACTION: {action}, using 'reject'")
            self._exceed_action = BudgetAction.REJECT
        
        # RPD_MODEL_LIMITS: JSON object {model: rpd_limit}
        limits_json = os.environ.get("RPD_MODEL_LIMITS")
        if limits_json:
            try:
                self._model_rpd_limits = json.loads(limits_json)
                logger.info(f"Loaded custom RPD limits for {len(self._model_rpd_limits)} models")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse RPD_MODEL_LIMITS: {e}")
    
    def set_windows(self, windows: List[TimeWindow]) -> bool:
        """Update time window configuration."""
        # Validate that percentages sum to ~100%
        total_percent = sum(w.budget_percent for w in windows)
        if not (95.0 <= total_percent <= 105.0):
            logger.warning(f"Window budget percentages sum to {total_percent}%, should be ~100%")
            return False
        
        with self._lock:
            self._windows = windows
            # Reinitialize window usage for today
            self._reset_for_new_day(force=True)
        
        logger.info(f"Updated budget windows: {[w.name for w in windows]}")
        return True
    
    def set_model_rpd_limit(self, model: str, rpd_limit: int):
        """Set custom RPD limit for a model."""
        with self._lock:
            self._model_rpd_limits[model] = rpd_limit
        logger.info(f"Set custom RPD limit for {model}: {rpd_limit}")
    
    def get_model_rpd_limit(self, model: str) -> int:
        """Get RPD limit for a model, falling back to usage_tracker limits."""
        if model in self._model_rpd_limits:
            return self._model_rpd_limits[model]
        
        # Import here to avoid circular imports
        from app.services.usage_tracker import UsageTracker
        limits = UsageTracker.RATE_LIMITS.get(model, {})
        return limits.get("rpd", 20)  # Default to 20
    
    def _get_current_window(self) -> Optional[TimeWindow]:
        """Get the current time window based on UTC hour."""
        current_hour = datetime.now(timezone.utc).hour
        for window in self._windows:
            if window.contains_hour(current_hour):
                return window
        return None
    
    def _check_date_reset(self):
        """Reset usage if it's a new day (UTC)."""
        today = datetime.now(timezone.utc).date()
        if today != self._current_date:
            self._reset_for_new_day()
    
    def _reset_for_new_day(self, force: bool = False):
        """Reset all window usage for a new day."""
        today = datetime.now(timezone.utc).date()
        
        if not force and today == self._current_date:
            return
        
        logger.info(f"Resetting RPD budget for new day: {today}")
        self._current_date = today
        self._window_usage.clear()
    
    def _ensure_window_usage(self, model: str, window: TimeWindow) -> WindowUsage:
        """Ensure WindowUsage exists for model/window combination."""
        date_str = self._current_date.isoformat()
        
        if window.name not in self._window_usage[model]:
            # Calculate budget for this window
            daily_rpd = self.get_model_rpd_limit(model)
            window_budget = int((window.budget_percent / 100.0) * daily_rpd)
            
            self._window_usage[model][window.name] = WindowUsage(
                window_name=window.name,
                date=date_str,
                budget=window_budget,
            )
        
        return self._window_usage[model][window.name]
    
    def check_budget(
        self,
        model: str,
        estimated_requests: int = 1
    ) -> Tuple[bool, str, BudgetAction]:
        """
        Check if a request can proceed within the current window's budget.
        
        Returns:
            Tuple of (allowed, reason, action_to_take)
        """
        with self._lock:
            self._check_date_reset()
            
            window = self._get_current_window()
            if not window:
                # No window defined for current hour, allow
                return True, "No budget window defined for current hour", BudgetAction.ALLOW
            
            usage = self._ensure_window_usage(model, window)
            
            if usage.used + estimated_requests <= usage.budget:
                return True, "Within budget", BudgetAction.ALLOW
            
            # Budget exceeded
            reason = (
                f"Window '{window.name}' budget exceeded: "
                f"{usage.used}/{usage.budget} requests used"
            )
            
            return False, reason, self._exceed_action
    
    def record_request(self, model: str, count: int = 1) -> Dict:
        """Record a request against the current window's budget."""
        with self._lock:
            self._check_date_reset()
            
            window = self._get_current_window()
            if not window:
                return {"recorded": False, "reason": "No window for current hour"}
            
            usage = self._ensure_window_usage(model, window)
            usage.used += count
            
            logger.debug(
                f"Recorded {count} request(s) for {model} in window '{window.name}': "
                f"{usage.used}/{usage.budget}"
            )
        
        # Save asynchronously
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_to_disk_async())
        except RuntimeError:
            pass
        
        return {
            "recorded": True,
            "window": window.name,
            "used": usage.used,
            "budget": usage.budget,
            "remaining": usage.remaining,
        }
    
    def record_queued(self, model: str, count: int = 1):
        """Record a request that was queued due to budget limits."""
        with self._lock:
            self._check_date_reset()
            window = self._get_current_window()
            if window:
                usage = self._ensure_window_usage(model, window)
                usage.queued += count
    
    def record_rejected(self, model: str, count: int = 1):
        """Record a request that was rejected due to budget limits."""
        with self._lock:
            self._check_date_reset()
            window = self._get_current_window()
            if window:
                usage = self._ensure_window_usage(model, window)
                usage.rejected += count
    
    def get_current_window_status(self, model: str) -> Dict:
        """Get status for the current time window."""
        with self._lock:
            self._check_date_reset()
            
            window = self._get_current_window()
            if not window:
                return {
                    "current_window": None,
                    "message": "No budget window defined for current hour"
                }
            
            usage = self._ensure_window_usage(model, window)
            now = datetime.now(timezone.utc)
            
            # Calculate time remaining in window
            if window.start_hour <= window.end_hour:
                window_end = now.replace(hour=window.end_hour, minute=0, second=0, microsecond=0)
                if now.hour >= window.end_hour:
                    window_end += timedelta(days=1)
            else:
                if now.hour >= window.start_hour:
                    window_end = (now + timedelta(days=1)).replace(
                        hour=window.end_hour, minute=0, second=0, microsecond=0
                    )
                else:
                    window_end = now.replace(hour=window.end_hour, minute=0, second=0, microsecond=0)
            
            time_remaining = window_end - now
            
            return {
                "model": model,
                "current_window": window.to_dict(),
                "usage": usage.to_dict(),
                "time_remaining_seconds": int(time_remaining.total_seconds()),
                "time_remaining_human": str(time_remaining).split('.')[0],
            }
    
    def get_dashboard(self, model: Optional[str] = None) -> Dict:
        """Get comprehensive budget dashboard showing budget vs actual."""
        with self._lock:
            self._check_date_reset()
            
            now = datetime.now(timezone.utc)
            current_window = self._get_current_window()
            
            result = {
                "timestamp": now.isoformat(),
                "date": self._current_date.isoformat(),
                "current_hour_utc": now.hour,
                "current_window": current_window.name if current_window else None,
                "exceed_action": self._exceed_action.value,
                "windows": [w.to_dict() for w in self._windows],
                "models": {},
            }
            
            # Determine which models to include
            if model:
                models = [model]
            else:
                # Include all models with usage or limits
                from app.services.usage_tracker import UsageTracker
                models = list(
                    set(self._model_rpd_limits.keys()) |
                    set(self._window_usage.keys()) |
                    set(UsageTracker.RATE_LIMITS.keys())
                )
            
            for m in models:
                daily_rpd = self.get_model_rpd_limit(m)
                model_data = {
                    "daily_rpd_limit": daily_rpd,
                    "windows": {},
                    "totals": {
                        "budget": 0,
                        "used": 0,
                        "queued": 0,
                        "rejected": 0,
                    }
                }
                
                for window in self._windows:
                    usage = self._ensure_window_usage(m, window)
                    model_data["windows"][window.name] = usage.to_dict()
                    model_data["totals"]["budget"] += usage.budget
                    model_data["totals"]["used"] += usage.used
                    model_data["totals"]["queued"] += usage.queued
                    model_data["totals"]["rejected"] += usage.rejected
                
                # Calculate overall utilization
                total_budget = model_data["totals"]["budget"]
                total_used = model_data["totals"]["used"]
                model_data["totals"]["remaining"] = total_budget - total_used
                model_data["totals"]["utilization_percent"] = (
                    round((total_used / total_budget) * 100, 2) if total_budget > 0 else 0.0
                )
                
                result["models"][m] = model_data
            
            return result
    
    def get_windows_config(self) -> List[Dict]:
        """Get current window configuration."""
        return [w.to_dict() for w in self._windows]
    
    def _load_from_disk(self):
        """Load budget data from disk."""
        try:
            if self._persistence_file.exists():
                with open(self._persistence_file, 'r') as f:
                    data = json.load(f)
                
                saved_date_str = data.get("date", "")
                if not saved_date_str:
                    return
                
                saved_date = datetime.fromisoformat(saved_date_str).date()
                today = datetime.now(timezone.utc).date()
                
                if saved_date == today:
                    self._current_date = saved_date
                    
                    # Restore window usage
                    for model, windows_data in data.get("window_usage", {}).items():
                        for window_name, usage_data in windows_data.items():
                            self._window_usage[model][window_name] = WindowUsage(
                                window_name=usage_data["window_name"],
                                date=usage_data["date"],
                                budget=usage_data["budget"],
                                used=usage_data["used"],
                                queued=usage_data["queued"],
                                rejected=usage_data["rejected"],
                            )
                    
                    logger.info(f"Loaded RPD budget data from {self._persistence_file}")
                else:
                    logger.info(f"Budget data is from {saved_date}, starting fresh for {today}")
        except Exception as e:
            logger.warning(f"Could not load RPD budget data: {e}")
    
    async def _save_to_disk_async(self):
        """Save budget data to disk asynchronously."""
        try:
            with self._lock:
                data = {
                    "date": self._current_date.isoformat(),
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "window_usage": {
                        model: {
                            window_name: usage.to_dict()
                            for window_name, usage in windows.items()
                        }
                        for model, windows in self._window_usage.items()
                    },
                }
            
            def _write_file():
                temp_file = self._persistence_file.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump(data, f, indent=2)
                temp_file.replace(self._persistence_file)
            
            await asyncio.to_thread(_write_file)
            logger.debug(f"Saved RPD budget data to {self._persistence_file}")
        except Exception as e:
            logger.error(f"Failed to save RPD budget data: {e}")


# Global instance
rpd_budget = RPDBudgetAllocator()
