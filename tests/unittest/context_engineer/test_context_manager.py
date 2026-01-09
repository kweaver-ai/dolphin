"""Tests for ContextManager."""

from dolphin.core.context_engineer.core.context_manager import (
    ContextManager,
    ContextBucket,
    ContextState,
)
from dolphin.core.common.enums import MessageRole


class TestContextManager:
    """Test cases for ContextManager."""

    def test_context_bucket_creation(self):
        """Test creating ContextBucket."""
        bucket = ContextBucket(
            name="system",
            content="You are a helpful assistant.",
            priority=2.0,
            token_count=10,
            allocated_tokens=50,
            message_role=MessageRole.SYSTEM,
        )

        assert bucket.name == "system"
        assert bucket.content == "You are a helpful assistant."
        assert bucket.priority == 2.0
        assert bucket.token_count == 10
        assert bucket.allocated_tokens == 50
        assert bucket.message_role == MessageRole.SYSTEM
        assert bucket.is_dirty == True
        assert bucket.is_compressed == False

    def test_context_state_initialization(self):
        """Test ContextState initialization."""
        state = ContextState()

        assert state.buckets == {}
        assert state.total_tokens == 0
        assert state.layout_policy == "default"
        assert state.bucket_order == []
        assert state.dirty_buckets == set()

    def test_incremental_context_manager_initialization(self):
        """Test ContextManager initialization."""
        manager = ContextManager()

        assert manager.tokenizer is not None
        assert manager.compressor is not None
        assert manager.context_config is not None
        assert isinstance(manager.state, ContextState)

    def test_add_bucket_basic(self):
        """Test adding a basic bucket."""
        manager = ContextManager()

        manager.add_bucket(
            bucket_name="system",
            content="You are a helpful assistant.",
            priority=2.0,
        )

        assert "system" in manager.state.buckets
        bucket = manager.state.buckets["system"]
        assert bucket.name == "system"
        assert bucket.content == "You are a helpful assistant."
        assert bucket.priority == 2.0
        assert bucket.is_dirty == True
        assert "system" in manager.state.dirty_buckets

    def test_add_bucket_with_allocated_tokens(self):
        """Test adding a bucket with allocated tokens."""
        manager = ContextManager()

        manager.add_bucket(
            bucket_name="task",
            content="Help the user with their question.",
            priority=1.5,
            allocated_tokens=100,
            message_role=MessageRole.USER,
        )

        bucket = manager.state.buckets["task"]
        assert bucket.allocated_tokens == 100
        assert bucket.message_role == MessageRole.USER

    def test_update_bucket_content(self):
        """Test updating bucket content."""
        manager = ContextManager()

        # Add initial bucket
        manager.add_bucket("task", "Initial content", 1.0)

        # Update content
        manager.update_bucket_content("task", "Updated content")

        bucket = manager.state.buckets["task"]
        assert bucket.content == "Updated content"
        assert bucket.is_dirty == True
        assert bucket.is_compressed == False
        assert "task" in manager.state.dirty_buckets

    def test_remove_bucket(self):
        """Test removing a bucket."""
        manager = ContextManager()

        manager.add_bucket("system", "System prompt", 2.0)
        manager.add_bucket("task", "Task description", 1.5)

        assert "system" in manager.state.buckets
        assert "task" in manager.state.buckets

        manager.remove_bucket("system")

        assert "system" not in manager.state.buckets
        assert "task" in manager.state.buckets
        assert "system" not in manager.state.dirty_buckets

    def test_set_layout_policy(self):
        """Test setting layout policy."""
        manager = ContextManager()

        manager.set_layout_policy("default")

        assert manager.state.layout_policy == "default"
        assert manager.state.total_tokens == 0  # Should reset

    def test_get_token_stats_empty(self):
        """Test getting token stats with empty context."""
        manager = ContextManager()

        stats = manager.get_token_stats()

        assert stats["total_tokens"] == 0
        assert stats["bucket_count"] == 0
        assert stats["buckets"] == {}
        assert stats["compression_needed"] == False

    def test_get_token_stats_with_buckets(self):
        """Test getting token stats with buckets."""
        manager = ContextManager()

        manager.add_bucket("system", "Short system prompt", 2.0, allocated_tokens=50)
        manager.add_bucket("task", "Task description", 1.5, allocated_tokens=100)

        stats = manager.get_token_stats()

        assert stats["total_tokens"] > 0
        assert stats["bucket_count"] == 2
        assert "system" in stats["buckets"]
        assert "task" in stats["buckets"]

        # Check bucket details
        system_stats = stats["buckets"]["system"]
        assert system_stats["tokens"] > 0
        assert system_stats["allocated"] == 50
        assert system_stats["priority"] == 2.0
        assert system_stats["is_compressed"] == False

    def test_needs_compression(self):
        """Test compression need detection."""
        manager = ContextManager()

        # Add a bucket that doesn't need compression
        manager.add_bucket("short", "Short content", 1.0, allocated_tokens=100)

        # Initially should not need compression
        assert manager.needs_compression() == False

        # Add a bucket that might need compression (long content with small allocation)
        manager.add_bucket(
            "long",
            "This is a very long content that should require compression " * 10,
            1.0,
            allocated_tokens=10,
        )

        # Now should need compression
        assert manager.needs_compression() == True

    def test_compress_bucket(self):
        """Test compressing a specific bucket."""
        manager = ContextManager()

        # Add a bucket that needs compression
        long_content = "This is a very long content that should be compressed " * 20
        manager.add_bucket("long_bucket", long_content, 1.0, allocated_tokens=10)

        # Check initial state
        bucket = manager.state.buckets["long_bucket"]
        initial_tokens = bucket.token_count

        # Compress the bucket
        result = manager.compress_bucket("long_bucket")

        assert result == True
        assert bucket.is_compressed == True
        assert bucket.is_dirty == False
        assert bucket.token_count <= bucket.allocated_tokens
        assert "long_bucket" not in manager.state.dirty_buckets

    def test_compress_all(self):
        """Test compressing all buckets."""
        manager = ContextManager()

        # Add multiple buckets that need compression
        manager.add_bucket("long1", "Long content 1 " * 20, 1.0, allocated_tokens=10)
        manager.add_bucket("long2", "Long content 2 " * 20, 1.0, allocated_tokens=10)
        manager.add_bucket("short", "Short content", 1.0, allocated_tokens=100)

        # Compress all
        results = manager.compress_all()

        assert len(results) == 3
        assert results["long1"] == True
        assert results["long2"] == True
        assert (
            results["short"] == True
        )  # Should return True even if no compression needed

        # Check that buckets are properly compressed
        assert manager.state.buckets["long1"].is_compressed == True
        assert manager.state.buckets["long2"].is_compressed == True
        assert (
            manager.state.buckets["short"].is_compressed == False
        )  # No compression needed

    def test_assemble_context(self):
        """Test assembling final context."""
        manager = ContextManager()

        manager.add_bucket("system", "System prompt", 2.0)
        manager.add_bucket("task", "Task description", 1.5)
        manager.add_bucket("history", "Conversation history", 1.0)

        context = manager.assemble_context()

        assert "sections" in context
        assert "total_tokens" in context
        assert "bucket_order" in context
        assert "layout_policy" in context

        assert "system" in context["sections"]
        assert "task" in context["sections"]
        assert "history" in context["sections"]
        assert context["total_tokens"] > 0

    def test_to_messages(self):
        """Test converting to message format."""
        manager = ContextManager()

        manager.add_bucket("system", "System instructions", 2.0)
        manager.add_bucket("task", "User task", 1.5)

        messages = manager.to_messages()

        assert isinstance(messages, list)
        assert len(messages) > 0

        # Check message structure
        for message in messages:
            assert "role" in message
            assert "content" in message

    def test_clear_context(self):
        """Test clearing all context data."""
        manager = ContextManager()

        manager.add_bucket("system", "System prompt", 2.0)
        manager.add_bucket("task", "Task description", 1.5)

        assert len(manager.state.buckets) == 2
        assert manager.state.total_tokens > 0

        manager.clear()

        assert len(manager.state.buckets) == 0
        assert manager.state.total_tokens == 0
        assert manager.state.dirty_buckets == set()

    def test_get_bucket_names(self):
        """Test getting all bucket names."""
        manager = ContextManager()

        manager.add_bucket("system", "System", 2.0)
        manager.add_bucket("task", "Task", 1.5)
        manager.add_bucket("history", "History", 1.0)

        bucket_names = manager.get_bucket_names()

        assert len(bucket_names) == 3
        assert "system" in bucket_names
        assert "task" in bucket_names
        assert "history" in bucket_names

    def test_has_bucket(self):
        """Test checking if bucket exists."""
        manager = ContextManager()

        manager.add_bucket("existing", "Content", 1.0)

        assert manager.has_bucket("existing") == True
        assert manager.has_bucket("nonexistent") == False

    def test_incremental_updates(self):
        """Test incremental updates and token recalculation."""
        manager = ContextManager()

        # Add initial bucket
        manager.add_bucket("task", "Initial content", 1.0)
        initial_stats = manager.get_token_stats()
        initial_tokens = initial_stats["total_tokens"]

        # Update content (should immediately recalculate tokens)
        manager.update_bucket_content(
            "task", "Updated and longer content that should increase token count"
        )

        # After updating content, total tokens should be immediately updated
        stats_after_update = manager.get_token_stats()
        assert stats_after_update["total_tokens"] > initial_tokens
        assert manager.state.dirty_buckets == set()  # Should be cleared after update

    def test_compression_with_method(self):
        """Test compression with specific method."""
        manager = ContextManager()

        # Add content that needs compression
        long_content = (
            "This is a very long content that should be compressed using a specific method "
            * 30
        )
        manager.add_bucket("compressible", long_content, 1.0, allocated_tokens=15)

        # Try to compress with a method (even if compressor doesn't support it, should fallback)
        result = manager.compress_bucket("compressible", method="truncate")

        assert result == True
        bucket = manager.state.buckets["compressible"]
        assert bucket.is_compressed == True
        assert bucket.token_count <= bucket.allocated_tokens
