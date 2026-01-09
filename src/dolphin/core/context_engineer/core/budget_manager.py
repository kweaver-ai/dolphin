"""Budget manager for token allocation across context buckets."""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass


# Import BucketConfig from settings
from ..config.settings import BucketConfig, ContextConfig


@dataclass
class BudgetAllocation:
    """Result of budget allocation for a bucket.

        Data class for bucket budget allocation results.

        Attributes:
            bucket_name (str): The name of the bucket
            allocated_tokens (int): The number of tokens allocated to this bucket
            priority (float): The priority (weight) of this bucket
            content_score (float): The content score, default is 0.0
    """

    bucket_name: str
    allocated_tokens: int
    priority: float
    content_score: float = 0.0


class BudgetManager:
    """Manages token allocation across context buckets.

        Manages token allocation across context buckets.
        This class is responsible for calculating the available input budget based on the model's context limit, output budget, and system overhead,
        and distributing tokens among buckets according to bucket configurations and content scores.
    """

    def __init__(
        self,
        context_config: ContextConfig,
    ):
        """Initialize budget manager.

                Initialize the budget manager.

        Args:
            tokenizer_service: Instance of TokenizerService, used for token counting
        """
        self.buckets: Dict[str, BucketConfig] = {}
        self.drop_order: List[str] = []
        self.model_config = context_config.model
        if context_config.buckets:
            self.configure_buckets(context_config.buckets)

    def add_bucket(self, bucket_config: BucketConfig):
        """Add a bucket configuration.

                Add a bucket configuration.

        Args:
            bucket_config (BucketConfig): The bucket configuration object
        """
        self.buckets[bucket_config.name] = bucket_config

    def configure_buckets(self, bucket_configs: Dict[str, Any]):
        """Configure multiple buckets from dictionary or BucketConfig objects.

                Configure multiple buckets from a dictionary or BucketConfig objects.

        Args:
            bucket_configs: A dictionary of bucket configurations (dict or BucketConfig objects)
        """
        for name, config in bucket_configs.items():
            if (
                hasattr(config, "min_tokens")
                and hasattr(config, "max_tokens")
                and hasattr(config, "weight")
            ):
                # Looks like a BucketConfig object - create compatible one with name
                bucket_data = {
                    "min_tokens": config.min_tokens,
                    "max_tokens": config.max_tokens,
                    "weight": config.weight,
                    "compress": getattr(config, "compress", None),
                    "content_score": getattr(config, "content_score", 0.5),
                    "message_role": getattr(config, "message_role", "system"),
                }
                # Add optional attributes only if they exist
                for attr in ["select", "rerank", "droppable", "placement"]:
                    if hasattr(config, attr):
                        bucket_data[attr] = getattr(config, attr)
                bucket = BucketConfig(name=name, **bucket_data)
                self.add_bucket(bucket)
            elif isinstance(config, dict):
                # Dictionary configuration
                bucket = BucketConfig(name=name, **config)
                self.add_bucket(bucket)
            else:
                raise ValueError(
                    f"Invalid bucket configuration type for {name}: {type(config)}"
                )

    def allocate_budget(
        self,
        content_scores: Optional[Dict[str, float]] = None,
        system_overhead: int = 200,
    ) -> List[BudgetAllocation]:
        """
        Allocate budget across buckets using the algorithm from context_engineer.md.

        Args:
            model_context_limit: Model's context window limit
            output_budget: Tokens reserved for output
            content_scores: Relevance scores for each bucket's content (optional)
            system_overhead: System overhead tokens

        Returns:
            List of budget allocations
        """
        available_budget = self.calculate_budget(
            self.model_config.context_limit,
            self.model_config.output_budget,
            system_overhead,
        )

        # Step 1: Initial allocation with minimum requirements
        allocations = self._initial_allocation(available_budget)
        remaining_budget = available_budget - sum(
            alloc.allocated_tokens for alloc in allocations
        )

        # Step 2: Dynamic optimization based on content scores
        if remaining_budget > 0:
            # If content_scores is not provided, use the default values from BucketConfig
            if content_scores is None:
                content_scores = {
                    name: bucket.content_score for name, bucket in self.buckets.items()
                }
            allocations = self._optimize_allocation(
                allocations, content_scores, remaining_budget
            )

        # Remove meaningless overflow handling logic
        # The preceding allocation logic has already ensured that the total allocation will not exceed the available budget.
        # Compression decisions should be based on actual content vs allocated_tokens, rather than "overflow" at the budget level
        return allocations

    def _initial_allocation(self, available_budget: int) -> List[BudgetAllocation]:
        """Step 1: Initial allocation with minimum requirements."""
        allocations = []
        min_total = sum(bucket.min_tokens for bucket in self.buckets.values())

        if available_budget < min_total:
            # Not enough budget for minimum requirements
            # Handle edge cases: budget is negative or zero
            if available_budget <= 0:
                # Extreme case: each bucket is allocated at least 1 token, distributed according to the minimum required ratio
                for bucket in self.buckets.values():
                    allocated = max(
                        1, int((bucket.min_tokens / min_total) * 1)
                    )  # Allocate at least 1 proportionally
                    allocation = BudgetAllocation(
                        bucket_name=bucket.name,
                        allocated_tokens=allocated,
                        priority=bucket.weight,
                    )
                    allocations.append(allocation)
            else:
                # Normal scale reduction: Allocate positive budget proportionally
                for bucket in self.buckets.values():
                    allocated = max(
                        1, int((bucket.min_tokens / min_total) * available_budget)
                    )
                    allocation = BudgetAllocation(
                        bucket_name=bucket.name,
                        allocated_tokens=allocated,
                        priority=bucket.weight,
                    )
                    allocations.append(allocation)
        else:
            # Normal allocation
            remaining_budget = available_budget - min_total
            total_weight = sum(bucket.weight for bucket in self.buckets.values())

            for bucket in self.buckets.values():
                # Calculate additional allocation based on weight
                additional = int((bucket.weight / total_weight) * remaining_budget)
                final_allocation = min(
                    bucket.max_tokens, bucket.min_tokens + additional
                )

                allocation = BudgetAllocation(
                    bucket_name=bucket.name,
                    allocated_tokens=final_allocation,
                    priority=bucket.weight,
                )
                allocations.append(allocation)

        return allocations

    def _optimize_allocation(
        self,
        allocations: List[BudgetAllocation],
        content_scores: Dict[str, float],
        remaining_budget: int,
    ) -> List[BudgetAllocation]:
        """Step 2: Optimize allocation based on content relevance scores."""
        # Calculate marginal utility for each bucket
        utilities = []
        for allocation in allocations:
            bucket = self.buckets[allocation.bucket_name]
            current_score = content_scores.get(bucket.name, 0.0)

            # Calculate potential improvement
            current_tokens = allocation.allocated_tokens
            max_tokens = bucket.max_tokens

            if current_tokens < max_tokens:
                # Marginal utility = score improvement per token
                marginal_utility = current_score / (current_tokens + 1)
                utilities.append(
                    (bucket.name, marginal_utility, max_tokens - current_tokens)
                )

        # Sort by marginal utility (descending)
        utilities.sort(key=lambda x: x[1], reverse=True)

        # Allocate remaining budget based on marginal utility
        for bucket_name, utility, available in utilities:
            if remaining_budget <= 0:
                break

            allocation = next(a for a in allocations if a.bucket_name == bucket_name)
            allocate_amount = min(available, remaining_budget)
            allocation.allocated_tokens += allocate_amount
            remaining_budget -= allocate_amount

        return allocations

    def calculate_budget(
        self, model_context_limit: int, output_budget: int, system_overhead: int = 200
    ) -> int:
        """Calculate available input budget.

                Calculate the available input budget.

        Args:
            model_context_limit: The model's context window limit
            output_budget: Number of tokens reserved for output
            system_overhead: Number of tokens for system overhead

        Returns:
            Available input budget
        """
        return model_context_limit - output_budget - system_overhead

    # Removed the meaningless _handle_overflow method
    # Compression logic is now based entirely on the comparison between actual content and allocated_tokens
    # Instead of "overflow" detection at the budget level

    def get_bucket_config(self, bucket_name: str) -> Optional[BucketConfig]:
        """Get configuration for a specific bucket.

                Get the configuration of a specific bucket.

        Args:
            bucket_name: The name of the bucket

        Returns:
            Bucket configuration object, or None if it does not exist
        """
        return self.buckets.get(bucket_name)

    def set_drop_order(self, drop_order: List[str]):
        """Set the order for dropping content when budget is exceeded.

                Set the order in which content is dropped when the budget is exceeded.

        Args:
            drop_order: List of bucket names, defining the drop order
        """
        self.drop_order = drop_order

    def validate_configuration(self) -> bool:
        """Validate the bucket configuration.

                Validate the validity of the bucket configuration.

        Returns:
            True if the configuration is valid, False otherwise
        """
        if not self.buckets:
            return False

        # Check that all buckets in drop order exist
        for bucket_name in self.drop_order:
            if bucket_name not in self.buckets:
                return False

        # Check basic constraints
        for bucket in self.buckets.values():
            if bucket.min_tokens > bucket.max_tokens:
                return False
            if bucket.weight < 0:
                return False

        return True

    def get_total_min_tokens(self) -> int:
        """Get total minimum tokens required across all buckets.

                Get the total minimum number of tokens required across all buckets.

        Returns:
            The total minimum number of tokens across all buckets
        """
        return sum(bucket.min_tokens for bucket in self.buckets.values())

    def get_total_max_tokens(self) -> int:
        """Get total maximum tokens across all buckets.

                Get the total maximum number of tokens across all buckets.

        Returns:
            The total maximum number of tokens across all buckets
        """
        return sum(bucket.max_tokens for bucket in self.buckets.values())
