"""Unit tests for COWContext (Copy-On-Write Context)."""

import pytest

from dolphin.core.context.context import Context
from dolphin.core.context.cow_context import COWContext


class TestCOWContext:
    """Test Copy-On-Write Context isolation."""

    def test_cow_context_creation(self):
        """Test COWContext initialization."""
        parent = Context()
        task_id = "task_1"
        
        child = COWContext(parent, task_id)
        
        assert child.parent is parent
        assert child.task_id == task_id
        assert child.writes == {}
        assert child.deletes == set()
    
    def test_get_variable_from_parent(self):
        """Test reading variable from parent."""
        parent = Context()
        parent.set_variable("key1", "value1")
        
        child = COWContext(parent, "task_1")
        
        assert child.get_variable("key1") == "value1"
    
    def test_set_variable_local_only(self):
        """Test writing variable to local layer."""
        parent = Context()
        parent.set_variable("key1", "parent_value")
        
        child = COWContext(parent, "task_1")
        child.set_variable("key1", "child_value")
        child.set_variable("key2", "new_value")
        
        # Child sees local values
        assert child.get_variable("key1") == "child_value"
        assert child.get_variable("key2") == "new_value"
        
        # Parent unchanged
        assert parent.get_var_value("key1") == "parent_value"
        assert parent.get_var_value("key2") is None
    
    def test_delete_variable_tombstone(self):
        """Test deleting variable creates tombstone."""
        parent = Context()
        parent.set_variable("key1", "value1")
        
        child = COWContext(parent, "task_1")
        child.delete_variable("key1")
        
        # Child sees None (tombstone)
        assert child.get_variable("key1") is None
        
        # Parent unchanged
        assert parent.get_var_value("key1") == "value1"
    
    def test_get_local_changes(self):
        """Test getting local writes."""
        parent = Context()
        parent.set_variable("key1", "parent_value")
        
        child = COWContext(parent, "task_1")
        child.set_variable("key1", "child_value")
        child.set_variable("key2", "new_value")
        
        changes = child.get_local_changes()
        
        assert changes == {"key1": "child_value", "key2": "new_value"}
    
    def test_merge_to_parent_selective(self):
        """Test selective merge to parent."""
        parent = Context()
        
        child = COWContext(parent, "task_1")
        child.set_variable("key1", "value1")
        child.set_variable("key2", "value2")
        child.set_variable("key3", "value3")
        
        # Merge only key1 and key2
        child.merge_to_parent(keys={"key1", "key2"})
        
        assert parent.get_var_value("key1") == "value1"
        assert parent.get_var_value("key2") == "value2"
        assert parent.get_var_value("key3") is None
    
    def test_merge_to_parent_full(self):
        """Test full merge to parent."""
        parent = Context()
        
        child = COWContext(parent, "task_1")
        child.set_variable("key1", "value1")
        child.set_variable("key2", "value2")
        child.set_variable("key3", "value3")
        
        # Merge all
        child.merge_to_parent()
        
        assert parent.get_var_value("key1") == "value1"
        assert parent.get_var_value("key2") == "value2"
        assert parent.get_var_value("key3") == "value3"

    def test_variable_pool_direct_mutation_is_tracked_for_merge(self):
        """Test direct variable_pool mutation participates in COW merge semantics."""
        parent = Context()
        parent.set_variable("key_delete", "parent_value")

        child = COWContext(parent, "task_1")

        # Bypass COWContext.set_variable() on purpose.
        child.variable_pool.set_var("key_set", "child_value")
        child.variable_pool.delete_var("key_delete")

        child.merge_to_parent()

        assert parent.get_var_value("key_set") == "child_value"
        assert parent.get_var_value("key_delete") is None

    def test_tuple_with_mutable_elements_is_isolated(self):
        """Test tuples containing mutable elements are deep-copied for isolation."""
        parent = Context()
        parent.set_variable("tup", ([1, 2],))

        child = COWContext(parent, "task_1")
        tup = child.get_variable("tup")

        tup[0].append(3)

        assert parent.get_var_value("tup")[0] == [1, 2]
    
    @pytest.mark.asyncio
    async def test_attribute_delegation(self):
        """Test __getattr__ delegates to parent."""
        parent = Context()
        await parent.enable_plan(plan_id="test_plan")
        
        child = COWContext(parent, "task_1")
        
        # Access parent plan id (for observability)
        assert child.get_plan_id() == "test_plan"
        # Subtask contexts must not be plan-enabled
        assert child.is_plan_enabled() is False
        assert child.has_active_plan() is False
