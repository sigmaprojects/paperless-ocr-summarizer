"""
Ollama API client service.
Handles communication with the Ollama instance for vision-based OCR and summarization.
"""

import base64
import logging
import json
import tempfile
import os
from typing import Optional, Dict, Any, List
import asyncio
import aiohttp
import aiofiles
from PIL import Image
from pdf2image import convert_from_path
from models import OllamaResponse
from config import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for interacting with Ollama API."""
    
    def __init__(self):
        """Initialize the Ollama client."""
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.headers = {
            "Content-Type": "application/json"
        }
        self._model_capabilities = None
    
    async def test_connection(self) -> bool:
        """
        Test connection to Ollama instance.
        
        Returns:
            True if connection is successful, False otherwise.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            return False
    
    async def get_model_capabilities(self) -> Dict[str, Any]:
        """
        Get model capabilities and details from Ollama.
        
        Returns:
            Dictionary containing model capabilities including:
            - has_vision: Whether model supports image processing
            - families: List of model families
            - details: Full model details from Ollama
        """
        if self._model_capabilities is not None:
            return self._model_capabilities
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Find our specific model
                        model_info = None
                        for model in data.get("models", []):
                            if model["name"] == self.model:
                                model_info = model
                                break
                        
                        if model_info is None:
                            logger.error(f"Model {self.model} not found in available models")
                            self._model_capabilities = {
                                "has_vision": False,
                                "families": [],
                                "details": None,
                                "error": f"Model {self.model} not found"
                            }
                            return self._model_capabilities
                        
                        # Extract capabilities
                        families = model_info.get("details", {}).get("families", [])
                        has_vision = "clip" in families
                        
                        self._model_capabilities = {
                            "has_vision": has_vision,
                            "families": families,
                            "details": model_info,
                            "parameter_size": model_info.get("details", {}).get("parameter_size", "unknown"),
                            "model_family": model_info.get("details", {}).get("family", "unknown")
                        }
                        
                        logger.info(f"Model {self.model} capabilities: "
                                  f"vision={has_vision}, families={families}")
                        
                        return self._model_capabilities
                    else:
                        logger.error(f"Failed to get model capabilities: {response.status}")
                        self._model_capabilities = {
                            "has_vision": False,
                            "families": [],
                            "details": None,
                            "error": f"API error {response.status}"
                        }
                        return self._model_capabilities
        
        except Exception as e:
            logger.error(f"Error getting model capabilities: {e}")
            self._model_capabilities = {
                "has_vision": False,
                "families": [],
                "details": None,
                "error": str(e)
            }
            return self._model_capabilities

    async def check_model_availability(self) -> bool:
        """
        Check if the configured model is available.
        
        Returns:
            True if model is available, False otherwise.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        available_models = [model["name"] for model in data.get("models", [])]
                        is_available = self.model in available_models
                        
                        if not is_available:
                            logger.warning(f"Model {self.model} not available. Available models: {available_models}")
                        
                        return is_available
                    else:
                        logger.error(f"Failed to get model list: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error checking model availability: {e}")
            return False
    
    async def encode_image_to_base64(self, image_path: str) -> Optional[str]:
        """
        Encode an image file to base64.
        
        Args:
            image_path: Path to the image file.
            
        Returns:
            Base64 encoded string if successful, None otherwise.
        """
        try:
            async with aiofiles.open(image_path, "rb") as f:
                image_data = await f.read()
                encoded = base64.b64encode(image_data).decode("utf-8")
                return encoded
        except Exception as e:
            logger.error(f"Error encoding image to base64: {e}")
            return None
    
    async def process_pdf_with_vision(
        self, 
        pdf_path: str, 
        progress_callback: Optional[callable] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Process a PDF file with Ollama model for OCR and summarization.
        Automatically adapts to model capabilities (vision vs text-only).
        
        Args:
            pdf_path: Path to the PDF file.
            progress_callback: Optional callback function for progress updates.
            
        Returns:
            Tuple of (ocr_content, summary_content) if successful, (None, None) otherwise.
        """
        try:
            # Check model capabilities first
            capabilities = await self.get_model_capabilities()
            
            if "error" in capabilities:
                logger.error(f"Failed to get model capabilities: {capabilities['error']}")
                return None, None
            
            if progress_callback:
                progress_callback(f"Model: {self.model} (vision: {capabilities['has_vision']})")
            
            # Handle based on model capabilities
            if capabilities["has_vision"]:
                return await self._process_with_vision_model(pdf_path, progress_callback, capabilities)
            else:
                return await self._process_with_text_model(pdf_path, progress_callback, capabilities)
        
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            return None, None
    
    async def _process_with_vision_model(
        self, 
        pdf_path: str, 
        progress_callback: Optional[callable],
        capabilities: Dict[str, Any]
    ) -> tuple[Optional[str], Optional[str]]:
        """Process PDF with a vision-capable model."""
        temp_image_path = None
        try:
            if progress_callback:
                progress_callback("Using vision model for image processing...")
            
            # Convert PDF to image
            if progress_callback:
                progress_callback("Converting PDF to image...")
            
            temp_image_path = await self.convert_pdf_to_image(pdf_path)
            if temp_image_path is None:
                logger.error("Failed to convert PDF to image")
                return None, None
            
            # Encode image as base64
            if progress_callback:
                progress_callback("Encoding image for vision API...")
            
            encoded_image = await self.encode_image_to_base64(temp_image_path)
            if encoded_image is None:
                logger.error("Failed to encode image to base64")
                return None, None
            
            # First request: OCR extraction using vision
            if progress_callback:
                progress_callback("Extracting text with vision OCR...")
            
            ocr_content = await self._perform_ocr(encoded_image, progress_callback)
            if ocr_content is None:
                logger.error("Vision OCR extraction failed")
                return None, None
            
            # Second request: Summarization
            if progress_callback:
                progress_callback("Generating summary...")
            
            summary_content = await self._perform_summarization(ocr_content, progress_callback)
            if summary_content is None:
                logger.error("Summarization failed")
                return ocr_content, None  # Return OCR even if summarization fails
            
            if progress_callback:
                progress_callback("Vision processing completed successfully")
            
            return ocr_content, summary_content
        
        except Exception as e:
            logger.error(f"Error processing with vision model: {e}")
            return None, None
        
        finally:
            # Clean up temporary image file
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.unlink(temp_image_path)
                    logger.debug(f"Cleaned up temporary image: {temp_image_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary image {temp_image_path}: {e}")
    
    async def _process_with_text_model(
        self, 
        pdf_path: str, 
        progress_callback: Optional[callable],
        capabilities: Dict[str, Any]
    ) -> tuple[Optional[str], Optional[str]]:
        """Process PDF with a text-only model (fallback approach)."""
        try:
            if progress_callback:
                progress_callback(f"Text-only model detected. Suggesting vision model for better results...")
            
            # Log helpful information for the user
            logger.warning(f"Model {self.model} doesn't support vision (families: {capabilities['families']})")
            logger.info("For better OCR results, consider using a vision model like:")
            logger.info("  - minicpm-v:latest")
            logger.info("  - moondream:latest") 
            logger.info("  - llava:latest")
            logger.info("  - bakllava:latest")
            
            # For text-only models, we can't process images directly
            # We need to provide a helpful error message
            error_msg = (
                f"Cannot process PDF images with text-only model '{self.model}'. "
                f"This model has families {capabilities['families']} but needs 'clip' for vision. "
                f"Please switch to a vision-capable model for OCR functionality."
            )
            
            if progress_callback:
                progress_callback(error_msg)
            
            logger.error(error_msg)
            return None, None
        
        except Exception as e:
            logger.error(f"Error in text model fallback: {e}")
            return None, None
    
    async def _perform_ocr(self, encoded_image: str, progress_callback: Optional[callable] = None) -> Optional[str]:
        """
        Perform OCR on the encoded image.
        
        Args:
            encoded_image: Base64 encoded image data.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            Extracted text if successful, None otherwise.
        """
        ocr_prompt = "Just transcribe the text in this image and preserve the formatting and layout (high quality OCR). Do that for ALL the text in the image. Be thorough and pay attention. This is very important. The image is from a text document so be sure to continue until the bottom of the page. Thanks a lot! You tend to forget about some text in the image so please focus!"
        
        return await self._make_vision_request(encoded_image, ocr_prompt, progress_callback)
    
    async def _perform_summarization(self, text_content: str, progress_callback: Optional[callable] = None) -> Optional[str]:
        """
        Perform summarization on the extracted text.
        
        Args:
            text_content: Text content to summarize.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            Summary if successful, None otherwise.
        """
        summary_prompt = f"""Please provide a comprehensive summary of the following document text:

        {text_content}
        
        Instructions for the summary:
        1. Create a clear, concise summary that captures the main points and key information
        2. Include important names, dates, numbers, and specific details mentioned
        3. Organize the summary with bullet points or short paragraphs for readability
        4. Identify the document type (e.g., invoice, contract, report, letter, etc.) at the beginning
        5. Highlight any action items, deadlines, or important requirements
        6. Keep the summary length proportional to the original document (longer documents get longer summaries)
        7. Maintain professional tone and focus on factual content
        
        Format your response as:
        **Document Type:** [type]
        **Summary:**
        [your summary here]
        """
        
        # For summarization, we don't need the image, just text processing
        return await self._make_text_request(summary_prompt, progress_callback)
    
    async def _make_vision_request(
        self, 
        encoded_image: str, 
        prompt: str, 
        progress_callback: Optional[callable] = None
    ) -> Optional[str]:
        """
        Make a vision request to Ollama.
        
        Args:
            encoded_image: Base64 encoded image data.
            prompt: Text prompt for the model.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            Model response if successful, None otherwise.
        """
        request_data = {
            "model": self.model,
            "prompt": prompt,
            "images": [encoded_image],
            "stream": False
        }
        
        return await self._make_request("/api/generate", request_data, progress_callback)
    
    async def _make_text_request(
        self, 
        prompt: str, 
        progress_callback: Optional[callable] = None
    ) -> Optional[str]:
        """
        Make a text-only request to Ollama.
        
        Args:
            prompt: Text prompt for the model.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            Model response if successful, None otherwise.
        """
        request_data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }

        # Unload the model after the request is complete
        request_data["keep_alive"] = 5
        
        return await self._make_request("/api/generate", request_data, progress_callback)
    
    async def _make_request(
        self, 
        endpoint: str, 
        request_data: Dict[str, Any], 
        progress_callback: Optional[callable] = None
    ) -> Optional[str]:
        """
        Make a request to Ollama API.
        
        Args:
            endpoint: API endpoint to call.
            request_data: Request payload.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            Model response if successful, None otherwise.
        """
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.job_timeout_seconds)
            ) as session:
                
                async with session.post(
                    f"{self.base_url}{endpoint}",
                    json=request_data,
                    headers=self.headers
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        # Handle streaming vs non-streaming responses
                        if "response" in data:
                            return data["response"]
                        elif "message" in data and "content" in data["message"]:
                            return data["message"]["content"]
                        else:
                            logger.error(f"Unexpected response format: {data}")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"Ollama API error {response.status}: {error_text}")
                        
                        # Log additional context for vision-related errors
                        if "llava" in error_text.lower() or "embedding" in error_text.lower():
                            logger.error(f"Vision processing error with model {self.model}. "
                                       f"Consider switching to a different vision model.")
                        
                        return None
        
        except asyncio.TimeoutError:
            logger.error("Ollama request timed out")
            return None
        except Exception as e:
            logger.error(f"Error making Ollama request: {e}")
            return None

    async def convert_pdf_to_image(self, pdf_path: str) -> Optional[str]:
        """
        Convert PDF to a single concatenated image.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            Path to the generated image file if successful, None otherwise.
        """
        def _convert_sync():
            """Synchronous PDF conversion function to run in thread pool."""
            try:
                logger.info(f"Converting PDF to image: {pdf_path}")
                
                # Convert PDF pages to images
                images = convert_from_path(
                    pdf_path,
                    dpi=200,  # Good balance between quality and file size
                    fmt='RGB'
                )
                
                if not images:
                    logger.error("No pages found in PDF")
                    return None
                
                logger.info(f"Converted PDF to {len(images)} page(s)")
                
                # If single page, just save it
                if len(images) == 1:
                    temp_image_path = tempfile.mktemp(suffix=".png")
                    images[0].save(temp_image_path, "PNG", optimize=True)
                    logger.info(f"Saved single page image: {temp_image_path}")
                    return temp_image_path
                
                # For multiple pages, concatenate them vertically into a single long image
                # Calculate total height and max width
                total_height = sum(img.height for img in images)
                max_width = max(img.width for img in images)
                
                # Create new image with combined dimensions
                combined_image = Image.new('RGB', (max_width, total_height), 'white')
                
                # Paste each page vertically
                y_offset = 0
                for img in images:
                    # Center the image horizontally if it's narrower than max_width
                    x_offset = (max_width - img.width) // 2
                    combined_image.paste(img, (x_offset, y_offset))
                    y_offset += img.height
                
                # Save the combined image
                temp_image_path = tempfile.mktemp(suffix=".png")
                combined_image.save(temp_image_path, "PNG", optimize=True)
                
                logger.info(f"Created combined image ({max_width}x{total_height}) from {len(images)} pages: {temp_image_path}")
                return temp_image_path
                
            except Exception as e:
                logger.error(f"Error converting PDF to image: {e}")
                return None
        
        # Run the synchronous conversion in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _convert_sync) 