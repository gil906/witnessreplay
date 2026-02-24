import os
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    gemini_model: str = "gemini-2.0-flash-exp"
    gemini_vision_model: str = "gemini-2.0-flash-exp"
    
    # Rate Limiting
    max_requests_per_minute: int = 60
    enforce_rate_limits: bool = False  # Set to True in production
    
    # Admin Configuration
    admin_password: str = "change_this_password_immediately"
    
    # Database Configuration
    database_path: str = "/app/data/witnessreplay.db"
    
    # Session Configuration
    session_timeout_minutes: int = 60
    max_session_size_mb: int = 100
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_assignment=True  # Allow runtime updates
    )


# Global settings instance
settings = Settings()
