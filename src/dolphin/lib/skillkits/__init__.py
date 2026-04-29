# -*- coding: utf-8 -*-
"""Skillkits 模块 - 内置 Skillkits"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.lib.skillkits.search_skillkit import SearchSkillkit
    from dolphin.lib.skillkits.sql_skillkit import SQLSkillkit
    from dolphin.lib.skillkits.memory_skillkit import MemorySkillkit
    from dolphin.lib.skillkits.mcp_skillkit import MCPSkillkit
    from dolphin.lib.skillkits.ontology_skillkit import OntologySkillkit
    from dolphin.lib.skillkits.plan_skillkit import PlanSkillkit
    from dolphin.lib.skillkits.cognitive_skillkit import CognitiveSkillkit
    from dolphin.lib.skillkits.vm_skillkit import VMSkillkit
    from dolphin.lib.skillkits.noop_skillkit import NoopSkillkit
    from dolphin.lib.skillkits.resource_skillkit import ResourceSkillkit
    from dolphin.lib.skillkits.system_skillkit import SystemFunctionsSkillKit
    from dolphin.lib.skillkits.agent_skillkit import AgentSkillKit
    from dolphin.lib.skillkits.env_skillkit import EnvSkillkit

_module_lookup = {
    "SearchSkillkit": "dolphin.lib.skillkits.search_skillkit",
    "SQLSkillkit": "dolphin.lib.skillkits.sql_skillkit",
    "MemorySkillkit": "dolphin.lib.skillkits.memory_skillkit",
    "MCPSkillkit": "dolphin.lib.skillkits.mcp_skillkit",
    "OntologySkillkit": "dolphin.lib.skillkits.ontology_skillkit",
    "PlanSkillkit": "dolphin.lib.skillkits.plan_skillkit",
    "CognitiveSkillkit": "dolphin.lib.skillkits.cognitive_skillkit",
    "VMSkillkit": "dolphin.lib.skillkits.vm_skillkit",
    "NoopSkillkit": "dolphin.lib.skillkits.noop_skillkit",
    "ResourceSkillkit": "dolphin.lib.skillkits.resource_skillkit",
    "SystemFunctionsSkillKit": "dolphin.lib.skillkits.system_skillkit",
    "AgentSkillKit": "dolphin.lib.skillkits.agent_skillkit",
    "EnvSkillkit": "dolphin.lib.skillkits.env_skillkit",
}

def __getattr__(name):
    if name in _module_lookup:
        import importlib
        module = importlib.import_module(_module_lookup[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = list(_module_lookup.keys())
