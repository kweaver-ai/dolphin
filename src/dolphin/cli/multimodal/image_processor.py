"""
Image processor for multimodal CLI input.

Handles image validation, format conversion, and compression.
"""

import io
from dataclasses import dataclass, field
from typing import Tuple, Optional

from dolphin.core.common.multimodal import (
    UnsupportedImageFormatError,
    ImagePayloadTooLargeError,
)


@dataclass
class ImageProcessConfig:
    """Configuration for image processing."""
    max_size_bytes: int = 4 * 1024 * 1024      # 4MB
    max_dimension: int = 2048                   # Maximum edge length
    quality: int = 85                           # JPEG compression quality
    # Added MPO (Multi-Picture Object) - used by some cameras/phones, JPEG-based
    allowed_formats: Tuple[str, ...] = ("PNG", "JPEG", "GIF", "WEBP", "MPO")
    auto_compress: bool = True                  # Auto-compress oversized images


class ImageProcessor:
    """Image preprocessor for CLI multimodal input.
    
    Handles:
    - Format validation
    - Size checking and compression
    - Format conversion
    
    Usage:
        processor = ImageProcessor()
        processed_data = processor.process(raw_image_data)
    """
    
    def __init__(self, config: Optional[ImageProcessConfig] = None):
        """Initialize the processor with configuration.
        
        Args:
            config: Processing configuration (uses defaults if not provided)
        """
        self.config = config or ImageProcessConfig()
    
    def process(self, image_data: bytes) -> bytes:
        """Process image data: validate, resize if needed, optimize.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            Processed image bytes
            
        Raises:
            UnsupportedImageFormatError: If format not allowed
            ImagePayloadTooLargeError: If size exceeds limit (after compression attempt)
        """
        try:
            from PIL import Image
        except ImportError:
            # Pillow not installed, return data as-is but check size
            if len(image_data) > self.config.max_size_bytes:
                raise ImagePayloadTooLargeError(
                    f"Image size {len(image_data)} exceeds limit {self.config.max_size_bytes}. "
                    f"Install Pillow for automatic compression."
                )
            return image_data
        
        # Open and validate image
        img = Image.open(io.BytesIO(image_data))
        
        # Check format - treat MPO as JPEG (MPO is JPEG-based multi-picture format)
        img_format = img.format.upper() if img.format else None
        if img_format and img_format not in self.config.allowed_formats:
            raise UnsupportedImageFormatError(
                f"Image format '{img.format}' not supported. "
                f"Allowed formats: {', '.join(self.config.allowed_formats)}"
            )
        
        # Check and resize if needed
        if max(img.size) > self.config.max_dimension:
            if self.config.auto_compress:
                img = self._resize(img)
            else:
                raise ImagePayloadTooLargeError(
                    f"Image dimensions {img.size} exceed limit {self.config.max_dimension}. "
                    f"Enable auto_compress to automatically resize."
                )
        
        # Convert to output format
        output = io.BytesIO()
        
        # Choose format based on image mode
        if img.mode in ('RGBA', 'LA', 'P'):
            # Preserve transparency with PNG
            if img.mode == 'P' and 'transparency' in img.info:
                img = img.convert('RGBA')
            output_format = "PNG"
            img.save(output, format=output_format, optimize=True)
        else:
            # Use JPEG for photos (smaller size)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            output_format = "JPEG"
            img.save(output, format=output_format, quality=self.config.quality, optimize=True)
        
        result = output.getvalue()
        
        # Final size check
        if len(result) > self.config.max_size_bytes:
            if self.config.auto_compress:
                # Try more aggressive compression
                result = self._aggressive_compress(img, output_format)
            
            if len(result) > self.config.max_size_bytes:
                raise ImagePayloadTooLargeError(
                    f"Image size {len(result)} exceeds limit {self.config.max_size_bytes} "
                    f"even after compression."
                )
        
        return result
    
    def _resize(self, img) -> "Image.Image":
        """Resize image to fit within max_dimension while preserving aspect ratio.
        
        Args:
            img: PIL Image object
            
        Returns:
            Resized PIL Image
        """
        from PIL import Image
        
        ratio = self.config.max_dimension / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        return img.resize(new_size, Image.Resampling.LANCZOS)
    
    def _aggressive_compress(self, img, output_format: str) -> bytes:
        """Apply aggressive compression to reduce file size.
        
        Args:
            img: PIL Image object
            output_format: Target format
            
        Returns:
            Compressed image bytes
        """
        output = io.BytesIO()
        
        # Reduce dimensions further
        max_dim = min(self.config.max_dimension, 1024)
        if max(img.size) > max_dim:
            from PIL import Image
            ratio = max_dim / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Use lower quality
        if output_format == "JPEG":
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(output, format="JPEG", quality=60, optimize=True)
        else:
            img.save(output, format="PNG", optimize=True)
        
        return output.getvalue()
    
    def get_image_info(self, image_data: bytes) -> dict:
        """Get information about an image.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            Dict with format, size, mode, dimensions
        """
        try:
            from PIL import Image
            
            img = Image.open(io.BytesIO(image_data))
            return {
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size_bytes": len(image_data),
            }
        except Exception as e:
            return {
                "error": str(e),
                "size_bytes": len(image_data),
            }
    
    def validate_file(self, file_path: str) -> bool:
        """Validate that a file is a valid image.
        
        Args:
            file_path: Path to image file
            
        Returns:
            True if valid image
        """
        try:
            from PIL import Image
            
            with Image.open(file_path) as img:
                img.verify()
            return True
        except Exception:
            return False
