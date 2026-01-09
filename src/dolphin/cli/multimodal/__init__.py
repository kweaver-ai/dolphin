"""
Multimodal input module for Dolphin CLI.

This module provides support for multimodal input in the CLI, including:
- Clipboard image reading (@paste)
- File path references (@image:<path>)
- URL references (@url:<url>)
"""

from dolphin.cli.multimodal.input_parser import (
    MultimodalInputParser,
    ParsedMultimodalInput,
    ImageReference,
    ImageSourceType,
)
from dolphin.cli.multimodal.clipboard import ClipboardImageReader
from dolphin.cli.multimodal.image_processor import ImageProcessor, ImageProcessConfig
from dolphin.cli.multimodal.handler import (
    MultimodalInputHandler,
    process_multimodal_input,
)

__all__ = [
    "MultimodalInputParser",
    "ParsedMultimodalInput",
    "ImageReference",
    "ImageSourceType",
    "ClipboardImageReader",
    "ImageProcessor",
    "ImageProcessConfig",
    "MultimodalInputHandler",
    "process_multimodal_input",
]

