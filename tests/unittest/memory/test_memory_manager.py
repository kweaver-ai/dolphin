"""
Unit tests for the memory manager.
"""

import unittest
import tempfile
import shutil
import time
from unittest.mock import Mock, patch


from dolphin.lib.memory.manager import MemoryManager
from dolphin.core.config.global_config import MemoryConfig, GlobalConfig
from dolphin.core.common.enums import KnowledgePoint, Messages, SingleMessage
import pytest


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self):
        self.call_count = 0
        self.extraction_response = None
        self.merge_response = None
        # Mock config attribute
        self.config = Mock()
        mock_model_config = Mock()
        mock_model_config.name = "mock_model"
        self.config.get_fast_model_config.return_value = mock_model_config

    def mf_chat(self, messages: Messages, model=None, temperature=None, **kwargs):
        """Mock mf_chat method to match LLMClient interface."""
        self.call_count += 1

        # Get the prompt from the user message
        prompt = messages.first().content if messages else ""

        if "知识管理专家" in prompt or "extract valuable knowledge" in prompt:
            # Return mock extraction result
            return (
                self.extraction_response
                or """{"content": "User prefers Python programming", "type": "OtherKnowledge", "score": 85, "metadata": {}}
{"content": "Machine learning requires data preprocessing", "type": "ExperientialKnowledge", "score": 90, "metadata": {}}"""
            )

        elif "智能合并" in prompt or "perform intelligent merging" in prompt:
            # Return mock merge result
            return (
                self.merge_response
                or """[
    {"content": "User prefers Python programming", "type": "OtherKnowledge", "score": 85, "user_id": "test_user", "metadata": {}},
    {"content": "Machine learning requires data preprocessing", "type": "ExperientialKnowledge", "score": 90, "user_id": "test_user", "metadata": {}}
]"""
            )

        return "Mock response"


@pytest.mark.skip(
    reason="These tests were written for a different MemoryManager API that is not currently implemented"
)
class TestMemoryManager(unittest.TestCase):
    """Test cases for memory manager."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

        # Create memory config
        memory_config = MemoryConfig(
            enabled=True, storage_path=self.temp_dir, default_top_k=10
        )

        # Create mock global config
        self.mock_global_config = Mock(spec=GlobalConfig)
        self.mock_global_config.memory_config = memory_config

        # Create manager with mocked global config
        self.manager = MemoryManager(self.mock_global_config)
        self.storage = self.manager.memory_storage

        # Create mock context and LLM client
        self.mock_context = Mock()
        self.mock_llm_client = MockLLMClient()

        # Sample conversation for testing (as Messages object)
        self.sample_conversation = Messages()
        self.sample_conversation.clear_messages()
        self.sample_conversation.extend_plain_messages(
            [
                {
                    "role": "user",
                    "content": "I love Python programming",
                    "timestamp": "2023-10-27T12:00:00Z",
                    "user_id": "test_user",
                    "metadata": {},
                },
                {
                    "role": "assistant",
                    "content": "Python is a great language! What do you like most about it?",
                    "timestamp": "2023-10-27T12:00:05Z",
                    "user_id": "test_user",
                    "metadata": {},
                },
                {
                    "role": "user",
                    "content": "I like its simplicity and the machine learning libraries",
                    "timestamp": "2023-10-27T12:00:10Z",
                    "user_id": "test_user",
                    "metadata": {},
                },
            ]
        )

        # Sample external messages without user_id (as Messages object)
        self.external_messages = Messages()
        self.external_messages.clear_messages()
        self.external_messages.extend_plain_messages(
            [
                {"role": "user", "content": "I love Python programming"},
                {
                    "role": "assistant",
                    "content": "Python is a great language! What do you like most about it?",
                },
                {
                    "role": "user",
                    "content": "I like its simplicity and the machine learning libraries",
                },
            ]
        )

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir)

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_extract_knowledge_sync(self, mock_create_llm_client):
        """Test synchronous knowledge extraction."""
        mock_create_llm_client.return_value = self.mock_llm_client

        self.manager.extract_knowledge_sync(
            "test_user",
            self.sample_conversation,
            self.mock_context,
            auto_merge=False,  # Disable auto merge for testing staging
        )

        # Verify LLM was called
        self.assertGreater(self.mock_llm_client.call_count, 0)

        # Verify knowledge was saved as a new version
        latest_version = self.storage.get_latest_version_id("test_user")
        self.assertIsNotNone(latest_version)
        self.assertNotEqual(latest_version, "")

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_extract_knowledge_sync_with_conversation_messages(
        self, mock_create_llm_client
    ):
        """Test synchronous knowledge extraction with SingleMessage format."""
        mock_create_llm_client.return_value = self.mock_llm_client

        self.manager.extract_knowledge_sync(
            "test_user",
            self.sample_conversation,
            self.mock_context,
            auto_merge=False,  # Disable auto merge for testing
        )

        # Wait a bit for the background thread
        time.sleep(0.1)

        # Verify knowledge was saved as a new version
        latest_version = self.storage.get_latest_version_id("test_user")
        self.assertIsNotNone(latest_version)
        self.assertNotEqual(latest_version, "")

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_extract_knowledge_sync_with_external_messages(
        self, mock_create_llm_client
    ):
        """Test synchronous knowledge extraction with external Dict format."""
        mock_create_llm_client.return_value = self.mock_llm_client

        self.manager.extract_knowledge_sync(
            user_id="test_user",
            messages=self.external_messages,
            context=self.mock_context,
            auto_merge=False,  # Disable auto merge for testing
        )

        # Wait a bit for the background thread
        time.sleep(0.1)

        # Verify knowledge was saved as a new version
        latest_version = self.storage.get_latest_version_id("test_user")
        self.assertIsNotNone(latest_version)
        self.assertNotEqual(latest_version, "")

    def test_extract_knowledge_sync_missing_user_id(self):
        """Test error when user_id is missing for external messages."""
        with self.assertRaises(TypeError):
            self.manager.extract_knowledge_sync(
                messages=self.external_messages, context=self.mock_context
            )

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_parse_extraction_result(self, mock_create_llm_client):
        """Test parsing of LLM extraction results."""
        mock_create_llm_client.return_value = self.mock_llm_client

        # Create extractor for testing
        from dolphin.lib.memory.llm_calls import KnowledgeExtractionCall

        extractor = KnowledgeExtractionCall(
            self.mock_llm_client, self.manager.memory_config
        )

        extraction_text = """{"content": "User prefers Python", "type": "OtherKnowledge", "score": 85, "metadata": {"test": true}}
{"content": "Python is simple", "type": "WorldModel", "score": 90, "metadata": {}}"""

        result = extractor._post_process(extraction_text, "test_user")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "User prefers Python")
        self.assertEqual(result[0].type, "OtherKnowledge")
        self.assertEqual(result[0].score, 85)
        self.assertEqual(result[0].user_id, "test_user")
        self.assertIn("extraction_time", result[0].metadata)

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_parse_extraction_result_invalid_lines(self, mock_create_llm_client):
        """Test parsing with some invalid lines."""
        mock_create_llm_client.return_value = self.mock_llm_client

        # Create extractor for testing
        from dolphin.lib.memory.llm_calls import KnowledgeExtractionCall

        extractor = KnowledgeExtractionCall(
            self.mock_llm_client, self.manager.memory_config
        )

        extraction_text = """{"content": "Valid knowledge", "type": "WorldModel", "score": 85, "metadata": {}}
invalid json line
{"content": "Another valid", "type": "OtherKnowledge", "score": 75, "metadata": {}}
{"invalid": "missing required fields"}"""

        result = extractor._post_process(extraction_text, "test_user")

        # Should only return valid knowledge points
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "Valid knowledge")
        self.assertEqual(result[1].content, "Another valid")

    def test_retrieve_relevant_knowledge_empty(self):
        """Test retrieving knowledge when none exists."""
        result = self.manager.retrieve_relevant_knowledge(
            "test_user", "Python programming"
        )
        self.assertEqual(result, [])

    def test_retrieve_relevant_knowledge_with_data(self):
        """Test retrieving relevant knowledge with actual data."""
        # Save some knowledge first
        sample_knowledge = [
            KnowledgePoint(
                content="Python is a programming language",
                type="WorldModel",
                score=90,
                user_id="test_user",
                metadata={},
            ),
            KnowledgePoint(
                content="User prefers blue color",
                type="OtherKnowledge",
                score=70,
                user_id="test_user",
                metadata={},
            ),
            KnowledgePoint(
                content="Machine learning with Python is powerful",
                type="ExperientialKnowledge",
                score=85,
                user_id="test_user",
                metadata={},
            ),
        ]

        version_id = "20231027_120000"
        self.storage.save_knowledge("test_user", version_id, sample_knowledge)

        # Query for Python-related knowledge
        result = self.manager.retrieve_relevant_knowledge(
            "test_user", "Python programming", top_k=2
        )

        # Should return Python-related knowledge, sorted by relevance and score
        self.assertLessEqual(len(result), 2)

        for point in result:
            self.assertIn("python", point.content.lower())

    def test_retrieve_relevant_knowledge_score_threshold(self):
        """Test that low-scored knowledge is filtered out."""
        # Save knowledge with low score
        low_score_knowledge = [
            KnowledgePoint(
                content="Python programming tips",
                type="ExperientialKnowledge",
                score=10,  # Below default threshold of 20
                user_id="test_user",
                metadata={},
            )
        ]

        version_id = "20231027_120000"
        self.storage.save_knowledge("test_user", version_id, low_score_knowledge)

        # Query should return empty due to score threshold
        result = self.manager.retrieve_relevant_knowledge("test_user", "Python")
        self.assertEqual(result, [])

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_llm_failure_fallback(self, mock_create_llm_client):
        """Test fallback behavior when LLM calls fail."""
        # Configure mock to fail
        self.mock_llm_client.extraction_response = "invalid json response"
        mock_create_llm_client.return_value = self.mock_llm_client

        # Should not raise exception, should handle gracefully
        self.manager.extract_knowledge_sync(
            "test_user", self.sample_conversation, self.mock_context
        )

        # Should handle gracefully even if LLM fails
        # May or may not have saved anything, but shouldn't crash

    @patch("src.dolphin.lib.memory.manager.MemoryManager._create_llm_client")
    def test_user_isolation_in_manager(self, mock_create_llm_client):
        """Test that manager operations respect user isolation."""
        mock_create_llm_client.return_value = self.mock_llm_client

        user1_conversation = [
            SingleMessage(
                role="user",
                content="User 1 message",
                timestamp="2023-10-27T12:00:00Z",
                user_id="user1",
                metadata={},
            )
        ]

        user2_conversation = [
            SingleMessage(
                role="user",
                content="User 2 message",
                timestamp="2023-10-27T12:00:00Z",
                user_id="user2",
                metadata={},
            )
        ]

        # Extract knowledge for both users (knowledge will be saved directly as new versions)
        self.manager.extract_knowledge_sync(
            "user1", user1_conversation, self.mock_context, auto_merge=False
        )
        self.manager.extract_knowledge_sync(
            "user2", user2_conversation, self.mock_context, auto_merge=False
        )

        # Wait for processing to complete
        time.sleep(0.1)

        # Verify each user gets their own knowledge
        user1_knowledge = self.manager.retrieve_relevant_knowledge("user1", "message")
        user2_knowledge = self.manager.retrieve_relevant_knowledge("user2", "message")

        # Each should have their own knowledge
        for point in user1_knowledge:
            self.assertEqual(point.user_id, "user1")

        for point in user2_knowledge:
            self.assertEqual(point.user_id, "user2")


if __name__ == "__main__":
    unittest.main()
