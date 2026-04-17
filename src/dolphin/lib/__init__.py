# -*- coding: utf-8 -*-
"""
Dolphin Lib - 标准库和工具集（用户态）

职责：
- 内置 Toolkits（search、sql、memory、mcp 等）
- Ontology 管理系统
- VM 虚拟机（可选执行后端）
- Memory 内存管理（知识管理）
- 工具函数库
- 调试可视化工具

依赖规则：
- dolphin.lib → 依赖 dolphin.core
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Toolkits
    from dolphin.lib.toolkits import (
        SearchToolkit,
        SQLToolkit,
        MemoryToolkit,
        MCPToolkit,
        OntologyToolkit,
        CognitiveToolkit,
        VMToolkit,
        NoopToolkit,
        ResourceToolkit,
        SystemFunctionsToolkit,
        AgentToolkit,
    )
    # Ontology
    from dolphin.lib.ontology import (
        Ontology,
        OntologyManager,
        OntologyContext,
    )
    # VM
    from dolphin.lib.vm import (
        VM,
        PythonSessionManager,
    )
    # Memory
    from dolphin.lib.memory import (
        MemoryManager,
    )
    # Skill Results
    from dolphin.lib.skill_results import (
        CacheBackend,
        ResultProcessor,
        ResultReference,
    )

_module_lookup = {
    # Toolkits
    "SearchToolkit": "dolphin.lib.toolkits",
    "SQLToolkit": "dolphin.lib.toolkits",
    "MemoryToolkit": "dolphin.lib.toolkits",
    "MCPToolkit": "dolphin.lib.toolkits",
    "OntologyToolkit": "dolphin.lib.toolkits",
    "CognitiveToolkit": "dolphin.lib.toolkits",
    "VMToolkit": "dolphin.lib.toolkits",
    "NoopToolkit": "dolphin.lib.toolkits",
    "ResourceToolkit": "dolphin.lib.toolkits",
    "SystemFunctionsToolkit": "dolphin.lib.toolkits",
    "AgentToolkit": "dolphin.lib.toolkits",
    # Deprecated Skillkit aliases (backward-compat shim)
    "SearchSkillkit": "dolphin.lib.skillkits",
    "SQLSkillkit": "dolphin.lib.skillkits",
    "MemorySkillkit": "dolphin.lib.skillkits",
    "MCPSkillkit": "dolphin.lib.skillkits",
    "OntologySkillkit": "dolphin.lib.skillkits",
    "PlanSkillkit": "dolphin.lib.skillkits",
    "CognitiveSkillkit": "dolphin.lib.skillkits",
    "VMSkillkit": "dolphin.lib.skillkits",
    "NoopSkillkit": "dolphin.lib.skillkits",
    "ResourceSkillkit": "dolphin.lib.skillkits",
    "SystemFunctionsSkillKit": "dolphin.lib.skillkits",
    "AgentSkillKit": "dolphin.lib.skillkits",
    "EnvSkillkit": "dolphin.lib.skillkits",
    # Ontology
    "Ontology": "dolphin.lib.ontology",
    "OntologyManager": "dolphin.lib.ontology",
    "OntologyContext": "dolphin.lib.ontology",
    # VM
    "VM": "dolphin.lib.vm",
    "PythonSessionManager": "dolphin.lib.vm",
    # Memory
    "MemoryManager": "dolphin.lib.memory",
    # Skill Results
    "CacheBackend": "dolphin.lib.skill_results",
    "ResultProcessor": "dolphin.lib.skill_results",
    "ResultReference": "dolphin.lib.skill_results",
}

def __getattr__(name):
    if name in _module_lookup:
        import importlib
        module = importlib.import_module(_module_lookup[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = list(_module_lookup.keys())
