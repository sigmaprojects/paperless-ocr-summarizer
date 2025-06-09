"""
Configuration module for the Paperless AI OCR application.
Handles environment variables and application settings.
"""

import os
from typing import Optional, List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Paperless-NGX Configuration
    paperless_base_url: str = "http://localhost:8000"
    paperless_token: str = ""
    summarized_field: str = "summarized"
    
    # Ollama Configuration
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "minicpm-v:latest"
    
    # Application Configuration
    data_dir: str = "./data"
    max_concurrent_jobs: int = 1
    job_timeout_seconds: int = 3600  # 1 hour default
    
    # Background Processor Configuration
    start_background_processor: bool = True
    job_interval_seconds: int = 30
    processor_retry_minutes: int = 5
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8574
    
    # Debug Configuration
    debug: bool = False
    
    class Config:
        env_file = ".env"


# Global settings instance
settings = Settings()


def validate_configuration() -> List[str]:
    """
    Validate the current configuration and return any errors.
    
    Returns:
        List of error messages if configuration is invalid.
    """
    errors = []
    
    if not settings.paperless_token:
        errors.append("PAPERLESS_TOKEN is required")
    
    if not settings.paperless_base_url:
        errors.append("PAPERLESS_BASE_URL is required")
    
    if not settings.ollama_base_url:
        errors.append("OLLAMA_BASE_URL is required")
    
    return errors 