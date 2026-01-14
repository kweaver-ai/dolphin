#!/usr/bin/env python3
"""Unit tests for isolated_variable_pool module."""

import unittest
from dolphin.core.context.variable_pool import VariablePool
from dolphin.core.hook.isolated_variable_pool import (
    IsolatedVariablePool,
    VariableAccessError,
)


class TestIsolatedVariablePool(unittest.TestCase):
    """Tests for IsolatedVariablePool class."""

    def setUp(self):
        """Set up test fixtures."""
        self.parent = VariablePool()
        self.parent.set_var("datasources", {"db1": "connection1"})
        self.parent.set_var("config", {"timeout": 30})
        self.parent.set_var("secret_key", "super_secret_123")
        self.parent.set_var("result", {"answer": "test"})

    def test_get_from_parent_no_whitelist(self):
        """Test get from parent without whitelist."""
        pool = IsolatedVariablePool(parent=self.parent)
        value = pool.get("datasources")
        self.assertEqual(value, {"db1": "connection1"})

    def test_get_with_whitelist_allowed(self):
        """Test get with whitelist - allowed variable."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["datasources", "config"]
        )
        value = pool.get("datasources")
        self.assertEqual(value, {"db1": "connection1"})

    def test_get_with_whitelist_denied(self):
        """Test get with whitelist - denied variable raises error."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["datasources"]
        )
        with self.assertRaises(VariableAccessError):
            pool.get("secret_key")

    def test_get_with_dollar_prefix(self):
        """Test get handles $ prefix correctly."""
        pool = IsolatedVariablePool(parent=self.parent)
        value = pool.get("$datasources")
        self.assertEqual(value, {"db1": "connection1"})

    def test_set_local_variable(self):
        """Test setting local variable."""
        pool = IsolatedVariablePool(parent=self.parent, read_only=True)
        pool.set("local_var", "local_value")
        self.assertEqual(pool.get("local_var"), "local_value")

    def test_set_hook_context(self):
        """Test setting $_hook_context special variable."""
        pool = IsolatedVariablePool(parent=self.parent)
        pool.set("_hook_context", {"answer": "test", "attempt": 1})
        value = pool.get("_hook_context")
        self.assertEqual(value["answer"], "test")
        self.assertEqual(value["attempt"], 1)

    def test_read_only_prevents_parent_modification(self):
        """Test read_only mode stores in local, not parent."""
        pool = IsolatedVariablePool(parent=self.parent, read_only=True)
        pool.set("datasources", "modified")

        # Local should be modified
        self.assertEqual(pool.get("datasources"), "modified")

        # Parent should be unchanged
        self.assertEqual(self.parent.get_var_value("datasources"), {"db1": "connection1"})

    def test_contains_local_variable(self):
        """Test __contains__ for local variable."""
        pool = IsolatedVariablePool(parent=self.parent)
        pool.set("local", "value")
        self.assertIn("local", pool)

    def test_contains_parent_variable(self):
        """Test __contains__ for parent variable."""
        pool = IsolatedVariablePool(parent=self.parent)
        self.assertIn("datasources", pool)

    def test_contains_with_whitelist(self):
        """Test __contains__ respects whitelist."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["datasources"]
        )
        self.assertIn("datasources", pool)
        self.assertNotIn("secret_key", pool)

    def test_get_default_value(self):
        """Test get returns default when variable not found."""
        pool = IsolatedVariablePool(parent=self.parent)
        value = pool.get("nonexistent", "default")
        self.assertEqual(value, "default")

    def test_get_var_path_value(self):
        """Test get_var_path_value with dot notation."""
        pool = IsolatedVariablePool(parent=self.parent)
        value = pool.get_var_path_value("config.timeout")
        self.assertEqual(value, 30)

    def test_get_var_path_value_with_dollar(self):
        """Test get_var_path_value handles $ prefix."""
        pool = IsolatedVariablePool(parent=self.parent)
        value = pool.get_var_path_value("$config.timeout")
        self.assertEqual(value, 30)

    def test_delete_local_variable(self):
        """Test delete_var removes local variable."""
        pool = IsolatedVariablePool(parent=self.parent)
        pool.set("temp", "value")
        self.assertIn("temp", pool)
        pool.delete_var("temp")
        self.assertNotIn("temp", pool)

    def test_keys(self):
        """Test keys returns all accessible variable names."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["datasources"]
        )
        pool.set("_hook_context", {})

        keys = pool.keys()
        self.assertIn("datasources", keys)
        self.assertIn("_hook_context", keys)

    def test_get_all_variables(self):
        """Test get_all_variables with whitelist."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["config"]
        )
        pool.set("_hook_context", {"test": True})

        all_vars = pool.get_all_variables()
        self.assertIn("config", all_vars)
        self.assertIn("_hook_context", all_vars)
        self.assertNotIn("secret_key", all_vars)

    def test_clear_only_affects_local(self):
        """Test clear only clears local variables."""
        pool = IsolatedVariablePool(parent=self.parent)
        pool.set("local", "value")
        pool.clear()

        self.assertNotIn("local", pool._local)
        # Parent unchanged
        self.assertEqual(self.parent.get_var_value("datasources"), {"db1": "connection1"})

    def test_is_read_only_property(self):
        """Test is_read_only property."""
        pool = IsolatedVariablePool(parent=self.parent, read_only=True)
        self.assertTrue(pool.is_read_only)

        pool = IsolatedVariablePool(parent=self.parent, read_only=False)
        self.assertFalse(pool.is_read_only)

    def test_exposed_variable_names_property(self):
        """Test exposed_variable_names property."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["$datasources", "config"]
        )
        names = pool.exposed_variable_names
        # Should have $ prefix removed
        self.assertIn("datasources", names)
        self.assertIn("config", names)

    def test_whitelist_with_dollar_prefix(self):
        """Test whitelist handles $ prefix in variable names."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["$datasources"]  # With $ prefix
        )
        # Should work because $ is stripped
        value = pool.get("datasources")
        self.assertEqual(value, {"db1": "connection1"})

    def test_contain_var_alias(self):
        """Test contain_var is alias for __contains__."""
        pool = IsolatedVariablePool(parent=self.parent)
        self.assertTrue(pool.contain_var("datasources"))
        self.assertFalse(pool.contain_var("nonexistent"))

    def test_get_var_value_alias(self):
        """Test get_var_value is compatible with VariablePool interface."""
        pool = IsolatedVariablePool(parent=self.parent)
        value = pool.get_var_value("datasources")
        self.assertEqual(value, {"db1": "connection1"})

    def test_get_var_value_catches_access_error(self):
        """Test get_var_value returns default on VariableAccessError."""
        pool = IsolatedVariablePool(
            parent=self.parent,
            exposed_variables=["config"]
        )
        # This would raise VariableAccessError via get()
        # but get_var_value should return default instead
        value = pool.get_var_value("secret_key", "default")
        self.assertEqual(value, "default")


if __name__ == "__main__":
    unittest.main()
