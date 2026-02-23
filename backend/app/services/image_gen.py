import logging
import base64
from typing import Optional, List
from io import BytesIO
from PIL import Image
from google import genai

from app.config import settings
from app.models.schemas import SceneElement

logger = logging.getLogger(__name__)


class ImageGenerationService:
    """Service for generating scene images using Gemini."""
    
    def __init__(self):
        self.client = None
        self.model = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Gemini client for image generation."""
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                self.model = settings.gemini_vision_model
                logger.info("Gemini image generation client initialized")
            else:
                logger.warning("GOOGLE_API_KEY not set, image generation not available")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None
            self.model = None
    
    def _create_image_prompt(
        self,
        scene_description: str,
        elements: List[SceneElement],
        is_correction: bool = False,
        previous_description: Optional[str] = None
    ) -> str:
        """
        Create a detailed prompt for image generation.
        
        Args:
            scene_description: Natural language description of the scene
            elements: List of scene elements to include
            is_correction: Whether this is a correction of a previous image
            previous_description: Previous scene description (for corrections)
        
        Returns:
            Detailed prompt for image generation
        """
        prompt_parts = [
            "Create a photorealistic crime/accident scene reconstruction based on the following witness description.",
            "",
            f"Scene Description: {scene_description}",
            "",
        ]
        
        if elements:
            prompt_parts.append("Key Elements to Include:")
            for elem in elements:
                elem_desc = f"- {elem.type.upper()}: {elem.description}"
                if elem.position:
                    elem_desc += f" (Position: {elem.position})"
                if elem.color:
                    elem_desc += f" (Color: {elem.color})"
                if elem.size:
                    elem_desc += f" (Size: {elem.size})"
                prompt_parts.append(elem_desc)
            prompt_parts.append("")
        
        if is_correction and previous_description:
            prompt_parts.extend([
                "IMPORTANT: This is a correction to a previous scene.",
                f"Previous scene was: {previous_description}",
                "Please emphasize the corrections in the new scene.",
                ""
            ])
        
        prompt_parts.extend([
            "Style Requirements:",
            "- Photorealistic rendering",
            "- Clear visibility of all described elements",
            "- Forensic/documentary quality",
            "- Neutral lighting that reveals details",
            "- Professional crime scene reconstruction aesthetic",
            "- No people's faces shown (use silhouettes or back views if people are mentioned)",
        ])
        
        return "\n".join(prompt_parts)
    
    async def generate_scene_image(
        self,
        scene_description: str,
        elements: List[SceneElement] = [],
        is_correction: bool = False,
        previous_description: Optional[str] = None
    ) -> Optional[bytes]:
        """
        Generate a scene image based on the description and elements.
        
        Note: As of this implementation, Gemini 2.0 may not support direct image generation
        via the API. This method provides a placeholder structure. In production, you would:
        1. Use Imagen 3 via Vertex AI, or
        2. Use a text-to-image model like Stable Diffusion, or
        3. Generate a descriptive placeholder image with the scene text
        
        For now, this generates a placeholder image with scene information.
        
        Args:
            scene_description: Natural language description
            elements: List of scene elements
            is_correction: Whether this is a correction
            previous_description: Previous description (for corrections)
        
        Returns:
            Image bytes (PNG format) or None on failure
        """
        try:
            # Generate the prompt
            prompt = self._create_image_prompt(
                scene_description, elements, is_correction, previous_description
            )
            
            logger.info(f"Generated image prompt: {prompt[:200]}...")
            
            # PLACEHOLDER: Since Gemini may not support direct image generation,
            # we create a placeholder image with the scene description
            # In production, integrate with Imagen 3 or another image generation service
            
            image = self._create_placeholder_image(scene_description, elements)
            
            # Convert to bytes
            img_byte_arr = BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_bytes = img_byte_arr.getvalue()
            
            logger.info("Generated placeholder scene image")
            return img_bytes
        
        except Exception as e:
            logger.error(f"Failed to generate scene image: {e}")
            return None
    
    def _create_placeholder_image(
        self,
        scene_description: str,
        elements: List[SceneElement]
    ) -> Image.Image:
        """
        Create a placeholder image with scene information.
        This is a temporary solution until proper image generation is integrated.
        """
        # Create a simple colored image with text
        width, height = 800, 600
        
        # Create a gradient background
        img = Image.new('RGB', (width, height), color=(20, 30, 40))
        
        # In a real implementation, you would:
        # 1. Call Imagen 3 API via Vertex AI
        # 2. Use the generated prompt
        # 3. Return the actual generated image
        
        # For now, return a simple placeholder
        from PIL import ImageDraw, ImageFont
        
        draw = ImageDraw.Draw(img)
        
        # Add text
        y_offset = 50
        line_height = 30
        
        # Title
        draw.text((50, y_offset), "Scene Reconstruction", fill=(255, 255, 255))
        y_offset += line_height * 2
        
        # Description
        draw.text((50, y_offset), "Description:", fill=(200, 200, 200))
        y_offset += line_height
        
        # Wrap description text
        words = scene_description.split()
        line = ""
        for word in words[:50]:  # Limit words
            if len(line + word) < 80:
                line += word + " "
            else:
                draw.text((50, y_offset), line.strip(), fill=(180, 180, 180))
                y_offset += line_height
                line = word + " "
        if line:
            draw.text((50, y_offset), line.strip(), fill=(180, 180, 180))
        
        # Elements
        if elements:
            y_offset += line_height * 2
            draw.text((50, y_offset), "Key Elements:", fill=(200, 200, 200))
            y_offset += line_height
            
            for elem in elements[:10]:  # Limit elements
                elem_text = f"• {elem.type}: {elem.description[:60]}"
                draw.text((50, y_offset), elem_text, fill=(160, 160, 160))
                y_offset += line_height
        
        return img
    
    def health_check(self) -> bool:
        """Check if image generation service is available."""
        return self.client is not None


# Global instance
image_service = ImageGenerationService()
