# -*- coding: utf-8 -*-
"""Toolkits 模块 - 内置 Toolkits"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.lib.toolkits.search_toolkit import SearchToolkit
    from dolphin.lib.toolkits.sql_toolkit import SQLToolkit
    from dolphin.lib.toolkits.memory_toolkit import MemoryToolkit
    from dolphin.lib.toolkits.mcp_toolkit import MCPToolkit
    from dolphin.lib.toolkits.ontology_toolkit import OntologyToolkit
    from dolphin.lib.toolkits.plan_toolkit import PlanToolkit
    from dolphin.lib.toolkits.cognitive_toolkit import CognitiveToolkit
    from dolphin.lib.toolkits.vm_toolkit import VMToolkit
    from dolphin.lib.toolkits.noop_toolkit import NoopToolkit
    from dolphin.lib.toolkits.resource_toolkit import ResourceToolkit
    from dolphin.lib.toolkits.system_toolkit import SystemFunctionsToolkit
    from dolphin.lib.toolkits.agent_toolkit import AgentToolkit
    from dolphin.lib.toolkits.env_toolkit import EnvToolkit

_module_lookup = {
    "SearchToolkit": "dolphin.lib.toolkits.search_toolkit",
    "SQLToolkit": "dolphin.lib.toolkits.sql_toolkit",
    "MemoryToolkit": "dolphin.lib.toolkits.memory_toolkit",
    "MCPToolkit": "dolphin.lib.toolkits.mcp_toolkit",
    "OntologyToolkit": "dolphin.lib.toolkits.ontology_toolkit",
    "PlanToolkit": "dolphin.lib.toolkits.plan_toolkit",
    "CognitiveToolkit": "dolphin.lib.toolkits.cognitive_toolkit",
    "VMToolkit": "dolphin.lib.toolkits.vm_toolkit",
    "NoopToolkit": "dolphin.lib.toolkits.noop_toolkit",
    "ResourceToolkit": "dolphin.lib.toolkits.resource_toolkit",
    "SystemFunctionsToolkit": "dolphin.lib.toolkits.system_toolkit",
    "AgentToolkit": "dolphin.lib.toolkits.agent_toolkit",
    "EnvToolkit": "dolphin.lib.toolkits.env_toolkit",
}

def __getattr__(name):
    if name in _module_lookup:
        import importlib
        module = importlib.import_module(_module_lookup[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = list(_module_lookup.keys())
