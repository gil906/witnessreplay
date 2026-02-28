import os
import logging
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Google AI Configuration
    google_api_key: str = ""
    google_api_keys: str = ""  # Comma-separated list for rotation/fallback
    
    # Google Cloud Project Configuration
    gcp_project_id: str = ""
    gcs_bucket: str = "witnessreplay-images"
    firestore_collection: str = "reconstruction_sessions"
    
    # Application Configuration
    environment: str = "development"
    debug: bool = False
    maintenance_mode: bool = False
    data_retention_days: int = 30

    allowed_origins: List[str] = ["*"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
    
    # Server Configuration
    port: int = 8080
    host: str = "0.0.0.0"
    
    # Model Configuration
    gemini_model: str = "gemini-3-flash"
    gemini_vision_model: str = "gemini-3-flash"
    gemini_lite_model: str = "gemini-2.5-flash-lite"
    gemma_model: str = "gemma-3-27b-it"
    imagen_model: str = "imagen-4-fast-generate"
    embedding_model: str = "gemini-embedding-001"
    tts_model: str = "gemini-2.5-flash-native-audio-latest"
    live_model: str = "gemini-2.5-flash-native-audio-latest"
    
    # Rate Limiting
    max_requests_per_minute: int = 60
    enforce_rate_limits: bool = False  # Set to True in production
    
    # RPD Budget Allocator
    rpd_budget_exceed_action: str = "reject"  # reject, queue, or allow
    rpd_budget_windows: str = ""  # JSON array of window configs (optional)
    
    # Multi-Model Verification
    multi_model_verification_enabled: bool = True  # Enable cross-model verification
    
    # Quota Alerts
    quota_alert_threshold: float = 0.80  # Default 80% warning threshold
    quota_alert_critical_threshold: float = 0.95  # Default 95% critical threshold
    quota_alert_webhook_url: str = ""  # Webhook URL for alerts
    quota_alert_check_interval: int = 60  # Seconds between periodic checks
    
    # Request Batching
    batch_embedding_size: int = 20  # Max embedding requests per batch
    batch_embedding_wait_ms: int = 100  # Max wait time for batch to fill
    batch_embedding_enabled: bool = True  # Enable embedding batching
    batch_classification_size: int = 10  # Max classification requests per batch
    batch_classification_wait_ms: int = 150  # Max wait time for batch to fill
    batch_classification_enabled: bool = True  # Enable classification batching
    
    # Admin Configuration
    admin_password: str = "change_this_password_immediately"
    
    # Database Configuration
    database_path: str = "/app/data/witnessreplay.db"
    
    # Session Configuration
    session_timeout_minutes: int = 60
    max_session_size_mb: int = 100
    
    # AI Confidence Thresholds
    confidence_threshold: float = 0.7  # Minimum confidence for auto-acceptance
    low_confidence_threshold: float = 0.4  # Below this is flagged as low confidence
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_assignment=True  # Allow runtime updates
    )

    def validate_config(self):
        """Log warnings for missing configurations."""
        warnings = []
        if not self.google_api_key:
            warnings.append("GOOGLE_API_KEY not set - AI features will not work")
        if not self.gcp_project_id:
            warnings.append("GCP_PROJECT_ID not set - Firestore will not work")
        if self.admin_password == "change_this_password_immediately":
            warnings.append("⚠️ ADMIN_PASSWORD is using default value - CHANGE IT for production!")
        for w in warnings:
            _config_logger.warning(f"[CONFIG] {w}")
        return warnings


# Global settings instance
settings = Settings()
