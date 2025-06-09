"""
Data models for the Paperless AI OCR application.
Defines the structure for jobs, documents, and API responses.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Enumeration of possible job statuses."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingJob(BaseModel):
    """Model representing a document processing job."""
    
    job_id: str = Field(..., description="Unique identifier for the job")
    document_id: int = Field(..., description="Paperless document ID")
    status: JobStatus = Field(default=JobStatus.PENDING, description="Current job status")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Job creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Job start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Job completion timestamp")
    error_message: Optional[str] = Field(None, description="Error message if job failed")
    progress_message: Optional[str] = Field(None, description="Current progress message")
    
    # File paths for temporary storage
    pdf_path: Optional[str] = Field(None, description="Path to downloaded PDF file")
    ocr_path: Optional[str] = Field(None, description="Path to OCR output file")
    summary_path: Optional[str] = Field(None, description="Path to summary output file")
    
    # Processing results
    ocr_content: Optional[str] = Field(None, description="OCR extracted text")
    summary_content: Optional[str] = Field(None, description="Generated summary")
    
    def get_duration_seconds(self) -> Optional[int]:
        """Get the duration of the job in seconds."""
        if self.started_at is None:
            return None
        
        end_time = self.completed_at or datetime.utcnow()
        return int((end_time - self.started_at).total_seconds())
    
    def get_status_description(self) -> str:
        """Get a human-readable status description."""
        status_descriptions = {
            JobStatus.PENDING: "Waiting to start processing",
            JobStatus.DOWNLOADING: "Downloading PDF from Paperless",
            JobStatus.PROCESSING: "Processing with Ollama AI",
            JobStatus.UPLOADING: "Uploading results to Paperless",
            JobStatus.COMPLETED: "Successfully completed",
            JobStatus.FAILED: f"Failed: {self.error_message or 'Unknown error'}",
            JobStatus.CANCELLED: "Cancelled by user"
        }
        return status_descriptions.get(self.status, "Unknown status")


class JobCreateRequest(BaseModel):
    """Request model for creating a new processing job."""
    
    document_id: Optional[int] = Field(None, description="Specific document ID to process")
    auto_discover: bool = Field(default=True, description="Auto-discover documents without summarized custom field")


class JobResponse(BaseModel):
    """Response model for job information."""
    
    job_id: str
    document_id: int
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    status_description: str
    progress_message: Optional[str]
    error_message: Optional[str]
    
    @classmethod
    def from_processing_job(cls, job: ProcessingJob) -> "JobResponse":
        """Create a JobResponse from a ProcessingJob."""
        return cls(
            job_id=job.job_id,
            document_id=job.document_id,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            duration_seconds=job.get_duration_seconds(),
            status_description=job.get_status_description(),
            progress_message=job.progress_message,
            error_message=job.error_message
        )


class JobStatusResponse(BaseModel):
    """Response model for job status requests."""
    
    job_id: str
    document_id: int
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    ocr_content: Optional[str] = None
    summary_content: Optional[str] = None


class ProcessorStatusResponse(BaseModel):
    """Response model for background processor status."""
    
    is_running: bool
    is_processing: bool
    job_interval_seconds: int
    processor_retry_minutes: int
    start_time: Optional[str] = None


class PaperlessDocument(BaseModel):
    """Model representing a Paperless document."""
    
    id: int
    title: str
    content: Optional[str]
    tags: List[int]
    created: datetime
    modified: datetime
    original_file_name: str
    download_url: Optional[str] = None


class OllamaResponse(BaseModel):
    """Model for Ollama API response."""
    
    model: str
    created_at: datetime
    response: str
    done: bool
    context: Optional[List[int]] = None
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration: Optional[int] = None


class HealthStatus(BaseModel):
    """Model for application health status."""
    
    status: str
    paperless_connected: bool
    ollama_connected: bool
    active_jobs: int
    total_jobs: int
    errors: List[str] = Field(default_factory=list) 