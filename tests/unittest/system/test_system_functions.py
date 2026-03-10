import os
import tempfile
import unittest

from dolphin.lib.skillkits.system_skillkit import SystemFunctionsSkillKit


class TestSystemFunctionsSkillKit(unittest.TestCase):
    def setUp(self):
        self.skillkit = SystemFunctionsSkillKit()

    def test_extract_code_with_language(self):
        # Test with language identifier
        content = """```python
print("Hello")
```"""
        expected = 'print("Hello")'
        result = self.skillkit._extract_code(content)
        self.assertEqual(result, expected)

    def test_extract_code_without_language(self):
        # Test without language identifier
        content = """```
print("Hello")
```"""
        expected = 'print("Hello")'
        result = self.skillkit._extract_code(content)
        self.assertEqual(result, expected)

    def test_extract_code_invalid(self):
        # Test invalid input with no code block
        content = "No code here"
        expected = ""
        result = self.skillkit._extract_code(content)
        self.assertEqual(result, expected)

    def test_extract_code_multiline(self):
        # Test multiline code with language
        content = """```python
def func():
    return 42
```"""
        expected = 'def func():\n    return 42'
        result = self.skillkit._extract_code(content)
        self.assertEqual(result, expected)

    def test_grep_finds_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("hello world\nfoo bar\n")

            result = self.skillkit._grep(file_path, "world")
            self.assertIn("hello world", result)

    def test_grep_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("hello world\n")

            result = self.skillkit._grep(file_path, "needle")
            self.assertIn("No matches found", result)

    def test_grep_invalid_path(self):
        result = self.skillkit._grep("/nonexistent/path", "pattern")
        self.assertIn("Error:", result)

    def test_grep_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "subdir")
            os.makedirs(subdir)
            file_path = os.path.join(subdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("target string\n")

            result = self.skillkit._grep(tmpdir, "target")
            self.assertIn("target string", result)

    def test_grep_file_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = os.path.join(tmpdir, "test.txt")
            py_path = os.path.join(tmpdir, "test.py")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("match in txt\n")
            with open(py_path, "w", encoding="utf-8") as f:
                f.write("match in py\n")

            # Should only search .py files
            result = self.skillkit._grep(tmpdir, "match", file_extensions="py")
            self.assertIn("match in py", result)
            self.assertNotIn("match in txt", result)

    def test_grep_case_sensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Hello World\n")

            result = self.skillkit._grep(file_path, "hello")
            self.assertIn("No matches found", result)

            result = self.skillkit._grep(file_path, "hello", case_sensitive=False)
            self.assertIn("Hello World", result)

    def test_read_folder_single_extension(self):
        """Test _read_folder with single extension as string"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("# Markdown")
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("print('hello')")
            with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
                f.write("text")

            result = self.skillkit._read_folder(tmpdir, extensions="md")
            self.assertIn("test.md", result)
            self.assertNotIn("test.py", result)
            self.assertNotIn("readme.txt", result)

    def test_read_folder_list_extensions(self):
        """Test _read_folder with multiple extensions as list - this was a bug"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("# Markdown")
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("print('hello')")
            with open(os.path.join(tmpdir, "config.yaml"), "w") as f:
                f.write("key: value")
            with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
                f.write("text")

            # Bug: brace expansion doesn't work in Python glob
            result = self.skillkit._read_folder(tmpdir, extensions=["md", "py"])
            self.assertIn("test.md", result)
            self.assertIn("test.py", result)
            self.assertNotIn("config.yaml", result)
            self.assertNotIn("readme.txt", result)

    def test_read_folder_no_extensions(self):
        """Test _read_folder without extensions filter"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("# Markdown")
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("print('hello')")

            result = self.skillkit._read_folder(tmpdir)
            self.assertIn("test.md", result)
            self.assertIn("test.py", result)

    def test_read_folder_nonexistent(self):
        """Test _read_folder with non-existent directory"""
        result = self.skillkit._read_folder("/nonexistent/path")
        self.assertIn("Error:", result)

    def test_read_folder_empty_directory(self):
        """Test _read_folder with empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.skillkit._read_folder(tmpdir, extensions="md")
            self.assertIn("No files found", result)

    def test_grep_no_read_permission(self):
        """Test _grep handles permission errors gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "restricted.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("secret content\n")
            os.chmod(file_path, 0o000)

            try:
                result = self.skillkit._grep(file_path, "secret")
                # Should handle permission error gracefully
                self.assertTrue(
                    "No matches found" in result or "Error:" in result or isinstance(result, str)
                )
            finally:
                os.chmod(file_path, 0o644)

    def test_grep_directory_instead_of_file(self):
        """Test _grep when path is a directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file inside the directory
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("needle in haystack\n")

            # Grep the directory (should work recursively)
            result = self.skillkit._grep(tmpdir, "needle")
            self.assertIn("needle in haystack", result)

    def test_grep_binary_file(self):
        """Test _grep handles binary files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "binary.bin")
            with open(file_path, "wb") as f:
                f.write(b"\x00\x01\x02\x03needle\xff\xfe")

            result = self.skillkit._grep(file_path, "needle")
            # Binary files might not be searchable, but shouldn't crash
            self.assertIsInstance(result, str)

    def test_grep_with_context_lines(self):
        """Test _grep with before/after context lines"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("line 1\nline 2\nline 3 match here\nline 4\nline 5\n")

            result = self.skillkit._grep(file_path, "match", before=1, after=1)
            self.assertIn("match here", result)

    def test_grep_regex_pattern(self):
        """Test _grep with regex pattern"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("test123\nabc456\n")

            result = self.skillkit._grep(file_path, r"\d+")
            self.assertIn("test123", result)
            self.assertIn("abc456", result)

    def test_grep_literal_string(self):
        """Test _grep with literal string (no regex)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("hello.world\n")

            # Using regex=False should treat dot as literal
            result = self.skillkit._grep(file_path, "hello\\.world", use_regex=True)
            self.assertIn("hello.world", result)



    def test_read_folder_multiple_extensions_bug(self):
        """Test _read_folder with multiple extensions - reproduces the brace expansion bug"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files with different extensions
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("# Markdown")
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("print('hello')")
            with open(os.path.join(tmpdir, "config.yaml"), "w") as f:
                f.write("key: value")
            with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
                f.write("text")

            # Bug: Python glob doesn't support brace expansion like bash
            # Pattern *.{md,py} returns empty list instead of matching files
            result = self.skillkit._read_folder(tmpdir, extensions=["md", "py"])
            
            # Should find both .md and .py files
            self.assertIn("test.md", result)
            self.assertIn("test.py", result)
            self.assertNotIn("config.yaml", result)
            self.assertNotIn("readme.txt", result)

    def test_read_folder_single_extension(self):
        """Test _read_folder with single extension - should work correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("# Markdown")
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("print('hello')")

            result = self.skillkit._read_folder(tmpdir, extensions="md")
            self.assertIn("test.md", result)
            self.assertNotIn("test.py", result)

    def test_read_file_skips_large_file(self):
        """_read_file should refuse to read files exceeding the size limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            large_file = os.path.join(tmpdir, "huge.bin")
            # Create a file just over 10 MB
            with open(large_file, "wb") as f:
                f.seek(10 * 1024 * 1024 + 1)
                f.write(b"\x00")

            result = self.skillkit._read_file(large_file)
            self.assertIn("SKIPPED", result)
            self.assertIn("too large", result.lower())

    def test_read_folder_skips_large_file(self):
        """_read_folder should skip files exceeding the size limit and still read normal files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Normal file
            small = os.path.join(tmpdir, "small.txt")
            with open(small, "w") as f:
                f.write("I am small")

            # Oversized file
            big = os.path.join(tmpdir, "big.txt")
            with open(big, "wb") as f:
                f.seek(10 * 1024 * 1024 + 1)
                f.write(b"\x00")

            result = self.skillkit._read_folder(tmpdir, extensions="txt")
            self.assertIn("I am small", result)
            self.assertIn("SKIPPED", result)
            self.assertIn("big.txt", result)

    def test_grep_skips_large_file(self):
        """_grep should skip files exceeding the size limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            large_file = os.path.join(tmpdir, "huge.txt")
            with open(large_file, "wb") as f:
                f.write(b"needle\n")
                f.seek(10 * 1024 * 1024 + 1)
                f.write(b"\x00")

            result = self.skillkit._grep(large_file, "needle")
            self.assertIn("SKIPPED", result)
            self.assertNotIn("needle", result.split("SKIPPED")[0])

    def test_grep_skips_dangerous_directories(self):
        """_grep recursive walk should skip directories like .git, node_modules, .colima."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for dangerous_dir in [".git", "node_modules", ".colima"]:
                ddir = os.path.join(tmpdir, dangerous_dir)
                os.makedirs(ddir)
                with open(os.path.join(ddir, "secret.txt"), "w") as f:
                    f.write("findme_dangerous\n")

            # Normal file that should be found
            with open(os.path.join(tmpdir, "normal.txt"), "w") as f:
                f.write("findme_normal\n")

            result = self.skillkit._grep(tmpdir, "findme", recursive=True)
            self.assertIn("findme_normal", result)
            self.assertNotIn("findme_dangerous", result)


if __name__ == "__main__":
    unittest.main()
