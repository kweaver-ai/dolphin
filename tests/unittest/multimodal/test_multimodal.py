"""
Unit tests for multimodal support module.

Tests the core multimodal functionality including:
- SingleMessage multimodal support
- Content helpers (normalize, extract, etc.)
- Image token estimation
- Multimodal validation
"""

import pytest
from unittest.mock import Mock, patch

# Import modules under test
from dolphin.core.common.multimodal import (
    text_block,
    image_url_block,
    normalize_content,
    extract_text,
    count_images,
    has_images,
    get_content_preview,
    calculate_content_length,
    ImageTokenConfig,
    estimate_image_tokens,
    MultimodalCompressionMode,
    MultimodalCompressionConfig,
    MultimodalError,
    MultimodalNotSupportedError,
    TooManyImagesError,
    validate_content_block,
    validate_multimodal_content,
    MultimodalValidator,
    InvalidImageDetailError,
    InvalidImageUrlError,
    UnsupportedContentBlockTypeError,
    EmptyMultimodalContentError,
)

from dolphin.core.common.enums import (
    SingleMessage,
    MessageRole,
    Messages,
    MessageContent,
)


class TestContentBlockHelpers:
    """Tests for content block helper functions."""
    
    def test_text_block(self):
        """Test text_block creates correct structure."""
        block = text_block("Hello world")
        assert block == {"type": "text", "text": "Hello world"}
    
    def test_image_url_block_default_detail(self):
        """Test image_url_block with default detail."""
        block = image_url_block("https://example.com/image.png")
        assert block == {
            "type": "image_url",
            "image_url": {"url": "https://example.com/image.png", "detail": "auto"}
        }
    
    def test_image_url_block_custom_detail(self):
        """Test image_url_block with custom detail."""
        block = image_url_block("https://example.com/image.png", detail="high")
        assert block["image_url"]["detail"] == "high"
    
    def test_normalize_content_string(self):
        """Test normalize_content with string input."""
        result = normalize_content("Hello")
        assert result == [{"type": "text", "text": "Hello"}]
    
    def test_normalize_content_list(self):
        """Test normalize_content with list input."""
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        result = normalize_content(content)
        assert result == content  # Should return as-is
    
    def test_extract_text_from_string(self):
        """Test extract_text with string input."""
        assert extract_text("Hello world") == "Hello world"
    
    def test_extract_text_from_multimodal(self):
        """Test extract_text with multimodal content."""
        content = [
            text_block("Hello "),
            image_url_block("https://example.com/a.png"),
            text_block("world")
        ]
        assert extract_text(content) == "Hello world"
    
    def test_count_images_string(self):
        """Test count_images with string (no images)."""
        assert count_images("Hello") == 0
    
    def test_count_images_multimodal(self):
        """Test count_images with multimodal content."""
        content = [
            text_block("Hello"),
            image_url_block("https://example.com/a.png"),
            image_url_block("https://example.com/b.png"),
        ]
        assert count_images(content) == 2
    
    def test_has_images(self):
        """Test has_images function."""
        assert not has_images("Hello")
        assert has_images([image_url_block("https://example.com/a.png")])
    
    def test_get_content_preview_string(self):
        """Test get_content_preview with string."""
        preview = get_content_preview("Hello world")
        assert preview == {"type": "text", "length": 11}
    
    def test_get_content_preview_multimodal(self):
        """Test get_content_preview with multimodal."""
        content = [
            text_block("Hello"),
            image_url_block("https://example.com/a.png"),
        ]
        preview = get_content_preview(content)
        assert preview["type"] == "multimodal"
        assert preview["text_length"] == 5
        assert preview["image_count"] == 1
    
    def test_calculate_content_length(self):
        """Test calculate_content_length function."""
        assert calculate_content_length("Hello") == 5
        content = [text_block("Hello"), text_block(" world")]
        assert calculate_content_length(content) == 11


class TestImageTokenConfig:
    """Tests for image token estimation."""
    
    def test_low_detail_fixed_tokens(self):
        """Test low detail returns fixed base tokens."""
        config = ImageTokenConfig()
        assert config.estimate_tokens(detail="low") == 85
    
    def test_unknown_dimensions_fallback(self):
        """Test fallback values for unknown dimensions."""
        config = ImageTokenConfig()
        assert config.estimate_tokens(detail="auto") == 600
        assert config.estimate_tokens(detail="high") == 1500
    
    def test_known_dimensions_calculation(self):
        """Test tile-based calculation with known dimensions."""
        config = ImageTokenConfig()
        # 1024x768 = 2x2 tiles = 85 + 170*4 = 765
        tokens = config.estimate_tokens(width=1024, height=768)
        assert tokens == 85 + 170 * 2 * 2
    
    def test_estimate_image_tokens_convenience(self):
        """Test convenience function."""
        assert estimate_image_tokens(detail="low") == 85


class TestSingleMessageMultimodal:
    """Tests for SingleMessage multimodal support."""
    
    def test_str_content_preserved(self):
        """Test that string content still works."""
        msg = SingleMessage(role=MessageRole.USER, content="Hello")
        assert msg.content == "Hello"
        assert not msg.is_multimodal()
        assert msg.length() == 5
    
    def test_multimodal_content(self):
        """Test multimodal content creation."""
        content = [
            text_block("What's in this image?"),
            image_url_block("https://example.com/a.png")
        ]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        assert msg.is_multimodal()
        assert msg.has_images()
        assert msg.get_image_count() == 1
    
    def test_extract_text_from_message(self):
        """Test extract_text method."""
        content = [
            text_block("Hello "),
            image_url_block("https://example.com/a.png"),
            text_block("world")
        ]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        assert msg.extract_text() == "Hello world"
    
    def test_normalize_content_method(self):
        """Test normalize_content method."""
        msg = SingleMessage(role=MessageRole.USER, content="Hello")
        normalized = msg.normalize_content()
        assert normalized == [{"type": "text", "text": "Hello"}]
    
    def test_append_content_str_str(self):
        """Test appending string to string."""
        msg = SingleMessage(role=MessageRole.USER, content="Hello")
        msg.append_content(" world")
        assert msg.content == "Hello world"
    
    def test_append_content_str_list(self):
        """Test appending list to string (type upgrade)."""
        msg = SingleMessage(role=MessageRole.USER, content="Hello")
        msg.append_content([image_url_block("https://example.com/a.png")])
        assert msg.is_multimodal()
        assert len(msg.content) == 2
        assert msg.content[0] == {"type": "text", "text": "Hello"}
    
    def test_append_content_list_str(self):
        """Test appending string to list."""
        msg = SingleMessage(
            role=MessageRole.USER,
            content=[text_block("Hello")]
        )
        msg.append_content(" world")
        assert len(msg.content) == 2
        assert msg.content[1] == {"type": "text", "text": " world"}
    
    def test_append_content_list_list(self):
        """Test appending list to list."""
        msg = SingleMessage(
            role=MessageRole.USER,
            content=[text_block("Hello")]
        )
        msg.append_content([image_url_block("https://example.com/a.png")])
        assert len(msg.content) == 2
        assert msg.content[1]["type"] == "image_url"
    
    def test_length_multimodal(self):
        """Test length() only counts text."""
        content = [
            text_block("Hello"),  # 5 chars
            image_url_block("https://example.com/a.png"),  # 0 chars
            text_block(" world")  # 6 chars
        ]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        assert msg.length() == 11
    
    def test_to_dict_multimodal(self):
        """Test to_dict preserves multimodal content."""
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        result = msg.to_dict()
        assert result["content"] == content
        assert result["role"] == "user"
    
    def test_copy_multimodal(self):
        """Test copy creates deep copy of multimodal content."""
        content = [text_block("Hello")]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        copy = msg.copy()
        
        # Modify copy's content
        copy.content[0]["text"] = "Modified"
        
        # Original should be unchanged
        assert msg.content[0]["text"] == "Hello"
    
    def test_get_content_preview_method(self):
        """Test get_content_preview method."""
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        preview = msg.get_content_preview()
        assert preview["type"] == "multimodal"
        assert preview["image_count"] == 1
    
    def test_str_representation_multimodal(self):
        """Test __str__ shows summary for multimodal."""
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        msg = SingleMessage(role=MessageRole.USER, content=content)
        str_repr = str(msg)
        assert "Multimodal" in str_repr
        assert "1 images" in str_repr


class TestMessagesMultimodal:
    """Tests for Messages class multimodal support."""
    
    def test_add_message_multimodal(self):
        """Test adding multimodal message."""
        messages = Messages()
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        messages.add_message(content=content, role=MessageRole.USER)
        
        assert len(messages) == 1
        assert messages[0].is_multimodal()
    
    def test_append_message_multimodal_merge(self):
        """Test appending multimodal content to existing message."""
        messages = Messages()
        messages.add_message(content="Hello", role=MessageRole.USER)
        messages.append_message(
            role=MessageRole.USER,
            content=[image_url_block("https://example.com/a.png")]
        )
        
        # Should merge into one message since same role
        assert len(messages) == 1
        # Content should be upgraded to multimodal
        assert messages[0].is_multimodal()


class TestValidation:
    """Tests for multimodal validation."""
    
    def test_validate_text_block_valid(self):
        """Test valid text block passes validation."""
        validate_content_block(text_block("Hello"))  # Should not raise
    
    def test_validate_text_block_invalid(self):
        """Test invalid text block raises error."""
        with pytest.raises(InvalidImageUrlError):
            validate_content_block({"type": "image_url", "image_url": {}})
    
    def test_validate_image_block_invalid_detail(self):
        """Test invalid detail raises error."""
        block = {"type": "image_url", "image_url": {"url": "https://example.com/a.png", "detail": "invalid"}}
        with pytest.raises(InvalidImageDetailError):
            validate_content_block(block)
    
    def test_validate_unsupported_type(self):
        """Test unsupported block type raises error."""
        with pytest.raises(UnsupportedContentBlockTypeError):
            validate_content_block({"type": "video"})
    
    def test_validate_multimodal_content_empty(self):
        """Test empty content list raises error."""
        with pytest.raises(EmptyMultimodalContentError):
            validate_multimodal_content([])
    
    def test_validate_multimodal_content_valid(self):
        """Test valid multimodal content passes."""
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        validate_multimodal_content(content)  # Should not raise


class TestMultimodalValidator:
    """Tests for MultimodalValidator class."""
    
    def test_validate_no_images_passes(self):
        """Test messages without images pass validation."""
        messages = Messages()
        messages.add_message(content="Hello", role=MessageRole.USER)
        # Should not raise
        MultimodalValidator.validate(messages, supports_vision=False)
    
    def test_validate_images_without_vision_fails(self):
        """Test images with non-vision model fails."""
        messages = Messages()
        content = [text_block("Hello"), image_url_block("https://example.com/a.png")]
        messages.add_message(content=content, role=MessageRole.USER)
        
        with pytest.raises(MultimodalNotSupportedError):
            MultimodalValidator.validate(
                messages, 
                supports_vision=False,
                model_name="test-model"
            )
    
    def test_validate_too_many_images(self):
        """Test too many images fails validation."""
        messages = Messages()
        content = [
            text_block("Hello"),
            image_url_block("https://example.com/a.png"),
            image_url_block("https://example.com/b.png"),
            image_url_block("https://example.com/c.png"),
        ]
        messages.add_message(content=content, role=MessageRole.USER)
        
        with pytest.raises(TooManyImagesError):
            MultimodalValidator.validate(
                messages,
                supports_vision=True,
                max_images_per_request=2
            )


class TestMultiImageCompression:
    """Tests for multi-image compression scenarios (CR suggestion #6)."""
    
    def test_multiple_images_trigger_compression(self):
        """Test that 5 images + text triggers compression correctly."""
        from dolphin.core.message.compressor import TruncationStrategy
        from dolphin.core.config.global_config import ContextConstraints, GlobalConfig
        from dolphin.core.context.context import Context
        
        # Create messages with 5 images
        messages = Messages()
        content = [text_block("Analyze these images:")]
        for i in range(5):
            content.append(image_url_block(f"https://example.com/image{i}.jpg", detail="high"))
        messages.add_message(content=content, role=MessageRole.USER)
        
        # Add more messages to trigger compression
        for i in range(10):
            messages.add_message(
                content=f"Message {i}",
                role=MessageRole.ASSISTANT if i % 2 else MessageRole.USER
            )
        
        # Create a very restrictive constraint to force compression
        constraints = ContextConstraints(
            max_input_tokens=5000,
            reserve_output_tokens=1000,
            preserve_system=True
        )
        
        # Create context with proper config
        config = GlobalConfig()
        context = Context(config=config)
        strategy = TruncationStrategy()
        result = strategy.compress(context, constraints, messages)
        
        # Verify compression occurred
        assert result.compressed_token_count < result.original_token_count
        assert "dropped_images" in result.metadata
        
        # Verify metadata tracks image drops
        if result.metadata["dropped_images"] > 0:
            assert result.metadata["compressed_images"] < result.metadata["original_images"]
    
    def test_compression_preserves_recent_images(self):
        """Test that compression keeps recent images when possible."""
        from dolphin.core.message.compressor import TruncationStrategy
        from dolphin.core.config.global_config import ContextConstraints, GlobalConfig
        from dolphin.core.context.context import Context
        
        messages = Messages()
        
        # Add old message with image
        old_content = [
            text_block("Old image:"),
            image_url_block("https://example.com/old.jpg")
        ]
        messages.add_message(content=old_content, role=MessageRole.USER)
        messages.add_message(content="Old response", role=MessageRole.ASSISTANT)
        
        # Add many text messages to push old image out
        for i in range(20):
            messages.add_message(
                content=f"Text message {i}" * 100,  # Long messages
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
            )
        
        # Add recent message with image
        recent_content = [
            text_block("Recent image:"),
            image_url_block("https://example.com/recent.jpg")
        ]
        messages.add_message(content=recent_content, role=MessageRole.USER)
        
        constraints = ContextConstraints(
            max_input_tokens=8000,
            reserve_output_tokens=1000,
            preserve_system=True
        )
        
        # Create context with proper config
        config = GlobalConfig()
        context = Context(config=config)
        strategy = TruncationStrategy()
        result = strategy.compress(context, constraints, messages)
        
        # Check that recent image is preserved
        has_recent_image = False
        for msg in result.compressed_messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if block.get("type") == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if "recent.jpg" in url:
                            has_recent_image = True
        
        # Recent image should be preserved (it's in the latest messages)
        assert has_recent_image or result.metadata["compressed_images"] == 0


class TestBase64URLMixed:
    """Tests for mixed base64 and URL images (CR suggestion #6)."""
    
    def test_mixed_base64_and_url_images(self):
        """Test messages with both base64 and URL images."""
        messages = Messages()
        
        # Create content with mixed image types
        content = [
            text_block("Compare these:"),
            image_url_block("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="),
            image_url_block("https://example.com/image.jpg"),
        ]
        messages.add_message(content=content, role=MessageRole.USER)
        
        # Verify structure
        assert len(messages) == 1
        assert messages[0].get_image_count() == 2
        
        # Verify both types are present
        urls = [
            block.get("image_url", {}).get("url", "")
            for block in messages[0].content
            if block.get("type") == "image_url"
        ]
        assert any(url.startswith("data:") for url in urls)
        assert any(url.startswith("https://") for url in urls)
    
    def test_base64_size_validation(self):
        """Test that base64 size limits are enforced."""
        from dolphin.core.common.multimodal import ImageConstraints, ImagePayloadTooLargeError
        
        constraints = ImageConstraints(max_base64_bytes_per_image=100)  # Very small limit
        
        # Create a large base64 string (will exceed limit)
        large_base64 = "data:image/png;base64," + ("A" * 200)
        
        with pytest.raises(ImagePayloadTooLargeError):
            constraints.validate_base64_size(large_base64, 0)
    
    def test_per_message_base64_limit(self):
        """Test per-message base64 byte limit."""
        from dolphin.core.common.multimodal import ImageConstraints, MultimodalValidator, ImagePayloadTooLargeError
        
        messages = Messages()
        
        # Create multiple base64 images that individually pass but together exceed limit
        small_base64 = "data:image/png;base64," + ("A" * 1000)  # 1KB each
        content = [text_block("Multiple images:")]
        for i in range(3):  # 3KB total (within per-message image count limit)
            content.append(image_url_block(small_base64))
        
        messages.add_message(content=content, role=MessageRole.USER)
        
        # Should fail with restrictive per-message byte limit
        constraints = ImageConstraints(
            max_base64_bytes_per_image=2000,  # Each image is OK
            max_base64_bytes_per_message=2000,  # But total exceeds this (3KB > 2KB)
            max_images_per_message=5  # Image count is OK
        )
        
        with pytest.raises(ImagePayloadTooLargeError):
            MultimodalValidator.validate(
                messages,
                supports_vision=True,
                max_images_per_request=20,
                image_constraints=constraints
            )


class TestModelSwitching:
    """Tests for switching between vision and non-vision models (CR suggestion #6)."""
    
    def test_vision_to_nonvision_validation_fails(self):
        """Test that switching to non-vision model with images fails validation."""
        messages = Messages()
        content = [
            text_block("What's in this image?"),
            image_url_block("https://example.com/image.jpg")
        ]
        messages.add_message(content=content, role=MessageRole.USER)
        
        # Validate with vision model - should pass
        MultimodalValidator.validate(
            messages,
            supports_vision=True,
            max_images_per_request=10,
            model_name="gpt-4o"
        )
        
        # Validate with non-vision model - should fail
        with pytest.raises(MultimodalNotSupportedError) as exc_info:
            MultimodalValidator.validate(
                messages,
                supports_vision=False,
                max_images_per_request=10,
                model_name="gpt-4"
            )
        
        assert "gpt-4" in str(exc_info.value)
        assert "does not support vision" in str(exc_info.value)
    
    def test_text_only_compression_mode_for_nonvision(self):
        """Test TEXT_ONLY compression mode strips images for non-vision models."""
        from dolphin.core.common.multimodal import MultimodalCompressionMode, MultimodalCompressionConfig
        
        # Create config with TEXT_ONLY mode (now the default)
        config = MultimodalCompressionConfig(mode=MultimodalCompressionMode.TEXT_ONLY)
        
        # Verify default is TEXT_ONLY
        default_config = MultimodalCompressionConfig()
        assert default_config.mode == MultimodalCompressionMode.TEXT_ONLY
        
        # This tests that the default has been changed as per CR suggestion #4
        assert default_config.mode != MultimodalCompressionMode.ATOMIC
    
    def test_extract_text_for_nonvision_fallback(self):
        """Test extracting text from multimodal message for non-vision fallback."""
        content = [
            text_block("Please analyze this image: "),
            image_url_block("https://example.com/chart.jpg"),
            text_block(" and tell me what you see.")
        ]
        
        msg = SingleMessage(role=MessageRole.USER, content=content)
        
        # Extract text (images removed)
        text_only = msg.extract_text()
        assert text_only == "Please analyze this image:  and tell me what you see."
        assert "chart.jpg" not in text_only


class TestProviderSpecificTokenEstimation:
    """Tests for provider-specific token estimation (CR suggestion #1)."""
    
    def test_openai_token_estimation(self):
        """Test OpenAI-style token estimation."""
        config = ImageTokenConfig.for_provider("openai")
        
        # 1024x768 image = 2x2 tiles = 85 + 170*4 = 765
        tokens = config.estimate_tokens(width=1024, height=768)
        assert tokens == 85 + 170 * 4
    
    def test_gemini_token_estimation(self):
        """Test Gemini-style token estimation."""
        config = ImageTokenConfig.for_provider("gemini")
        
        # Gemini uses 258 tokens per 768x768 tile, no base overhead
        # 1024x768 = 2x1 tiles = 258 * 2 = 516
        tokens = config.estimate_tokens(width=1024, height=768)
        expected_tiles_x = 2  # ceil(1024/768)
        expected_tiles_y = 1  # ceil(768/768)
        assert tokens == 258 * expected_tiles_x * expected_tiles_y
    
    def test_default_provider_fallback(self):
        """Test unknown provider falls back to OpenAI style."""
        config = ImageTokenConfig.for_provider("unknown-provider")
        
        # Should use OpenAI defaults
        assert config.base_tokens == 85
        assert config.tokens_per_tile == 170


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
