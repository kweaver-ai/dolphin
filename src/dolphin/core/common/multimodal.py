"""
Multimodal support module for Dolphin Language.

This module provides types, utilities, and exceptions for handling
multimodal content (text + images) in the message system.

Design based on: docs/core/multimodal_support_design.md
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# =============================================================================
# Type Definitions
# =============================================================================

# MessageContent can be either a plain string or a list of ContentBlocks
MessageContent = Union[str, List[Dict[str, Any]]]


# =============================================================================
# ContentBlock Helpers
# =============================================================================

def text_block(text: str) -> Dict[str, Any]:
    """Create a text content block.
    
    Args:
        text: The text content
        
    Returns:
        A text content block in OpenAI format
    """
    return {"type": "text", "text": text}


def image_url_block(url: str, detail: str = "auto") -> Dict[str, Any]:
    """Create an image URL content block.
    
    Args:
        url: The image URL (https:// or data:image/... for base64)
        detail: Resolution level - "auto", "low", or "high"
        
    Returns:
        An image_url content block in OpenAI format
    """
    return {"type": "image_url", "image_url": {"url": url, "detail": detail}}


def normalize_content(content: MessageContent) -> List[Dict[str, Any]]:
    """Normalize any content format to List[Dict].
    
    Args:
        content: Either a string or list of content blocks
        
    Returns:
        Content as a list of content blocks
    """
    if isinstance(content, str):
        return [text_block(content)]
    return content


def extract_text(content: MessageContent) -> str:
    """Extract plain text from multimodal content.
    
    Used for logging, fallback to non-vision models, etc.
    
    Args:
        content: Either a string or list of content blocks
        
    Returns:
        Extracted text content (images are omitted)
    """
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") 
        for block in content 
        if block.get("type") == "text"
    )


def count_images(content: MessageContent) -> int:
    """Count the number of images in content.
    
    Args:
        content: Either a string or list of content blocks
        
    Returns:
        Number of image blocks
    """
    if isinstance(content, str):
        return 0
    return sum(1 for block in content if block.get("type") == "image_url")


def has_images(content: MessageContent) -> bool:
    """Check if content contains any images.
    
    Args:
        content: Either a string or list of content blocks
        
    Returns:
        True if content contains at least one image
    """
    return count_images(content) > 0


def get_content_preview(content: MessageContent) -> Dict[str, Any]:
    """Generate a preview of content for logging.
    
    Used to avoid logging sensitive data like base64 or full URLs.
    
    Args:
        content: Either a string or list of content blocks
        
    Returns:
        A summary dict suitable for logging
    """
    if isinstance(content, str):
        return {"type": "text", "length": len(content)}
    
    image_count = count_images(content)
    text_length = sum(
        len(block.get("text", "")) 
        for block in content 
        if block.get("type") == "text"
    )
    return {
        "type": "multimodal",
        "text_length": text_length,
        "image_count": image_count
    }


def calculate_content_length(content: MessageContent) -> int:
    """Calculate the text length of content (excluding images).
    
    Args:
        content: Either a string or list of content blocks
        
    Returns:
        Total length of text content
    """
    if isinstance(content, str):
        return len(content)
    return sum(
        len(block.get("text", "")) 
        for block in content 
        if block.get("type") == "text"
    )


# =============================================================================
# Image Token Estimation
# =============================================================================

@dataclass
class ImageTokenConfig:
    """Simplified image token estimation configuration.
    
    Design Decision:
    - Uses OpenAI-style tile-based algorithm as universal estimate
    - Does not differentiate by provider (±20% error acceptable for compression)
    - Server-side usage is the authoritative source for billing/limits
    """
    
    # Tile-based estimation parameters (OpenAI style, universally applicable)
    base_tokens: int = 85           # Base overhead
    tokens_per_tile: int = 170      # Tokens per 512×512 tile
    tile_size: int = 512            # Tile side length
    
    # Fallback values when dimensions unknown
    fallback_tokens: Dict[str, int] = field(default_factory=lambda: {
        "low": 85,       # Low resolution mode
        "auto": 600,     # Default conservative estimate
        "high": 1500,    # High resolution conservative estimate
    })
    
    def estimate_tokens(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        detail: str = "auto"
    ) -> int:
        """Estimate token count for an image.
        
        Args:
            width: Image width in pixels (optional)
            height: Image height in pixels (optional)
            detail: Resolution level ("low", "auto", "high")
            
        Returns:
            Estimated token count
        """
        # Low mode returns fixed base overhead
        if detail == "low":
            return self.base_tokens
        
        # Use fallback when dimensions unknown
        if width is None or height is None:
            return self.fallback_tokens.get(detail, self.fallback_tokens["auto"])
        
        # Tile-based calculation: base + tiles × tokens_per_tile
        tiles_x = math.ceil(width / self.tile_size)
        tiles_y = math.ceil(height / self.tile_size)
        return self.base_tokens + self.tokens_per_tile * tiles_x * tiles_y
    
    @classmethod
    def for_provider(cls, provider: str) -> "ImageTokenConfig":
        """Create provider-specific token estimation config.
        
        Args:
            provider: LLM provider name (openai, gemini, anthropic, etc.)
            
        Returns:
            ImageTokenConfig optimized for the provider
            
        Note:
            This is an optional enhancement for improved accuracy.
            The default OpenAI-style config is sufficient for most use cases.
        """
        provider = provider.lower()
        
        if provider == "openai":
            return cls(base_tokens=85, tokens_per_tile=170, tile_size=512)
        elif provider == "gemini":
            # Gemini uses 258 tokens per 768x768 tile, no base overhead
            return cls(base_tokens=0, tokens_per_tile=258, tile_size=768)
        elif provider == "anthropic":
            # Anthropic uses pixel-based calculation: (width × height) / 750
            # We approximate with very fine tiles
            return cls(base_tokens=0, tokens_per_tile=1, tile_size=27)  # ~750 pixels
        else:
            # Default to OpenAI style
            return cls()


# Global default config instance
_default_image_token_config = ImageTokenConfig()


def estimate_image_tokens(
    width: Optional[int] = None,
    height: Optional[int] = None,
    detail: str = "auto",
    config: Optional[ImageTokenConfig] = None
) -> int:
    """Convenience function to estimate image tokens.
    
    Args:
        width: Image width in pixels (optional)
        height: Image height in pixels (optional)
        detail: Resolution level ("low", "auto", "high")
        config: Optional custom config (uses default if not provided)
        
    Returns:
        Estimated token count
    """
    cfg = config or _default_image_token_config
    return cfg.estimate_tokens(width, height, detail)


# =============================================================================
# Image Size Constraints
# =============================================================================

@dataclass
class ImageConstraints:
    """Constraints for image size and count to prevent memory issues.
    
    Design Rationale:
    - Multiple 2MB base64 images can cause OOM
    - Base64 strings inflate by ~33% during serialization
    - Need both per-image and aggregate limits
    """
    
    max_base64_bytes_per_image: int = 2 * 1024 * 1024    # 2MB per image
    max_base64_bytes_per_message: int = 5 * 1024 * 1024  # 5MB per message
    max_images_per_message: int = 5                       # 5 images per message
    max_images_in_context: int = 20                       # 20 images across all messages
    
    def validate_base64_size(self, base64_data: str, image_index: int = 0) -> None:
        """Validate a single base64 image size.
        
        Args:
            base64_data: The base64 encoded image data (with or without data: prefix)
            image_index: Index of the image (for error messages)
            
        Raises:
            ImagePayloadTooLargeError: If image exceeds size limit
        """
        # Strip data URL prefix if present
        if base64_data.startswith("data:"):
            base64_data = base64_data.split(",", 1)[-1]
        
        size_bytes = len(base64_data.encode('utf-8'))
        if size_bytes > self.max_base64_bytes_per_image:
            raise ImagePayloadTooLargeError(
                f"Base64 image #{image_index} size ({size_bytes / 1024 / 1024:.2f}MB) "
                f"exceeds limit ({self.max_base64_bytes_per_image / 1024 / 1024:.2f}MB)"
            )


# =============================================================================
# Multimodal Compression Configuration
# =============================================================================

class MultimodalCompressionMode(Enum):
    """Compression mode for multimodal messages.
    
    Modes:
    - TEXT_ONLY: Drop images when over limit, keep text (default, safest for information preservation)
    - ATOMIC: Keep or drop entire message (good for image-text binding scenarios)
    - LATEST_IMAGE: Keep only the latest N images (balance between modes)
    """
    TEXT_ONLY = "text_only"     # Drop images when over limit, keep text (default)
    ATOMIC = "atomic"           # Keep or drop entire message
    LATEST_IMAGE = "latest_image"  # Keep only the latest N images


@dataclass
class MultimodalCompressionConfig:
    """Configuration for multimodal message compression."""
    mode: MultimodalCompressionMode = MultimodalCompressionMode.TEXT_ONLY
    max_images_to_keep: int = 3  # For LATEST_IMAGE mode
    allow_truncate_text_blocks: bool = True  # Whether to allow truncating text blocks


# =============================================================================
# Exceptions
# =============================================================================

class MultimodalError(Exception):
    """Base class for multimodal-related errors."""
    pass


class MultimodalNotSupportedError(MultimodalError):
    """Raised when model does not support multimodal input."""
    pass


class TooManyImagesError(MultimodalError):
    """Raised when image count exceeds model limit."""
    pass


class UnsupportedImageFormatError(MultimodalError):
    """Raised when image format is not supported."""
    pass


class UnsupportedContentBlockTypeError(MultimodalError):
    """Raised when content block type is not supported."""
    pass


class EmptyMultimodalContentError(MultimodalError):
    """Raised when multimodal content list is empty."""
    pass


class InvalidTextBlockError(MultimodalError):
    """Raised when text block is invalid."""
    pass


class InvalidImageUrlError(MultimodalError):
    """Raised when image URL is invalid."""
    pass


class InvalidImageDetailError(MultimodalError):
    """Raised when image detail level is invalid."""
    pass


class ImagePayloadTooLargeError(MultimodalError):
    """Raised when base64 image payload exceeds limit."""
    pass


class ClipboardEmptyError(MultimodalError):
    """Raised when clipboard does not contain an image."""
    pass


# =============================================================================
# Validation
# =============================================================================

def validate_content_block(block: Dict[str, Any]) -> None:
    """Validate a single content block.
    
    Args:
        block: The content block to validate
        
    Raises:
        UnsupportedContentBlockTypeError: If block type is unknown
        InvalidTextBlockError: If text block is malformed
        InvalidImageUrlError: If image URL is invalid
        InvalidImageDetailError: If image detail level is invalid
    """
    block_type = block.get("type")
    
    if block_type == "text":
        if not isinstance(block.get("text"), str):
            raise InvalidTextBlockError("Text block requires 'text: str'.")
        return
    
    if block_type == "image_url":
        image_url = block.get("image_url") or {}
        url = image_url.get("url")
        detail = image_url.get("detail", "auto")
        
        if detail not in ("auto", "low", "high"):
            raise InvalidImageDetailError(f"Invalid image detail: {detail}")
        if not isinstance(url, str) or not url:
            raise InvalidImageUrlError("image_url block requires non-empty url.")
        return
    
    raise UnsupportedContentBlockTypeError(f"Unsupported content block type: {block_type}")


def validate_multimodal_content(content: MessageContent) -> None:
    """Validate multimodal content.
    
    Args:
        content: The content to validate
        
    Raises:
        EmptyMultimodalContentError: If content list is empty
        Other validation errors from validate_content_block
    """
    if isinstance(content, str):
        return  # Plain text is always valid
    
    if len(content) == 0:
        raise EmptyMultimodalContentError("Multimodal content list must not be empty.")
    
    for block in content:
        validate_content_block(block)


class MultimodalValidator:
    """Validator for multimodal messages against model capabilities."""
    
    @staticmethod
    def validate(
        messages,  # Messages type, but avoiding circular import
        supports_vision: bool = True,
        max_images_per_request: int = 10,
        model_name: str = "unknown",
        image_constraints: Optional[ImageConstraints] = None
    ) -> None:
        """Validate messages against model capabilities.
        
        Args:
            messages: Messages object to validate
            supports_vision: Whether model supports vision input
            max_images_per_request: Maximum images allowed per request
            model_name: Name of the model (for error messages)
            image_constraints: Optional size/count constraints for images
            
        Raises:
            MultimodalNotSupportedError: If model doesn't support vision
            TooManyImagesError: If image count exceeds limit
            ImagePayloadTooLargeError: If base64 images exceed size limits
            Other validation errors
        """
        total_images = 0
        has_any_images = False
        constraints = image_constraints or ImageConstraints()
        
        for msg in messages:
            content = msg.content
            if isinstance(content, list):
                # Validate content blocks
                validate_multimodal_content(content)
                
                # Count and validate images in this message
                img_count = 0
                total_base64_bytes = 0
                
                for idx, block in enumerate(content):
                    if block.get("type") == "image_url":
                        img_count += 1
                        has_any_images = True
                        total_images += 1
                        
                        # Validate base64 size if applicable
                        url = block.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            # Extract base64 data
                            base64_data = url.split(",", 1)[-1] if "," in url else url
                            base64_bytes = len(base64_data.encode('utf-8'))
                            total_base64_bytes += base64_bytes
                            
                            # Check per-image limit
                            constraints.validate_base64_size(url, idx)
                
                # Check per-message limits
                if img_count > constraints.max_images_per_message:
                    raise TooManyImagesError(
                        f"Message contains {img_count} images, exceeding limit of "
                        f"{constraints.max_images_per_message} images per message"
                    )
                
                if total_base64_bytes > constraints.max_base64_bytes_per_message:
                    raise ImagePayloadTooLargeError(
                        f"Message base64 images total {total_base64_bytes / 1024 / 1024:.2f}MB, "
                        f"exceeding limit of {constraints.max_base64_bytes_per_message / 1024 / 1024:.2f}MB"
                    )
        
        # Check vision support
        if has_any_images and not supports_vision:
            raise MultimodalNotSupportedError(
                f"Model '{model_name}' does not support vision input. "
                f"Please use a vision-capable model like gpt-4o or claude-3-5-sonnet."
            )
        
        # Check context-wide image count limit
        if total_images > constraints.max_images_in_context:
            raise TooManyImagesError(
                f"Context contains {total_images} images, exceeding limit of "
                f"{constraints.max_images_in_context} images across all messages"
            )
        
        # Check model-specific limit (backward compatibility)
        if total_images > max_images_per_request:
            raise TooManyImagesError(
                f"Request contains {total_images} images, but model limit is "
                f"{max_images_per_request}"
            )
