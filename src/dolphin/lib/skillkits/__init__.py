# -*- coding: utf-8 -*-
"""Deprecated: dolphin.lib.skillkits has been renamed to dolphin.lib.toolkits.

This package is a backward-compatibility shim. All names are re-exported from
:mod:`dolphin.lib.toolkits`. Importing from ``dolphin.lib.skillkits`` will emit
a :class:`DeprecationWarning`.
"""
import warnings as _warnings

_warnings.warn(
    "The 'dolphin.lib.skillkits' package is deprecated and will be removed in a "
    "future release. Use 'dolphin.lib.toolkits' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from dolphin.lib.toolkits.search_toolkit import SearchToolkit as SearchSkillkit  # noqa: E402
from dolphin.lib.toolkits.sql_toolkit import SQLToolkit as SQLSkillkit  # noqa: E402
from dolphin.lib.toolkits.memory_toolkit import MemoryToolkit as MemorySkillkit  # noqa: E402
try:
    from dolphin.lib.toolkits.mcp_toolkit import MCPToolkit as MCPSkillkit  # noqa: E402
except ImportError:
    MCPSkillkit = None  # mcp optional dependency not installed
from dolphin.lib.toolkits.ontology_toolkit import OntologyToolkit as OntologySkillkit  # noqa: E402
from dolphin.lib.toolkits.plan_toolkit import PlanToolkit as PlanSkillkit  # noqa: E402
from dolphin.lib.toolkits.cognitive_toolkit import CognitiveToolkit as CognitiveSkillkit  # noqa: E402
from dolphin.lib.toolkits.vm_toolkit import VMToolkit as VMSkillkit  # noqa: E402
from dolphin.lib.toolkits.noop_toolkit import NoopToolkit as NoopSkillkit  # noqa: E402
from dolphin.lib.toolkits.resource_toolkit import ResourceToolkit as ResourceSkillkit  # noqa: E402
from dolphin.lib.toolkits.system_toolkit import SystemFunctionsToolkit as SystemFunctionsSkillKit  # noqa: E402
from dolphin.lib.toolkits.agent_toolkit import AgentToolkit as AgentSkillKit  # noqa: E402
from dolphin.lib.toolkits.env_toolkit import EnvToolkit as EnvSkillkit  # noqa: E402

__all__ = [
    "SearchSkillkit",
    "SQLSkillkit",
    "MemorySkillkit",
    "MCPSkillkit",
    "OntologySkillkit",
    "PlanSkillkit",
    "CognitiveSkillkit",
    "VMSkillkit",
    "NoopSkillkit",
    "ResourceSkillkit",
    "SystemFunctionsSkillKit",
    "AgentSkillKit",
    "EnvSkillkit",
]
