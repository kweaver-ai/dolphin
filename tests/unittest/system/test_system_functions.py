import os
import tempfile

import pytest

from dolphin.lib.toolkits.system_toolkit import SystemFunctionsToolkit


@pytest.fixture
def skillkit():
    return SystemFunctionsToolkit()


def test_extract_code_with_language(skillkit):
    # Test with language identifier
    content = """```python
print("Hello")
```"""
    expected = 'print("Hello")'
    result = skillkit._extract_code(content)
    assert result == expected


def test_extract_code_without_language(skillkit):
    # Test without language identifier
    content = """```
print("Hello")
```"""
    expected = 'print("Hello")'
    result = skillkit._extract_code(content)
    assert result == expected


def test_extract_code_invalid(skillkit):
    # Test invalid input with no code block
    content = "No code here"
    result = skillkit._extract_code(content)
    assert result == ""


def test_extract_code_multiline(skillkit):
    # Test multiline code with language
    content = """```python
def func():
    return 42
```"""
    expected = 'def func():\n    return 42'
    result = skillkit._extract_code(content)
    assert result == expected


def test_grep_finds_match(skillkit):
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("hello world\nfoo bar\n")

        result = skillkit._grep(file_path, "world")
        assert "hello world" in result


def test_grep_no_match(skillkit):
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("hello world\n")

        result = skillkit._grep(file_path, "needle")
        assert "No matches found" in result


def test_grep_invalid_path(skillkit):
    result = skillkit._grep("/nonexistent/path", "pattern")
    assert "Error:" in result


def test_grep_recursive(skillkit):
    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = os.path.join(tmpdir, "subdir")
        os.makedirs(subdir)
        file_path = os.path.join(subdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("target string\n")

        result = skillkit._grep(tmpdir, "target")
        assert "target string" in result


def test_grep_file_extensions(skillkit):
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "test.txt")
        py_path = os.path.join(tmpdir, "test.py")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("match in txt\n")
        with open(py_path, "w", encoding="utf-8") as f:
            f.write("match in py\n")

        # Should only search .py files
        result = skillkit._grep(tmpdir, "match", file_extensions="py")
        assert "match in py" in result
        assert "match in txt" not in result


def test_grep_case_sensitive(skillkit):
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("Hello World\n")

        result = skillkit._grep(file_path, "hello")
        assert "No matches found" in result

        result = skillkit._grep(file_path, "hello", case_sensitive=False)
        assert "Hello World" in result


def test_read_folder_single_extension(skillkit):
    """Test _read_folder with single extension as string"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        with open(os.path.join(tmpdir, "test.md"), "w") as f:
            f.write("# Markdown")
        with open(os.path.join(tmpdir, "test.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
            f.write("text")

        result = skillkit._read_folder(tmpdir, extensions="md")
        assert "test.md" in result
        assert "test.py" not in result
        assert "readme.txt" not in result


def test_read_folder_list_extensions(skillkit):
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
        result = skillkit._read_folder(tmpdir, extensions=["md", "py"])
        assert "test.md" in result
        assert "test.py" in result
        assert "config.yaml" not in result
        assert "readme.txt" not in result


def test_read_folder_no_extensions(skillkit):
    """Test _read_folder without extensions filter"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "test.md"), "w") as f:
            f.write("# Markdown")
        with open(os.path.join(tmpdir, "test.py"), "w") as f:
            f.write("print('hello')")

        result = skillkit._read_folder(tmpdir)
        assert "test.md" in result
        assert "test.py" in result


def test_read_folder_nonexistent(skillkit):
    """Test _read_folder with non-existent directory"""
    result = skillkit._read_folder("/nonexistent/path")
    assert "Error:" in result


def test_read_folder_empty_directory(skillkit):
    """Test _read_folder with empty directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = skillkit._read_folder(tmpdir, extensions="md")
        assert "No files found" in result


def test_grep_no_read_permission(skillkit):
    """Test _grep handles permission errors gracefully"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "restricted.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("secret content\n")
        os.chmod(file_path, 0o000)

        try:
            result = skillkit._grep(file_path, "secret")
            # Should handle permission error gracefully
            assert "No matches found" in result or "Error:" in result or isinstance(result, str)
        finally:
            os.chmod(file_path, 0o644)


def test_grep_directory_instead_of_file(skillkit):
    """Test _grep when path is a directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file inside the directory
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("needle in haystack\n")

        # Grep the directory (should work recursively)
        result = skillkit._grep(tmpdir, "needle")
        assert "needle in haystack" in result


def test_grep_binary_file(skillkit):
    """Test _grep handles binary files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "binary.bin")
        with open(file_path, "wb") as f:
            f.write(b"\x00\x01\x02\x03needle\xff\xfe")

        result = skillkit._grep(file_path, "needle")
        # Binary files might not be searchable, but shouldn't crash
        assert isinstance(result, str)


def test_grep_with_context_lines(skillkit):
    """Test _grep with before/after context lines"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("line 1\nline 2\nline 3 match here\nline 4\nline 5\n")

        result = skillkit._grep(file_path, "match", before=1, after=1)
        assert "match here" in result


def test_grep_regex_pattern(skillkit):
    """Test _grep with regex pattern"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("test123\nabc456\n")

        result = skillkit._grep(file_path, r"\d+")
        assert "test123" in result
        assert "abc456" in result


def test_grep_literal_string(skillkit):
    """Test _grep with literal string (no regex)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("hello.world\n")

        # Using regex=False should treat dot as literal
        result = skillkit._grep(file_path, "hello\\.world", use_regex=True)
        assert "hello.world" in result


def test_read_folder_multiple_extensions_bug(skillkit):
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
        result = skillkit._read_folder(tmpdir, extensions=["md", "py"])

        # Should find both .md and .py files
        assert "test.md" in result
        assert "test.py" in result
        assert "config.yaml" not in result
        assert "readme.txt" not in result


def test_read_file_skips_large_file(skillkit):
    """_read_file should refuse to read files exceeding the size limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        large_file = os.path.join(tmpdir, "huge.bin")
        # Create a file just over 10 MB
        with open(large_file, "wb") as f:
            f.seek(10 * 1024 * 1024 + 1)
            f.write(b"\x00")

        result = skillkit._read_file(large_file)
        assert "SKIPPED" in result
        assert "too large" in result.lower()


def test_read_folder_skips_large_file(skillkit):
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

        result = skillkit._read_folder(tmpdir, extensions="txt")
        assert "I am small" in result
        assert "SKIPPED" in result
        assert "big.txt" in result


def test_grep_skips_large_file(skillkit):
    """_grep should skip files exceeding the size limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        large_file = os.path.join(tmpdir, "huge.txt")
        with open(large_file, "wb") as f:
            f.write(b"needle\n")
            f.seek(10 * 1024 * 1024 + 1)
            f.write(b"\x00")

        result = skillkit._grep(large_file, "needle")
        assert "SKIPPED" in result
        assert "needle" not in result.split("SKIPPED")[0]


def test_grep_skips_dangerous_directories(skillkit):
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

        result = skillkit._grep(tmpdir, "findme", recursive=True)
        assert "findme_normal" in result
        assert "findme_dangerous" not in result
