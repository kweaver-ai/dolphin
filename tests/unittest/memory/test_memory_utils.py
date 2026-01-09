"""
Unit tests for utility functions.
"""

import unittest

from dolphin.core.common.enums import KnowledgePoint
from dolphin.lib.memory.utils import validate_knowledge_point, sanitize_user_id


class TestUtilityFunctions(unittest.TestCase):
    """Test cases for utility functions."""

    def test_validate_knowledge_point_valid(self):
        """Test validation of valid knowledge points."""
        valid_data = {
            "content": "Test knowledge",
            "type": "WorldModel",
            "score": 85,
            "user_id": "test_user",
            "metadata": {"source": "test"},
        }

        result = validate_knowledge_point(KnowledgePoint(**valid_data))

        self.assertEqual(result.content, "Test knowledge")
        self.assertEqual(result.type, "WorldModel")
        self.assertEqual(result.score, 85)
        self.assertEqual(result.user_id, "test_user")
        self.assertEqual(result.metadata, {"source": "test"})

    def test_validate_knowledge_point_missing_fields(self):
        """Test validation with missing required fields."""
        incomplete_data = {
            "content": "Test knowledge",
            "type": "WorldModel",
            # Missing score and user_id
        }

        with self.assertRaises(Exception) as context:
            validate_knowledge_point(incomplete_data)

    def test_validate_knowledge_point_invalid_type(self):
        """Test validation with invalid knowledge type."""
        invalid_data = {
            "content": "Test knowledge",
            "type": "InvalidType",
            "score": 85,
            "user_id": "test_user",
        }

        with self.assertRaises(Exception) as context:
            validate_knowledge_point(invalid_data)

    def test_validate_knowledge_point_invalid_score(self):
        """Test validation with invalid score values."""
        # Test non-integer score
        invalid_data1 = {
            "content": "Test knowledge",
            "type": "WorldModel",
            "score": "85",  # String instead of int
            "user_id": "test_user",
        }

        with self.assertRaises(Exception):
            validate_knowledge_point(KnowledgePoint(**invalid_data1))

        # Test out-of-range score
        invalid_data2 = {
            "content": "Test knowledge",
            "type": "WorldModel",
            "score": 150,  # > 100
            "user_id": "test_user",
        }

        with self.assertRaises(Exception):
            validate_knowledge_point(KnowledgePoint(**invalid_data2))

        # Test negative score
        invalid_data3 = {
            "content": "Test knowledge",
            "type": "WorldModel",
            "score": -10,  # < 0
            "user_id": "test_user",
        }

        with self.assertRaises(Exception):
            validate_knowledge_point(KnowledgePoint(**invalid_data3))

    def test_validate_knowledge_point_user_id_mismatch(self):
        """Test validation with user ID mismatch."""
        data = {
            "content": "Test knowledge",
            "type": "WorldModel",
            "score": 85,
            "user_id": "user1",
        }

        with self.assertRaises(Exception) as context:
            validate_knowledge_point(KnowledgePoint(**data), expected_user_id="user2")

        self.assertIn("User ID mismatch", str(context.exception))

    def test_validate_knowledge_point_missing_metadata(self):
        """Test validation with missing metadata (should provide default)."""
        data = KnowledgePoint(
            content="Test knowledge", type="WorldModel", score=85, user_id="test_user"
        )

        result = validate_knowledge_point(data)
        self.assertEqual(result.metadata, {})

    def test_sanitize_user_id_normal(self):
        """Test sanitizing normal user IDs."""
        normal_id = "user123"
        result = sanitize_user_id(normal_id)
        self.assertEqual(result, "user123")

    def test_sanitize_user_id_special_chars(self):
        """Test sanitizing user IDs with special characters."""
        problematic_id = "user@domain.com/test#123"
        result = sanitize_user_id(problematic_id)

        # Should not contain problematic characters
        self.assertNotIn("@", result)
        self.assertNotIn("/", result)
        self.assertNotIn("#", result)

        # Should contain underscores as replacements
        self.assertIn("_", result)

    def test_sanitize_user_id_length_limit(self):
        """Test that user ID sanitization respects length limits."""
        long_id = "a" * 100  # Very long user ID
        result = sanitize_user_id(long_id)

        # Should be limited to 50 characters
        self.assertLessEqual(len(result), 50)

    def test_knowledge_types_exhaustive(self):
        """Test all valid knowledge types."""
        valid_types = ["WorldModel", "ExperientialKnowledge", "OtherKnowledge"]

        for knowledge_type in valid_types:
            data = KnowledgePoint(
                content=f"Test {knowledge_type}",
                type=knowledge_type,
                score=75,
                user_id="test_user",
            )

            # Should not raise exception
            result = validate_knowledge_point(data)
            self.assertEqual(result.type, knowledge_type)


if __name__ == "__main__":
    unittest.main()
