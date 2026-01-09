"""Configuration settings for context engineering."""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import yaml
import json
from pathlib import Path
from enum import Enum
from dolphin.core.common.enums import MessageRole


class BuildInBucket(Enum):
    """Enumeration type, defines context bucket names"""

    SYSTEM = "_system"
    QUERY = "_query"
    SCRATCHPAD = "_scratchpad"
    HISTORY = "_history"


@dataclass
class ModelConfig:
    """Model configuration."""

    # Model Name
    name: str

    # Model context window limit (token count)
    context_limit: int

    # Expected output target (number of tokens)
    output_target: int

    # Reserved space (number of tokens)
    output_headroom: int = 300

    @property
    def output_budget(self) -> int:
        """Total output budget including headroom.

                Returns the model's total output budget, including expected output.
                This ensures the model has enough space to generate a complete response.
        """
        return self.output_target

    def input_budget(self, system_overhead: int = 200) -> int:
        """Calculate available input budget.

                Calculate the token budget available for input, which equals the model's context limit minus the output budget.
                Does not include system overhead

        Returns:
            The number of tokens available for input
        """
        return self.context_limit - self.output_budget


@dataclass
class BucketConfig:
    """Configuration for a context bucket.

        Context bucket configuration, used to define how different types of messages are handled and their priority.
    """

    # The name of the bucket, used to identify different context types
    name: str

    # The minimum number of tokens in a bucket to ensure that important context is not overly compressed
    min_tokens: int

    # The maximum number of tokens for the bucket, limiting the maximum space this type of context can occupy.
    max_tokens: int

    # The weight of the bucket, used to determine priority when allocating tokens (the higher the weight, the more tokens allocated)
    weight: float

    # Compression strategy, optional compression methods (such as truncation, summarization, etc.)
    compress: Optional[str] = None

    # Content scoring, used to evaluate the importance of content (0.0-1.0, with 1.0 indicating the most important)
    content_score: float = 0.5

    # Message role, specifying the type of message this bucket handles (system/user/tool/assistant)
    message_role: MessageRole = MessageRole.SYSTEM


@dataclass
class PolicyConfig:
    """Policy configuration.

        Policy configuration, used to define the order of context buckets and their deletion priority.

        Example configuration:
        {
            'drop_order': ['scratchpad', 'history', 'rag'],  # Defines the priority order when content needs to be deleted, with decreasing priority from left to right
            'bucket_order': ['system', 'task', 'tools', 'rag', 'history', 'fewshot', 'memory', 'scratchpad']  # Global order
        }

        bucket_order defines the global placement order of all buckets in the context, arranged sequentially according to the list order.
    """

    # Delete order, defines the deletion priority of each bucket when space needs to be freed, arranged from highest to lowest priority
    drop_order: List[str]

    # Global order, defining the placement order of all buckets within the context
    bucket_order: List[str]


@dataclass
class ContextConfig:
    """Main configuration for context engineering.

        The main configuration class for context engineering, used to manage model configurations, bucket configurations, and policy configurations.
        This class provides functionality to load configurations from dictionaries, YAML or JSON files, as well as methods to save and validate configurations.

        Attributes:
            model (ModelConfig): Model configuration information
            buckets (Dict[str, BucketConfig]): Dictionary of bucket configurations, with bucket names as keys and corresponding bucket configurations as values
            policies (Dict[str, PolicyConfig]): Dictionary of policy configurations, with policy names as keys and corresponding policy configurations as values
    """

    model: ModelConfig
    buckets: Dict[str, BucketConfig]
    policies: Dict[str, PolicyConfig]

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ContextConfig":
        """Create configuration from dictionary.

                Create a context configuration instance from a dictionary. This method parses model configuration, bucket configuration, and policy configuration,
                and adds a name field to buckets that are not explicitly named.

        Args:
            config_dict (Dict[str, Any]): Dictionary containing configuration information

        Returns:
            ContextConfig: The created context configuration instance
        """
        # Parse model config
        model_data = config_dict.get("model", {})
        model = ModelConfig(
            name=model_data.get("name", "gpt-4"),
            context_limit=model_data.get("context_limit", 8192),
            output_target=model_data.get("output_target", 1200),
            output_headroom=model_data.get("output_headroom", 300),
        )

        # Parse bucket configs
        buckets = {}
        buckets_data = config_dict.get("buckets", {})
        for name, bucket_data in buckets_data.items():
            # Add name field to bucket_data if not present
            bucket_data_with_name = bucket_data.copy()
            if "name" not in bucket_data_with_name:
                bucket_data_with_name["name"] = name
            # Process the message_role enumeration
            if "message_role" in bucket_data_with_name:
                message_role_value = bucket_data_with_name["message_role"]
                if isinstance(message_role_value, str):
                    try:
                        bucket_data_with_name["message_role"] = MessageRole(
                            message_role_value
                        )
                    except ValueError:
                        # If the string is not a valid MessageRole member, use the default value SYSTEM
                        bucket_data_with_name["message_role"] = MessageRole.SYSTEM
                elif not isinstance(message_role_value, MessageRole):
                    bucket_data_with_name["message_role"] = MessageRole.SYSTEM
            buckets[name] = BucketConfig(**bucket_data_with_name)

        # Parse policy configs
        policies = {}
        policies_data = config_dict.get("policies", {})
        for name, policy_data in policies_data.items():
            policies[name] = PolicyConfig(**policy_data)

        return cls(
            model=model,
            buckets=buckets,
            policies=policies,
        )

    @classmethod
    def from_yaml(cls, file_path: str) -> "ContextConfig":
        """Load configuration from YAML file.

                Load configuration information from a YAML file and create a context configuration instance.

        Args:
            file_path (str): Path to the YAML configuration file

        Returns:
            ContextConfig: Context configuration instance created from the YAML file
        """
        with open(file_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
        return cls.from_dict(config_dict)

    @classmethod
    def from_json(cls, file_path: str) -> "ContextConfig":
        """Load configuration from JSON file.

                Load configuration information from a JSON file and create a context configuration instance.

        Args:
            file_path (str): Path to the JSON configuration file

        Returns:
            ContextConfig: Context configuration instance created from the JSON file
        """
        with open(file_path, "r", encoding="utf-8") as f:
            config_dict = json.load(f)
        return cls.from_dict(config_dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary.

                Convert the current configuration instance to dictionary format for saving to file or transmission.

        Returns:
            Dict[str, Any]: Dictionary containing all configuration information
        """
        return {
            "model": {
                "name": self.model.name,
                "context_limit": self.model.context_limit,
                "output_target": self.model.output_target,
                "output_headroom": self.model.output_headroom,
            },
            "buckets": {
                name: {
                    "name": bucket.name,
                    "min_tokens": bucket.min_tokens,
                    "max_tokens": bucket.max_tokens,
                    "weight": bucket.weight,
                    "compress": bucket.compress,
                    "content_score": bucket.content_score,
                    "message_role": str(bucket.message_role),  # Convert enum to string
                }
                for name, bucket in self.buckets.items()
            },
            "policies": {
                name: {
                    "drop_order": policy.drop_order,
                    "bucket_order": policy.bucket_order,
                }
                for name, policy in self.policies.items()
            },
        }

    def save_yaml(self, file_path: str):
        """Save configuration to YAML file.

                Save the current configuration to a YAML file.

        Args:
            file_path (str): Path to the YAML file to save to
        """
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True)

    def save_json(self, file_path: str):
        """Save configuration to JSON file.

                Save the current configuration to a JSON file.

        Args:
            file_path (str): The path to the JSON file to save.
        """
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def get_bucket_config(self, bucket_name: str) -> Optional[BucketConfig]:
        """Get configuration for a specific bucket.

                Get the configuration for a bucket with a specified name.

        Args:
            bucket_name (str): The name of the bucket

        Returns:
            Optional[BucketConfig]: The corresponding bucket configuration, or None if it does not exist
        """
        return self.buckets.get(bucket_name)

    def get_policy_config(self, policy_name: str) -> Optional[PolicyConfig]:
        """Get configuration for a specific policy.

                Get the configuration for a policy with a specific name.

        Args:
            policy_name (str): The name of the policy

        Returns:
            Optional[PolicyConfig]: The corresponding policy configuration, or None if it does not exist
        """
        return self.policies.get(policy_name)

    def get_default_policy(self) -> Optional[PolicyConfig]:
        """Get the default policy configuration.

                Get the default policy configuration.

        Returns:
            Optional[PolicyConfig]: The default policy configuration, or None if it does not exist
        """
        return self.policies.get("default")

    def validate(self) -> List[str]:
        """Validate configuration and return list of issues.

                Validate the validity of the configuration, checking whether the model configuration, bucket configuration, and policy configuration meet requirements.

        Returns:
            List[str]: List of validation issues; if the configuration is valid, returns an empty list
        """
        issues = []

        # Validate model config
        if self.model.context_limit <= 0:
            issues.append("Model context limit must be positive")

        if self.model.output_budget >= self.model.context_limit:
            issues.append("Output budget exceeds model context limit")

        # Validate bucket configs
        if not self.buckets:
            issues.append("No buckets configured")

        for name, bucket in self.buckets.items():
            if bucket.min_tokens > bucket.max_tokens:
                issues.append(f"Bucket '{name}': min_tokens > max_tokens")

            if bucket.weight < 0:
                issues.append(f"Bucket '{name}': weight must be non-negative")

        # Validate policy configs
        for name, policy in self.policies.items():
            for bucket_name in policy.drop_order:
                if bucket_name not in self.buckets:
                    issues.append(
                        f"Policy '{name}': unknown bucket in drop_order: '{bucket_name}'"
                    )

            for bucket_name in policy.bucket_order:
                if bucket_name not in self.buckets:
                    issues.append(
                        f"Policy '{name}': unknown bucket in bucket_order: '{bucket_name}'"
                    )

        return issues


def get_default_config() -> ContextConfig:
    """Get default configuration based on context_engineer.md specifications."""
    return ContextConfig.from_dict(
        {
            "model": {
                "name": "gpt-4",
                "context_limit": 8192,
                "output_target": 1200,
            },
            "buckets": {
                "_system": {
                    "name": "_system",
                    "min_tokens": 300,
                    "max_tokens": 1024,
                    "weight": 2.0,
                    "message_role": "system",
                },
                "_history": {
                    "name": "_history",
                    "min_tokens": 120,
                    "max_tokens": 1024,
                    "weight": 0.8,
                    "message_role": "user",
                },
                "_query": {
                    "name": "_query",
                    "min_tokens": 120,
                    "max_tokens": 1024,
                    "weight": 0.8,
                    "message_role": "user",
                },
                "_scratchpad": {
                    "name": "_scratchpad",
                    "min_tokens": 0,
                    "max_tokens": 2048,
                    "weight": 1.2,
                    "message_role": "user",
                },
            },
            "policies": {
                "default": {
                    "drop_order": [],
                    "bucket_order": ["_system", "_history", "_query", "_scratchpad"],
                }
            },
        }
    )
