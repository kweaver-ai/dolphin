import json
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from dolphin.lib.skillkits.memory_skillkit import (
    MemorySkillkit,
    MemoryStore,
    MemoryBucket,
    RWLock,
)
from dolphin.lib.utils.text_retrieval import (
    tokenize_simple as tokenize,
    is_cjk as _is_cjk,
)


class TestTokenization(unittest.TestCase):
    """Test tokenization utilities"""

    def test_is_cjk(self):
        self.assertTrue(_is_cjk("中"))
        self.assertTrue(_is_cjk("文"))
        self.assertTrue(_is_cjk("한"))
        self.assertTrue(_is_cjk("日"))
        self.assertFalse(_is_cjk("a"))
        self.assertFalse(_is_cjk("1"))
        self.assertFalse(_is_cjk(" "))

    def test_tokenize_english(self):
        tokens = tokenize("Hello World 123")
        self.assertEqual(tokens, ["hello", "world", "123"])

    def test_tokenize_cjk(self):
        tokens = tokenize("你好世界")
        self.assertEqual(tokens, ["你", "好", "世", "界"])

    def test_tokenize_mixed(self):
        tokens = tokenize("Hello 世界 123")
        self.assertEqual(tokens, ["hello", "世", "界", "123"])

    def test_tokenize_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])

    def test_tokenize_punctuation(self):
        tokens = tokenize("hello, world!")
        self.assertEqual(tokens, ["hello", "world"])


# BM25Index tests removed - memory_skillkit now uses simple string matching


class TestRWLock(unittest.TestCase):
    """Test Read-Write lock implementation"""

    def setUp(self):
        self.lock = RWLock()
        self.shared_resource = 0
        self.read_count = 0

    def test_multiple_readers(self):
        """Multiple readers should be able to access concurrently"""
        results = []

        def reader(delay):
            with self.lock.rlocked():
                time.sleep(delay)
                results.append(f"reader_{delay}")

        start = time.time()
        threads = [threading.Thread(target=reader, args=(0.1,)) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end = time.time()

        # All readers should complete in roughly 0.1 seconds (concurrent)
        self.assertLess(end - start, 0.2)
        self.assertEqual(len(results), 3)

    def test_writer_exclusion(self):
        """Writer should exclude all other access"""
        results = []

        def writer():
            with self.lock.wlocked():
                time.sleep(0.1)
                results.append("writer")

        def reader():
            with self.lock.rlocked():
                results.append("reader")

        start = time.time()
        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)

        writer_thread.start()
        time.sleep(0.05)  # Let writer acquire lock first
        reader_thread.start()

        writer_thread.join()
        reader_thread.join()
        end = time.time()

        self.assertEqual(results, ["writer", "reader"])
        self.assertGreater(end - start, 0.1)  # Reader had to wait


class TestMemoryBucket(unittest.TestCase):
    """Test memory bucket functionality"""

    def setUp(self):
        self.bucket = MemoryBucket()

    def test_set_get_value(self):
        self.bucket.set_value("user.name", "Alice")
        value = self.bucket.get_value("user.name")
        self.assertEqual(value, "Alice")

    def test_get_nonexistent_value(self):
        value = self.bucket.get_value("nonexistent.path")
        self.assertIsNone(value)

    def test_set_dict_simple(self):
        data = {"user": {"name": "Bob", "age": 30}}
        count = self.bucket.set_dict(data)
        self.assertEqual(count, 2)

        self.assertEqual(self.bucket.get_value("user.name"), "Bob")
        self.assertEqual(self.bucket.get_value("user.age"), "30")

    def test_set_dict_nested(self):
        data = {
            "config": {
                "database": {"host": "localhost", "port": 5432},
                "cache": {"enabled": True},
            }
        }
        count = self.bucket.set_dict(data)
        self.assertEqual(count, 3)

        self.assertEqual(self.bucket.get_value("config.database.host"), "localhost")
        self.assertEqual(self.bucket.get_value("config.database.port"), "5432")
        self.assertEqual(self.bucket.get_value("config.cache.enabled"), "true")

    def test_set_dict_non_string_values(self):
        data = {"numbers": [1, 2, 3], "flag": False, "obj": {"nested": "value"}}
        count = self.bucket.set_dict(data)
        self.assertEqual(count, 3)

        # Should be JSON-serialized (non-dict values) or expanded (dict values)
        self.assertEqual(self.bucket.get_value("numbers"), "[1, 2, 3]")
        self.assertEqual(self.bucket.get_value("flag"), "false")
        # The obj dictionary should be expanded, so obj.nested should exist
        self.assertEqual(self.bucket.get_value("obj.nested"), "value")

    def test_grep_basic(self):
        self.bucket.set_value("user.name", "Alice Smith")
        self.bucket.set_value("user.email", "alice@example.com")
        self.bucket.set_value("admin.name", "Bob Jones")

        # Search for "Alice" - should find both user.name and user.email due to indexing both key and value
        results = self.bucket.grep("", "Alice")
        self.assertGreaterEqual(len(results), 1)  # At least one result
        # Check that we find the correct path
        paths = [r["path"] for r in results]
        self.assertIn("user.name", paths)

    def test_grep_scoped_path(self):
        self.bucket.set_value("user.profile.name", "Alice")
        self.bucket.set_value("user.settings.theme", "dark")
        self.bucket.set_value("admin.profile.name", "Bob")

        # Search only under "user" path
        results = self.bucket.grep("user", "profile")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "user.profile.name")

    def test_grep_regex_pattern(self):
        self.bucket.set_value("test.email1", "alice@example.com")
        self.bucket.set_value("test.email2", "bob@test.org")
        self.bucket.set_value("test.phone", "123-456-7890")

        # Regex pattern for emails
        results = self.bucket.grep("test", "/.*@.*\\.com$/")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "test.email1")

    def test_grep_fallback_substring(self):
        self.bucket.set_value("info.description", "This is a test document")

        # Should use substring search directly for simple patterns
        results = self.bucket.grep("", "document")
        self.assertEqual(len(results), 1)

    def test_export_dict(self):
        self.bucket.set_value("user.name", "Alice")
        self.bucket.set_value("user.age", "25")

        exported = self.bucket.export_dict()
        self.assertIn("user", exported)
        self.assertIn("name", exported["user"])
        self.assertEqual(exported["user"]["name"]["_value"], "Alice")
        self.assertIn("_ts", exported["user"]["name"])

    def test_remove_path(self):
        self.bucket.set_value("user.name", "Alice")
        self.bucket.set_value("user.age", "25")

        # Remove existing path
        result = self.bucket.remove_path("user.name")
        self.assertTrue(result)

        # Check it's gone
        self.assertIsNone(self.bucket.get_value("user.name"))
        # But other path remains
        self.assertEqual(self.bucket.get_value("user.age"), "25")

        # Remove non-existent path
        result = self.bucket.remove_path("nonexistent.path")
        self.assertFalse(result)

    def test_expire_old_entries(self):
        self.bucket.set_value("old.data", "old_value")
        time.sleep(0.1)
        self.bucket.set_value("new.data", "new_value")

        # Expire entries older than 0.05 seconds
        expired_count = self.bucket.expire_old_entries(0.05)
        self.assertEqual(expired_count, 1)

        # Check that old data is gone, new data remains
        self.assertIsNone(self.bucket.get_value("old.data"))
        self.assertEqual(self.bucket.get_value("new.data"), "new_value")

    def test_get_stats(self):
        self.bucket.set_value("user.name", "Alice")
        self.bucket.set_value("user.age", "25")

        stats = self.bucket.get_stats()
        self.assertIn("total_entries", stats)
        self.assertIn("storage_type", stats)
        self.assertIn("search_method", stats)

        self.assertEqual(stats["total_entries"], 2)
        self.assertEqual(stats["storage_type"], "simple_tree")
        self.assertEqual(stats["search_method"], "string_matching")


class TestMemoryStore(unittest.TestCase):
    """Test memory store functionality"""

    def setUp(self):
        self.store = MemoryStore()

    def test_get_bucket_creates_new(self):
        bucket = self.store.get_bucket("session1")
        self.assertIsInstance(bucket, MemoryBucket)

    def test_get_bucket_returns_same(self):
        bucket1 = self.store.get_bucket("session1")
        bucket2 = self.store.get_bucket("session1")
        self.assertIs(bucket1, bucket2)

    def test_different_sessions_different_buckets(self):
        bucket1 = self.store.get_bucket("session1")
        bucket2 = self.store.get_bucket("session2")
        self.assertIsNot(bucket1, bucket2)

    def test_empty_session_id_raises(self):
        with self.assertRaises(ValueError):
            self.store.get_bucket("")

    def test_thread_safety(self):
        """Test concurrent bucket creation"""
        session_id = "concurrent_test"
        buckets = []

        def get_bucket():
            bucket = self.store.get_bucket(session_id)
            buckets.append(bucket)

        threads = [threading.Thread(target=get_bucket) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same bucket instance
        for bucket in buckets[1:]:
            self.assertIs(bucket, buckets[0])


class TestMemorySkillkit(unittest.TestCase):
    """Test the main MemorySkillkit interface"""

    def setUp(self):
        self.skillkit = MemorySkillkit()
        self.session_id = f"test_session_{int(time.time())}"

    def test_mem_set_get(self):
        result = json.loads(
            self.skillkit._mem_set("user.name", "Alice", session_id=self.session_id)
        )
        self.assertTrue(result.get("success"))

        value = json.loads(
            self.skillkit._mem_get("user.name", session_id=self.session_id)
        )
        self.assertTrue(value.get("success"))
        self.assertTrue(value.get("found"))
        self.assertEqual(value.get("value"), "Alice")

    def test_mem_get_nonexistent(self):
        value = json.loads(
            self.skillkit._mem_get("nonexistent.path", session_id=self.session_id)
        )
        self.assertTrue(value.get("success"))
        self.assertFalse(value.get("found"))
        self.assertEqual(value.get("value"), "")

    def test_mem_set_dict(self):
        data = {"user": {"name": "Bob", "age": 30}, "settings": {"theme": "dark"}}
        result = json.loads(
            self.skillkit._mem_set_dict(data, session_id=self.session_id)
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result["updated"], 3)

        self.assertEqual(
            json.loads(self.skillkit._mem_get("user.name", session_id=self.session_id))[
                "value"
            ],
            "Bob",
        )
        self.assertEqual(
            json.loads(self.skillkit._mem_get("user.age", session_id=self.session_id))[
                "value"
            ],
            "30",
        )
        self.assertEqual(
            json.loads(
                self.skillkit._mem_get("settings.theme", session_id=self.session_id)
            )["value"],
            "dark",
        )

    def test_mem_set_dict_invalid_input(self):
        with self.assertRaises(ValueError):
            self.skillkit._mem_set_dict("not a dict", session_id=self.session_id)

    def test_mem_grep(self):
        self.skillkit._mem_set("user.name", "Alice Smith", session_id=self.session_id)
        self.skillkit._mem_set(
            "user.email", "alice@example.com", session_id=self.session_id
        )

        result = json.loads(
            self.skillkit._mem_grep("", "Alice", session_id=self.session_id)
        )
        results = result.get("results", [])

        self.assertGreaterEqual(len(results), 1)  # At least one result
        # Check that we find the correct data
        paths = [r["path"] for r in results]
        self.assertIn("user.name", paths)

        # Find the user.name result specifically
        user_name_result = next(r for r in results if r["path"] == "user.name")
        self.assertEqual(user_name_result["value"], "Alice Smith")
        self.assertIn("score", user_name_result)
        self.assertIn("ts", user_name_result)

    def test_mem_save(self):
        self.skillkit._mem_set("user.name", "Alice", session_id=self.session_id)
        self.skillkit._mem_set("user.age", "25", session_id=self.session_id)

        # NOTE: sandbox now requires relative path under session; use allowed relative
        rel = "tmp_backup.json"
        result = json.loads(self.skillkit._mem_save(rel, session_id=self.session_id))
        self.assertTrue(result.get("success"))
        saved_path = result.get("path")

        # Verify file contents
        with open(saved_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        self.assertIn("user", saved_data)
        self.assertEqual(saved_data["user"]["name"]["_value"], "Alice")
        self.assertEqual(saved_data["user"]["age"]["_value"], "25")

    def test_mem_save_creates_directory(self):
        # Now sandboxed: create a nested relative path and ensure it is created inside sandbox
        self.skillkit._mem_set("test.value", "123", session_id=self.session_id)
        result = json.loads(
            self.skillkit._mem_save("subdir/data.json", session_id=self.session_id)
        )
        self.assertTrue(result.get("success"))
        save_path = result.get("path")
        self.assertTrue(os.path.exists(save_path))

    def test_mem_remove(self):
        # Set some data
        self.skillkit._mem_set("user.name", "Alice", session_id=self.session_id)
        self.skillkit._mem_set("user.age", "25", session_id=self.session_id)

        # Verify data exists
        self.assertEqual(
            json.loads(self.skillkit._mem_get("user.name", session_id=self.session_id))[
                "value"
            ],
            "Alice",
        )

        # Remove one path
        result_data = json.loads(
            self.skillkit._mem_remove("user.name", session_id=self.session_id)
        )
        self.assertTrue(result_data["success"])
        self.assertTrue(result_data["removed"])

        # Verify removed
        self.assertEqual(
            json.loads(self.skillkit._mem_get("user.name", session_id=self.session_id))[
                "value"
            ],
            "",
        )
        # But other path still exists
        self.assertEqual(
            json.loads(self.skillkit._mem_get("user.age", session_id=self.session_id))[
                "value"
            ],
            "25",
        )

        # Remove non-existent path
        result = self.skillkit._mem_remove(
            "nonexistent.path", session_id=self.session_id
        )
        result_data = json.loads(result)
        self.assertFalse(result_data["removed"])

    def test_mem_expire(self):
        # Set some data with different timestamps
        self.skillkit._mem_set("old.data", "old_value", session_id=self.session_id)
        time.sleep(1.1)  # Wait for timestamp difference
        self.skillkit._mem_set("new.data", "new_value", session_id=self.session_id)

        # Expire data older than 1 second
        result_data = json.loads(
            self.skillkit._mem_expire(1.0, session_id=self.session_id)
        )
        self.assertEqual(result_data["expired_count"], 1)

        # Check that old data is gone, new data remains
        self.assertEqual(
            json.loads(self.skillkit._mem_get("old.data", session_id=self.session_id))[
                "value"
            ],
            "",
        )
        self.assertEqual(
            json.loads(self.skillkit._mem_get("new.data", session_id=self.session_id))[
                "value"
            ],
            "new_value",
        )

    def test_mem_stats(self):
        # Use a fresh session ID to avoid interference
        fresh_session = f"fresh_session_{int(time.time())}"

        # Add some data
        self.skillkit._mem_set("user.name", "Alice", session_id=fresh_session)
        self.skillkit._mem_set("user.age", "25", session_id=fresh_session)

        stats = json.loads(self.skillkit._mem_stats(session_id=fresh_session))

        self.assertIn("total_entries", stats)
        self.assertIn("storage_type", stats)
        self.assertIn("search_method", stats)

        self.assertEqual(stats["total_entries"], 2)
        self.assertEqual(stats["storage_type"], "simple_tree")
        self.assertEqual(stats["search_method"], "string_matching")


class TestConcurrency(unittest.TestCase):
    """Test concurrent operations"""

    def setUp(self):
        self.skillkit = MemorySkillkit()
        self.session_id = f"concurrent_test_{int(time.time())}"

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes don't cause race conditions"""
        json.loads(self.skillkit._mem_set("counter", "0", session_id=self.session_id))

        results = []
        errors = []

        def writer(value):
            try:
                self.skillkit._mem_set(
                    f"data.item_{value}", str(value), session_id=self.session_id
                )
                results.append(f"write_{value}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                value = json.loads(
                    self.skillkit._mem_get("counter", session_id=self.session_id)
                ).get("value")
                results.append(f"read_{value}")
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []

            # Submit concurrent writes
            for i in range(5):
                futures.append(executor.submit(writer, i))

            # Submit concurrent reads
            for _ in range(5):
                futures.append(executor.submit(reader))

            # Wait for completion
            for future in futures:
                future.result()

        # Should have no errors
        self.assertEqual(len(errors), 0)

        # Should have completed all operations
        write_count = len([r for r in results if r.startswith("write_")])
        read_count = len([r for r in results if r.startswith("read_")])
        self.assertEqual(write_count, 5)
        self.assertEqual(read_count, 5)

    def test_concurrent_grep(self):
        """Test concurrent search operations"""
        # Setup test data
        for i in range(10):
            self.skillkit._mem_set(
                f"item_{i}", f"value_{i}", session_id=self.session_id
            )

        results = []
        errors = []

        def searcher(pattern):
            try:
                data = json.loads(
                    self.skillkit._mem_grep("", pattern, session_id=self.session_id)
                )
                results.append(len(data.get("results", [])))
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(10):
                futures.append(executor.submit(searcher, f"value_{i}"))

            for future in futures:
                future.result()

        self.assertEqual(len(errors), 0)
        # Each search should find exactly 1 result
        self.assertEqual(results, [1] * 10)


class TestMemorySandboxSecurity(unittest.TestCase):
    """Test security features of memory sandbox"""

    def setUp(self):
        self.skillkit = MemorySkillkit()
        self.session_id = f"security_test_{int(time.time())}"

    def test_path_traversal_attack(self):
        """Test that path traversal attacks are blocked"""
        self.skillkit._mem_set("test", "value", session_id=self.session_id)

        # Try to escape sandbox with ..
        result = json.loads(
            self.skillkit._mem_save("../../../etc/passwd", session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("escapes", result.get("error", "").lower())

    def test_file_type_validation(self):
        """Test that only .json files are allowed"""
        self.skillkit._mem_set("test", "value", session_id=self.session_id)

        # Try to save as non-JSON file
        result = json.loads(
            self.skillkit._mem_save("malware.exe", session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("json", result.get("error", "").lower())

    def test_absolute_path_rejected(self):
        """Test that absolute paths are rejected"""
        result = json.loads(
            self.skillkit._mem_save("/tmp/test.json", session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("relative", result.get("error", "").lower())

    def test_sandbox_isolation(self):
        """Test that different sessions have isolated sandboxes"""
        session_a = "session_a"
        session_b = "session_b"

        # Save same filename in different sessions
        self.skillkit._mem_set("data", "A", session_id=session_a)
        self.skillkit._mem_set("data", "B", session_id=session_b)

        result_a = json.loads(
            self.skillkit._mem_save("test.json", session_id=session_a)
        )
        result_b = json.loads(
            self.skillkit._mem_save("test.json", session_id=session_b)
        )

        self.assertTrue(result_a.get("success"))
        self.assertTrue(result_b.get("success"))

        path_a = result_a.get("path", "")
        path_b = result_b.get("path", "")

        # Paths should be different and isolated
        self.assertIn("session_a", path_a)
        self.assertIn("session_b", path_b)
        self.assertNotEqual(path_a, path_b)

    def test_file_size_limit(self):
        """Test that files exceeding size limit are rejected"""
        # Create a large data structure (> 10MB)
        large_dict = {f"key_{i}": "x" * 10000 for i in range(1100)}  # ~11MB
        self.skillkit._mem_set_dict(large_dict, session_id=self.session_id)

        result = json.loads(
            self.skillkit._mem_save("large.json", session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("large", result.get("error", "").lower())

    def test_path_length_limit(self):
        """Test that overly long paths are rejected"""
        # Create a path longer than 512 characters
        long_path = "a/" * 300 + "test.json"
        result = json.loads(
            self.skillkit._mem_save(long_path, session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("long", result.get("error", "").lower())

    def test_load_path_validation(self):
        """Test that _mem_load also validates paths"""
        # Try to load from an escaped path
        result = json.loads(
            self.skillkit._mem_load("../../../etc/passwd", session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("escapes", result.get("error", "").lower())

    def test_load_file_type_validation(self):
        """Test that _mem_load only allows .json files"""
        result = json.loads(
            self.skillkit._mem_load("config.txt", session_id=self.session_id)
        )
        self.assertFalse(result.get("success"))
        self.assertIn("json", result.get("error", "").lower())


class TestSkillkitInterface(unittest.TestCase):
    """Test Skillkit interface compliance"""

    def setUp(self):
        self.skillkit = MemorySkillkit()
        self.session_id = f"iface_session_{int(time.time())}"

    def test_get_name(self):
        self.assertEqual(self.skillkit.getName(), "memory_skillkit")

    def test_get_skills(self):
        skills = self.skillkit.getSkills()
        self.assertEqual(len(skills), 10)

        skill_names = [skill.func.__name__ for skill in skills]
        expected_names = [
            "_mem_set",
            "_mem_set_dict",
            "_mem_get",
            "_mem_grep",
            "_mem_view",
            "_mem_load",
            "_mem_save",
            "_mem_remove",
            "_mem_expire",
            "_mem_stats",
        ]
        self.assertEqual(set(skill_names), set(expected_names))

    def test_mem_view_and_load(self):
        # set some values
        json.loads(
            self.skillkit._mem_set("user.name", "Alice", session_id=self.session_id)
        )
        # view root
        vroot = json.loads(self.skillkit._mem_view(path="", session_id=self.session_id))
        self.assertTrue(vroot.get("success"))
        self.assertEqual(vroot.get("type"), "directory")
        # view file
        vfile = json.loads(
            self.skillkit._mem_view(path="user.name", session_id=self.session_id)
        )
        self.assertTrue(vfile.get("success"))
        self.assertEqual(vfile.get("type"), "file")
        self.assertEqual(vfile.get("value"), "Alice")
        # save and load
        save_ret = json.loads(
            self.skillkit._mem_save("backup.json", session_id=self.session_id)
        )
        self.assertTrue(save_ret.get("success"))
        load_ret = json.loads(
            self.skillkit._mem_load("backup.json", session_id=self.session_id)
        )
        self.assertTrue(load_ret.get("success"))


if __name__ == "__main__":
    unittest.main()
