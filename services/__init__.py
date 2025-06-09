"""
Services package for the Paperless AI OCR application.
Contains all service classes for external API integration and job management.
"""

from .paperless_client import PaperlessClient
from .ollama_client import OllamaClient
from .job_manager import JobManager

__all__ = ["PaperlessClient", "OllamaClient", "JobManager"] 