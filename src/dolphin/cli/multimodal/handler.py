"""
Multimodal input handler for CLI.

Integrates parsing, image reading, and processing to convert user input
with multimodal markers into proper multimodal content.
"""

import os
import base64
from typing import Union, List, Dict, Any, Optional

from dolphin.cli.multimodal.input_parser import (
    MultimodalInputParser,
    ParsedMultimodalInput,
    ImageSourceType,
)
from dolphin.cli.multimodal.clipboard import ClipboardImageReader
from dolphin.cli.multimodal.image_processor import ImageProcessor, ImageProcessConfig
from dolphin.core.common.multimodal import (
    text_block,
    image_url_block,
    ClipboardEmptyError,
)


# Type alias for message content
MessageContent = Union[str, List[Dict[str, Any]]]


class MultimodalInputHandler:
    """Handler for processing multimodal CLI input.
    
    Converts user input with @paste, @image:, @url: markers into
    proper multimodal content compatible with LLM APIs.
    
    Usage:
        handler = MultimodalInputHandler()
        content = handler.process("@paste 请描述这张图片")
        # Returns List[Dict] with image and text blocks
    """
    
    def __init__(
        self,
        image_config: Optional[ImageProcessConfig] = None,
        verbose: bool = False
    ):
        """Initialize the handler.
        
        Args:
            image_config: Configuration for image processing
            verbose: If True, print status messages
        """
        self.parser = MultimodalInputParser()
        self.clipboard = ClipboardImageReader()
        self.processor = ImageProcessor(image_config)
        self.verbose = verbose
    
    def process(self, raw_input: str) -> MessageContent:
        """Process user input and convert to message content.
        
        Args:
            raw_input: Raw user input string
            
        Returns:
            str if no multimodal markers, List[Dict] if multimodal
            
        Raises:
            ClipboardEmptyError: If @paste used but clipboard empty
            FileNotFoundError: If @image: file doesn't exist
            Other exceptions from image processing
        """
        # Quick check - if no markers, return as plain text
        if not self.parser.has_multimodal_markers(raw_input):
            return raw_input
        
        # Parse the input
        parsed = self.parser.parse(raw_input)
        
        if not parsed.has_images():
            return raw_input
        
        # Build multimodal content
        content: List[Dict[str, Any]] = []
        
        for i, text_part in enumerate(parsed.text_parts):
            # Add text block if not empty
            if text_part.strip():
                content.append(text_block(text_part.strip()))
            
            # Add corresponding image if exists
            if i < len(parsed.image_refs):
                ref = parsed.image_refs[i]
                image_url = self._resolve_image_ref(ref)
                content.append(image_url_block(image_url, detail="auto"))
        
        # Ensure we have at least one block
        if not content:
            return raw_input
        
        return content
    
    def _resolve_image_ref(self, ref) -> str:
        """Resolve an image reference to a usable URL.
        
        Args:
            ref: ImageReference object
            
        Returns:
            Image URL (data: URL for local/clipboard, https: for web)
        """
        if ref.source_type == ImageSourceType.CLIPBOARD:
            return self._read_clipboard()
        
        elif ref.source_type == ImageSourceType.FILE:
            return self._read_file(ref.source)
        
        elif ref.source_type == ImageSourceType.URL:
            # URL is passed through directly
            return ref.source
        
        raise ValueError(f"Unknown source type: {ref.source_type}")
    
    def _read_clipboard(self) -> str:
        """Read and process clipboard image.
        
        Returns:
            Base64 data URL
        """
        data = self.clipboard.read()
        if data is None:
            raise ClipboardEmptyError(
                "No image found in clipboard. "
                "Please copy an image first (Cmd/Ctrl+C on an image)."
            )
        
        if self.verbose:
            info = self.processor.get_image_info(data)
            print(f"📎 Read clipboard image: {info.get('width', '?')}x{info.get('height', '?')}, "
                  f"{info.get('size_bytes', 0) // 1024}KB")
        
        # Process the image (resize, compress if needed)
        processed = self.processor.process(data)
        
        if self.verbose and len(processed) != len(data):
            print(f"   Compressed to {len(processed) // 1024}KB")
        
        return self.clipboard.to_base64_url(processed)
    
    def _read_file(self, path: str) -> str:
        """Read and process image file.
        
        Args:
            path: File path (can be relative or use ~)
            
        Returns:
            Base64 data URL
        """
        # Expand user home and resolve path
        expanded_path = os.path.expanduser(path)
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.abspath(expanded_path)
        
        if not os.path.exists(expanded_path):
            raise FileNotFoundError(f"Image file not found: {path}")
        
        if self.verbose:
            print(f"📁 Reading image file: {path}")
        
        with open(expanded_path, "rb") as f:
            data = f.read()
        
        # Detect MIME type
        mime_type = self._detect_mime_type(data)
        
        # Process the image
        processed = self.processor.process(data)
        
        if self.verbose:
            info = self.processor.get_image_info(processed)
            print(f"   Image: {info.get('width', '?')}x{info.get('height', '?')}, "
                  f"{len(processed) // 1024}KB")
        
        return self._to_base64_url(processed, mime_type)
    
    def _detect_mime_type(self, data: bytes) -> str:
        """Detect MIME type from image data.
        
        Args:
            data: Image bytes
            
        Returns:
            MIME type string
        """
        # Check magic bytes
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        elif data[:2] == b'\xff\xd8':
            return "image/jpeg"
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            return "image/gif"
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "image/webp"
        else:
            # Default to PNG (processor will convert)
            return "image/png"
    
    def _to_base64_url(self, data: bytes, mime_type: str = "image/png") -> str:
        """Convert image data to base64 data URL.
        
        Args:
            data: Image bytes
            mime_type: MIME type
            
        Returns:
            Data URL string
        """
        b64 = base64.b64encode(data).decode('utf-8')
        return f"data:{mime_type};base64,{b64}"
    
    def check_clipboard_status(self) -> dict:
        """Check if clipboard contains an image.
        
        Returns:
            Status dict with has_image and optional info
        """
        data = self.clipboard.read()
        if data is None:
            return {"has_image": False}
        
        info = self.processor.get_image_info(data)
        return {
            "has_image": True,
            "info": info
        }


# Convenience function for quick processing
def process_multimodal_input(raw_input: str, verbose: bool = False) -> MessageContent:
    """Process user input and convert multimodal markers to content blocks.
    
    Args:
        raw_input: Raw user input string
        verbose: If True, print status messages
        
    Returns:
        str if no multimodal markers, List[Dict] if multimodal
    """
    handler = MultimodalInputHandler(verbose=verbose)
    return handler.process(raw_input)
