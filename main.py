"""
Main FastAPI application for the Paperless AI OCR service.
Provides REST API endpoints for managing document processing jobs.
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from config import settings, validate_configuration
from models import (
    JobCreateRequest, 
    JobResponse, 
    JobStatus, 
    HealthStatus, 
    ProcessingJob,
    JobStatusResponse,
    ProcessorStatusResponse
)
from services.job_manager import JobManager
from services.background_processor import BackgroundProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Global instances
job_manager: Optional[JobManager] = None
background_processor: Optional[BackgroundProcessor] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global job_manager, background_processor
    
    # Startup
    logger.info("🚀 Starting Paperless AI OCR API...")
    
    # Validate configuration
    config_errors = validate_configuration()
    if config_errors:
        logger.error("❌ Configuration errors:")
        for error in config_errors:
            logger.error(f"  - {error}")
        raise RuntimeError("Invalid configuration")
    else:
        logger.info("✅ Configuration validated successfully")
    
    # Initialize job manager
    job_manager = JobManager()
    
    # Initialize background processor with shared job manager
    background_processor = BackgroundProcessor(job_manager)
    
    # Test connections
    health = await job_manager.get_health_status()
    if not health["paperless_connected"]:
        logger.warning("Cannot connect to Paperless instance")
    if not health["ollama_connected"]:
        logger.warning("Cannot connect to Ollama instance")
    
    # Start background processor if enabled
    if settings.start_background_processor:
        logger.info("🔄 Starting background processor...")
        await background_processor.start()
    else:
        logger.info("⏸️ Background processor disabled by configuration")
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Paperless AI OCR API...")
    
    # Stop background processor
    if background_processor and background_processor.is_running:
        logger.info("🔄 Stopping background processor...")
        await background_processor.stop()
    
    if job_manager:
        await job_manager.shutdown()
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Paperless AI OCR",
    description="AI-powered OCR and summarization service for Paperless-NGX documents",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_job_manager() -> JobManager:
    """Dependency to get the job manager instance."""
    if job_manager is None:
        raise HTTPException(status_code=500, detail="Job manager not initialized")
    return job_manager


class JobCreateResponse(BaseModel):
    """Response model for job creation."""
    success: bool
    job_id: Optional[str] = None
    message: str


class JobListResponse(BaseModel):
    """Response model for job list."""
    jobs: List[JobResponse]
    total_count: int


class JobActionResponse(BaseModel):
    """Response model for job actions (cancel, remove)."""
    success: bool
    message: str


# Health check endpoint
@app.get("/health", response_model=HealthStatus)
async def health_check(manager: JobManager = Depends(get_job_manager)):
    """
    Get application health status.
    
    Returns:
        Health status including service connectivity and job statistics.
    """
    try:
        health_data = await manager.get_health_status()
        return HealthStatus(**health_data)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")


# Job management endpoints
@app.post("/jobs", response_model=JobCreateResponse)
async def create_job(
    request: JobCreateRequest,
    manager: JobManager = Depends(get_job_manager)
):
    """
    Create a new document processing job.
    
    Args:
        request: Job creation request containing document ID or auto-discovery settings.
        
    Returns:
        Job creation response with job ID if successful.
    """
    try:
        job = await manager.create_job(
            document_id=request.document_id,
            auto_discover=request.auto_discover
        )
        
        if job is None:
            return JobCreateResponse(
                success=False,
                message="Failed to create job - no eligible documents found or document not found"
            )
        
        return JobCreateResponse(
            success=True,
            job_id=job.job_id,
            message=f"Created job for document {job.document_id}"
        )
    
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        return JobCreateResponse(
            success=False,
            message=f"Failed to create job: {str(e)}"
        )


@app.get("/jobs", response_model=JobListResponse)
async def list_jobs(manager: JobManager = Depends(get_job_manager)):
    """
    List all processing jobs.
    
    Returns:
        List of all jobs with their current status.
    """
    try:
        jobs = await manager.list_jobs()
        job_responses = [JobResponse.from_processing_job(job) for job in jobs]
        
        return JobListResponse(
            jobs=job_responses,
            total_count=len(job_responses)
        )
    
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail="Failed to list jobs")


@app.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager)
):
    """
    Get details of a specific job.
    
    Args:
        job_id: The job ID to retrieve (matches document_id).
        
    Returns:
        Job details including status, progress, and timing information.
    """
    try:
        job = await manager.get_job(job_id)
        
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobResponse.from_processing_job(job)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get job")


@app.get("/jobs/document/{document_id}", response_model=JobResponse)
async def get_job_by_document_id(
    document_id: int,
    manager: JobManager = Depends(get_job_manager)
):
    """
    Get details of a job by document ID (convenience endpoint).
    
    Args:
        document_id: The document ID to retrieve job for.
        
    Returns:
        Job details including status, progress, and timing information.
    """
    try:
        job = await manager.get_job_by_document_id(document_id)
        
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found for document")
        
        return JobResponse.from_processing_job(job)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job for document {document_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get job")


@app.post("/jobs/{job_id}/cancel", response_model=JobActionResponse)
async def cancel_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager)
):
    """
    Cancel a running job.
    
    Args:
        job_id: The job ID to cancel.
        
    Returns:
        Action response indicating success or failure.
    """
    try:
        success = await manager.cancel_job(job_id)
        
        if success:
            return JobActionResponse(
                success=True,
                message=f"Job {job_id} cancelled successfully"
            )
        else:
            return JobActionResponse(
                success=False,
                message=f"Failed to cancel job {job_id} - job not found or cannot be cancelled"
            )
    
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        return JobActionResponse(
            success=False,
            message=f"Failed to cancel job: {str(e)}"
        )


@app.delete("/jobs/{job_id}", response_model=JobActionResponse)
async def remove_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager)
):
    """
    Remove a completed job.
    
    Args:
        job_id: The job ID to remove.
        
    Returns:
        Action response indicating success or failure.
    """
    try:
        success = await manager.remove_job(job_id)
        
        if success:
            return JobActionResponse(
                success=True,
                message=f"Job {job_id} removed successfully"
            )
        else:
            return JobActionResponse(
                success=False,
                message=f"Failed to remove job {job_id} - job not found or cannot be removed"
            )
    
    except Exception as e:
        logger.error(f"Error removing job {job_id}: {e}")
        return JobActionResponse(
            success=False,
            message=f"Failed to remove job: {str(e)}"
        )


# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint providing basic application information.
    
    Returns:
        Application welcome message and basic information.
    """
    return {
        "message": "Paperless AI OCR Service",
        "version": "1.0.0",
        "description": "AI-powered OCR and summarization for Paperless-NGX documents",
        "endpoints": {
            "health": "/health",
            "jobs": "/jobs",
            "create_job": "POST /jobs",
            "get_job": "/jobs/{job_id}",
            "get_job_by_document": "/jobs/document/{document_id}",
            "cancel_job": "POST /jobs/{job_id}/cancel",
            "remove_job": "DELETE /jobs/{job_id}"
        },
        "note": "job_id matches document_id for easy tracking"
    }


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Background Processor Endpoints
@app.get("/processor/status", response_model=ProcessorStatusResponse)
async def get_processor_status():
    """Get the current status of the background processor."""
    try:
        if background_processor is None:
            raise HTTPException(status_code=500, detail="Background processor not initialized")
        
        status = background_processor.get_status()
        return ProcessorStatusResponse(**status)
    
    except Exception as e:
        logger.error(f"Error getting processor status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/processor/start")
async def start_processor():
    """Start the background processor."""
    try:
        if background_processor is None:
            raise HTTPException(status_code=500, detail="Background processor not initialized")
        
        if background_processor.is_running:
            return {"message": "Background processor is already running"}
        
        await background_processor.start()
        return {"message": "Background processor started successfully"}
    
    except Exception as e:
        logger.error(f"Error starting processor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/processor/stop")
async def stop_processor():
    """Stop the background processor."""
    try:
        if background_processor is None:
            raise HTTPException(status_code=500, detail="Background processor not initialized")
        
        if not background_processor.is_running:
            return {"message": "Background processor is not running"}
        
        await background_processor.stop()
        return {"message": "Background processor stopped successfully"}
    
    except Exception as e:
        logger.error(f"Error stopping processor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting server on {settings.api_host}:{settings.api_port}")
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info"
    ) 