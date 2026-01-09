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
        expected = """def func():
    return 42"""
        result = self.skillkit._extract_code(content)
        self.assertEqual(result, expected)

    def test_grep_single_file_with_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "example.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("first line\nmatch line\nthird line\n")

            result = self.skillkit._grep(file_path, "match", before=1, after=1)
            lines = result.splitlines()

            self.assertIn(f"{file_path}:1:  first line", lines)
            self.assertIn(f"{file_path}:2:> match line", lines)
            self.assertIn(f"{file_path}:3:  third line", lines)

    def test_grep_directory_with_extension_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            match_file = os.path.join(tmpdir, "keep.txt")
            skip_file = os.path.join(tmpdir, "skip.md")
            sub_dir = os.path.join(tmpdir, "sub")
            os.makedirs(sub_dir, exist_ok=True)
            nested_file = os.path.join(sub_dir, "nested.txt")

            with open(match_file, "w", encoding="utf-8") as f:
                f.write("alpha\nbeta match\ngamma\n")
            with open(skip_file, "w", encoding="utf-8") as f:
                f.write("no match here\n")
            with open(nested_file, "w", encoding="utf-8") as f:
                f.write("match in nested\n")

            result = self.skillkit._grep(
                tmpdir, "match", before=0, after=0, file_extensions="txt"
            )

            self.assertIn(f"{match_file}:2:> beta match", result)
            self.assertIn(f"{nested_file}:1:> match in nested", result)
            self.assertNotIn(skip_file, result)

    def test_grep_no_match_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "empty.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("nothing here\n")

            result = self.skillkit._grep(file_path, "needle")
            self.assertIn("No matches found", result)


if __name__ == "__main__":
    unittest.main()
