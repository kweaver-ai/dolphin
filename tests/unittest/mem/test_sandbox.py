import tempfile
import unittest
from pathlib import Path
import os
import shutil

from dolphin.lib.memory.sandbox import MemorySandbox


class TestMemorySandbox(unittest.TestCase):
    """Test MemorySandbox path validation and security features"""

    def setUp(self):
        # Use a temporary directory for testing
        self.temp_dir = tempfile.mkdtemp()
        self.sandbox = MemorySandbox(self.temp_dir)

    def tearDown(self):
        # Clean up temporary directory
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_reject_absolute_path(self):
        """Test that absolute paths are rejected"""
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.resolve_session_path("test", "/absolute/path.json")
        self.assertIn("relative", str(ctx.exception).lower())

    def test_reject_directory_traversal(self):
        """Test that directory traversal attempts are rejected"""
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.resolve_session_path("test", "../escape.json")
        self.assertIn("escapes", str(ctx.exception).lower())

    def test_reject_directory_traversal_nested(self):
        """Test that nested directory traversal is rejected"""
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.resolve_session_path("test", "foo/../../escape.json")
        self.assertIn("escapes", str(ctx.exception).lower())

    def test_reject_non_json(self):
        """Test that non-JSON files are rejected"""
        test_cases = [
            "file.txt",
            "data.xml",
            "script.py",
            "malware.exe",
            "config.yaml",
        ]
        for filename in test_cases:
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError) as ctx:
                    self.sandbox.resolve_session_path("test", filename)
                self.assertIn("json", str(ctx.exception).lower())

    def test_reject_empty_session_id(self):
        """Test that empty session_id is rejected"""
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.resolve_session_path("", "test.json")
        self.assertIn("session_id", str(ctx.exception).lower())

    def test_reject_empty_path(self):
        """Test that empty relative path is rejected"""
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.resolve_session_path("test", "")
        self.assertIn("relative", str(ctx.exception).lower())

    def test_reject_too_long_path(self):
        """Test that paths exceeding MAX_PATH_LENGTH are rejected"""
        # Create a path longer than 512 characters
        long_path = "a/" * 300 + "test.json"
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.resolve_session_path("test", long_path)
        self.assertIn("long", str(ctx.exception).lower())

    def test_accept_valid_simple_path(self):
        """Test that valid simple paths are accepted"""
        result = self.sandbox.resolve_session_path("test_session", "backup.json")
        self.assertIsInstance(result, Path)
        self.assertIn("test_session", str(result))
        self.assertIn("backup.json", str(result))
        self.assertTrue(str(result).endswith("backup.json"))

    def test_accept_valid_nested_path(self):
        """Test that valid nested paths are accepted"""
        result = self.sandbox.resolve_session_path("test_session", "subdir/data.json")
        self.assertIsInstance(result, Path)
        self.assertIn("test_session", str(result))
        self.assertIn("subdir", str(result))
        self.assertIn("data.json", str(result))

    def test_path_within_session_directory(self):
        """Test that resolved paths are within the session directory"""
        result = self.sandbox.resolve_session_path("test_session", "backup.json")
        # The path should contain memories/test_session
        self.assertIn("memories", str(result))
        self.assertIn("test_session", str(result))

    def test_session_isolation(self):
        """Test that different sessions get different directories"""
        path_a = self.sandbox.resolve_session_path("session_a", "test.json")
        path_b = self.sandbox.resolve_session_path("session_b", "test.json")

        # Paths should be different
        self.assertNotEqual(path_a, path_b)
        # Each should be in its respective session directory
        self.assertIn("session_a", str(path_a))
        self.assertIn("session_b", str(path_b))

    def test_creates_parent_directories(self):
        """Test that parent directories are created automatically"""
        result = self.sandbox.resolve_session_path("test_session", "a/b/c/data.json")
        # The parent directories should be created
        self.assertTrue(result.parent.exists())
        self.assertEqual(result.name, "data.json")

    def test_check_size_bytes_accepts_valid_size(self):
        """Test that valid file sizes are accepted"""
        # Should not raise for sizes under 10MB
        self.sandbox.check_size_bytes(1024)  # 1KB
        self.sandbox.check_size_bytes(1024 * 1024)  # 1MB
        self.sandbox.check_size_bytes(5 * 1024 * 1024)  # 5MB

    def test_check_size_bytes_rejects_oversized(self):
        """Test that oversized files are rejected"""
        # Should raise for sizes over 10MB
        with self.assertRaises(ValueError) as ctx:
            self.sandbox.check_size_bytes(11 * 1024 * 1024)  # 11MB
        self.assertIn("large", str(ctx.exception).lower())

    def test_case_insensitive_json_extension(self):
        """Test that .JSON (uppercase) is also accepted"""
        # .json should work (already tested)
        result1 = self.sandbox.resolve_session_path("test", "file.json")
        self.assertIsNotNone(result1)

        # .JSON should also work due to case-insensitive check
        result2 = self.sandbox.resolve_session_path("test", "file.JSON")
        self.assertIsNotNone(result2)


class TestMemorySandboxEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sandbox = MemorySandbox(self.temp_dir)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_path_with_special_characters(self):
        """Test paths with special but valid characters"""
        # These should be accepted (common in filenames)
        valid_paths = [
            "backup-2024.json",
            "data_v1.json",
            "my.backup.json",
        ]
        for path in valid_paths:
            with self.subTest(path=path):
                result = self.sandbox.resolve_session_path("test", path)
                self.assertIsInstance(result, Path)

    def test_deeply_nested_path(self):
        """Test a valid deeply nested path"""
        path = "a/b/c/d/e/f/data.json"
        result = self.sandbox.resolve_session_path("test", path)
        self.assertIsInstance(result, Path)
        self.assertTrue(result.parent.exists())

    def test_root_initialization(self):
        """Test that sandbox root is created on init"""
        new_temp = tempfile.mkdtemp()
        try:
            sandbox = MemorySandbox(new_temp)
            # The memories directory should be created
            memories_dir = Path(new_temp) / "memories"
            self.assertTrue(memories_dir.exists())
            self.assertTrue(memories_dir.is_dir())
        finally:
            if os.path.exists(new_temp):
                shutil.rmtree(new_temp)


if __name__ == "__main__":
    unittest.main()
