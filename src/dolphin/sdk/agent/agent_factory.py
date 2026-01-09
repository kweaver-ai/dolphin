"""Agent factory class, used to create agents of different types"""

from typing import Dict, Any, Optional, Type
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.agent.base_agent import BaseAgent
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.logging.logger import get_logger


class AgentFactory:
    """Agent Factory Class"""

    def __init__(self):
        self._agent_types: Dict[str, Type[BaseAgent]] = {}
        self._default_config: Dict[str, Any] = {}

        # Register default Agent type
        self.register_agent_type("dolphin", DolphinAgent)

    def register_agent_type(self, name: str, agent_class: Type[BaseAgent]):
        """Register Agent Type"""
        if not issubclass(agent_class, BaseAgent):
            raise ValueError(
                f"Agent class {agent_class.__name__} must inherit from BaseAgent"
            )

        self._agent_types[name] = agent_class
        self._logger.debug(f"Registered agent type: {name} -> {agent_class.__name__}")

    def unregister_agent_type(self, name: str):
        """Deregister Agent Type"""
        if name in self._agent_types:
            del self._agent_types[name]
            self._logger.debug(f"Unregistered agent type: {name}")

    def get_agent_types(self) -> Dict[str, Type[BaseAgent]]:
        """Get all registered Agent types"""
        return self._agent_types.copy()

    def set_default_config(self, agent_type: str, config: Dict[str, Any]):
        """Set the default configuration for Agent types"""
        self._default_config[agent_type] = config

    def get_default_config(self, agent_type: str) -> Dict[str, Any]:
        """Get the default configuration for the Agent type"""
        return self._default_config.get(agent_type, {})

    def create_agent(self, agent_type: str, name: str, **kwargs) -> BaseAgent:
        """Create an Agent instance

        Args:
            agent_type: Name of the Agent type
            name: Name of the Agent instance
            **kwargs: Initialization parameters for the Agent

        Returns:
            Agent instance

        Raises:
            ValueError: Unknown Agent type
        """
        if agent_type not in self._agent_types:
            available_types = list(self._agent_types.keys())
            raise ValueError(
                f"Unknown agent type '{agent_type}'. Available types: {available_types}"
            )

        agent_class = self._agent_types[agent_type]
        default_config = self._default_config.get(agent_type, {})

        # Merge default configuration with the passed-in configuration
        # Note: Remove config from kwargs to avoid duplicate passing
        agent_kwargs = kwargs.copy()
        config_from_kwargs = agent_kwargs.pop("global_config", {})
        config_from_kwargs = agent_kwargs.pop("config", {})
        if config_from_kwargs is not None:
            merged_config = {**default_config, **config_from_kwargs}
        else:
            merged_config = default_config
        try:
            agent = agent_class(
                name=name,
                global_config=GlobalConfig.from_dict(merged_config),
                **agent_kwargs,
            )
            self._logger.debug(f"Created {agent_type} agent: {name}")
            return agent
        except Exception as e:
            raise RuntimeError(
                f"Failed to create {agent_type} agent '{name}': {str(e)}"
            )

    def create_dolphin_agent(
        self,
        file_path: str,
        global_config: GlobalConfig | None,
        name: Optional[str] = None,
        **kwargs,
    ) -> BaseAgent:
        """A convenient method to create a Dolphin Agent

        Args:
            file_path: DPH file path
            global_config: Global configuration
            name: Agent name
            **kwargs: Additional parameters

        Returns:
            DolphinAgent instance
        """
        if name is None:
            import os

            name = os.path.splitext(os.path.basename(file_path))[0]

        return self.create_agent(
            agent_type="dolphin",
            name=name,
            file_path=file_path,
            global_config=global_config,
            **kwargs,
        )

    def create_agent_from_config(self, config: Dict[str, Any]) -> BaseAgent:
        """Create an Agent from a configuration dictionary

        Args:
            config: Agent configuration dictionary

        Returns:
            Agent instance
        """
        required_fields = ["type", "name"]
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field '{field}' in agent config")

        return self.create_agent(
            agent_type=config["type"],
            name=config["name"],
            **{k: v for k, v in config.items() if k not in ["type", "name"]},
        )

    @property
    def _logger(self):
        """Get logger"""

        return get_logger("agent.agent_factory")


# Global Agent Factory Instance
_global_agent_factory = AgentFactory()


def get_agent_factory() -> AgentFactory:
    """Get the global Agent factory instance"""
    return _global_agent_factory


def create_agent(agent_type: str, name: str, **kwargs) -> BaseAgent:
    """Convenient Agent Creation Function"""
    return get_agent_factory().create_agent(agent_type, name, **kwargs)


def create_dolphin_agent(
    file_path: str,
    global_config: GlobalConfig | None,
    name: Optional[str] = None,
    **kwargs,
) -> BaseAgent:
    """Convenient Dolphin Agent creation function"""
    return get_agent_factory().create_dolphin_agent(
        file_path, global_config, name, **kwargs
    )


# Predefined Agent Configuration Templates
AGENT_TEMPLATES = {
    "basic_dolphin": {
        "type": "dolphin",
        "global_config": {"enable_logging": True, "timeout": 300},
    },
    "analysis_dolphin": {
        "type": "dolphin",
        "global_config": {
            "enable_logging": True,
            "timeout": 600,
            "enable_profiling": True,
        },
    },
    "chat_dolphin": {
        "type": "dolphin",
        "global_config": {
            "enable_logging": True,
            "timeout": 180,
            "enable_memory": True,
        },
    },
}


def create_agent_from_template(
    template_name: str, name: str, **template_overrides
) -> BaseAgent:
    """Create Agent from template

        Args:
            template_name: Template name
            name: Agent name
            template_overrides: Template parameter overrides

        Returns:
            Agent instance
    """
    if template_name not in AGENT_TEMPLATES:
        available_templates = list(AGENT_TEMPLATES.keys())
        raise ValueError(
            f"Unknown template '{template_name}'. Available templates: {available_templates}"
        )

    template = AGENT_TEMPLATES[template_name].copy()

    # Application Coverage Parameters
    if (
        "global_config" in template_overrides
        and template_overrides.pop("global_config") is not None
    ):
        template["global_config"] = {
            **template.get("global_config", {}),
            **template_overrides.pop("global_config"),
        }

    template.update(template_overrides)
    template["name"] = name

    return get_agent_factory().create_agent_from_config(template)
