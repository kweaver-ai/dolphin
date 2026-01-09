"""Compressor service for content optimization and compression."""

import re
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from abc import ABC, abstractmethod

from dolphin.core.common.enums import Messages
from ..core.tokenizer_service import TokenizerService
from ..utils.context_utils import extract_key_info, summarize_content


@dataclass
class CompressionResult:
    """Result of compression operation."""

    compressed_content: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    method_used: str
    metadata: Dict[str, Any]


class BaseCompressor(ABC):
    """Abstract base class for compressors."""

    @abstractmethod
    def compress(self, content: str, target_tokens: int, **kwargs) -> CompressionResult:
        """Compress content to target token count."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get compressor name."""
        pass


class TruncateCompressor(BaseCompressor):
    """Simple truncation-based compressor."""

    def __init__(self, tokenizer_service: Optional[TokenizerService] = None):
        self.tokenizer = tokenizer_service or TokenizerService()

    def compress(self, content: str, target_tokens: int, **kwargs) -> CompressionResult:
        """Compress by truncating content."""
        original_tokens = self.tokenizer.count_tokens(content)

        if original_tokens <= target_tokens:
            return CompressionResult(
                compressed_content=content,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                compression_ratio=1.0,
                method_used="no_compression",
                metadata={"reason": "content_already_fits"},
            )

        # Truncate content
        from ..utils.token_utils import truncate_to_tokens

        truncated = truncate_to_tokens(content, target_tokens, self.tokenizer)
        compressed_tokens = self.tokenizer.count_tokens(truncated)

        return CompressionResult(
            compressed_content=truncated,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compressed_tokens / original_tokens,
            method_used="truncate",
            metadata={"strategy": "simple_truncate"},
        )

    def get_name(self) -> str:
        return "truncate"


class ExtractiveCompressor(BaseCompressor):
    """Extractive compressor that keeps key sentences."""

    def __init__(self, tokenizer_service: Optional[TokenizerService] = None):
        self.tokenizer = tokenizer_service or TokenizerService()

    def compress(self, content: str, target_tokens: int, **kwargs) -> CompressionResult:
        """Compress by extracting key sentences."""
        original_tokens = self.tokenizer.count_tokens(content)

        if original_tokens <= target_tokens:
            return CompressionResult(
                compressed_content=content,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                compression_ratio=1.0,
                method_used="no_compression",
                metadata={"reason": "content_already_fits"},
            )

        # Extract key information
        target_sentences = max(1, int(target_tokens / 20))  # Rough estimate
        key_info = extract_key_info(content, max_sentences=target_sentences)

        compressed_tokens = self.tokenizer.count_tokens(key_info)

        return CompressionResult(
            compressed_content=key_info,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compressed_tokens / original_tokens,
            method_used="extractive",
            metadata={"sentences_extracted": target_sentences},
        )

    def get_name(self) -> str:
        return "extractive"


class AbstractiveCompressor(BaseCompressor):
    """Abstractive compressor using summarization."""

    def __init__(self, tokenizer_service: Optional[TokenizerService] = None):
        self.tokenizer = tokenizer_service or TokenizerService()

    def compress(self, content: str, target_tokens: int, **kwargs) -> CompressionResult:
        """Compress using abstractive summarization."""
        original_tokens = self.tokenizer.count_tokens(content)

        if original_tokens <= target_tokens:
            return CompressionResult(
                compressed_content=content,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                compression_ratio=1.0,
                method_used="no_compression",
                metadata={"reason": "content_already_fits"},
            )

        # Calculate target compression ratio
        target_ratio = target_tokens / original_tokens

        # Use summarization
        summary = summarize_content(
            content, target_ratio=target_ratio, preserve_keywords=True
        )
        compressed_tokens = self.tokenizer.count_tokens(summary)

        return CompressionResult(
            compressed_content=summary,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compressed_tokens / original_tokens,
            method_used="abstractive",
            metadata={"target_ratio": target_ratio},
        )

    def get_name(self) -> str:
        return "abstractive"


class SignatureOnlyCompressor(BaseCompressor):
    """Compressor that keeps only function signatures or essential info."""

    def __init__(self, tokenizer_service: Optional[TokenizerService] = None):
        self.tokenizer = tokenizer_service or TokenizerService()

    def compress(self, content: str, target_tokens: int, **kwargs) -> CompressionResult:
        """Compress by keeping only signatures and essential information."""
        original_tokens = self.tokenizer.count_tokens(content)

        # Extract function signatures, class definitions, etc.
        signatures = self._extract_signatures(content)

        if not signatures:
            # Fallback to simple truncation
            return TruncateCompressor(self.tokenizer).compress(content, target_tokens)

        # Join signatures
        compressed = "\n".join(signatures)
        compressed_tokens = self.tokenizer.count_tokens(compressed)

        return CompressionResult(
            compressed_content=compressed,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compressed_tokens / original_tokens,
            method_used="signature_only",
            metadata={"signatures_extracted": len(signatures)},
        )

    def _extract_signatures(self, content: str) -> List[str]:
        """Extract function signatures and class definitions."""
        signatures = []

        # Python function signatures
        func_pattern = r"^\s*(?:def|class)\s+(\w+)\s*\([^)]*\)\s*(?:->\s*\w+)?\s*:"
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            signatures.append(match.group(0).strip())

        # API endpoint signatures
        api_pattern = r"^\s*(GET|POST|PUT|DELETE|PATCH)\s+[^\s]+"
        for match in re.finditer(api_pattern, content, re.MULTILINE):
            signatures.append(match.group(0).strip())

        # Database schema signatures
        schema_pattern = r"^\s*(CREATE TABLE|ALTER TABLE|DROP TABLE)\s+\w+"
        for match in re.finditer(schema_pattern, content, re.MULTILINE | re.IGNORECASE):
            signatures.append(match.group(0).strip())

        return signatures

    def get_name(self) -> str:
        return "signature_only"


class Compressor:
    """Main compressor service with multiple compression strategies."""

    def __init__(self, tokenizer_service: Optional[TokenizerService] = None):
        """
        Initialize compressor with available compression methods.

        Args:
            tokenizer_service: TokenizerService instance for token counting
        """
        self.tokenizer = tokenizer_service or TokenizerService()
        self.compressors = {
            "truncate": TruncateCompressor(self.tokenizer),
            "extractive": ExtractiveCompressor(self.tokenizer),
            "abstractive": AbstractiveCompressor(self.tokenizer),
            "signature_only": SignatureOnlyCompressor(self.tokenizer),
            "task_summary": ExtractiveCompressor(
                self.tokenizer
            ),  # Alias for extractive
            "aggressive_extract": ExtractiveCompressor(
                self.tokenizer
            ),  # More aggressive extraction
        }

    def compress(
        self,
        content: Union[str, Messages],
        target_tokens: int,
        method: str = "extractive",
        **kwargs,
    ) -> CompressionResult:
        """
        Compress content using specified method.

        Args:
            content: Content to compress
            target_tokens: Target token count
            method: Compression method to use
            **kwargs: Additional arguments for specific compressors

        Returns:
            CompressionResult with compressed content and metadata
        """
        if method not in self.compressors:
            raise ValueError(f"Unknown compression method: {method}")

        compressor = self.compressors[method]

        # Add method-specific parameters
        if method == "aggressive_extract":
            kwargs["max_sentences"] = kwargs.get("max_sentences", 1)

        return compressor.compress(content, target_tokens, **kwargs)

    def compress_with_fallback(
        self, content: str, target_tokens: int, preferred_methods: List[str], **kwargs
    ) -> CompressionResult:
        """
        Compress content trying multiple methods in order of preference.

        Args:
            content: Content to compress
            target_tokens: Target token count
            preferred_methods: List of compression methods to try
            **kwargs: Additional arguments for compressors

        Returns:
            CompressionResult from the first successful method
        """
        for method in preferred_methods:
            try:
                result = self.compress(content, target_tokens, method, **kwargs)
                if result.compression_ratio <= 1.0:  # Valid compression
                    return result
            except Exception:
                continue

        # Fallback to truncate
        return self.compress(content, target_tokens, "truncate", **kwargs)

    def batch_compress(
        self,
        contents: Dict[str, str],
        allocations: Dict[str, int],
        method: str = "extractive",
        **kwargs,
    ) -> Dict[str, CompressionResult]:
        """
        Compress multiple content sections with different token allocations.

        Args:
            contents: Dictionary of section names to content
            allocations: Dictionary of section names to token allocations
            method: Compression method to use
            **kwargs: Additional arguments for compressors

        Returns:
            Dictionary of section names to CompressionResults
        """
        results = {}

        for section_name, content in contents.items():
            if section_name in allocations:
                target_tokens = allocations[section_name]
                try:
                    result = self.compress(content, target_tokens, method, **kwargs)
                    results[section_name] = result
                except Exception as e:
                    # Create error result
                    results[section_name] = CompressionResult(
                        compressed_content=content,
                        original_tokens=self.tokenizer.count_tokens(content),
                        compressed_tokens=0,
                        compression_ratio=1.0,
                        method_used="error",
                        metadata={"error": str(e)},
                    )

        return results

    def get_compression_stats(
        self, results: Dict[str, CompressionResult]
    ) -> Dict[str, Any]:
        """
        Get statistics from batch compression results.

        Args:
            results: Dictionary of compression results

        Returns:
            Statistics about the compression operation
        """
        if not results:
            return {}

        total_original = sum(result.original_tokens for result in results.values())
        total_compressed = sum(result.compressed_tokens for result in results.values())

        stats = {
            "total_sections": len(results),
            "total_original_tokens": total_original,
            "total_compressed_tokens": total_compressed,
            "overall_compression_ratio": (
                total_compressed / total_original if total_original > 0 else 0
            ),
            "methods_used": list(
                set(result.method_used for result in results.values())
            ),
            "section_stats": {},
        }

        for section_name, result in results.items():
            stats["section_stats"][section_name] = {
                "original_tokens": result.original_tokens,
                "compressed_tokens": result.compressed_tokens,
                "compression_ratio": result.compression_ratio,
                "method_used": result.method_used,
            }

        return stats

    def add_custom_compressor(self, name: str, compressor: BaseCompressor):
        """Add a custom compressor implementation."""
        self.compressors[name] = compressor

    def get_available_methods(self) -> List[str]:
        """Get list of available compression methods."""
        return list(self.compressors.keys())

    def get_compressor_info(self, method: str) -> Dict[str, Any]:
        """Get information about a specific compression method."""
        if method not in self.compressors:
            return {}

        compressor = self.compressors[method]
        return {
            "name": compressor.get_name(),
            "description": compressor.__class__.__doc__,
            "type": (
                "extractive"
                if "extract" in method
                else "abstractive"
                if "abstract" in method
                else "truncation"
            ),
        }
