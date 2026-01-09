# -*- coding: utf-8 -*-
"""
DolphinLanguageSDK - 兼容层

⚠️ 警告：此模块已弃用，请迁移至新的模块结构。

旧导入路径 → 新导入路径：
- from DolphinLanguageSDK import DolphinAgent → from dolphin.sdk import DolphinAgent
- from DolphinLanguageSDK import Context → from dolphin.core import Context
- from DolphinLanguageSDK import Env → from dolphin.sdk import Env

详见 docs/architecture/module_restructure_design.md
"""

import warnings

# 发出弃用警告
warnings.warn(
    "DolphinLanguageSDK is deprecated. "
    "Please migrate to the new module structure: dolphin.core, dolphin.lib, dolphin.sdk, dolphin.cli. "
    "See docs/architecture/module_restructure_design.md for migration guide.",
    DeprecationWarning,
    stacklevel=2
)

# =============================================================================
# 重新导出所有公共 API（保持向后兼容）
# =============================================================================

# Core 组件
from dolphin.core import (
    Context,
    Executor,
    DebugController,
    Trajectory,
    Recorder,
    GlobalConfig,
    BaseAgent,
    AgentState,
    RuntimeGraph,
    RuntimeInstance,
    Skillkit,
    Skillset,
    SkillFunction,
    SkillMatcher,
    LLM,
    LLMClient,
    LLMCall,
    MessageRole,
    SkillType,
    DolphinException,
    get_logger,
    VariablePool,
)
from dolphin.core.executor import DolphinExecutor
from dolphin.core.parser import Parser
from dolphin.core.message import MessageCompressor
from dolphin.core.common.enums import (
    Messages,
    SingleMessage,
    SkillInfo,
    CompressLevel,
    StreamItem,
)
from dolphin.core.common.constants import (
    MAX_ANSWER_CONTENT_LENGTH,
    MAX_LOG_LENGTH,
    MAX_SKILL_CALL_TIMES,
)
# 向后兼容：定义旧异常类（新模块中已移除，使用 DolphinException 替代）
DolphinSyntaxError = DolphinException
DolphinRuntimeError = DolphinException
from dolphin.core.common.types import Var, SourceType
from dolphin.core.context.var_output import VarOutput
from dolphin.core.context.context_manager import ContextEngineer
from dolphin.core.logging.logger import setup_logger, console

# Flags 模块：为了向后兼容，创建一个包含所有 flags API 的对象
from dolphin.core import flags as _flags_module
# 创建一个兼容对象，包含所有 flags 函数和常量
class _FlagsCompat:
    """兼容层：将 flags 模块的函数和常量作为对象属性"""
    def __init__(self):
        # 导入所有函数和常量
        from dolphin.core.flags import (
            is_enabled,
            override,
            reset,
            get_all,
            set_flag,
            EXPLORE_BLOCK_V2,
            DEBUG_MODE,
            DISABLE_LLM_CACHE,
        )
        self.is_enabled = is_enabled
        self.override = override
        self.reset = reset
        self.get_all = get_all
        self.set_flag = set_flag
        self.EXPLORE_BLOCK_V2 = EXPLORE_BLOCK_V2
        self.DEBUG_MODE = DEBUG_MODE
        self.DISABLE_LLM_CACHE = DISABLE_LLM_CACHE

flags = _FlagsCompat()

# SDK 组件
from dolphin.sdk import (
    DolphinAgent,
    AgentFactory,
    Env,
    GlobalSkills,
)
from dolphin.sdk.skill.traditional_toolkit import TriditionalToolkit

# Lib 组件
from dolphin.lib.skillkits.system_skillkit import SystemFunctionsSkillKit
from dolphin.lib.skillkits.agent_skillkit import AgentSkillKit

# 为了向后兼容，SystemFunctions 映射到 SystemFunctionsSkillKit
SystemFunctions = SystemFunctionsSkillKit

# Skill function decorator: 为了向后兼容，创建一个简单的装饰器
# 注意：新代码应该直接使用 SkillFunction 类
def skill_function(func=None, **kwargs):
    """向后兼容的 skill_function 装饰器
    
    注意：此装饰器已弃用，新代码应该直接使用 SkillFunction 类
    """
    from dolphin.core.skill.skill_function import SkillFunction
    if func is None:
        # 作为装饰器使用：@skill_function
        def decorator(f):
            return SkillFunction(f, **kwargs)
        return decorator
    else:
        # 直接调用：skill_function(func)
        return SkillFunction(func, **kwargs)

# 导出列表
__all__ = [
    # Context
    "Context",
    "VariablePool",
    "Var",
    "VarOutput",
    "SourceType",
    # Executor
    "Executor",
    "DolphinExecutor",
    "DebugController",
    "Parser",
    # Runtime
    "Env",
    "RuntimeGraph",
    "RuntimeInstance",
    # Agent
    "BaseAgent",
    "DolphinAgent",
    "AgentFactory",
    "AgentState",
    # Skill
    "Skillkit",
    "Skillset",
    "skill_function",
    "SkillFunction",
    "SkillMatcher",
    "GlobalSkills",
    "SystemFunctions",
    "AgentSkillKit",
    # LLM
    "LLM",
    "LLMClient",
    "LLMCall",
    # Config
    "GlobalConfig",
    # Common
    "MessageRole",
    "SkillType",
    "Messages",
    "SingleMessage",
    "SkillInfo",
    "CompressLevel",
    "StreamItem",
    "DolphinException",
    "DolphinSyntaxError",
    "DolphinRuntimeError",
    # Constants
    "MAX_ANSWER_CONTENT_LENGTH",
    "MAX_LOG_LENGTH",
    "MAX_SKILL_CALL_TIMES",
    # Trajectory
    "Trajectory",
    "Recorder",
    "MessageCompressor",
    # Logging
    "get_logger",
    "setup_logger",
    "console",
    # Flags
    "flags",
    # Context Engineer
    "ContextEngineer",
]
