"""
Quota alert service for monitoring API usage and triggering alerts.
Supports multiple channels: console log, webhook, email placeholder.
"""
import logging
import asyncio
import os
import json
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class AlertChannel(Enum):
    CONSOLE = "console"
    WEBHOOK = "webhook"
    EMAIL = "email"


class AlertLevel(Enum):
    WARNING = "warning"
    CRITICAL = "critical"
    RESOLVED = "resolved"


@dataclass
class QuotaAlert:
    """Represents a quota alert event."""
    id: str
    model: str
    metric: str  # rpm, rpd, tpm
    level: AlertLevel
    threshold_percent: float
    current_percent: float
    current_value: int
    limit_value: int
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    channels_notified: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "model": self.model,
            "metric": self.metric,
            "level": self.level.value,
            "threshold_percent": self.threshold_percent,
            "current_percent": self.current_percent,
            "current_value": self.current_value,
            "limit_value": self.limit_value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "channels_notified": self.channels_notified,
        }


class QuotaAlertService:
    """
    Service for monitoring quota usage and triggering alerts
    when thresholds are exceeded.
    """
    
    def __init__(
        self,
        warning_threshold: float = 0.80,
        critical_threshold: float = 0.95,
        webhook_url: Optional[str] = None,
        max_history: int = 100,
    ):
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._webhook_url = webhook_url or os.getenv("QUOTA_ALERT_WEBHOOK_URL")
        self._max_history = max_history
        
        # Alert history (recent alerts)
        self._alert_history: deque = deque(maxlen=max_history)
        
        # Track active alerts to avoid duplicate notifications
        self._active_alerts: Dict[str, QuotaAlert] = {}
        
        # Background task for periodic checking
        self._check_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Check interval in seconds (default: 60 seconds)
        self._check_interval = int(os.getenv("QUOTA_ALERT_CHECK_INTERVAL", "60"))
        
        logger.info(
            f"QuotaAlertService initialized: "
            f"warning={self._warning_threshold*100}%, "
            f"critical={self._critical_threshold*100}%, "
            f"webhook={'configured' if self._webhook_url else 'not configured'}"
        )
    
    @property
    def warning_threshold(self) -> float:
        return self._warning_threshold
    
    @property
    def critical_threshold(self) -> float:
        return self._critical_threshold
    
    def set_thresholds(self, warning: float = None, critical: float = None):
        """Update alert thresholds dynamically."""
        if warning is not None:
            self._warning_threshold = warning
        if critical is not None:
            self._critical_threshold = critical
        logger.info(f"Thresholds updated: warning={self._warning_threshold}, critical={self._critical_threshold}")
    
    def _generate_alert_key(self, model: str, metric: str) -> str:
        """Generate unique key for tracking active alerts."""
        return f"{model}:{metric}"
    
    def _generate_alert_id(self) -> str:
        """Generate unique alert ID."""
        import uuid
        return str(uuid.uuid4())[:8]
    
    async def check_quota(self, model: str, usage: Dict) -> List[QuotaAlert]:
        """
        Check quota usage for a model and generate alerts if thresholds exceeded.
        
        Args:
            model: Model name
            usage: Usage data from usage_tracker.get_usage()
            
        Returns:
            List of alerts generated
        """
        alerts = []
        
        # Check each metric (rpm, rpd, tpm)
        metrics = [
            ("rpm", usage.get("requests", {}).get("minute", {})),
            ("rpd", usage.get("requests", {}).get("day", {})),
            ("tpm", usage.get("tokens", {}).get("day", {})),
        ]
        
        for metric_name, metric_data in metrics:
            used = metric_data.get("used", 0)
            limit = metric_data.get("limit", 0)
            
            if limit <= 0:
                continue
            
            percent = used / limit
            alert_key = self._generate_alert_key(model, metric_name)
            
            # Determine alert level
            if percent >= self._critical_threshold:
                level = AlertLevel.CRITICAL
            elif percent >= self._warning_threshold:
                level = AlertLevel.WARNING
            else:
                # Check if we need to send a resolved alert
                if alert_key in self._active_alerts:
                    resolved_alert = QuotaAlert(
                        id=self._generate_alert_id(),
                        model=model,
                        metric=metric_name,
                        level=AlertLevel.RESOLVED,
                        threshold_percent=self._warning_threshold * 100,
                        current_percent=round(percent * 100, 1),
                        current_value=used,
                        limit_value=limit,
                        message=f"Quota {metric_name.upper()} for {model} back to normal ({percent*100:.1f}%)"
                    )
                    alerts.append(resolved_alert)
                    await self._send_alert(resolved_alert)
                    del self._active_alerts[alert_key]
                continue
            
            # Check if alert already active at same or higher level
            existing = self._active_alerts.get(alert_key)
            if existing:
                # Only send new alert if level escalated
                if existing.level == AlertLevel.WARNING and level == AlertLevel.CRITICAL:
                    pass  # Escalate
                else:
                    continue  # Skip duplicate
            
            # Create and send alert
            alert = QuotaAlert(
                id=self._generate_alert_id(),
                model=model,
                metric=metric_name,
                level=level,
                threshold_percent=self._warning_threshold * 100 if level == AlertLevel.WARNING else self._critical_threshold * 100,
                current_percent=round(percent * 100, 1),
                current_value=used,
                limit_value=limit,
                message=f"{level.value.upper()}: {model} {metric_name.upper()} at {percent*100:.1f}% ({used}/{limit})"
            )
            
            alerts.append(alert)
            await self._send_alert(alert)
            self._active_alerts[alert_key] = alert
        
        return alerts
    
    async def _send_alert(self, alert: QuotaAlert):
        """Send alert through all configured channels."""
        channels_used = []
        
        # Console logging (always enabled)
        await self._send_console_alert(alert)
        channels_used.append(AlertChannel.CONSOLE.value)
        
        # Webhook
        if self._webhook_url:
            try:
                await self._send_webhook_alert(alert)
                channels_used.append(AlertChannel.WEBHOOK.value)
            except Exception as e:
                logger.error(f"Failed to send webhook alert: {e}")
        
        # Email placeholder
        await self._send_email_alert(alert)
        channels_used.append(AlertChannel.EMAIL.value)
        
        alert.channels_notified = channels_used
        self._alert_history.append(alert)
    
    async def _send_console_alert(self, alert: QuotaAlert):
        """Log alert to console."""
        if alert.level == AlertLevel.CRITICAL:
            logger.critical(alert.message)
        elif alert.level == AlertLevel.WARNING:
            logger.warning(alert.message)
        else:
            logger.info(alert.message)
    
    async def _send_webhook_alert(self, alert: QuotaAlert):
        """Send alert to configured webhook URL."""
        if not self._webhook_url:
            return
        
        payload = {
            "type": "quota_alert",
            "alert": alert.to_dict(),
            "source": "witnessreplay",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            logger.info(f"Webhook alert sent: {alert.id}")
    
    async def _send_email_alert(self, alert: QuotaAlert):
        """
        Email alert placeholder.
        Implement actual email sending when email service is configured.
        """
        # Placeholder: log that email would be sent
        logger.debug(f"Email alert placeholder: {alert.message}")
        # TODO: Implement actual email sending when SMTP is configured
        # Example implementation:
        # smtp_host = os.getenv("SMTP_HOST")
        # smtp_port = os.getenv("SMTP_PORT", 587)
        # email_to = os.getenv("QUOTA_ALERT_EMAIL")
        # if smtp_host and email_to:
        #     # Send email...
        #     pass
    
    async def check_all_quotas(self):
        """Check quotas for all tracked models."""
        from app.services.usage_tracker import usage_tracker
        
        all_usage = usage_tracker.get_all_usage()
        all_alerts = []
        
        for model, usage in all_usage.items():
            alerts = await self.check_quota(model, usage)
            all_alerts.extend(alerts)
        
        return all_alerts
    
    async def _periodic_check(self):
        """Background task that periodically checks quotas."""
        logger.info(f"Starting periodic quota check (interval: {self._check_interval}s)")
        
        while self._running:
            try:
                await self.check_all_quotas()
            except Exception as e:
                logger.error(f"Error in periodic quota check: {e}")
            
            await asyncio.sleep(self._check_interval)
    
    async def start(self):
        """Start periodic quota checking."""
        if self._running:
            return
        
        self._running = True
        self._check_task = asyncio.create_task(self._periodic_check())
        logger.info("QuotaAlertService started")
    
    async def stop(self):
        """Stop periodic quota checking."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("QuotaAlertService stopped")
    
    def get_alert_history(self, limit: int = 50, model: str = None, level: str = None) -> List[Dict]:
        """
        Get recent alert history.
        
        Args:
            limit: Maximum number of alerts to return
            model: Filter by model name
            level: Filter by alert level
            
        Returns:
            List of alert dictionaries
        """
        alerts = list(self._alert_history)
        
        # Apply filters
        if model:
            alerts = [a for a in alerts if a.model == model]
        if level:
            alerts = [a for a in alerts if a.level.value == level]
        
        # Return most recent first
        alerts = sorted(alerts, key=lambda a: a.timestamp, reverse=True)
        return [a.to_dict() for a in alerts[:limit]]
    
    def get_active_alerts(self) -> List[Dict]:
        """Get currently active (unresolved) alerts."""
        return [a.to_dict() for a in self._active_alerts.values()]
    
    def get_config(self) -> Dict:
        """Get current alert service configuration."""
        return {
            "warning_threshold_percent": self._warning_threshold * 100,
            "critical_threshold_percent": self._critical_threshold * 100,
            "webhook_configured": bool(self._webhook_url),
            "check_interval_seconds": self._check_interval,
            "max_history": self._max_history,
            "active_alert_count": len(self._active_alerts),
            "history_count": len(self._alert_history),
        }


# Global instance with configurable threshold
_default_threshold = float(os.getenv("QUOTA_ALERT_THRESHOLD", "0.80"))
quota_alert_service = QuotaAlertService(warning_threshold=_default_threshold)
