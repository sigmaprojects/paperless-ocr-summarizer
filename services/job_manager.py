"""
Job manager service for the Paperless AI OCR application.
Handles job scheduling, processing pipeline, and coordination between services.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional, List, Callable
import aiofiles

from models import ProcessingJob, JobStatus, PaperlessDocument
from services.paperless_client import PaperlessClient
from services.ollama_client import OllamaClient
from config import settings

logger = logging.getLogger(__name__)


class JobManager:
    """Manages document processing jobs and coordinates the entire pipeline."""
    
    def __init__(self):
        """Initialize the job manager."""
        self.jobs: Dict[str, ProcessingJob] = {}
        self.active_job: Optional[str] = None
        self.paperless_client = PaperlessClient()
        self.ollama_client = OllamaClient()
        self._processing_lock = asyncio.Lock()
        self._shutdown = False
        
        # Ensure data directory exists
        os.makedirs(settings.data_dir, exist_ok=True)
    
    async def create_job(
        self, 
        document_id: Optional[int] = None, 
        auto_discover: bool = True
    ) -> Optional[ProcessingJob]:
        """
        Create a new processing job.
        
        Args:
            document_id: Specific document ID to process, or None for auto-discovery.
            auto_discover: Whether to auto-discover documents without summarized custom field.
            
        Returns:
            Created job if successful, None otherwise.
        """
        try:
            # If document_id is provided, validate it exists
            if document_id is not None:
                document = await self.paperless_client.get_document_by_id(document_id)
                if document is None:
                    logger.error(f"Document {document_id} not found")
                    return None
                target_document_id = document_id
            
            # Auto-discover mode: find a document without summarized custom field
            elif auto_discover:
                documents = await self._get_unprocessed_documents(limit=1)
                if not documents:
                    logger.info("No documents found without summarized custom field")
                    return None
                target_document_id = documents[0].id
            
            else:
                logger.error("Either document_id must be provided or auto_discover must be True")
                return None
            
            # Check if there's already a job for this document
            job_id = str(target_document_id)
            existing_job = self.jobs.get(job_id)
            if existing_job and existing_job.status not in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                logger.warning(f"Job already exists for document {target_document_id}")
                return existing_job
            
            # Create new job - use document_id as job_id for easy tracking
            job = ProcessingJob(
                job_id=job_id,
                document_id=target_document_id,
                status=JobStatus.PENDING
            )
            
            # Set up file paths
            job.pdf_path = os.path.join(settings.data_dir, f"{target_document_id}.pdf")
            job.ocr_path = os.path.join(settings.data_dir, f"{target_document_id}_ocr.txt")
            job.summary_path = os.path.join(settings.data_dir, f"{target_document_id}_summary.txt")
            
            self.jobs[job_id] = job
            logger.info(f"Created job {job_id} for document {target_document_id}")
            
            # Start processing the job
            asyncio.create_task(self._process_job(job_id))
            
            return job
        
        except Exception as e:
            logger.error(f"Error creating job: {e}")
            return None
    

    
    async def get_job(self, job_id: str) -> Optional[ProcessingJob]:
        """
        Get a job by ID.
        
        Args:
            job_id: The job ID to retrieve.
            
        Returns:
            Job if found, None otherwise.
        """
        return self.jobs.get(job_id)
    
    async def get_job_by_document_id(self, document_id: int) -> Optional[ProcessingJob]:
        """
        Get a job by document ID (convenience method).
        
        Args:
            document_id: The document ID to retrieve job for.
            
        Returns:
            Job if found, None otherwise.
        """
        return self.jobs.get(str(document_id))
    
    async def list_jobs(self) -> List[ProcessingJob]:
        """
        List all jobs.
        
        Returns:
            List of all jobs.
        """
        return list(self.jobs.values())
    
    async def _get_unprocessed_documents(self, limit: int = 10) -> List[PaperlessDocument]:
        """
        Get documents that don't have the summarized custom field set to true.
        
        Args:
            limit: Maximum number of documents to return.
            
        Returns:
            List of documents without the summarized custom field set.
        """
        try:
            # First, ensure we have the custom field
            field_id = await self.paperless_client.get_summarized_field_id()
            if field_id is None:
                logger.error(f"Cannot get '{settings.summarized_field}' custom field ID")
                return []
            
            async with self.paperless_client._get_session() as session:
                # Query for all documents first, then filter based on custom field
                params = {
                    "page_size": limit * 3,  # Get more to account for filtering
                    "ordering": "-created"
                }
                
                async with session.get(f"{self.paperless_client.base_url}/api/documents/", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        unprocessed_documents = []
                        
                        for doc_data in data.get("results", []):
                            # Check if this document has the summarized custom field set to true
                            custom_fields = doc_data.get("custom_fields", [])
                            is_processed = False
                            
                            for field in custom_fields:
                                if field.get("field") == field_id and field.get("value") is True:
                                    is_processed = True
                                    break
                            
                            # If not processed, add to our list
                            if not is_processed:
                                document = PaperlessDocument(
                                    id=doc_data["id"],
                                    title=doc_data["title"],
                                    content=doc_data.get("content"),
                                    tags=doc_data.get("tags", []),
                                    created=doc_data["created"],
                                    modified=doc_data["modified"],
                                    original_file_name=doc_data.get("original_file_name") or f"document_{doc_data['id']}.pdf"
                                )
                                unprocessed_documents.append(document)
                                
                                # Stop if we have enough
                                if len(unprocessed_documents) >= limit:
                                    break
                        
                        logger.info(f"Found {len(unprocessed_documents)} documents without '{settings.summarized_field}' custom field")
                        return unprocessed_documents
                    else:
                        logger.error(f"Failed to get documents: {response.status}")
                        return []
        
        except Exception as e:
            logger.error(f"Error getting unprocessed documents: {e}")
            return []
    
    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a job.
        
        Args:
            job_id: The job ID to cancel.
            
        Returns:
            True if job was cancelled, False otherwise.
        """
        job = self.jobs.get(job_id)
        if job is None:
            logger.warning(f"Job {job_id} not found for cancellation")
            return False
        
        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            logger.warning(f"Job {job_id} cannot be cancelled (status: {job.status})")
            return False
        
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()
        job.error_message = "Cancelled by user"
        
        # Clean up files
        await self._cleanup_job_files(job)
        
        logger.info(f"Cancelled job {job_id}")
        return True
    
    async def remove_job(self, job_id: str) -> bool:
        """
        Remove a completed job.
        
        Args:
            job_id: The job ID to remove.
            
        Returns:
            True if job was removed, False otherwise.
        """
        job = self.jobs.get(job_id)
        if job is None:
            logger.warning(f"Job {job_id} not found for removal")
            return False
        
        # Only allow removal of completed, failed, or cancelled jobs
        if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            logger.warning(f"Job {job_id} cannot be removed (status: {job.status})")
            return False
        
        # Clean up files
        await self._cleanup_job_files(job)
        
        # Remove from jobs dictionary
        del self.jobs[job_id]
        
        logger.info(f"Removed job {job_id}")
        return True
    
    async def _process_job(self, job_id: str):
        """
        Process a job through the entire pipeline.
        
        Args:
            job_id: The job ID to process.
        """
        # Ensure only one job processes at a time
        async with self._processing_lock:
            if self._shutdown:
                return
            
            self.active_job = job_id
            job = self.jobs.get(job_id)
            
            if job is None:
                logger.error(f"Job {job_id} not found for processing")
                return
            
            try:
                await self._execute_job_pipeline(job)
            except Exception as e:
                logger.error(f"Error processing job {job_id}: {e}")
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
            finally:
                self.active_job = None
    
    async def _execute_job_pipeline(self, job: ProcessingJob):
        """
        Execute the complete job processing pipeline.
        
        Args:
            job: The job to process.
        """
        def update_progress(message: str):
            """Update job progress message."""
            job.progress_message = message
            logger.info(f"Job {job.job_id}: {message}")
        
        try:
            # Mark job as started
            job.started_at = datetime.utcnow()
            job.status = JobStatus.DOWNLOADING
            update_progress("Starting document processing...")
            
            # Step 1: Download PDF from Paperless
            update_progress("Downloading PDF from Paperless...")
            success = await self.paperless_client.download_document_pdf(
                job.document_id, 
                job.pdf_path
            )
            
            if not success:
                raise Exception("Failed to download PDF from Paperless")
            
            # Step 2: Process with Ollama
            job.status = JobStatus.PROCESSING
            update_progress("Processing document with AI...")
            
            ocr_content, summary_content = await self.ollama_client.process_pdf_with_vision(
                job.pdf_path, 
                progress_callback=update_progress
            )
            
            if ocr_content is None:
                raise Exception("Failed to extract text from document")
            
            # Store results in job
            job.ocr_content = ocr_content
            job.summary_content = summary_content or "Summary generation failed"
            
            # Step 3: Save to text files
            update_progress("Saving results to text files...")
            await self._save_results_to_files(job)
            
            # Step 4: Upload results to Paperless
            job.status = JobStatus.UPLOADING
            update_progress("Uploading results to Paperless...")
            
            # Create note content with summary first, then OCR
            note_content = f"**AI Generated Summary:**\n\n{job.summary_content}\n\n"
            note_content += f"**OCR Extracted Text:**\n\n{job.ocr_content}"
            
            # Add note to document
            note_success = await self.paperless_client.add_note_to_document(
                job.document_id,
                note_content
            )
            
            if not note_success:
                logger.warning(f"Failed to add note to document {job.document_id}")
            
            # Set custom field to mark document as summarized
            field_success = await self.paperless_client.set_summarized_field(
                job.document_id, 
                value=True
            )
            if not field_success:
                logger.warning(f"Failed to set '{settings.summarized_field}' custom field for document {job.document_id}")
            
            # Mark job as completed
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            update_progress("Document processing completed successfully")
            
            # Clean up PDF file if DEBUG is disabled
            if not settings.debug:
                update_progress("Cleaning up temporary PDF file...")
                await self._cleanup_pdf_file(job)
            
            logger.info(f"Successfully completed job {job.job_id} for document {job.document_id}")
        
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            update_progress(f"Job failed: {str(e)}")
            logger.error(f"Job {job.job_id} failed: {e}")
            raise
    
    async def _save_results_to_files(self, job: ProcessingJob):
        """
        Save OCR and summary results to text files.
        Only saves files when DEBUG mode is enabled.
        
        Args:
            job: The job containing results to save.
        """
        if not settings.debug:
            logger.info("DEBUG mode disabled - skipping text file saving")
            return
        
        try:
            # Save OCR content
            if job.ocr_content and job.ocr_path:
                async with aiofiles.open(job.ocr_path, "w", encoding="utf-8") as f:
                    await f.write(job.ocr_content)
                logger.info(f"Saved OCR content to {job.ocr_path}")
            
            # Save summary content
            if job.summary_content and job.summary_path:
                async with aiofiles.open(job.summary_path, "w", encoding="utf-8") as f:
                    await f.write(job.summary_content)
                logger.info(f"Saved summary content to {job.summary_path}")
        
        except Exception as e:
            logger.error(f"Error saving results to files: {e}")
            raise
    
    async def _cleanup_pdf_file(self, job: ProcessingJob):
        """
        Clean up only the PDF file for a job.
        
        Args:
            job: The job to clean up PDF file for.
        """
        if job.pdf_path and os.path.exists(job.pdf_path):
            try:
                os.remove(job.pdf_path)
                logger.info(f"Cleaned up PDF file: {job.pdf_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up PDF file {job.pdf_path}: {e}")
    
    async def _cleanup_job_files(self, job: ProcessingJob):
        """
        Clean up temporary files for a job.
        Respects DEBUG mode settings for txt files.
        
        Args:
            job: The job to clean up files for.
        """
        # Always clean up PDF file
        if job.pdf_path and os.path.exists(job.pdf_path):
            try:
                os.remove(job.pdf_path)
                logger.info(f"Cleaned up file: {job.pdf_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up file {job.pdf_path}: {e}")
        
        # Only clean up txt files if DEBUG is disabled
        # (If DEBUG is enabled, we want to keep them for inspection)
        if not settings.debug:
            txt_files = [job.ocr_path, job.summary_path]
            
            for file_path in txt_files:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Cleaned up file: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to clean up file {file_path}: {e}")
    
    async def get_health_status(self) -> Dict[str, any]:
        """
        Get the current health status of the job manager.
        
        Returns:
            Dictionary containing health status information.
        """
        # Test connections
        paperless_connected = await self.paperless_client.test_connection()
        ollama_connected = await self.ollama_client.test_connection()
        
        # Count jobs by status
        active_jobs = len([j for j in self.jobs.values() 
                          if j.status not in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]])
        
        return {
            "status": "healthy" if paperless_connected and ollama_connected else "degraded",
            "paperless_connected": paperless_connected,
            "ollama_connected": ollama_connected,
            "active_jobs": active_jobs,
            "total_jobs": len(self.jobs),
            "current_active_job": self.active_job,
            "errors": []
        }
    
    async def shutdown(self):
        """Gracefully shutdown the job manager."""
        self._shutdown = True
        
        # Cancel any active jobs
        if self.active_job:
            await self.cancel_job(self.active_job)
        
        logger.info("Job manager shutdown complete") 