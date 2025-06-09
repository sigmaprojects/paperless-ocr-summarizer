"""
Paperless-NGX API client service.
Handles communication with the Paperless-NGX instance.
"""

import base64
import logging
from typing import Optional, List, Dict, Any
import aiohttp
import aiofiles
from models import PaperlessDocument
from config import settings

logger = logging.getLogger(__name__)


class PaperlessClient:
    """Client for interacting with Paperless-NGX API."""
    
    def __init__(self):
        """Initialize the Paperless client."""
        self.base_url = settings.paperless_base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {settings.paperless_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Add X-Requested-With header to indicate this is an AJAX/API request
            "X-Requested-With": "XMLHttpRequest"
        }
        self._summarized_field_id: Optional[int] = None
    
    def _get_session(self) -> aiohttp.ClientSession:
        """Get an aiohttp session with proper headers."""
        # Create a connector that doesn't validate SSL (if needed for development)
        # connector = aiohttp.TCPConnector(ssl=False)
        return aiohttp.ClientSession(headers=self.headers)
    
    async def test_connection(self) -> bool:
        """
        Test connection to Paperless instance.
        
        Returns:
            True if connection is successful, False otherwise.
        """
        try:
            async with self._get_session() as session:
                async with session.get(f"{self.base_url}/api/documents/") as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Failed to connect to Paperless: {e}")
            return False
    


    async def get_document_by_id(self, document_id: int) -> Optional[PaperlessDocument]:
        """
        Get a specific document by ID.
        
        Args:
            document_id: The document ID to retrieve.
            
        Returns:
            Document if found, None otherwise.
        """
        try:
            async with self._get_session() as session:
                async with session.get(f"{self.base_url}/api/documents/{document_id}/") as response:
                    if response.status == 200:
                        doc_data = await response.json()
                        return PaperlessDocument(
                            id=doc_data["id"],
                            title=doc_data["title"],
                            content=doc_data.get("content"),
                            tags=doc_data.get("tags", []),
                            created=doc_data["created"],
                            modified=doc_data["modified"],
                            original_file_name=doc_data.get("original_file_name") or f"document_{doc_data['id']}.pdf"
                        )
                    else:
                        logger.error(f"Document {document_id} not found: {response.status}")
                        return None
        
        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return None
    
    async def download_document_pdf(self, document_id: int, output_path: str) -> bool:
        """
        Download a document's PDF file.
        
        Args:
            document_id: The document ID to download.
            output_path: Where to save the PDF file.
            
        Returns:
            True if download successful, False otherwise.
        """
        try:
            async with self._get_session() as session:
                download_url = f"{self.base_url}/api/documents/{document_id}/download/"
                async with session.get(download_url) as response:
                    if response.status == 200:
                        async with aiofiles.open(output_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                        
                        logger.info(f"Downloaded PDF for document {document_id} to {output_path}")
                        return True
                    else:
                        logger.error(f"Failed to download PDF for document {document_id}: {response.status}")
                        return False
        
        except Exception as e:
            logger.error(f"Error downloading PDF for document {document_id}: {e}")
            return False
    
    async def add_note_to_document(self, document_id: int, note_content: str) -> bool:
        """
        Add a note to a document.
        
        Args:
            document_id: The document ID to add note to.
            note_content: The note content to add.
            
        Returns:
            True if note added successfully, False otherwise.
        """
        try:
            async with self._get_session() as session:
                note_data = {"note": note_content}
                
                # Use the document-specific notes endpoint (this works reliably)
                async with session.post(f"{self.base_url}/api/documents/{document_id}/notes/", json=note_data) as response:
                    if response.status in [200, 201]:
                        logger.info(f"Added note to document {document_id}")
                        return True
                    else:
                        logger.error(f"Failed to add note to document {document_id}: {response.status}")
                        logger.error(f"Response: {await response.text()}")
                        return False
        
        except Exception as e:
            logger.error(f"Error adding note to document {document_id}: {e}")
            return False
    
    async def get_summarized_field_id(self) -> Optional[int]:
        """
        Get or create the configured summarized custom field.
        
        Returns:
            Field ID if successful, None otherwise.
        """
        if self._summarized_field_id is not None:
            return self._summarized_field_id
        
        field_name = settings.summarized_field
        
        try:
            async with self._get_session() as session:
                # First, try to find existing custom field
                async with session.get(f"{self.base_url}/api/custom_fields/") as response:
                    if response.status == 200:
                        data = await response.json()
                        for field in data.get("results", []):
                            if field["name"] == field_name:
                                self._summarized_field_id = field["id"]
                                logger.info(f"Found existing custom field '{field_name}' with ID: {self._summarized_field_id}")
                                return self._summarized_field_id
                
                # If not found, create the custom field
                create_data = {
                    "name": field_name,
                    "data_type": "boolean"  # Boolean field for true/false
                }
                
                async with session.post(f"{self.base_url}/api/custom_fields/", json=create_data) as response:
                    if response.status == 201:
                        field_data = await response.json()
                        self._summarized_field_id = field_data["id"]
                        logger.info(f"Created custom field '{field_name}' with ID: {self._summarized_field_id}")
                        return self._summarized_field_id
                    else:
                        logger.error(f"Failed to create custom field '{field_name}': {response.status}")
                        logger.error(f"Response: {await response.text()}")
                        return None
        
        except Exception as e:
            logger.error(f"Error getting/creating custom field '{field_name}': {e}")
            return None
    
    async def set_summarized_field(self, document_id: int, value: bool = True) -> bool:
        """
        Set the configured summarized custom field value for a document.
        
        Args:
            document_id: The document ID to update.
            value: The boolean value to set (default: True).
            
        Returns:
            True if field set successfully, False otherwise.
        """
        field_id = await self.get_summarized_field_id()
        if field_id is None:
            logger.error("Cannot set custom field - field ID is None")
            return False
        
        try:
            async with self._get_session() as session:
                # Update document with custom field value
                update_data = {
                    "custom_fields": [
                        {
                            "field": field_id,
                            "value": value
                        }
                    ]
                }
                
                async with session.patch(f"{self.base_url}/api/documents/{document_id}/", json=update_data) as response:
                    if response.status == 200:
                        logger.info(f"Set custom field '{settings.summarized_field}' to {value} for document {document_id}")
                        return True
                    else:
                        logger.error(f"Failed to set custom field for document {document_id}: {response.status}")
                        logger.error(f"Response: {await response.text()}")
                        return False
        
        except Exception as e:
            logger.error(f"Error setting custom field for document {document_id}: {e}")
            return False

 