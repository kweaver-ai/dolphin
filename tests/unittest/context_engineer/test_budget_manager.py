"""Tests for BudgetManager."""

import pytest


from dolphin.core.context_engineer.core.budget_manager import (
    BudgetManager,
)
from dolphin.core.context_engineer.config.settings import (
    BucketConfig,
    ContextConfig,
    ModelConfig,
)


class TestBudgetManager:
    """Test cases for BudgetManager."""

    def create_test_context_config(self):
        """Create a test context configuration."""
        model_config = ModelConfig(
            name="test-model",
            context_limit=8192,
            output_target=1200,
            output_headroom=300,
        )
        return ContextConfig(model=model_config, buckets={}, policies={})

    def test_bucket_config_creation(self):
        """Test creating bucket configuration."""
        bucket = BucketConfig(
            name="test_bucket",
            min_tokens=100,
            max_tokens=500,
            weight=1.5,
            compress="signature_only",
        )

        assert bucket.name == "test_bucket"
        assert bucket.min_tokens == 100
        assert bucket.max_tokens == 500
        assert bucket.weight == 1.5
        assert bucket.compress == "signature_only"

    def test_budget_manager_initialization(self):
        """Test BudgetManager initialization."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)
        assert len(manager.buckets) == 0
        assert len(manager.drop_order) == 0

    def test_add_bucket(self):
        """Test adding a bucket to the manager."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)
        bucket = BucketConfig(name="system", min_tokens=100, max_tokens=300, weight=2.0)

        manager.add_bucket(bucket)
        assert len(manager.buckets) == 1
        assert "system" in manager.buckets
        assert manager.buckets["system"] == bucket

    def test_configure_buckets(self):
        """Test configuring multiple buckets from dictionary."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)

        bucket_configs = {
            "system": {
                "min_tokens": 100,
                "max_tokens": 300,
                "weight": 2.0,
            },
            "task": {"min_tokens": 50, "max_tokens": 200, "weight": 1.5},
        }

        manager.configure_buckets(bucket_configs)

        assert len(manager.buckets) == 2
        assert "system" in manager.buckets
        assert "task" in manager.buckets
        assert manager.buckets["system"].min_tokens == 100
        assert manager.buckets["task"].weight == 1.5

    def test_calculate_budget(self):
        """Test budget calculation."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)

        model_limit = 8000
        output_budget = 1200
        system_overhead = 200

        available = manager.calculate_budget(
            model_limit, output_budget, system_overhead
        )

        expected = model_limit - output_budget - system_overhead
        assert available == expected

    def test_initial_allocation_normal_case(self):
        """Test initial allocation with sufficient budget - REMOVED."""
        # This test is removed because _initial_allocation method was removed
        # Budget allocation logic is now handled by callers
        pytest.skip(
            "_initial_allocation method removed - budget allocation handled by callers"
        )

    def test_initial_allocation_insufficient_budget(self):
        """Test initial allocation with insufficient budget - REMOVED."""
        # This test is removed because _initial_allocation method was removed
        # Budget allocation logic is now handled by callers
        pytest.skip(
            "_initial_allocation method removed - budget allocation handled by callers"
        )

    # 移除了 test_allocate_budget 方法
    # allocate_budget 方法已被移除，预算分配逻辑由调用者实现
    def test_set_drop_order(self):
        """Test setting drop order."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)
        drop_order = ["fewshot", "history", "tools", "rag"]

        manager.set_drop_order(drop_order)
        assert manager.drop_order == drop_order

    def test_validate_configuration(self):
        """Test configuration validation."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)

        # Valid configuration
        manager.add_bucket(BucketConfig("system", 100, 300, 2.0))
        manager.add_bucket(BucketConfig("task", 50, 200, 1.5))
        manager.set_drop_order(["task", "system"])

        assert manager.validate_configuration() is True

        # Invalid configuration - min > max
        manager.buckets.clear()
        manager.add_bucket(BucketConfig("system", 300, 100, 2.0))  # Invalid

        assert manager.validate_configuration() is False

    def test_get_bucket_config(self):
        """Test getting bucket configuration."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)
        bucket = BucketConfig("system", 100, 300, 2.0)
        manager.add_bucket(bucket)

        retrieved = manager.get_bucket_config("system")
        assert retrieved == bucket

        missing = manager.get_bucket_config("nonexistent")
        assert missing is None

    def test_get_total_min_max_tokens(self):
        """Test getting total minimum and maximum tokens."""
        context_config = self.create_test_context_config()
        manager = BudgetManager(context_config)

        manager.add_bucket(BucketConfig("system", 100, 300, 2.0))
        manager.add_bucket(BucketConfig("task", 50, 200, 1.5))
        manager.add_bucket(BucketConfig("tools", 30, 150, 1.0))

        total_min = manager.get_total_min_tokens()
        total_max = manager.get_total_max_tokens()

        assert total_min == 180  # 100 + 50 + 30
        assert total_max == 650  # 300 + 200 + 150
