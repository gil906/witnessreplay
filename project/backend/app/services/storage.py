import logging
from typing import Optional
from io import BytesIO
from google.cloud import storage
from google.api_core import exceptions as gcp_exceptions

from app.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Service for managing Google Cloud Storage operations."""
    
    def __init__(self):
        self.client = None
        self.bucket_name = settings.gcs_bucket
        self.bucket = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize GCS client."""
        try:
            if settings.gcp_project_id:
                self.client = storage.Client(project=settings.gcp_project_id)
                self.bucket = self.client.bucket(self.bucket_name)
                logger.info(f"GCS client initialized for bucket: {self.bucket_name}")
            else:
                logger.warning("GCP_PROJECT_ID not set, GCS client not initialized")
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}")
            self.client = None
            self.bucket = None
    
    async def upload_image(
        self,
        image_data: bytes,
        filename: str,
        content_type: str = "image/png",
        session_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Upload an image to GCS and return the public URL.
        
        Args:
            image_data: Image bytes
            filename: Name of the file
            content_type: MIME type of the image
            session_id: Optional session ID to organize files
        
        Returns:
            Public URL of the uploaded image, or None on failure
        """
        if not self.bucket:
            logger.warning("GCS bucket not available")
            return None
        
        try:
            # Create blob path
            if session_id:
                blob_name = f"sessions/{session_id}/{filename}"
            else:
                blob_name = f"images/{filename}"
            
            blob = self.bucket.blob(blob_name)
            
            # Upload the image
            blob.upload_from_string(image_data, content_type=content_type)
            
            # Make the blob publicly accessible
            blob.make_public()
            
            public_url = blob.public_url
            logger.info(f"Uploaded image to GCS: {public_url}")
            return public_url
        
        except Exception as e:
            logger.error(f"Failed to upload image to GCS: {e}")
            return None
    
    async def upload_audio(
        self,
        audio_data: bytes,
        filename: str,
        content_type: str = "audio/webm",
        session_id: Optional[str] = None
    ) -> Optional[str]:
        """Upload an audio file to GCS and return the public URL."""
        if not self.bucket:
            logger.warning("GCS bucket not available")
            return None
        
        try:
            if session_id:
                blob_name = f"sessions/{session_id}/audio/{filename}"
            else:
                blob_name = f"audio/{filename}"
            
            blob = self.bucket.blob(blob_name)
            blob.upload_from_string(audio_data, content_type=content_type)
            blob.make_public()
            
            public_url = blob.public_url
            logger.info(f"Uploaded audio to GCS: {public_url}")
            return public_url
        
        except Exception as e:
            logger.error(f"Failed to upload audio to GCS: {e}")
            return None
    
    async def delete_file(self, blob_name: str) -> bool:
        """Delete a file from GCS."""
        if not self.bucket:
            logger.warning("GCS bucket not available")
            return False
        
        try:
            blob = self.bucket.blob(blob_name)
            blob.delete()
            logger.info(f"Deleted file from GCS: {blob_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from GCS: {e}")
            return False
    
    async def delete_session_files(self, session_id: str) -> bool:
        """Delete all files for a session."""
        if not self.bucket:
            logger.warning("GCS bucket not available")
            return False
        
        try:
            blobs = self.bucket.list_blobs(prefix=f"sessions/{session_id}/")
            for blob in blobs:
                blob.delete()
            logger.info(f"Deleted all files for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session files: {e}")
            return False
    
    def health_check(self) -> bool:
        """Check if GCS is accessible."""
        if not self.bucket:
            return False
        try:
            self.bucket.exists()
            return True
        except Exception as e:
            logger.error(f"GCS health check failed: {e}")
            return False


# Global instance
storage_service = StorageService()
