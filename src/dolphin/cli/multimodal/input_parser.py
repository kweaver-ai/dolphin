"""
Input parser for multimodal CLI input.

Parses user input to extract multimodal references like @paste, @image:<path>, @url:<url>.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple


class ImageSourceType(Enum):
    """Type of image source."""
    CLIPBOARD = "clipboard"      # @paste
    FILE = "file"                # @image:<path>
    URL = "url"                  # @url:<url>


@dataclass
class ImageReference:
    """Reference to an image in user input."""
    source_type: ImageSourceType
    source: str                   # Path, URL, or "clipboard"
    position: int                 # Position in original text
    original_text: str            # Original matched text (e.g., "@paste", "@image:./foo.png")


@dataclass
class ParsedMultimodalInput:
    """Result of parsing multimodal input."""
    text_parts: List[str]         # Text fragments after removing image references
    image_refs: List[ImageReference]  # List of image references
    original_input: str           # Original unmodified input
    
    def has_images(self) -> bool:
        """Check if input contains any image references."""
        return len(self.image_refs) > 0
    
    def get_combined_text(self) -> str:
        """Get all text parts combined (without image markers)."""
        return " ".join(part.strip() for part in self.text_parts if part.strip())


class MultimodalInputParser:
    """Parser for multimodal CLI input.
    
    Supports:
    - @paste: Read image from clipboard
    - @image:<path>: Read image from local file
    - @url:<url>: Reference image by URL (https only)
    
    Example:
        parser = MultimodalInputParser()
        result = parser.parse("@paste 请描述这张图片")
        # result.has_images() == True
        # result.image_refs[0].source_type == ImageSourceType.CLIPBOARD
    """
    
    # Pattern definitions
    PASTE_PATTERN = r"@paste"
    IMAGE_PATTERN = r"@image:([^\s]+)"
    URL_PATTERN = r"@url:(https://[^\s]+)"
    
    def __init__(self):
        """Initialize the parser with compiled regex patterns."""
        self._patterns = [
            (re.compile(self.PASTE_PATTERN, re.IGNORECASE), ImageSourceType.CLIPBOARD),
            (re.compile(self.IMAGE_PATTERN, re.IGNORECASE), ImageSourceType.FILE),
            (re.compile(self.URL_PATTERN, re.IGNORECASE), ImageSourceType.URL),
        ]
    
    def parse(self, raw_input: str) -> ParsedMultimodalInput:
        """Parse raw input to extract multimodal references.
        
        Args:
            raw_input: User's raw input string
            
        Returns:
            ParsedMultimodalInput containing text parts and image references
        """
        if not raw_input:
            return ParsedMultimodalInput(
                text_parts=[""],
                image_refs=[],
                original_input=raw_input
            )
        
        # Find all matches with their positions
        matches: List[Tuple[int, int, ImageReference]] = []
        
        for pattern, source_type in self._patterns:
            for match in pattern.finditer(raw_input):
                start, end = match.span()
                
                if source_type == ImageSourceType.CLIPBOARD:
                    source = "clipboard"
                elif source_type == ImageSourceType.FILE:
                    source = match.group(1)  # The path
                elif source_type == ImageSourceType.URL:
                    source = match.group(1)  # The URL
                else:
                    continue
                
                ref = ImageReference(
                    source_type=source_type,
                    source=source,
                    position=start,
                    original_text=match.group(0)
                )
                matches.append((start, end, ref))
        
        # Sort by position
        matches.sort(key=lambda x: x[0])
        
        # Extract text parts and image references
        text_parts: List[str] = []
        image_refs: List[ImageReference] = []
        last_end = 0
        
        for start, end, ref in matches:
            # Add text before this match
            text_before = raw_input[last_end:start]
            text_parts.append(text_before)
            image_refs.append(ref)
            last_end = end
        
        # Add remaining text after last match
        text_parts.append(raw_input[last_end:])
        
        return ParsedMultimodalInput(
            text_parts=text_parts,
            image_refs=image_refs,
            original_input=raw_input
        )
    
    def has_multimodal_markers(self, text: str) -> bool:
        """Quick check if text contains any multimodal markers.
        
        Args:
            text: Text to check
            
        Returns:
            True if text contains @paste, @image:, or @url:
        """
        for pattern, _ in self._patterns:
            if pattern.search(text):
                return True
        return False
