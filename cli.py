#!/usr/bin/env python3
"""
Command-line interface for the Paperless AI OCR application.
Provides direct access to document processing functionality.
"""

import argparse
import asyncio
import logging
import sys
from typing import Optional
import time

from config import settings, validate_configuration
from services.job_manager import JobManager
from models import JobStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def process_document(document_id: Optional[int] = None, auto_discover: bool = True) -> bool:
    """
    Process a document or auto-discover one to process.
    
    Args:
        document_id: Specific document ID to process, or None for auto-discovery.
        auto_discover: Whether to auto-discover documents without summarized custom field.
        
    Returns:
        True if processing was successful, False otherwise.
    """
    job_manager = JobManager()
    
    try:
        # Create and start the job
        print(f"Creating processing job...")
        if document_id:
            print(f"  Target document ID: {document_id}")
        else:
            print(f"  Auto-discovering next document without '{settings.summarized_field}' custom field")
        
        job = await job_manager.create_job(
            document_id=document_id,
            auto_discover=auto_discover
        )
        
        if job is None:
            print("❌ Failed to create job - no eligible documents found or document not found")
            return False
        
        print(f"✅ Created job {job.job_id} for document {job.document_id} (job_id matches document_id)")
        
        # Monitor job progress
        print("\n📊 Monitoring job progress...")
        last_status = None
        last_message = None
        last_status_output = 0
        
        while True:
            current_job = await job_manager.get_job(job.job_id)
            if current_job is None:
                print("❌ Job disappeared unexpectedly")
                return False
            
            current_time = time.time()
            
            # Check if we should print status update (on change or every 30 seconds)
            should_print_status = (
                current_job.status != last_status or 
                current_job.progress_message != last_message or
                current_time - last_status_output >= 30.0
            )
            
            # Print status updates
            if should_print_status:
                status_emoji = {
                    JobStatus.PENDING: "⏳",
                    JobStatus.DOWNLOADING: "⬇️",
                    JobStatus.PROCESSING: "🤖",
                    JobStatus.UPLOADING: "⬆️",
                    JobStatus.COMPLETED: "✅",
                    JobStatus.FAILED: "❌",
                    JobStatus.CANCELLED: "🚫"
                }.get(current_job.status, "❓")
                
                # Add elapsed time to status
                elapsed = current_job.get_duration_seconds()
                elapsed_str = f" ({elapsed}s elapsed)" if elapsed else ""
                
                print(f"{status_emoji} {current_job.status.value.upper()}: {current_job.get_status_description()}{elapsed_str}")
                if current_job.progress_message:
                    print(f"   📝 {current_job.progress_message}")
                
                last_status = current_job.status
                last_message = current_job.progress_message
                last_status_output = current_time
            
            # Check if job is complete
            if current_job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                break
            
            # Wait before checking again
            await asyncio.sleep(2)
        
        # Final status
        duration = current_job.get_duration_seconds()
        duration_str = f" (took {duration}s)" if duration else ""
        
        if current_job.status == JobStatus.COMPLETED:
            print(f"\n🎉 Job completed successfully{duration_str}")
            print(f"   OCR and summary have been added to document {current_job.document_id}")
            print(f"   Files saved: {current_job.ocr_path}, {current_job.summary_path}")
            return True
        else:
            print(f"\n💥 Job {current_job.status.lower()}{duration_str}")
            if current_job.error_message:
                print(f"   Error: {current_job.error_message}")
            return False
    
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        print(f"❌ Processing failed: {e}")
        return False
    
    finally:
        await job_manager.shutdown()


async def show_status() -> bool:
    """
    Show the current application status.
    
    Returns:
        True if status check was successful, False otherwise.
    """
    job_manager = JobManager()
    
    try:
        print("🔍 Checking application status...\n")
        
        # Get health status
        health = await job_manager.get_health_status()
        
        # Display service connectivity
        print("📡 Service Connectivity:")
        print(f"   Paperless-NGX: {'✅ Connected' if health['paperless_connected'] else '❌ Disconnected'}")
        print(f"   Ollama:        {'✅ Connected' if health['ollama_connected'] else '❌ Disconnected'}")
        
        # Display configuration
        print(f"\n⚙️  Configuration:")
        print(f"   Paperless URL:    {settings.paperless_base_url}")
        print(f"   Ollama URL:       {settings.ollama_base_url}")
        print(f"   Ollama Model:     {settings.ollama_model}")
        print(f"   Summarized Field: {settings.summarized_field}")
        print(f"   Data Directory:   {settings.data_dir}")
        
        # Display job statistics
        print(f"\n📊 Job Statistics:")
        print(f"   Active Jobs:      {health['active_jobs']}")
        print(f"   Total Jobs:       {health['total_jobs']}")
        if health['current_active_job']:
            print(f"   Current Job:      {health['current_active_job']}")
        
        # List recent jobs
        jobs = await job_manager.list_jobs()
        if jobs:
            print(f"\n📋 Recent Jobs:")
            for job in sorted(jobs, key=lambda x: x.created_at, reverse=True)[:5]:
                duration = job.get_duration_seconds()
                duration_str = f" ({duration}s)" if duration else ""
                print(f"   Job {job.job_id} - Doc {job.document_id} - {job.status.upper()}{duration_str}")
        
        return health['paperless_connected'] and health['ollama_connected']
    
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        print(f"❌ Status check failed: {e}")
        return False
    
    finally:
        await job_manager.shutdown()


async def monitor_jobs() -> bool:
    """
    Monitor active jobs with real-time status updates every 30 seconds.
    
    Returns:
        True if monitoring completed successfully, False otherwise.
    """
    job_manager = JobManager()
    
    try:
        print("📊 Starting job monitoring (Press Ctrl+C to stop)...")
        print("Updates every 30 seconds or when status changes\n")
        
        last_update_times = {}  # Track last update time per job
        
        while True:
            try:
                # Get all jobs
                jobs = await job_manager.list_jobs()
                active_jobs = [job for job in jobs if job.status.value in ["pending", "downloading", "processing", "uploading"]]
                
                current_time = time.time()
                
                if not active_jobs:
                    print("⏸️  No active jobs found")
                    print("   Waiting 30 seconds before next check...\n")
                    await asyncio.sleep(30)
                    continue
                
                print(f"🔄 Found {len(active_jobs)} active job(s):")
                
                for job in active_jobs:
                    job_id = job.job_id
                    last_update = last_update_times.get(job_id, 0)
                    
                    # Check if we should show an update for this job
                    should_update = (
                        current_time - last_update >= 30.0 or  # Every 30 seconds
                        job_id not in last_update_times        # First time seeing this job
                    )
                    
                    if should_update:
                        # Get status emoji
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
                        
                        # Display job status
                        print(f"   {status_emoji} Job {job_id} (Doc {job.document_id}) - {job.status.value.upper()}: {job.get_status_description()}{elapsed_str}")
                        
                        # Show progress message if available
                        if job.progress_message:
                            print(f"      📝 {job.progress_message}")
                        
                        last_update_times[job_id] = current_time
                
                print()  # Empty line for spacing
                
                # Wait before next check
                await asyncio.sleep(5)  # Check more frequently for status changes
                
            except KeyboardInterrupt:
                print("\n🛑 Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error during monitoring: {e}")
                print(f"❌ Monitoring error: {e}")
                await asyncio.sleep(10)  # Wait before retrying
        
        return True
    
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
        return True
    except Exception as e:
        logger.error(f"Error in job monitoring: {e}")
        print(f"❌ Monitoring failed: {e}")
        return False
    
    finally:
        await job_manager.shutdown()


async def list_jobs() -> bool:
    """
    List all processing jobs.
    
    Returns:
        True if listing was successful, False otherwise.
    """
    job_manager = JobManager()
    
    try:
        print("📋 Listing all jobs...\n")
        
        jobs = await job_manager.list_jobs()
        
        if not jobs:
            print("No jobs found.")
            return True
        
        # Sort jobs by creation time (newest first)
        jobs_sorted = sorted(jobs, key=lambda x: x.created_at, reverse=True)
        
        print(f"{'Job ID':<12} {'Document':<10} {'Status':<12} {'Duration':<10} {'Created':<20}")
        print("-" * 70)
        
        for job in jobs_sorted:
            duration = job.get_duration_seconds()
            duration_str = f"{duration}s" if duration else "N/A"
            created_str = job.created_at.strftime("%Y-%m-%d %H:%M:%S")
            
            # Since job_id now matches document_id, just show the full job_id
            print(f"{job.job_id:<12} {job.document_id:<10} {job.status.upper():<12} {duration_str:<10} {created_str}")
            
            if job.error_message:
                print(f"             Error: {job.error_message}")
            elif job.progress_message:
                print(f"             Progress: {job.progress_message}")
        
        return True
    
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        print(f"❌ Failed to list jobs: {e}")
        return False
    
    finally:
        await job_manager.shutdown()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Paperless AI OCR - Command Line Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --status                    # Check application status
  %(prog)s --auto-discover            # Process next unprocessed document
  %(prog)s --document-id 123          # Process specific document
  %(prog)s --list-jobs                # List all jobs
  %(prog)s --monitor-jobs             # Monitor active jobs
        """
    )
    
    # Command options
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--status",
        action="store_true",
        help="Check application and service status"
    )
    action_group.add_argument(
        "--auto-discover",
        action="store_true",
        help="Auto-discover and process next document without summarized custom field"
    )
    action_group.add_argument(
        "--document-id",
        type=int,
        metavar="ID",
        help="Process specific document by ID"
    )
    action_group.add_argument(
        "--list-jobs",
        action="store_true",
        help="List all processing jobs"
    )
    action_group.add_argument(
        "--monitor-jobs",
        action="store_true",
        help="Monitor active jobs with real-time status updates"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate configuration
    print("🔧 Validating configuration...")
    config_errors = validate_configuration()
    if config_errors:
        print("❌ Configuration validation failed:")
        for error in config_errors:
            print(f"   - {error}")
        print("\nPlease check your environment variables or .env file.")
        sys.exit(1)
    
    print("✅ Configuration valid\n")
    
    # Execute the requested action
    success = False
    
    if args.status:
        success = asyncio.run(show_status())
    elif args.auto_discover:
        success = asyncio.run(process_document(auto_discover=True))
    elif args.document_id:
        success = asyncio.run(process_document(document_id=args.document_id, auto_discover=False))
    elif args.list_jobs:
        success = asyncio.run(list_jobs())
    elif args.monitor_jobs:
        success = asyncio.run(monitor_jobs())
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 