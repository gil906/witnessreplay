import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Google AI Configuration
    google_api_key: str = ""
    
    # Google Cloud Project Configuration
    gcp_project_id: str = ""
    gcs_bucket: str = "witnessreplay-images"
    firestore_collection: str = "reconstruction_sessions"
    
    # Application Configuration
    environment: str = "development"
    debug: bool = True
    allowed_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8080",
    ]
    
    # Server Configuration
    port: int = 8080
    host: str = "0.0.0.0"
    
    # Model Configuration
    gemini_model: str = "gemini-2.0-flash-exp"
    gemini_vision_model: str = "gemini-2.0-flash-exp"
    
    # Rate Limiting
    max_requests_per_minute: int = 60
    
    # Session Configuration
    session_timeout_minutes: int = 60
    max_session_size_mb: int = 100
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings instance
settings = Settings()
