"""
Background processor service for automated document processing.
Continuously processes documents without the 'summarized' custom field.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional
from services.job_manager import JobManager
from services.paperless_client import PaperlessClient
from config import settings

logger = logging.getLogger(__name__)


class BackgroundProcessor:
    """Background service that automatically processes unprocessed documents."""
    
    def __init__(self, job_manager: "JobManager" = None):
        """Initialize the background processor.
        
        Args:
            job_manager: Shared JobManager instance. If None, creates a new one.
        """
        if job_manager is not None:
            self.job_manager = job_manager
        else:
            # Import here to avoid circular imports
            from services.job_manager import JobManager
            self.job_manager = JobManager()
        
        self.paperless_client = PaperlessClient()
        self.is_running = False
        self.is_processing = False
        self._stop_event = asyncio.Event()
        
    async def start(self):
        """Start the background processor."""
        if self.is_running:
            logger.warning("Background processor is already running")
            return
            
        logger.info("Starting background processor...")
        logger.info(f"Configuration:")
        logger.info(f"  - Job interval: {settings.job_interval_seconds} seconds")
        logger.info(f"  - Retry interval: {settings.processor_retry_minutes} minutes")
        logger.info(f"  - Auto-start enabled: {settings.start_background_processor}")
        
        self.is_running = True
        self._stop_event.clear()
        
        # Start the main processing loop
        asyncio.create_task(self._processing_loop())
        logger.info("✅ Background processor started successfully")
    
    async def stop(self):
        """Stop the background processor."""
        if not self.is_running:
            logger.warning("Background processor is not running")
            return
            
        logger.info("Stopping background processor...")
        self.is_running = False
        self._stop_event.set()
        
        # Wait for current processing to finish
        while self.is_processing:
            logger.info("Waiting for current processing to complete...")
            await asyncio.sleep(1)
        
        logger.info("✅ Background processor stopped")
    
    async def _processing_loop(self):
        """Main processing loop that runs continuously."""
        retry_interval_seconds = settings.processor_retry_minutes * 60
        
        while self.is_running:
            try:
                await self._process_batch()
                
                # Wait for the retry interval before checking again
                logger.info(f"No more documents to process. Waiting {settings.processor_retry_minutes} minutes before next check...")
                
                # Use event.wait with timeout to allow graceful shutdown
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=retry_interval_seconds)
                    # If we get here, stop was requested
                    break
                except asyncio.TimeoutError:
                    # Timeout means we should continue processing
                    continue
                    
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                logger.info(f"Retrying in {settings.processor_retry_minutes} minutes...")
                
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=retry_interval_seconds)
                    break
                except asyncio.TimeoutError:
                    continue
    
    async def _process_batch(self):
        """Process a batch of documents without the summarized field."""
        if self.is_processing:
            logger.info("Processing is already running, skipping this cycle")
            return
        
        self.is_processing = True
        processed_count = 0
        
        try:
            logger.info(f"🔍 Checking for documents without '{settings.summarized_field}' custom field...")
            
            # Query documents without the summarized custom field
            documents = await self._get_unprocessed_documents()
            
            if not documents:
                logger.info("✅ No unprocessed documents found")
                return
            
            logger.info(f"📋 Found {len(documents)} unprocessed documents")
            
            # Process each document
            for document in documents:
                if not self.is_running:
                    logger.info("Stop requested, breaking out of processing loop")
                    break
                
                logger.info(f"🚀 Processing document: {document.title} (ID: {document.id})")
                
                # Create and execute job
                success = await self._process_document(document.id)
                
                if success:
                    processed_count += 1
                    logger.info(f"✅ Successfully processed document {document.id}")
                else:
                    logger.error(f"❌ Failed to process document {document.id}")
                
                # Wait between jobs (unless stopping)
                if self.is_running and settings.job_interval_seconds > 0:
                    logger.info(f"⏱️ Waiting {settings.job_interval_seconds} seconds before next job...")
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=settings.job_interval_seconds)
                        # If we get here, stop was requested
                        break
                    except asyncio.TimeoutError:
                        # Timeout means we should continue
                        pass
            
            logger.info(f"📊 Batch complete: Successfully processed {processed_count}/{len(documents)} documents")
            
        finally:
            self.is_processing = False
    
    async def _get_unprocessed_documents(self):
        """Get documents that don't have the configured summarized custom field set to true."""
        try:
            # First, ensure we have the custom field
            field_id = await self.paperless_client.get_summarized_field_id()
            if field_id is None:
                logger.error(f"Cannot get '{settings.summarized_field}' custom field ID")
                return []
            
            async with self.paperless_client._get_session() as session:
                # Query for all documents, then filter based on custom field
                params = {
                    "page_size": 100,
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
                                from models import PaperlessDocument
                                document = PaperlessDocument(
                                    id=doc_data["id"],
                                    title=doc_data["title"],
                                    content=doc_data.get("content"),
                                    tags=doc_data.get("tags", []),
                                    created=doc_data["created"],
                                    modified=doc_data["modified"],
                                    original_file_name=doc_data["original_file_name"]
                                )
                                unprocessed_documents.append(document)
                        
                        logger.info(f"Found {len(unprocessed_documents)} documents without '{settings.summarized_field}' custom field")
                        return unprocessed_documents
                    else:
                        logger.error(f"Failed to get documents: {response.status}")
                        return []
            
        except Exception as e:
            logger.error(f"Error getting unprocessed documents: {e}")
            return []
    
    async def _process_document(self, document_id: int) -> bool:
        """Process a single document through the full pipeline."""
        try:
            # Create a job for this document
            job = await self.job_manager.create_job(
                document_id=document_id,
                auto_discover=False
            )
            
            if job is None:
                logger.error(f"Failed to create job for document {document_id}")
                return False
            
            logger.info(f"📊 Starting job monitoring for document {document_id} (Job ID: {job.job_id})")
            
            last_status_check = 0
            last_status = None
            last_progress_message = None
            
            # Wait for the job to complete with detailed status updates
            while job.status.value in ["pending", "downloading", "processing", "uploading"]:
                current_time = asyncio.get_event_loop().time()
                
                # Update job status from manager
                updated_job = await self.job_manager.get_job(job.job_id)
                if updated_job:
                    job = updated_job
                
                # Check if we should log a status update (every 30 seconds or on status change)
                should_log_status = (
                    current_time - last_status_check >= 30.0 or  # Every 30 seconds
                    job.status != last_status or                 # Status changed
                    job.progress_message != last_progress_message # Progress message changed
                )
                
                if should_log_status:
                    # Get status emoji and description
                    status_emoji = {
                        "pending": "⏳",
                        "downloading": "⬇️", 
                        "processing": "🤖",
                        "uploading": "⬆️",
                        "completed": "✅",
                        "failed": "❌",
                        "cancelled": "🚫"
                    }.get(job.status.value, "❓")
                    
                    # Calculate elapsed time
                    elapsed = job.get_duration_seconds()
                    elapsed_str = f" ({elapsed}s elapsed)" if elapsed else ""
                    
                    # Log the status update
                    logger.info(f"{status_emoji} Document {document_id} - {job.status.value.upper()}: {job.get_status_description()}{elapsed_str}")
                    
                    # Log progress message if available
                    if job.progress_message and job.progress_message != last_progress_message:
                        logger.info(f"   📝 {job.progress_message}")
                    
                    # Update tracking variables
                    last_status_check = current_time
                    last_status = job.status
                    last_progress_message = job.progress_message
                
                # Check if processor should stop
                if not self.is_running:
                    logger.info(f"🛑 Stopping requested - cancelling job for document {document_id}")
                    await self.job_manager.cancel_job(job.job_id)
                    return False
                
                # Wait before next check
                await asyncio.sleep(2)
            
            # Final status check and logging
            final_job = await self.job_manager.get_job(job.job_id)
            if final_job:
                job = final_job
            
            # Log final result
            duration = job.get_duration_seconds()
            duration_str = f" (took {duration}s)" if duration else ""
            
            success = job.status.value == "completed"
            if success:
                logger.info(f"🎉 Document {document_id} completed successfully{duration_str}")
                if job.ocr_path and job.summary_path:
                    logger.info(f"   📄 Files created: OCR={job.ocr_path}, Summary={job.summary_path}")
            else:
                logger.error(f"💥 Document {document_id} failed{duration_str}")
                if job.error_message:
                    logger.error(f"   ❌ Error: {job.error_message}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error processing document {document_id}: {e}")
            return False
    
    def get_status(self) -> dict:
        """Get the current status of the background processor."""
        return {
            "is_running": self.is_running,
            "is_processing": self.is_processing,
            "job_interval_seconds": settings.job_interval_seconds,
            "processor_retry_minutes": settings.processor_retry_minutes,
            "start_time": datetime.utcnow().isoformat() if self.is_running else None
        }


# Global background processor instance (will be initialized in main.py with job manager)
background_processor = None 