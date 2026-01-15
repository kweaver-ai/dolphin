from enum import Enum
import json
import os
import re
from typing import Optional, Dict, Any, List

from dolphin.core.context_engineer.config.settings import ContextConfig
import yaml

from dolphin.core.common.enums import Messages
from dolphin.core.config.ontology_config import OntologyConfig
from dolphin.core.utils.cache_kv import GlobalCacheKVCenter


def _resolve_env_var(value: str) -> str:
    """Resolve environment variable references in string values.
    
    Supports format: ${VAR_NAME}
    If the environment variable is not found, raises ValueError (fail fast).
    
    Args:
        value: String value that may contain environment variable references
        
    Returns:
        Resolved string with environment variables substituted
        
    Raises:
        ValueError: If referenced environment variable is not found
    """
    if not isinstance(value, str):
        return value
    
    # If value doesn't contain ${}, return as-is
    if '${' not in value:
        return value
    
    # Pattern to match ${VAR_NAME} format
    pattern = r'\$\{([^}]+)\}'
    
    def replace_env_var(match):
        var_name = match.group(1)
        env_value = os.getenv(var_name)
        if env_value is None:
            raise ValueError(
                f"Environment variable '{var_name}' not found. "
                f"Please set it before running the application."
            )
        return env_value
    
    result = re.sub(pattern, replace_env_var, value)
    return result


class TypeAPI(Enum):
    OPENAI = "openai"
    AISHU_MODEL_FACTORY = "aishu_model_factory"

    @staticmethod
    def from_str(type_api_str: str) -> "TypeAPI":
        if type_api_str == TypeAPI.AISHU_MODEL_FACTORY.value:
            return TypeAPI.AISHU_MODEL_FACTORY
        elif type_api_str == TypeAPI.OPENAI.value:
            return TypeAPI.OPENAI
        else:
            raise ValueError(f"不支持的API类型: {type_api_str}")


class CloudConfig:
    def __init__(
        self,
        api: str = None,
        api_key: str = None,
        user_id: str = None,
        headers: dict = None,
    ):
        self.api = api
        self.api_key = api_key
        self.user_id = user_id
        self.headers = headers or {}

    @staticmethod
    def from_dict(config_dict) -> "CloudConfig":
        api = _resolve_env_var(config_dict.get("api")) if config_dict.get("api") else None
        api_key = _resolve_env_var(config_dict.get("api_key")) if config_dict.get("api_key") else None
        user_id = None

        if "userid" in config_dict:
            user_id = _resolve_env_var(config_dict.get("userid"))
            headers = {"x-user-id": user_id}
        else:
            user_id = _resolve_env_var(
                config_dict.get("headers", {}).get(
                    "x-user-id", "default-x-user-id"
                )
            )
            headers = {"x-user-id": user_id}

        if "security_token" in config_dict:
            headers["security-token"] = _resolve_env_var(config_dict.get("security_token"))

        # Merge the headers field in the configuration file
        if "headers" in config_dict:
            # Resolve environment variables in headers values
            resolved_headers = {
                k: _resolve_env_var(v) if isinstance(v, str) else v
                for k, v in config_dict["headers"].items()
            }
            headers.update(resolved_headers)

        headers["Authorization"] = f"Bearer {api_key}"
        headers["Content-Type"] = "application/json"
        return CloudConfig(api=api, api_key=api_key, user_id=user_id, headers=headers)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "api": self.api,
            "api_key": self.api_key,
            "user_id": self.user_id,
            "headers": self.headers,
        }


class AllCloudsConfig:
    def __init__(self, default_cloud: str, clouds: dict):
        self.default_cloud = default_cloud
        self.clouds = clouds

    def get_cloud_config(self, cloud_name: Optional[str]) -> CloudConfig:
        if cloud_name in self.clouds:
            return self.clouds[cloud_name]
        elif cloud_name is None:
            return self.clouds[self.default_cloud]
        else:
            raise ValueError(f"cloud_name {cloud_name} not found in clouds")

    @staticmethod
    def from_dict(config_dict: dict) -> "AllCloudsConfig":
        clouds = {}
        default_cloud = config_dict.get("default")
        for cloud_name, cloud_config in config_dict.items():
            if cloud_name == "default":
                continue

            if cloud_name not in clouds:
                clouds[cloud_name] = CloudConfig.from_dict(cloud_config)
            else:
                raise ValueError(f"cloud_name {cloud_name} already exists in clouds")
        return AllCloudsConfig(default_cloud, clouds)


class LLMConfig:
    def __init__(
        self,
        name: str,
        temperature: float,
        top_p: float,
        top_k: int,
        frequency_penalty: int,
        presence_penalty: int,
        max_tokens: int,
        icon: str,
        model_name: str,
        type_api: TypeAPI,
        api: str,
        userid: str,
        headers: dict,
        security_token: str,
        id: str,
    ):
        self.name = name
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.icon = icon
        self.model_name = model_name
        self.type_api = type_api
        self.api = api
        self.userid = userid
        self.headers = headers or {}
        self.security_token = security_token
        self.id = id

    @staticmethod
    def from_dict(llm_name, config_dict) -> "LLMConfig":
        temperature = config_dict.get("temperature", 0)
        top_p = config_dict.get("top_p", 0.95)
        top_k = config_dict.get("top_k", 1)
        frequency_penalty = config_dict.get("frequency_penalty", 0)
        presence_penalty = config_dict.get("presence_penalty", 0)
        max_tokens = config_dict.get("max_tokens", 8192)
        icon = config_dict.get("icon", "")
        model_name = config_dict.get("model_name")
        type_api = TypeAPI.from_str(
            config_dict.get("type_api", TypeAPI.AISHU_MODEL_FACTORY.value)
        )
        api = _resolve_env_var(config_dict.get("api")) if config_dict.get("api") else None
        userid = _resolve_env_var(config_dict.get("userid")) if config_dict.get("userid") else None
        # Resolve environment variables in headers values
        headers_raw = config_dict.get("headers", {})
        headers = {
            k: _resolve_env_var(v) if isinstance(v, str) else v
            for k, v in headers_raw.items()
        } if headers_raw else {}
        security_token = _resolve_env_var(config_dict.get("security_token")) if config_dict.get("security_token") else None
        id_value = config_dict.get("id")
        return LLMConfig(
            name=llm_name,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            max_tokens=max_tokens,
            icon=icon,
            model_name=model_name,
            type_api=type_api,
            api=api,
            userid=userid,
            headers=headers,
            security_token=security_token,
            id=id_value,
        )

    def to_dict(self) -> dict:
        return {
            "llm_name": self.name,
            "model_name": self.model_name,
            "type_api": self.type_api,
            "api": self.api,
            "userid": self.userid,
            "headers": self.headers,
            "security_token": self.security_token,
            "id": self.id,
            "icon": self.icon,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


class LLMInstanceConfig:
    def __init__(self, llm_name: str, cloud_config: CloudConfig, llm_config: LLMConfig):
        self.llm_name = llm_name
        self.cloud_config = cloud_config
        self.llm_config = llm_config

    # LLMConfig Attribute Accessor
    @property
    def name(self) -> str:
        return self.llm_config.name

    @property
    def temperature(self) -> float:
        return self.llm_config.temperature

    @property
    def top_p(self) -> float:
        return self.llm_config.top_p

    @property
    def top_k(self) -> int:
        return self.llm_config.top_k

    @property
    def frequency_penalty(self) -> int:
        return self.llm_config.frequency_penalty

    @property
    def presence_penalty(self) -> int:
        return self.llm_config.presence_penalty

    @property
    def max_tokens(self) -> int:
        return self.llm_config.max_tokens

    @property
    def icon(self) -> str:
        return self.llm_config.icon

    @property
    def model_name(self) -> str:
        return self.llm_config.model_name

    @property
    def llm_api(self) -> str:
        return self.llm_config.api

    @property
    def userid(self) -> str:
        return self.llm_config.userid

    @property
    def llm_headers(self) -> dict:
        return self.llm_config.headers

    @property
    def security_token(self) -> str:
        return self.llm_config.security_token

    @property
    def id(self) -> str:
        return self.llm_config.id

    @property
    def type_api(self) -> TypeAPI:
        return self.llm_config.type_api

    # CloudConfig Attribute Accessor
    @property
    def api(self) -> str:
        return self.cloud_config.api

    @property
    def api_key(self) -> str:
        return self.cloud_config.api_key

    def set_api_key(self, api_key: str):
        self.cloud_config.api_key = api_key

    @property
    def user_id(self) -> str:
        return self.cloud_config.user_id

    @property
    def headers(self) -> dict:
        return self.cloud_config.headers

    # Convenient method:Prioritize using LLMConfig 的 api，如果没有则使用 CloudConfig 的 api
    @property
    def effective_api(self) -> str:
        return self.llm_config.api if self.llm_config.api else self.cloud_config.api

    @property
    def effective_headers(self) -> dict:
        # Merge CloudConfig and LLMConfig headers
        combined_headers = {}
        if self.cloud_config.headers:
            combined_headers.update(self.cloud_config.headers)
        if self.llm_config.headers:
            combined_headers.update(self.llm_config.headers)
        return combined_headers

    @staticmethod
    def from_dict(llm_name, all_clouds_config, config_dict) -> "LLMInstanceConfig":
        cloud_name = config_dict.get("cloud", None)
        if cloud_name:
            cloud_config = all_clouds_config.get_cloud_config(cloud_name)
        else:
            cloud_config = CloudConfig.from_dict(config_dict)

        llm_config = LLMConfig.from_dict(llm_name, config_dict)
        return LLMInstanceConfig(
            llm_name=llm_name, cloud_config=cloud_config, llm_config=llm_config
        )

    def to_dict(self) -> dict:
        return {
            "llm_name": self.llm_name,
            "cloud_config": self.cloud_config.to_dict(),
            "llm_config": self.llm_config.to_dict(),
        }


class VMConnectionType(Enum):
    SSH = 0
    DOCKER = 1


class VMConfig:
    def __init__(
        self,
        connectionType: VMConnectionType,
        host: str,
        port: int,
        username: str,
        encryptedPassword: str,
        sshKeyPath: str = None,
        timeout: int = 10,
        retryCount: int = 3,
    ):
        self.connectionType = connectionType
        self.connection_type = connectionType  # Add alias for backward compatibility
        self.host = host
        self.port = port
        self.username = username
        self.encryptedPassword = encryptedPassword
        self.sshKeyPath = sshKeyPath
        self.timeout = timeout
        self.retryCount = retryCount

    @staticmethod
    def fromArgs(config: dict):
        # Get basic configuration
        connectionType = (
            VMConnectionType.SSH
            if config["connection_type"] == "ssh"
            else VMConnectionType.DOCKER
        )
        host = config["host"]
        port = config["port"]
        username = config["username"]
        encryptedPassword = config["encrypted_password"]

        # Get optional configuration
        sshKeyPath = config.get("ssh_key_path", None)
        timeout = config.get("timeout", 10)
        retryCount = config.get("retry_count", 3)

        return VMConfig(
            connectionType=connectionType,
            host=host,
            port=port,
            username=username,
            encryptedPassword=encryptedPassword,
            sshKeyPath=sshKeyPath,
            timeout=timeout,
            retryCount=retryCount,
        )

    def validate(self) -> bool:
        """Validate whether the configuration is valid

        Returns:
            bool: Whether the configuration is valid
        """
        # Validate basic parameters
        if not self.host or not isinstance(self.host, str):
            return False

        if not isinstance(self.port, int) or self.port <= 0 or self.port > 65535:
            return False

        if not self.username or not isinstance(self.username, str):
            return False

        # At least one of password and SSH key must be provided
        if not self.encryptedPassword and not self.sshKeyPath:
            return False

        # If an SSH key path is specified, check whether the file exists
        if self.sshKeyPath and not os.path.exists(self.sshKeyPath):
            return False

        return True

    def toDict(self) -> dict:
        """Convert configuration to dictionary

        Returns:
            dict: configuration dictionary
        """
        return {
            "connection_type": (
                "ssh" if self.connectionType == VMConnectionType.SSH else "docker"
            ),
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "encrypted_password": self.encryptedPassword,
            "ssh_key_path": self.sshKeyPath,
            "timeout": self.timeout,
            "retry_count": self.retryCount,
        }

    def __str__(self) -> str:
        """Return the string representation of the configuration

        Returns:
            str: The string representation of the configuration
        """
        return f"VMConfig(type={self.connectionType.name}, host={self.host}, port={self.port}, username={self.username})"


class ContextConstraints:
    """Context Constraint Parameters

        Parameter Description:
        - max_input_tokens: Maximum number of input tokens the model can accept, which is the model's input capacity limit
        - reserve_output_tokens: Number of tokens reserved for model output, ensuring sufficient space to generate a response
        - preserve_system: Whether to retain system messages during compression

        Calculation Logic:
        Available input tokens = max_input_tokens - reserve_output_tokens

        Recommendation:
        - max_input_tokens: Usually set to the model's maximum context length (e.g., 128K, 32K, etc.)
        - reserve_output_tokens: Set to the expected maximum output length, typically the model's max_tokens configuration value

        Automatic Adjustment:
        When model_config is provided, the system automatically sets reserve_output_tokens to model_config.max_tokens
    """

    def __init__(
        self,
        max_input_tokens: int = 64000,  # Maximum input token count
        reserve_output_tokens: int = 8192,  # Number of tokens reserved for output
        preserve_system: bool = True,  # Whether to retain system messages
    ):
        self.max_input_tokens = max_input_tokens
        self.reserve_output_tokens = reserve_output_tokens
        self.preserve_system = preserve_system

    @staticmethod
    def from_dict(config_dict: dict) -> "ContextConstraints":
        """Create constraints from dictionary"""
        return ContextConstraints(
            max_input_tokens=config_dict.get("max_input_tokens", 64000),
            reserve_output_tokens=config_dict.get("reserve_output_tokens", 8192),
            preserve_system=config_dict.get("preserve_system", True),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "max_input_tokens": self.max_input_tokens,
            "reserve_output_tokens": self.reserve_output_tokens,
            "preserve_system": self.preserve_system,
        }


class MemoryConfig:
    """Configuration for the memory system."""

    def __init__(
        self,
        enabled: bool = False,
        storage_path: str = "data/memory/",
        dialog_path: str = "data/dialog/",
        default_top_k: int = 10,
    ):
        self.enabled = enabled
        self.storage_path = storage_path
        self.dialog_path = dialog_path
        self.default_top_k = default_top_k

    @staticmethod
    def from_dict(config_dict: dict) -> "MemoryConfig":
        return MemoryConfig(
            enabled=config_dict.get("enabled", False),
            storage_path=config_dict.get("storage_path", "data/memory/"),
            dialog_path=config_dict.get("dialog_path", "data/dialog/"),
            default_top_k=config_dict.get("default_top_k", 10),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "storage_path": self.storage_path,
            "dialog_path": self.dialog_path,
            "default_top_k": self.default_top_k,
        }


class MCPServerConfig:
    """MCP Server Configuration"""

    def __init__(
        self,
        name: str,
        connection_mode: str = "stdio",  # "stdio" or "http"
        command: str = None,  # stdio mode usage
        args: List[str] = None,  # stdio mode usage
        url: str = None,  # HTTP Mode Usage
        env: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        enabled: bool = False,
        auth: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.connection_mode = connection_mode
        self.command = command  # Start command, such as "npx"
        self.args = args or []  # Parameter List
        self.url = url  # HTTP Server URL
        self.env = env  # Environment Variables
        self.timeout = timeout
        self.enabled = enabled
        self.auth = auth  # Authentication Information

        # Validate configuration
        if connection_mode == "stdio":
            if not command:
                raise ValueError(f"stdio mode requires 'command' for server {name}")
        elif connection_mode == "http":
            if not url:
                raise ValueError(f"http mode requires 'url' for server {name}")
        else:
            raise ValueError(
                f"Invalid connection_mode: {connection_mode}, must be 'stdio' or 'http'"
            )

    @staticmethod
    def from_dict(config_dict: dict) -> "MCPServerConfig":
        return MCPServerConfig(
            name=config_dict["name"],
            connection_mode=config_dict.get("connection_mode", "stdio"),
            command=config_dict.get("command"),
            args=config_dict.get("args", []),
            url=config_dict.get("url"),
            env=config_dict.get("env"),
            timeout=config_dict.get("timeout", 30),
            enabled=config_dict.get("enabled", True),
            auth=config_dict.get("auth"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "connection_mode": self.connection_mode,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "env": self.env,
            "timeout": self.timeout,
            "enabled": self.enabled,
            "auth": self.auth,
        }


class MCPConfig:
    """MCP Configuration"""

    def __init__(self, enabled: bool = True, servers: List[MCPServerConfig] = None):
        self.enabled = enabled
        self.servers = servers or []

    @staticmethod
    def from_dict(config_dict: dict) -> "MCPConfig":
        servers = []
        for server_dict in config_dict.get("servers", []):
            server = MCPServerConfig.from_dict(server_dict)
            servers.append(server)

        return MCPConfig(enabled=config_dict.get("enabled", True), servers=servers)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "enabled": self.enabled,
            "servers": [server.to_dict() for server in self.servers],
        }


class SkillConfig:
    """Skill Loading Configuration"""

    def __init__(self, enabled_skills: List[str] = None):
        """Initialize skill configuration

        Args:
            enabled_skills: List of enabled skills, None means load all skills
                                 Supports the following formats:
                                 - "vm_skillkit": Load a specific skillkit
                                 - "mcp": Load all MCP servers
                                 - "mcp.filesystem": Load a specific MCP server
        """
        self.enabled_skills = enabled_skills

    @staticmethod
    def _normalize_skill_name(name: str) -> str:
        """Normalize skill identifiers for backward compatibility.

        Historically, config examples used names like "vm_skillkit" while the
        entry-point based loader uses names like "vm". We accept both by
        normalizing the "_skillkit" suffix for non-namespaced skill ids.
        """
        if not isinstance(name, str):
            return name
        # Keep namespaced ids as-is (e.g. "mcp.playwright", "system_functions.grep")
        if "." in name:
            return name
        if name.endswith("_skillkit"):
            return name[: -len("_skillkit")]
        return name

    def should_load_skill(self, skill_name: str) -> bool:
        """Check whether a certain skill should be loaded

        Args:
            skill_name: Name of the skill

        Returns:
            bool: Whether it should be loaded
        """
        if self.enabled_skills is None:
            return True

        # If it's an empty list, no skills will be loaded.
        if len(self.enabled_skills) == 0:
            return False

        normalized_enabled = set()
        for enabled in self.enabled_skills:
            normalized_enabled.add(enabled)
            normalized_enabled.add(self._normalize_skill_name(enabled))

        normalized_skill_name = self._normalize_skill_name(skill_name)

        # Check direct match
        if skill_name in normalized_enabled or normalized_skill_name in normalized_enabled:
            return True

        # Check MCP mode matching
        if skill_name.startswith("mcp."):
            # If "mcp" is included, load all MCP servers
            if "mcp" in normalized_enabled:
                return True
            # If a specific MCP server name is included, load that server
            if skill_name in normalized_enabled:
                return True

        return False

    def should_load_mcp_server(self, server_name: str) -> bool:
        """Check whether a certain MCP server should be loaded

        Args:
            server_name: Name of the MCP server

        Returns:
            bool: Whether it should be loaded
        """
        if self.enabled_skills is None:
            return True

        # If "mcp" is included, load all MCP servers
        if "mcp" in self.enabled_skills:
            return True

        # If a specific MCP server name is included, load that server.
        if f"mcp.{server_name}" in self.enabled_skills:
            return True

        return False

    @staticmethod
    def from_dict(config_dict: dict) -> "SkillConfig":
        """Create configuration from dictionary"""
        return SkillConfig(enabled_skills=config_dict.get("enabled_skills"))

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {"enabled_skills": self.enabled_skills}


class RetrievalProcessingConfig:
    """Retrieval system processing configuration"""

    def __init__(
        self,
        max_text_length: int = 512,
        max_batch_size: int = 16,
        max_documents_per_rerank: int = 100,
        chunk_overlap: int = 50,
        chunk_size: int = 512,
    ):
        self.max_text_length = max_text_length  # Maximum length (tokens) for a single text
        self.max_batch_size = max_batch_size  # embedding batch size
        self.max_documents_per_rerank = max_documents_per_rerank  # Number of documents processed at once by rerank
        self.chunk_overlap = chunk_overlap  # Document slice overlap length
        self.chunk_size = chunk_size  # Document chunk size

    @staticmethod
    def from_dict(config_dict: dict) -> "RetrievalProcessingConfig":
        """Create configuration from dictionary"""
        return RetrievalProcessingConfig(
            max_text_length=config_dict.get("max_text_length", 512),
            max_batch_size=config_dict.get("max_batch_size", 16),
            max_documents_per_rerank=config_dict.get("max_documents_per_rerank", 100),
            chunk_overlap=config_dict.get("chunk_overlap", 50),
            chunk_size=config_dict.get("chunk_size", 512),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "max_text_length": self.max_text_length,
            "max_batch_size": self.max_batch_size,
            "max_documents_per_rerank": self.max_documents_per_rerank,
            "chunk_overlap": self.chunk_overlap,
            "chunk_size": self.chunk_size,
        }


class RetrievalModelConfig:
    """Retrieval model configuration, supports multiple cloud providers"""

    def __init__(
        self,
        embedding_config: dict = None,
        rerank_config: dict = None,
        cloud: str = None,
        index_path: str = None,
        processing_config: RetrievalProcessingConfig = None,
    ):
        self.embedding_config = embedding_config or {}
        self.rerank_config = rerank_config or {}
        self.cloud = cloud  # Specify the cloud provider to use
        self.index_path = index_path or "data/local_retrieval_index.pkl"  # Index file path
        # System Processing Configuration
        self.processing_config = processing_config or RetrievalProcessingConfig()

    @staticmethod
    def from_dict(config_dict: dict) -> "RetrievalModelConfig":
        """Create configuration from dictionary"""
        processing_config = None
        if "processing_config" in config_dict:
            processing_config = RetrievalProcessingConfig.from_dict(
                config_dict["processing_config"]
            )

        return RetrievalModelConfig(
            embedding_config=config_dict.get("embedding_config", {}),
            rerank_config=config_dict.get("rerank_config", {}),
            cloud=config_dict.get("cloud"),
            index_path=config_dict.get("index_path"),
            processing_config=processing_config,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "embedding_config": self.embedding_config,
            "rerank_config": self.rerank_config,
            "cloud": self.cloud,
            "index_path": self.index_path,
            "processing_config": self.processing_config.to_dict(),
        }


class ContextEngineerConfig:
    """Context Engineer Configuration"""

    def __init__(
        self,
        context_config: ContextConfig = None,
        import_mem: bool = False,
        default_strategy: str = "level",
        constraints: ContextConstraints = None,
        strategy_configs: Dict[str, Any] = None,
        tokenizer_backend: str = "auto",
    ):
        self.context_config = context_config
        self.import_mem = import_mem
        self.default_strategy = default_strategy
        self.constraints = constraints or ContextConstraints()
        self.strategy_configs = strategy_configs or {}
        self.tokenizer_backend = tokenizer_backend

    @staticmethod
    def from_dict(config_dict: dict, base_dir: str = None) -> "ContextEngineerConfig":
        """Create configuration from dictionary

        Args:
            config_dict: Configuration dictionary
            base_dir: Base directory for resolving relative paths in config_path
        """
        context_config = None
        config_path = config_dict.get("config_path")
        if config_path:
            # Resolve relative path relative to base_dir if provided
            if not os.path.isabs(config_path) and base_dir:
                # If config_path starts with base_dir name, remove the prefix to avoid duplication
                base_dir_name = os.path.basename(base_dir)
                if config_path.startswith(base_dir_name + os.sep):
                    config_path = config_path[len(base_dir_name + os.sep):]
                config_path = os.path.join(base_dir, config_path)
            context_config = ContextConfig.from_yaml(config_path)

        constraints_dict = config_dict.get("constraints", {})
        constraints = ContextConstraints.from_dict(constraints_dict)
        return ContextEngineerConfig(
            context_config=context_config,
            import_mem=config_dict.get("import_mem", False),
            default_strategy=config_dict.get("default_strategy", "level"),
            constraints=constraints,
            strategy_configs=config_dict.get("strategy_configs", {}),
            tokenizer_backend=config_dict.get("tokenizer_backend", "auto"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        data = {
            "import_mem": self.import_mem,
            "default_strategy": self.default_strategy,
            "constraints": self.constraints.to_dict(),
            "strategy_configs": self.strategy_configs,
            "tokenizer_backend": self.tokenizer_backend,
        }
        # Compatible output extended fields
        if hasattr(self, "config_path") and getattr(self, "config_path"):
            data["config_path"] = getattr(self, "config_path")
        return data

class GlobalConfig:
    def __init__(
        self,
        default_llm: str = "",
        llmInstanceConfigs: dict = {},
        fast_llm: str = None,
        all_clouds_config: AllCloudsConfig = None,
        vm_config: VMConfig = None,
        context_engineer_config: ContextEngineerConfig = None,
        memory_config: MemoryConfig = None,
        mcp_config: MCPConfig = None,
        skill_config: SkillConfig = None,
        resource_skills: Optional[Dict[str, Any]] = None,
        ontology_config: OntologyConfig = None,
        retrieval_model_config: RetrievalModelConfig = None,
        base_dir: Optional[str] = None,
    ):
        self.default_llm = default_llm
        self.fast_llm = fast_llm if fast_llm else default_llm
        self.all_clouds_config = all_clouds_config
        self.llmInstanceConfigs = llmInstanceConfigs
        self._vm_config = vm_config
        self._context_engineer_config = (
            context_engineer_config or ContextEngineerConfig()
        )
        self._memory_config = memory_config or MemoryConfig()
        self._mcp_config = mcp_config or MCPConfig()
        self._skill_config = skill_config or SkillConfig()
        self._resource_skills = resource_skills
        self._llm_cache = GlobalCacheKVCenter.getCacheMgr(
            "data/cache/", category="llm", expireTimeByDay=7
        )
        self._ontology_config = ontology_config
        self._retrieval_model_config = retrieval_model_config
        self._base_dir = base_dir

    @property
    def base_dir(self) -> Optional[str]:
        """Get the base directory for resolving relative paths.

        Returns:
            The directory where the config file is located, or None if not set.
        """
        return self._base_dir

    @property
    def vm_config(self) -> VMConfig:
        return self._vm_config

    @property
    def context_engineer_config(self) -> ContextEngineerConfig:
        """[Deprecated alias] Old name, returns MessageCompressor configuration"""
        return self._context_engineer_config

    @property
    def message_compressor_config(self) -> ContextEngineerConfig:
        """MessageCompressor New Naming Configuration Access Entry"""
        return self._context_engineer_config

    @property
    def memory_config(self) -> MemoryConfig:
        return self._memory_config

    @property
    def mcp_config(self) -> MCPConfig:
        return self._mcp_config

    @property
    def skill_config(self) -> SkillConfig:
        return self._skill_config

    @property
    def resource_skills(self) -> Optional[Dict[str, Any]]:
        return self._resource_skills

    @property
    def ontology_config(self) -> OntologyConfig:
        return self._ontology_config

    @property
    def retrieval_model_config(self) -> RetrievalModelConfig:
        return self._retrieval_model_config

    def get_model_config(self, llm_name: Optional[str]) -> LLMInstanceConfig:
        if llm_name in self.llmInstanceConfigs:
            return self.llmInstanceConfigs.get(llm_name, "")
        elif not llm_name:
            return self.llmInstanceConfigs.get(self.default_llm, {})
        else:
            raise ValueError(f"llm_name {llm_name} not found in llmInstanceConfigs")

    def get_default_model_config(self) -> LLMInstanceConfig:
        return self.get_model_config(self.default_llm)

    def get_fast_model_config(self) -> LLMInstanceConfig:
        return self.get_model_config(self.fast_llm)

    def set_llm_cache(self, llm: str, key: Messages, value: Any):
        self._llm_cache.setValue(llm, key=key.get_messages_as_dict(), value=value)

    def get_llm_cache(self, llm: str, key: Messages):
        return self._llm_cache.getValue(llm, key=key.get_messages_as_dict())

    def set_llm_cache_by_dict(self, llm: str, key: List[Dict[str, Any]], value: Any):
        """Set LLM cache using a sanitized dict-list key."""
        self._llm_cache.setValue(llm, key=key, value=value)

    def get_llm_cache_by_dict(self, llm: str, key: List[Dict[str, Any]]):
        """Get LLM cache using a sanitized dict-list key."""
        return self._llm_cache.getValue(llm, key=key)

    @staticmethod
    def from_dict(config_dict: dict, base_dir: str = None) -> "GlobalConfig":
        is_new_config_format = "llms" in config_dict and "default" in config_dict
        if is_new_config_format:
            default_llm = config_dict.get("default")
            fast_llm = config_dict.get("fast", None)

            clouds = config_dict.get("clouds", None)
            all_clouds_config = AllCloudsConfig.from_dict(clouds) if clouds else None

            llms = config_dict.get("llms")
            llmInstanceConfigs = {}
            for llm_name, llm_config in llms.items():
                llmInstanceConfigs[llm_name] = LLMInstanceConfig.from_dict(
                    llm_name, all_clouds_config, llm_config
                )

            if default_llm not in llmInstanceConfigs:
                raise ValueError(
                    f"default_llm {default_llm} not found in llmInstanceConfigs"
                )

            if fast_llm and fast_llm not in llmInstanceConfigs:
                raise ValueError(f"fast_llm {fast_llm} not found in llmInstanceConfigs")

            vm = config_dict.get("vm", None)
            vm_config = VMConfig.fromArgs(vm) if vm else None

            context_engineer = config_dict.get("context_engineer", None)
            context_engineer_config = (
                ContextEngineerConfig.from_dict(context_engineer, base_dir=base_dir)
                if context_engineer
                else None
            )

            memory = config_dict.get("memory", None)
            memory_config = MemoryConfig.from_dict(memory) if memory else None

            # Parse MCP configuration
            mcp = config_dict.get("mcp", None)
            mcp_config = MCPConfig.from_dict(mcp) if mcp else None

            # Parse skill configuration
            skill = config_dict.get("skill", None)
            skill_config = SkillConfig.from_dict(skill) if skill else None

            # ResourceSkillkit configuration (Claude Skill format support)
            resource_skills = config_dict.get("resource_skills", None)

            ontology = config_dict.get("ontology", None)
            ontology_config = OntologyConfig.from_dict(ontology) if ontology else None

            # Parse retrieval_model_config
            retrieval_model = config_dict.get("retrieval_model_config", None)
            retrieval_model_config = (
                RetrievalModelConfig.from_dict(retrieval_model)
                if retrieval_model
                else None
            )

            return GlobalConfig(
                default_llm=default_llm,
                fast_llm=fast_llm,
                all_clouds_config=all_clouds_config,
                llmInstanceConfigs=llmInstanceConfigs,
                vm_config=vm_config,
                context_engineer_config=context_engineer_config,
                memory_config=memory_config,
                mcp_config=mcp_config,
                skill_config=skill_config,
                resource_skills=resource_skills,
                ontology_config=ontology_config,
                retrieval_model_config=retrieval_model_config,
                base_dir=base_dir,
            )
        else:
            model_name = config_dict.get("model_name")
            llm_instance_config = LLMInstanceConfig.from_dict(
                model_name, all_clouds_config=None, config_dict=config_dict
            )

            # The old format also supports context_engineer, memory, and mcp configurations
            context_engineer = config_dict.get("context_engineer", None)
            context_engineer_config = (
                ContextEngineerConfig.from_dict(context_engineer, base_dir=base_dir)
                if context_engineer
                else None
            )

            memory = config_dict.get("memory", None)
            memory_config = MemoryConfig.from_dict(memory) if memory else None

            mcp = config_dict.get("mcp", None)
            mcp_config = MCPConfig.from_dict(mcp) if mcp else None

            skill = config_dict.get("skill", None)
            skill_config = SkillConfig.from_dict(skill) if skill else None

            resource_skills = config_dict.get("resource_skills", None)

            ontology = config_dict.get("ontology", None)
            ontology_config = OntologyConfig.from_dict(ontology) if ontology else None

            # Parse retrieval_model_config
            retrieval_model = config_dict.get("retrieval_model_config", None)
            retrieval_model_config = (
                RetrievalModelConfig.from_dict(retrieval_model)
                if retrieval_model
                else None
            )

            llmInstanceConfigs = {model_name: llm_instance_config}
            if "name" in config_dict:
                llmInstanceConfigs[config_dict["name"]] = llm_instance_config
            return GlobalConfig(
                default_llm=model_name,
                llmInstanceConfigs=llmInstanceConfigs,
                context_engineer_config=context_engineer_config,
                memory_config=memory_config,
                mcp_config=mcp_config,
                skill_config=skill_config,
                resource_skills=resource_skills,
                ontology_config=ontology_config,
                retrieval_model_config=retrieval_model_config,
            )

    @staticmethod
    def from_yaml(yaml_path: str) -> "GlobalConfig":
        with open(yaml_path, "r", encoding="utf-8") as file:
            config_dict = yaml.load(file, Loader=yaml.FullLoader)
        # Get the directory of the YAML file to resolve relative paths
        base_dir = os.path.dirname(os.path.abspath(yaml_path))
        return GlobalConfig.from_dict(config_dict, base_dir=base_dir)

    @staticmethod
    def from_yaml_with_base(
        base_yaml: str, override_yaml: str = None
    ) -> "GlobalConfig":
        """Load from base configuration and override configuration, supporting configuration inheritance and merging.

        Args:
            base_yaml: Path to the base configuration file (required)
            override_yaml: Path to the override configuration file (optional), will recursively override the base configuration

        Returns:
            GlobalConfig: Merged configuration object

        Examples:
            # Use only the base configuration
            config = GlobalConfig.from_yaml_with_base("config/global.yaml")

                    # Use base configuration + agent-specific configuration
            config = GlobalConfig.from_yaml_with_base(
                base_yaml="config/global.yaml",
                override_yaml="config/alice/agent.yaml"
            )
        """
        # Load base configuration
        with open(base_yaml, "r", encoding="utf-8") as f:
            base_dict = yaml.load(f, Loader=yaml.FullLoader)

        # If there is a configuration overlay, perform a deep merge.
        if override_yaml and os.path.exists(override_yaml):
            with open(override_yaml, "r", encoding="utf-8") as f:
                override_dict = yaml.load(f, Loader=yaml.FullLoader)
            # If the override_yaml file contains only comments or is empty, yaml.load will return None
            if override_dict:
                config_dict = GlobalConfig._deep_merge(base_dict, override_dict)
            else:
                config_dict = base_dict
            # Use override_yaml directory as base_dir for relative paths
            base_dir = os.path.dirname(os.path.abspath(override_yaml))
        else:
            config_dict = base_dict
            # Use base_yaml directory as base_dir for relative paths
            base_dir = os.path.dirname(os.path.abspath(base_yaml))

        return GlobalConfig.from_dict(config_dict, base_dir=base_dir)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deeply merge two dictionaries, with values in override recursively overriding those in base.

        Args:
            base: Base dictionary
            override: Override dictionary

        Returns:
            dict: Merged dictionary (new dictionary, original dictionaries are not modified)

        Note:
            - Dictionary types are merged recursively
            - Other types (including lists) are directly overwritten
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge dictionaries
                result[key] = GlobalConfig._deep_merge(result[key], value)
            else:
                # Direct override (including lists, strings, numbers, etc.)
                result[key] = value
        return result

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        result = {
            "default": self.default_llm,
        }

        # Add fast_llm (if different from default_llm)
        if self.fast_llm and self.fast_llm != self.default_llm:
            result["fast"] = self.fast_llm

        # Add clouds configuration
        if self.all_clouds_config:
            clouds = {"default": self.all_clouds_config.default_cloud}
            for cloud_name, cloud_config in self.all_clouds_config.clouds.items():
                clouds[cloud_name] = {
                    "api": cloud_config.api,
                    "api_key": cloud_config.api_key,
                }
                if cloud_config.user_id:
                    clouds[cloud_name]["userid"] = cloud_config.user_id
                if cloud_config.headers:
                    clouds[cloud_name]["headers"] = cloud_config.headers
            result["clouds"] = clouds

        # Add llms configuration
        if self.llmInstanceConfigs:
            llms = {}
            for llm_name, llm_instance_config in self.llmInstanceConfigs.items():
                llm_dict = llm_instance_config.llm_config.to_dict()
                # If cloud configuration is used, add a cloud reference
                if self.all_clouds_config:
                    for cloud_name, cloud_config in self.all_clouds_config.clouds.items():
                        if cloud_config == llm_instance_config.cloud_config:
                            llm_dict["cloud"] = cloud_name
                            break
                llms[llm_name] = llm_dict
            result["llms"] = llms

        # Add additional configuration
        if self._vm_config:
            result["vm"] = self._vm_config.toDict()

        if self._context_engineer_config:
            result["context_engineer"] = self._context_engineer_config.to_dict()

        if self._memory_config:
            result["memory"] = self._memory_config.to_dict()

        if self._mcp_config:
            result["mcp"] = self._mcp_config.to_dict()

        if self._skill_config:
            result["skill"] = self._skill_config.to_dict()

        if self._resource_skills is not None:
            result["resource_skills"] = self._resource_skills

        if self._ontology_config:
            result["ontology"] = self._ontology_config.to_dict()

        if self._retrieval_model_config:
            result["retrieval_model_config"] = self._retrieval_model_config.to_dict()

        return result
