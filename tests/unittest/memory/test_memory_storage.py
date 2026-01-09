"""
Unit tests for the memory storage layer.
"""

import unittest
import tempfile
import shutil
import pytest

from dolphin.lib.memory.storage import MemoryFileSys
from dolphin.core.common.enums import KnowledgePoint


@pytest.mark.skip(
    reason="These tests were written for a different storage API that is not currently implemented"
)
class TestMemoryFileSys(unittest.TestCase):
    """Test cases for file system storage implementation."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        # Create a mock memory config for testing
        from dolphin.core.config.global_config import MemoryConfig

        self.memory_config = MemoryConfig(enabled=True, default_top_k=5)
        self.storage = MemoryFileSys(self.temp_dir)
        self.test_user_id = "test_user_123"

        # Sample knowledge points for testing
        self.sample_knowledge = [
            KnowledgePoint(
                content="User prefers blue color",
                type="OtherKnowledge",
                score=85,
                user_id=self.test_user_id,
                metadata={"session_id": "session_1"},
            ),
            KnowledgePoint(
                content="Python is a programming language",
                type="WorldModel",
                score=95,
                user_id=self.test_user_id,
                metadata={"session_id": "session_1"},
            ),
        ]

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir)

    def test_user_path_creation(self):
        """Test that user paths are created correctly."""
        user_dir, versions_dir, latest_file = self.storage._get_user_paths(
            self.test_user_id
        )

        self.assertTrue(versions_dir.exists())
        self.assertEqual(user_dir.name, f"user_{self.test_user_id}")

    def test_save_and_load_knowledge(self):
        """Test saving and loading knowledge."""
        version_id = "20231027_120000"

        # Save knowledge
        self.storage.save_knowledge(
            self.test_user_id, version_id, self.sample_knowledge
        )

        # Load knowledge
        loaded_knowledge = self.storage.load_knowledge(self.test_user_id, version_id)

        self.assertEqual(len(loaded_knowledge), 2)
        self.assertEqual(loaded_knowledge[0].content, "User prefers blue color")
        self.assertEqual(
            loaded_knowledge[1].content, "Python is a programming language"
        )

        # Verify user_id is properly set
        for point in loaded_knowledge:
            self.assertEqual(point.user_id, self.test_user_id)

    def test_latest_version_management(self):
        """Test latest version tracking."""
        version1 = "20231027_120000"
        version2 = "20231027_130000"

        # Initially no latest version
        self.assertEqual(self.storage.get_latest_version_id(self.test_user_id), "")

        # Save first version
        self.storage.save_knowledge(self.test_user_id, version1, self.sample_knowledge)
        self.assertEqual(
            self.storage.get_latest_version_id(self.test_user_id), version1
        )

        # Save second version
        self.storage.save_knowledge(self.test_user_id, version2, self.sample_knowledge)
        self.assertEqual(
            self.storage.get_latest_version_id(self.test_user_id), version2
        )

        # Load latest
        loaded = self.storage.load_knowledge(self.test_user_id, "latest")
        self.assertEqual(len(loaded), 2)

    def test_user_isolation(self):
        """Test that different users have isolated storage."""
        user1 = "user_1"
        user2 = "user_2"
        version_id = "20231027_120000"

        knowledge1 = [
            KnowledgePoint(
                content="User 1 knowledge",
                type="OtherKnowledge",
                score=80,
                user_id=user1,
                metadata={},
            )
        ]

        knowledge2 = [
            KnowledgePoint(
                content="User 2 knowledge",
                type="OtherKnowledge",
                score=90,
                user_id=user2,
                metadata={},
            )
        ]

        # Save knowledge for both users
        self.storage.save_knowledge(user1, version_id, knowledge1)
        self.storage.save_knowledge(user2, version_id, knowledge2)

        # Load knowledge for each user
        loaded1 = self.storage.load_knowledge(user1, version_id)
        loaded2 = self.storage.load_knowledge(user2, version_id)

        # Verify isolation
        self.assertEqual(len(loaded1), 1)
        self.assertEqual(len(loaded2), 1)
        self.assertEqual(loaded1[0].content, "User 1 knowledge")
        self.assertEqual(loaded2[0].content, "User 2 knowledge")
        self.assertEqual(loaded1[0].user_id, user1)
        self.assertEqual(loaded2[0].user_id, user2)

    def test_sanitized_user_id(self):
        """Test that user IDs are properly sanitized for filesystem."""
        problematic_user_id = "user@domain.com/special#chars"

        # Should not raise an error
        user_dir, _, _ = self.storage._get_user_paths(problematic_user_id)

        # Directory should be created with sanitized name
        self.assertTrue(user_dir.exists())
        self.assertNotIn("@", user_dir.name)
        self.assertNotIn("/", user_dir.name)
        self.assertNotIn("#", user_dir.name)

    def test_empty_load(self):
        """Test loading from non-existent version/user."""
        # Load from non-existent user
        result = self.storage.load_knowledge("non_existent_user", "latest")
        self.assertEqual(result, [])

        # Load from non-existent version
        result = self.storage.load_knowledge(self.test_user_id, "non_existent_version")
        self.assertEqual(result, [])

    def test_get_recent_versions(self):
        """Test getting recent versions."""
        # Initially no versions
        recent = self.storage.get_recent_versions(self.test_user_id, 3)
        self.assertEqual(recent, [])

        # Save multiple versions
        version1 = "20231027_120000"
        version2 = "20231027_130000"
        version3 = "20231027_140000"

        self.storage.save_knowledge(self.test_user_id, version1, self.sample_knowledge)
        self.storage.save_knowledge(self.test_user_id, version2, self.sample_knowledge)
        self.storage.save_knowledge(self.test_user_id, version3, self.sample_knowledge)

        # Get recent versions (should be in reverse chronological order)
        recent = self.storage.get_recent_versions(self.test_user_id, 2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0], version3)  # Most recent first
        self.assertEqual(recent[1], version2)

        # Get all versions
        recent = self.storage.get_recent_versions(self.test_user_id, 5)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0], version3)
        self.assertEqual(recent[1], version2)
        self.assertEqual(recent[2], version1)

    def test_load_knowledge_with_sampling(self):
        """Test loading knowledge with probability sampling when version_id is None."""
        # Create multiple versions with different knowledge
        version1 = "20231027_120000"
        version2 = "20231027_130000"
        version3 = "20231027_140000"

        knowledge_v1 = [
            KnowledgePoint(
                content="High score knowledge v1",
                type="WorldModel",
                score=90,
                user_id=self.test_user_id,
                metadata={"version": "v1"},
            ),
            KnowledgePoint(
                content="Low score knowledge v1",
                type="OtherKnowledge",
                score=10,  # Below threshold
                user_id=self.test_user_id,
                metadata={"version": "v1"},
            ),
        ]

        knowledge_v2 = [
            KnowledgePoint(
                content="Medium score knowledge v2",
                type="ExperientialKnowledge",
                score=70,
                user_id=self.test_user_id,
                metadata={"version": "v2"},
            )
        ]

        knowledge_v3 = [
            KnowledgePoint(
                content="High score knowledge v3",
                type="WorldModel",
                score=95,
                user_id=self.test_user_id,
                metadata={"version": "v3"},
            )
        ]

        # Save all versions
        self.storage.save_knowledge(self.test_user_id, version1, knowledge_v1)
        self.storage.save_knowledge(self.test_user_id, version2, knowledge_v2)
        self.storage.save_knowledge(self.test_user_id, version3, knowledge_v3)

        # Test sampling with version_id=None
        sampled = self.storage.load_knowledge(
            self.test_user_id, version_id="latest", top_k=2
        )

        # Should only return knowledge above threshold (score >= 20)
        # and should be a subset of the available knowledge
        self.assertGreater(len(sampled), 0)
        self.assertLessEqual(len(sampled), 1)  # Requested top_k=2

        # All returned knowledge should have score >= threshold
        for point in sampled:
            self.assertGreaterEqual(point.score, 20)
            self.assertEqual(point.user_id, self.test_user_id)

    def test_load_knowledge_sampling_empty_case(self):
        """Test sampling when no versions exist or all scores are below threshold."""
        # No versions exist
        result = self.storage.load_knowledge(self.test_user_id, version_id=None)
        self.assertEqual(result, [])

        # Save knowledge with all scores below threshold
        low_score_knowledge = [
            KnowledgePoint(
                content="Very low score knowledge",
                type="OtherKnowledge",
                score=5,  # Below threshold
                user_id=self.test_user_id,
                metadata={},
            )
        ]

        version_id = "20231027_120000"
        self.storage.save_knowledge(self.test_user_id, version_id, low_score_knowledge)

        # Should return empty list since all scores are below threshold
        result = self.storage.load_knowledge(self.test_user_id, version_id=None)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
